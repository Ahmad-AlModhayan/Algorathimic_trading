export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "lab_admin_token";

export type PostStatus = "pending_review" | "approved" | "rejected" | "published" | "failed";

export interface Insight {
  id: string;
  kind: string;
  strategy: string;
  instrument: string;
  timeframe: string;
  rule_text: string;
  period_start: string;
  period_end: string;
  figures: Record<string, number | string | boolean>;
}

export interface Post {
  id: string;
  insight_id: string;
  template_id: string;
  text: string;
  status: PostStatus;
  created_at: string;
  scheduled_at: string | null;
  published_at: string | null;
  external_id: string | null;
  review_note: string | null;
  error: string | null;
}

export interface ReviewItem {
  post: Post;
  insight: Insight | null;
}

export interface Funnel {
  impressions: number;
  engagements: number;
  link_clicks: number;
  preorders: number;
  preorders_manual: number;
  preorder_target: number;
  posts_published: number;
  posts_pending: number;
}

export interface JobRun {
  id: string;
  job: string;
  started_at: string;
  finished_at: string | null;
  ok: boolean | null;
  detail: string;
}

export interface PublicResult {
  text: string;
  published_at: string | null;
}

export type Condition =
  | { type: "breakout"; n: number }
  | { type: "ma_cross"; fast: number; slow: number; kind: "sma" | "ema" }
  | { type: "rsi"; n: number; level: number; op: "<" | ">" };
export interface TrendFilter {
  type: "trend";
  n: number;
  kind: "sma" | "ema";
}
export interface Rule {
  name: string;
  style: "swing" | "intraday" | "scalp";
  timeframe: string;
  side: "long" | "short" | "both";
  entry: Condition[];
  filters: TrendFilter[];
  stop: { type: "atr"; n: number; mult: number } | { type: "pct"; pct: number };
  target: { type: "fixed_r"; r: number };
}
export interface Criterion {
  name: string;
  value: number;
  threshold: number;
  passed: boolean;
}
export interface BacktestResponse {
  rule_text: string;
  rule_text_ar: string;
  instrument: string;
  timeframe: string;
  bars: number;
  folds: { test_start: string; test_end: string; n_trades: number; expectancy_r: number; total_r: number }[];
  oos: Record<string, number>;
  criteria: Criterion[];
  meets_criteria: boolean;
}
export type Library = Record<string, { rule: Rule; text: string; text_ar: string }>;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {}
}

async function req<T>(path: string, init?: RequestInit, auth = true): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) {
    const t = getToken();
    if (t) headers.Authorization = `Bearer ${t}`;
  }
  const r = await fetch(`${API}${path}`, { ...init, headers: { ...headers, ...(init?.headers ?? {}) }, cache: "no-store" });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {}
    throw new ApiError(r.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json();
}

export const api = {
  review: () => req<ReviewItem[]>("/api/review"),
  calendar: (days = 14) => req<Record<string, Post[]>>(`/api/calendar?days=${days}`),
  funnel: () => req<Funnel>("/api/funnel"),
  jobs: () => req<JobRun[]>("/api/jobs"),
  approve: (id: string, body: { scheduled_at?: string | null; text?: string | null }) =>
    req<Post>(`/api/posts/${id}/approve`, { method: "POST", body: JSON.stringify(body) }),
  reject: (id: string, note: string) =>
    req<Post>(`/api/posts/${id}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  setCounter: (name: "preorders_manual" | "landing_clicks", value: number) =>
    req(`/api/counters/${name}`, { method: "PUT", body: JSON.stringify({ value }) }),
  labLibrary: () => req<Library>("/api/lab/library"),
  labBacktest: (rule: Rule, venue = "binance", symbol = "BTC/USDT") =>
    req<BacktestResponse>("/api/lab/backtest", { method: "POST", body: JSON.stringify({ rule, venue, symbol }) }),
  publicResults: (limit = 3) => req<PublicResult[]>(`/api/public/results?limit=${limit}`, undefined, false),
  landingEvent: (ref: string | null) =>
    req(`/api/public/landing`, { method: "POST", body: JSON.stringify({ ref }) }, false),
};
