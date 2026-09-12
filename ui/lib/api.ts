import { loadConnection } from './storage';

export type RunSummary = {
  id: string;
  objective: string;
  repo_path: string;
  best_score: number;
  status: string;
  created_at: string;
  updated_at: string;
};

export type RunDetail = RunSummary & {
  candidates: Array<{ iteration: number; score: number; improved: number; worker_success: number; created_at: string }>;
  invocations: Array<{ iteration: number; role: string; backend: string; success: number; duration_seconds: number; input_tokens?: number; output_tokens?: number; cost_usd?: number }>;
  role_runs: Array<{ iteration: number; sequence: number; role: string; reason: string; success: number; duration_ms: number; output: string; error: string }>;
  evaluations: Array<{ iteration: number; name: string; score: number; passed: number; summary: string }>;
  metadata: Record<string, unknown>;
};

export type VariantMetrics = {
  trials?: number;
  oracle_solve_rate?: number;
  mean_oracle_score?: number;
  mean_visible_score?: number;
  mean_total_tokens?: number;
  tokens_per_oracle_solve?: number | null;
  mean_wall_seconds?: number;
  mean_role_invocations?: number;
  mean_role_seconds?: number;
  reported_cost_usd?: number;
};

export type StrategyChoice = {
  variant: string;
  trials?: number;
  solve_rate?: number;
  mean_oracle_score?: number;
  mean_tokens?: number;
  mean_wall_seconds?: number;
  mean_cost_usd?: number;
};

export type BenchmarkSummary = {
  id: string;
  experiment: string;
  updated_at: number;
  variant_count: number;
  trial_count: number;
  default_strategy?: string | null;
};

export type BenchmarkDetail = {
  id: string;
  report: {
    experiment?: string;
    variants?: Record<string, VariantMetrics>;
    trials?: Array<Record<string, unknown>>;
    routing_policy?: Record<string, unknown>;
  };
  routing_policy: {
    version?: number;
    selection?: string;
    default?: StrategyChoice | null;
    by_tag?: Record<string, StrategyChoice>;
  };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { apiUrl, token } = await loadConnection();
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Avo API returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ ok: boolean; auth: boolean; benchmark_root?: string }>('/api/health'),
  runs: () => request<RunSummary[]>('/api/runs'),
  run: (id: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  start: (objective: string) => request<{ accepted: boolean; pid: number }>('/api/runs', {
    method: 'POST',
    body: JSON.stringify({ objective }),
  }),
  benchmarks: () => request<BenchmarkSummary[]>('/api/benchmarks'),
  benchmark: (id: string) => request<BenchmarkDetail>(`/api/benchmarks/${id.split('/').map(encodeURIComponent).join('/')}`),
};
