"""Policy retrieval - semantic search over the procurement policy (FR-3.10).

The Investigator has to say *which rule* a transaction offends, by its clause
number, so an auditor can check the claim. Keyword search cannot do that:
"purchase over limit" and "exceeds threshold" share no words. Sentence
embeddings can.

Retrieval is **dense embeddings**, and that was measured rather than assumed.
Hybrid retrieval (dense + BM25, fused by Reciprocal Rank Fusion) is the usual
remedy when queries turn on exact terms, so it was built and compared on a
10-query benchmark of colloquial paraphrases:

    dense only            top-1 5/10   top-3 7/10   <- kept
    BM25 only             top-1 2/10   top-3 3/10
    hybrid RRF (top 5)    top-1 4/10   top-3 7/10
    hybrid RRF (full)     top-1 3/10   top-3 7/10

Hybrid never won. With 41 short clauses of formal prose and questions phrased in
plain language, there is little lexical overlap for BM25 to exploit, so it
mostly injects noise. The other modes stay available through ``search(mode=...)``
so the comparison can be reproduced for the ablation table.

Two further properties matter, and both come from the policy document itself:

* **Chunk on clause boundaries, never on a character count.** Half a clause
  reads as authoritative and is incomplete - exactly the failure the Verifier
  exists to catch. Each ``SG-PP-x.y`` clause becomes one chunk, carrying its
  section heading for context.
* **Return the clause identifier, not just text.** An audit note cites
  ``SG-PP-3.2``; a quotation with no traceable source is worth nothing.

Embeddings are cached next to the processed data and keyed by a hash of the
policy, so editing the policy rebuilds the index and nothing else does.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from spendguard.config import settings

# "**SG-PP-3.2 — Indicators of splitting.**"
CLAUSE_HEADING = re.compile(r"^\*\*(SG-PP-[\d.]+)\s*[—–-]\s*(.+?)\.?\*\*\s*$", re.MULTILINE)
SECTION_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# bge models are trained with an instruction on the query side only.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

# Reciprocal Rank Fusion constant, from the original paper. Large enough that no
# single first-place hit dominates, small enough that rank still matters.
RRF_K = 60

_WORD = re.compile(r"[a-z0-9₹.,]+")


def tokenize(text: str) -> list[str]:
    """Lowercase words, keeping figures like '2,50,000' and '₹25,000' intact."""
    return [t.strip(".,") for t in _WORD.findall(text.lower()) if t.strip(".,")]


def to_prose(markdown: str) -> str:
    """Flatten markdown to the sentence-like text an embedding model expects.

    Clause SG-PP-2.1 is mostly a table of value bands. Left as pipes and dashes
    it embedded poorly and lost the very query it should answer ("how much can I
    buy without quotes?"), so tables become "cell, cell, cell" lines and bullets
    become clauses.
    """
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if set(line) <= set("|-: "):  # table separator row
            continue
        if line.startswith("|"):
            line = ", ".join(cell.strip() for cell in line.strip("|").split("|") if cell.strip())
        elif line.startswith(("-", "*", "+")):
            line = line.lstrip("-*+ ").strip()
        lines.append(line.rstrip(".") + ".")
    text = " ".join(lines)
    text = re.sub(r"\*\*|__|`", "", text)  # bold, italics, inline code
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Clause:
    clause_id: str
    title: str
    section: str
    text: str

    @property
    def embedding_text(self) -> str:
        """What gets embedded: heading plus body as prose, so the title carries weight."""
        return to_prose(f"{self.section}. {self.title}. {self.text}")

    def as_citation(self) -> dict[str, str]:
        return {"clause_id": self.clause_id, "title": self.title, "section": self.section}


@dataclass(frozen=True)
class PolicyMatch:
    clause: Clause
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause.clause_id,
            "title": self.clause.title,
            "section": self.clause.section,
            "text": self.clause.text,
            "similarity": round(self.score, 4),
        }


def parse_clauses(policy_path: Path | None = None) -> list[Clause]:
    """Split the policy into whole clauses, each tagged with its section."""
    path = policy_path or settings.policy_path
    document = path.read_text(encoding="utf-8")

    sections = [(m.start(), m.group(1)) for m in SECTION_HEADING.finditer(document)]

    def section_for(position: int) -> str:
        current = "Procurement policy"
        for start, title in sections:
            if start < position:
                current = title
            else:
                break
        return current

    matches = list(CLAUSE_HEADING.finditer(document))
    clauses: list[Clause] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(document)
        body = document[match.end() : end]
        # Stop at the next section heading so a clause never swallows one.
        body = SECTION_HEADING.split(body)[0]
        text = re.sub(r"\n{3,}", "\n\n", body).strip()
        if not text:
            continue
        clauses.append(
            Clause(
                clause_id=match.group(1),
                title=match.group(2).strip(),
                section=section_for(match.start()),
                text=text,
            )
        )
    if not clauses:
        raise ValueError(f"No SG-PP clauses found in {path}")
    return clauses


def fingerprint(clauses: list[Clause], model_name: str) -> str:
    """Cache key over the *exact text that gets embedded*, plus the model.

    Hashing the policy file alone is not enough: changing how clauses are parsed
    or flattened changes the embeddings while the file stays identical, and the
    stale cache silently wins. This key moves whenever either input moves.
    """
    payload = "␟".join(c.embedding_text for c in clauses) + f"␟{model_name}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class PolicyIndex:
    """Clause embeddings plus a FAISS index, cached on disk."""

    def __init__(self, policy_path: Path | None = None, cache_dir: Path | None = None) -> None:
        self.policy_path = policy_path or settings.policy_path
        self.cache_dir = cache_dir or settings.processed_data_dir / "policy_index"
        self.clauses = parse_clauses(self.policy_path)
        self.fingerprint = fingerprint(self.clauses, settings.embedding_model)
        self._embeddings = self._load_or_build()
        self._index = self._build_index(self._embeddings)

    # ------------------------------------------------------------ embeddings

    @property
    def _cache_file(self) -> Path:
        return self.cache_dir / f"clauses-{self.fingerprint}.npz"

    def _encode(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        model = _embedding_model(settings.embedding_model)
        prepared = [QUERY_INSTRUCTION + t for t in texts] if is_query else texts
        vectors = model.encode(prepared, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)

    def _load_or_build(self) -> np.ndarray:
        if self._cache_file.exists():
            cached = np.load(self._cache_file)
            if cached["count"] == len(self.clauses):
                return cached["embeddings"].astype(np.float32)
        embeddings = self._encode([c.embedding_text for c in self.clauses])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        np.savez(self._cache_file, embeddings=embeddings, count=len(self.clauses))
        (self.cache_dir / "clauses.json").write_text(
            json.dumps([c.as_citation() for c in self.clauses], indent=2), encoding="utf-8"
        )
        return embeddings

    @staticmethod
    def _build_index(embeddings: np.ndarray) -> Any:
        import faiss

        index = faiss.IndexFlatIP(embeddings.shape[1])  # vectors are normalized: IP == cosine
        index.add(embeddings)
        return index

    # ------------------------------------------------------------ BM25

    def _bm25_ranking(self, query: str, k1: float = 1.5, b: float = 0.75) -> list[int]:
        """Clause positions ordered by BM25 against the query."""
        import math
        from collections import Counter

        documents = [tokenize(c.embedding_text) for c in self.clauses]
        lengths = np.array([len(d) for d in documents], dtype=float)
        average_length = float(lengths.mean()) or 1.0
        terms = Counter(tokenize(query))

        scores = np.zeros(len(documents))
        for term, query_count in terms.items():
            containing = [i for i, d in enumerate(documents) if term in d]
            if not containing:
                continue
            idf = math.log(1 + (len(documents) - len(containing) + 0.5) / (len(containing) + 0.5))
            for i in containing:
                frequency = documents[i].count(term)
                denominator = frequency + k1 * (1 - b + b * lengths[i] / average_length)
                scores[i] += query_count * idf * frequency * (k1 + 1) / denominator
        return [int(i) for i in np.argsort(-scores) if scores[i] > 0]

    # ------------------------------------------------------------ search

    def search(self, query: str, k: int = 3, mode: str = "dense") -> list[PolicyMatch]:
        """Top-k clauses. ``mode`` is 'dense' (default), 'lexical', or 'hybrid'.

        Non-default modes exist so the retrieval comparison stays reproducible;
        dense won on the benchmark in this module's docstring.
        """
        if not query.strip():
            return []
        if mode not in {"dense", "lexical", "hybrid"}:
            raise ValueError(f"Unknown retrieval mode {mode!r}")

        vector = self._encode([query], is_query=True)
        similarity, positions = self._index.search(vector, len(self.clauses))
        dense_order = [int(p) for p in positions[0] if p >= 0]
        cosine = {int(p): float(s) for s, p in zip(similarity[0], positions[0], strict=True)}

        if mode == "dense":
            best = dense_order[:k]
        elif mode == "lexical":
            best = self._bm25_ranking(query)[:k]
        else:
            fused: dict[int, float] = {}
            for ranking in (dense_order, self._bm25_ranking(query)):
                for rank, position in enumerate(ranking[:5], start=1):
                    fused[position] = fused.get(position, 0.0) + 1.0 / (RRF_K + rank)
            best = sorted(fused, key=lambda p: (-fused[p], p))[:k]

        # Report cosine similarity: interpretable, unlike a fused rank.
        return [PolicyMatch(self.clauses[p], cosine.get(p, 0.0)) for p in best]

    def by_id(self, clause_id: str) -> Clause | None:
        return next((c for c in self.clauses if c.clause_id == clause_id), None)


@lru_cache(maxsize=2)
def _embedding_model(name: str) -> Any:
    """Loading the model costs seconds; do it once per process."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name)


@lru_cache(maxsize=1)
def get_policy_index() -> PolicyIndex:
    return PolicyIndex()
