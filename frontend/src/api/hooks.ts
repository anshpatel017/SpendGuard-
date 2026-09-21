// TanStack Query hooks: caching, loading and error state for every read, and the
// one write. After a review decision the queue, the case and the KPIs refetch,
// so nothing on screen contradicts what was just saved.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type CaseFilters } from "./client";
import type { CaseStatus } from "./types";

export const keys = {
  metrics: ["metrics"] as const,
  cases: (filters: CaseFilters) => ["cases", filters] as const,
  caseDetail: (caseId: string) => ["case", caseId] as const,
  evaluation: (seed: number) => ["evaluation", seed] as const,
};

export function useMetrics() {
  return useQuery({ queryKey: keys.metrics, queryFn: api.metrics });
}

export function useCases(filters: CaseFilters) {
  return useQuery({
    queryKey: keys.cases(filters),
    queryFn: () => api.cases(filters),
    placeholderData: keepPreviousData, // keep the table on screen while the next page loads
  });
}

export function useCaseDetail(caseId: string) {
  return useQuery({ queryKey: keys.caseDetail(caseId), queryFn: () => api.caseDetail(caseId) });
}

export function useEvaluation(seed: number) {
  return useQuery({ queryKey: keys.evaluation(seed), queryFn: () => api.evaluation(seed) });
}

/** The live demo: plants anomalies in a throwaway copy and detects them (a few seconds). */
export function useDemoInject() {
  return useMutation({
    mutationFn: ({ count, seed }: { count: number; seed: number | null }) => api.demoInject(count, seed),
  });
}

export function useUpdateStatus(caseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ status, note }: { status: CaseStatus; note: string }) =>
      api.updateStatus(caseId, status, note),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.caseDetail(caseId) }),
        client.invalidateQueries({ queryKey: ["cases"] }),
        client.invalidateQueries({ queryKey: keys.metrics }),
      ]);
    },
  });
}
