"""Single source of truth for every tunable value in SpendGuard.

Nothing in this module may be hardcoded anywhere else in the codebase.

The threshold values here are mirrored in ``policy/policy.md``. They must agree:
if they drift, the agent will cite a policy clause stating one figure while the
detector that raised the case used another, which breaks the citation guarantee
the project rests on. ``policy_check.py`` parses the policy and a test asserts
equality (see docs/REQUIREMENTS.md FR-2.14).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/spendguard/config.py -> backend/src -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LLMProvider(StrEnum):
    """Which OpenAI-compatible endpoint the agent talks to."""

    OLLAMA = "ollama"
    GROQ = "groq"
    GEMINI = "gemini"


class SeverityBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------- paths
    project_root: Path = PROJECT_ROOT
    duckdb_path: Path = PROJECT_ROOT / "data" / "processed" / "spendguard.duckdb"
    database_url: str = (
        f"sqlite:///{(PROJECT_ROOT / 'data' / 'processed' / 'spendguard.sqlite').as_posix()}"
    )
    policy_path: Path = PROJECT_ROOT / "policy" / "policy.md"
    mappings_dir: Path = PROJECT_ROOT / "backend" / "mappings"
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    processed_data_dir: Path = PROJECT_ROOT / "data" / "processed"
    frozen_data_dir: Path = PROJECT_ROOT / "data" / "frozen"
    # Generated result tables, committed: every number in docs/EVALUATION.md is
    # copied from here, and each file names the command and commit that made it.
    results_dir: Path = PROJECT_ROOT / "docs" / "results"

    # ------------------------------------------------------- reproducibility
    random_seed: int = 42
    # Seeds reported. The first is the development seed every threshold was tuned
    # on; the rest are held out (CLAUDE.md convention 6).
    evaluation_seeds: list[int] = Field(default_factory=lambda: [42, 7, 2026])

    # -------------------------------------------------------------- currency
    # Decision D-15. Conversion for non-INR datasets uses a rate pinned per
    # dataset in its mapping file, never a live rate.
    currency: str = "INR"
    currency_symbol: str = "₹"

    # ------------------------------------------- thresholds (mirror policy.md)
    # Policy SG-PP-2.1 - direct purchase ceiling
    direct_purchase_ceiling: float = 25_000.0

    # Policy SG-PP-2.2 - the principal control threshold. D2 anchors here.
    approval_threshold: float = 250_000.0

    # Policy SG-PP-2.1 - limited tender ceiling
    limited_tender_ceiling: float = 2_500_000.0

    # Policy SG-PP-4.4 - D1 duplicate matching
    duplicate_amount_tolerance: float = 0.005  # 0.5%
    duplicate_date_window_days: int = 14

    # Policy SG-PP-4.2 - pre-payment duplicate lookback
    prepayment_lookback_days: int = 90

    # Policy SG-PP-3.2 / SG-PP-3.3 - D2 split windows
    split_window_days: int = 14
    split_scrutiny_windows_days: list[int] = Field(default_factory=lambda: [3, 7])

    # Policy SG-PP-5.3 - D4 new vendor period
    new_vendor_days: int = 90

    # Policy SG-PP-6.2 - D3 price history comparison period
    price_history_months: int = 12

    # -------------------------------------------------- detector tuning knobs
    # Not policy-derived; these are statistical choices, documented in the
    # detector specs rather than in the procurement policy.
    duplicate_name_confirm: float = 80.0  # D1: name_similarity needed to confirm identity (D-12)
    duplicate_match_threshold: float = 0.5  # D1: posterior match probability to raise a case
    duplicate_em_max_iterations: int = 200
    # D2: minimum run score to raise a case. Chosen to maximize F1 on the
    # development seed (42) only; reported on held-out seeds (decision D-21).
    split_score_threshold: float = 0.85
    # D3: chosen to maximize F1 on the development seed (42) only (decision D-23).
    inflation_zscore_threshold: float = 5.5
    inflation_min_category_size: int = 20
    benford_min_transactions: int = 30
    benford_pvalue_threshold: float = 0.01
    # D4: minimum observations for each vendor-level test (decision D-24)
    vendor_min_distinct_amounts: int = 20
    vendor_min_transactions: int = 20
    vendor_fdr_alpha: float = 0.05
    round_number_unit: float = 1_000.0
    isolation_forest_contamination: float = 0.02

    # -------------------------------------------------------- severity model
    # Decision D-08. See open issue O-03 on reference_amount.
    severity_band_high: float = 66.0
    severity_band_medium: float = 33.0
    # Fixed reference so severity is comparable across runs, ablations and the
    # demo. Using the run maximum would let one large transaction rescale every
    # other case (docs/DECISIONS.md O-03).
    severity_reference_amount: float = 10_000_000.0  # Rs 1 crore

    # ------------------------------------------------------------ agent / LLM
    # Switching provider is one line, LLM_PROVIDER: each provider keeps its own
    # key, endpoint and model below (decision D-33). LLM_BASE_URL, LLM_MODEL and
    # LLM_API_KEY, when set, override whichever provider is active.
    llm_provider: LLMProvider = LLMProvider.GROQ

    groq_api_key: str = "not-set"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "qwen/qwen3.8-27b"

    gemini_api_key: str = "not-set"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-2.5-flash"

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:3b-instruct-q4_K_M"

    # Resolved from the provider unless set explicitly (see _resolve_llm below).
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048
    llm_timeout_seconds: int = 120

    agent_max_steps: int = 12
    # Tool results are truncated before going back to the model. Every turn resends
    # the whole conversation, so an oversized result is paid for on every step.
    agent_tool_result_chars: int = 2_500
    # Largest request the agent may send, in input tokens. Groq's free tier refuses
    # anything over ~7,000 (HTTP 413) and Ollama silently truncates past num_ctx, so
    # the oldest tool results are trimmed to stay under this. Keep it below both.
    agent_context_tokens: int = 5_500
    # Verifier (Phase 7, decision D-31). Off releases notes unchecked by a model and
    # never regenerates - the FR-7.8 ablation. The deterministic check still runs
    # and is recorded either way, because it is free and it is the measurement.
    verifier_enabled: bool = True
    verifier_semantic_check: bool = True  # the LLM judge; off saves one call per note
    verifier_max_retries: int = 2
    verifier_temperature: float = 0.0
    # Evidence shown to the judge: cited rows, then the investigator's tool results.
    verifier_max_rows: int = 25
    verifier_context_chars: int = 2_500
    investigate_top_n: int = 50

    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # -------------------------------------------------------------------- API
    # Phase 8. The API reads batch results and writes review state; it never runs
    # a detector or the LLM inside a request (D-10).
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # The Vite dev server. The built frontend is served by the API itself.
    api_cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    api_page_size_max: int = 200
    api_evidence_rows: int = 200  # case rows returned with the detail; the rest are paged
    api_context_rows: int = 15  # the supplier's nearby rows shown for comparison
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"

    # ----------------------------------------------------------------- runtime
    log_level: str = "INFO"

    # ------------------------------------------------------------- helpers
    @model_validator(mode="after")
    def _resolve_llm(self) -> Settings:
        """Fill the active provider's endpoint, model and key into the llm_* fields.

        Everything downstream reads ``llm_base_url`` / ``llm_model`` /
        ``llm_api_key`` and never needs to know which provider is active. An
        explicit LLM_* value still wins, so one-off experiments need no new field.
        """
        base_url, model, key = self._preset(self.llm_provider)
        self.llm_base_url = self.llm_base_url or base_url
        self.llm_model = self.llm_model or model
        self.llm_api_key = self.llm_api_key or key
        return self

    def _preset(self, provider: LLMProvider) -> tuple[str, str, str]:
        return {
            LLMProvider.GROQ: (self.groq_base_url, self.groq_model, self.groq_api_key),
            LLMProvider.GEMINI: (self.gemini_base_url, self.gemini_model, self.gemini_api_key),
            LLMProvider.OLLAMA: (self.ollama_base_url, self.ollama_model, "ollama"),
        }[provider]

    def endpoint_for(self, provider: LLMProvider) -> tuple[str, str, str]:
        """(base_url, model, api_key) for any provider; the active one includes LLM_* overrides."""
        if provider is self.llm_provider:
            return self.llm_base_url, self.llm_model, self.llm_api_key
        return self._preset(provider)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def split_windows_all(self) -> list[int]:
        """Every rolling window D2 evaluates, shortest first."""
        return sorted({*self.split_scrutiny_windows_days, self.split_window_days})

    def band_for(self, severity: float) -> SeverityBand:
        """Map a 0-100 severity score onto its band (docs/DECISIONS.md D-08)."""
        if severity >= self.severity_band_high:
            return SeverityBand.HIGH
        if severity >= self.severity_band_medium:
            return SeverityBand.MEDIUM
        return SeverityBand.LOW

    def money(self, amount: float) -> str:
        """Format a number as currency using Indian digit grouping (FR-6.10).

        Lakh/crore grouping, not thousands separators:
        ``1234567.5`` renders as ``₹12,34,567.50``, never ``₹1,234,567.50``.
        """
        rounded = round(abs(amount), 2)
        neg = amount < 0 and rounded > 0  # avoid rendering "-₹0.00"
        whole, frac = divmod(rounded, 1)
        digits = str(int(whole))

        if len(digits) > 3:
            head, tail = digits[:-3], digits[-3:]
            groups: list[str] = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            digits = ",".join([*groups, tail])

        out = f"{self.currency_symbol}{digits}.{int(round(frac * 100)):02d}"
        return f"-{out}" if neg else out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance. Import this, never instantiate Settings directly."""
    return Settings()


settings = get_settings()
