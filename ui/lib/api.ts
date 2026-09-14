import { Platform } from 'react-native';
import { apiBaseUrl, loadSessionToken } from './storage';

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

export type ChatEvidence = { fact: string; source: string };

export type ChatMessage = {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  kind: 'text' | 'thinking' | 'ready' | 'execution' | 'error' | string;
  status: 'complete' | 'thinking' | 'error' | string;
  run_id?: string | null;
  created_at: string;
  updated_at: string;
  metadata: {
    action?: 'answer' | 'clarify' | 'execute';
    objective?: string;
    evidence?: ChatEvidence[];
    acceptance?: string[];
    constraints?: string[];
    question?: string;
    execution_ready?: boolean;
    auto_executed?: boolean;
  };
  run?: RunSummary;
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

export type AuthStatus = {
  authenticated: boolean;
  bootstrap_required: boolean;
  passkey_count: number;
  rp_id: string;
  auth_disabled: boolean;
};

export type PasskeyCredential = {
  id: string;
  label: string;
  device_type: string;
  backed_up: boolean;
  created_at: string;
  last_used_at?: string | null;
};

export type CeremonyOptions = {
  challenge_id: string;
  options: Record<string, unknown>;
};

export type SessionResponse = {
  ok: boolean;
  expires_at: string;
  token?: string;
};

export type AccessManifest = {
  version: 1;
  repositories: Record<string, { path: string; access: 'read' | 'write' }>;
  secrets: Record<string, { source: string; expose_to: string[] }>;
  services: Record<string, { url: string; access: 'read' | 'write' }>;
  tools: Record<string, { enabled: boolean; expose_to: string[] }>;
  network: { allow: string[] };
};

export type AccessChange = {
  category: 'repositories' | 'secrets' | 'services' | 'tools' | 'network' | string;
  name: string;
  change: 'added' | 'removed' | 'changed' | string;
  increase: boolean;
  before?: unknown;
  after?: unknown;
};

export type AccessStatus = {
  path: string;
  yaml: string;
  requested: AccessManifest;
  effective: AccessManifest;
  secret_status: Record<string, { source: string; configured: boolean }>;
  changes: AccessChange[];
  requires_approval: boolean;
};

export type AccessPreview = {
  manifest: AccessManifest;
  changes: AccessChange[];
  requires_approval: boolean;
};

export type AccessApplyResult = {
  applied: boolean;
  requires_passkey: boolean;
  approval_id?: string;
  changes: AccessChange[];
  status?: AccessStatus;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await loadSessionToken();
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    credentials: Platform.OS === 'web' ? 'include' : init?.credentials,
    headers: {
      'Content-Type': 'application/json',
      ...(Platform.OS !== 'web' ? { 'X-Avo-Client': 'native' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.text();
    let message = body;
    try {
      const payload = JSON.parse(body) as { detail?: unknown };
      message = typeof payload.detail === 'string'
        ? payload.detail
        : payload.detail
          ? JSON.stringify(payload.detail)
          : body;
    } catch {
      // Keep the raw response text when it is not JSON.
    }
    const error = new Error(message || `Avo API returned ${response.status}`);
    (error as Error & { status?: number }).status = response.status;
    throw error;
  }
  return response.json() as Promise<T>;
}

export const api = {
  authStatus: () => request<AuthStatus>('/api/auth/status'),
  bootstrapOptions: (code: string) => request<CeremonyOptions>('/api/auth/bootstrap/options', {
    method: 'POST',
    body: JSON.stringify({ code }),
  }),
  bootstrapVerify: (code: string, challengeId: string, credential: Record<string, unknown>) => request<SessionResponse>('/api/auth/bootstrap/verify', {
    method: 'POST',
    body: JSON.stringify({ code, challenge_id: challengeId, credential }),
  }),
  loginOptions: () => request<CeremonyOptions>('/api/auth/login/options', { method: 'POST' }),
  loginVerify: (challengeId: string, credential: Record<string, unknown>) => request<SessionResponse>('/api/auth/login/verify', {
    method: 'POST',
    body: JSON.stringify({ challenge_id: challengeId, credential }),
  }),
  registerOptions: () => request<CeremonyOptions>('/api/auth/register/options', { method: 'POST' }),
  registerVerify: (challengeId: string, credential: Record<string, unknown>) => request<{ ok: boolean; credential_id: string }>('/api/auth/register/verify', {
    method: 'POST',
    body: JSON.stringify({ challenge_id: challengeId, credential }),
  }),
  credentials: () => request<PasskeyCredential[]>('/api/auth/credentials'),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  health: () => request<{ ok: boolean; benchmark_root?: string; rp_id?: string; static_web?: boolean }>('/api/health'),
  chatMessages: () => request<ChatMessage[]>('/api/chat/messages'),
  sendChat: (content: string, autoExecute = true) => request<{ accepted: boolean; user_message_id: string; assistant_message_id: string }>('/api/chat/messages', {
    method: 'POST',
    body: JSON.stringify({ content, auto_execute: autoExecute }),
  }),
  runs: () => request<RunSummary[]>('/api/runs'),
  run: (id: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  start: (objective: string) => request<{ accepted: boolean; pid: number }>('/api/runs', {
    method: 'POST',
    body: JSON.stringify({ objective }),
  }),
  benchmarks: () => request<BenchmarkSummary[]>('/api/benchmarks'),
  benchmark: (id: string) => request<BenchmarkDetail>(`/api/benchmarks/${id.split('/').map(encodeURIComponent).join('/')}`),
  access: () => request<AccessStatus>('/api/access'),
  previewAccess: (yaml: string) => request<AccessPreview>('/api/access/preview', {
    method: 'POST',
    body: JSON.stringify({ yaml }),
  }),
  applyAccess: (yaml: string) => request<AccessApplyResult>('/api/access/apply', {
    method: 'POST',
    body: JSON.stringify({ yaml }),
  }),
  accessApprovalOptions: (approvalId: string) => request<CeremonyOptions>(`/api/access/approvals/${encodeURIComponent(approvalId)}/options`, { method: 'POST' }),
  verifyAccessApproval: (approvalId: string, challengeId: string, credential: Record<string, unknown>) => request<{ ok: boolean; status: AccessStatus }>(`/api/access/approvals/${encodeURIComponent(approvalId)}/verify`, {
    method: 'POST',
    body: JSON.stringify({ challenge_id: challengeId, credential }),
  }),
};
