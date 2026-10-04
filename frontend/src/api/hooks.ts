// TanStack Query hooks: caching, loading and error state for every read, and the
// one write. After a review decision the queue, the case and the KPIs refetch,
// so nothing on screen contradicts what was just saved.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type CaseFilters, type TransactionFilters } from "./client";
import type { CaseStatus } from "./types";

export const keys = {
  metrics: ["metrics"] as const,
  cases: (filters: CaseFilters) => ["cases", filters] as const,
  caseDetail: (caseId: string) => ["case", caseId] as const,
  investigationStatus: (caseId: string) => ["investigation-status", caseId] as const,
  transactions: (filters: TransactionFilters) => ["transactions", filters] as const,
  runs: ["runs"] as const,
  health: ["health"] as const,
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

export function useInvestigationStatus(caseId: string, enabled: boolean) {
  const client = useQueryClient();
  return useQuery({
    queryKey: keys.investigationStatus(caseId),
    queryFn: async () => {
      const res = await api.investigationStatus(caseId);
      if (res.state === "completed" || res.state === "failed") {
        client.invalidateQueries({ queryKey: keys.caseDetail(caseId) });
      }
      return res;
    },
    enabled: Boolean(caseId) && enabled,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === "queued" || state === "investigating" || state === "verifying" ? 1500 : false;
    },
  });
}

export function useTriggerInvestigation(caseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.triggerInvestigation(caseId),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.caseDetail(caseId) }),
        client.invalidateQueries({ queryKey: keys.investigationStatus(caseId) }),
      ]);
    },
  });
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
    mutationFn: ({
      status,
      note,
      reviewer,
    }: {
      status: CaseStatus;
      note: string;
      reviewer?: string;
    }) => api.updateStatus(caseId, status, note, reviewer),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.caseDetail(caseId) }),
        client.invalidateQueries({ queryKey: ["cases"] }),
        client.invalidateQueries({ queryKey: keys.metrics }),
      ]);
    },
  });
}

export function useTransactions(filters: TransactionFilters = {}) {
  return useQuery({
    queryKey: keys.transactions(filters),
    queryFn: () => api.transactions(filters),
    placeholderData: keepPreviousData,
  });
}

export function useRuns(limit: number = 50) {
  return useQuery({
    queryKey: keys.runs,
    queryFn: () => api.runs(limit),
  });
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: api.health,
    refetchInterval: 30000,
  });
}

export function useDemoReset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.demoReset(),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["cases"] }),
        client.invalidateQueries({ queryKey: keys.metrics }),
        client.invalidateQueries({ queryKey: keys.health }),
      ]);
    },
  });
}
