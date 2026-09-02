export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
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
  setCounter: (name: "preorders" | "landing_clicks", value: number) =>
    req(`/api/counters/${name}`, { method: "PUT", body: JSON.stringify({ value }) }),
};
