"use client";

import { useCallback, useEffect, useState } from "react";
import TokenGate from "@/components/TokenGate";
import { ApiError, api, getToken, setToken, type Funnel, type JobRun, type Post, type ReviewItem } from "@/lib/api";

const STATUS_AR: Record<Post["status"], string> = {
  pending_review: "بانتظار المراجعة",
  approved: "معتمد",
  rejected: "مرفوض",
  published: "منشور",
  failed: "فشل",
};

function fmt(dt: string | null | undefined) {
  if (!dt) return "—";
  return new Date(dt).toLocaleString("ar-SA", { dateStyle: "medium", timeStyle: "short" });
}

function toLocalInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function Dashboard() {
  const [review, setReview] = useState<ReviewItem[]>([]);
  const [calendar, setCalendar] = useState<Record<string, Post[]>>({});
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [jobs, setJobs] = useState<JobRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [needToken, setNeedToken] = useState(false);

  const load = useCallback(async () => {
    if (!getToken()) {
      setNeedToken(true);
      return;
    }
    try {
      const [r, c, f, j] = await Promise.all([api.review(), api.calendar(), api.funnel(), api.jobs()]);
      setReview(r);
      setCalendar(c);
      setFunnel(f);
      setJobs(j);
      setError(null);
      setNeedToken(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setToken(null);
        setNeedToken(true);
        return;
      }
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(load, 0);
    const t = setInterval(load, 30_000);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [load]);

  return (
    <main className="mx-auto max-w-6xl space-y-10 p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">لوحة المحتوى</h1>
        <span className="text-sm text-zinc-500">لا يُنشر شيء بدون اعتماد يدوي</span>
      </header>
      {needToken && <TokenGate onSaved={load} />}
      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          تعذر الاتصال بالواجهة الخلفية: {error}
        </div>
      )}

      <FunnelSection funnel={funnel} onChange={load} />
      <ReviewSection items={review} onChange={load} />
      <CalendarSection calendar={calendar} />
      <JobsSection jobs={jobs} />
    </main>
  );
}

function Tile({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4">
      <div className="text-sm text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-zinc-400">{sub}</div>}
    </div>
  );
}

function FunnelSection({ funnel, onChange }: { funnel: Funnel | null; onChange: () => void }) {
  const [preorders, setPreorders] = useState<string>("");
  if (!funnel) return null;
  const pct = Math.min(100, Math.round((100 * funnel.preorders) / Math.max(1, funnel.preorder_target)));
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">القمع</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Tile label="منشورات" value={funnel.posts_published} sub={`${funnel.posts_pending} بانتظار المراجعة`} />
        <Tile label="مشاهدات" value={funnel.impressions.toLocaleString("ar-SA")} />
        <Tile label="تفاعلات" value={funnel.engagements.toLocaleString("ar-SA")} />
        <Tile label="نقرات الصفحة" value={funnel.link_clicks.toLocaleString("ar-SA")} />
        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <div className="text-sm text-zinc-500">الطلبات المسبقة المدفوعة</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">
            {funnel.preorders} / {funnel.preorder_target}
          </div>
          <div className="mt-2 h-2 w-full rounded bg-zinc-100">
            <div className="h-2 rounded bg-emerald-500" style={{ width: `${pct}%` }} />
          </div>
          <form
            className="mt-2 flex gap-1"
            onSubmit={async (e) => {
              e.preventDefault();
              const v = parseInt(preorders, 10);
              if (Number.isNaN(v)) return;
              await api.setCounter("preorders_manual", v);
              setPreorders("");
              onChange();
            }}
          >
            <input
              className="w-16 rounded border border-zinc-300 px-1 text-sm"
              inputMode="numeric"
              placeholder={`يدوي: ${funnel.preorders_manual}`}
              value={preorders}
              onChange={(e) => setPreorders(e.target.value)}
            />
            <button className="rounded bg-zinc-800 px-2 text-xs text-white">حفظ</button>
          </form>
        </div>
      </div>
    </section>
  );
}

function ReviewSection({ items, onChange }: { items: ReviewItem[]; onChange: () => void }) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">قائمة المراجعة ({items.length})</h2>
      {items.length === 0 && <p className="text-sm text-zinc-500">لا منشورات بانتظار المراجعة.</p>}
      <div className="grid gap-4 md:grid-cols-2">
        {items.map((it) => (
          <ReviewCard key={it.post.id} item={it} onChange={onChange} />
        ))}
      </div>
    </section>
  );
}

function ReviewCard({ item, onChange }: { item: ReviewItem; onChange: () => void }) {
  const { post, insight } = item;
  const [text, setText] = useState(post.text);
  const [when, setWhen] = useState(() => toLocalInput(new Date(Date.now() + 60 * 60 * 1000)));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-zinc-200 bg-white p-4">
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>
          {insight?.instrument.split(":").pop()} · {insight?.timeframe} · {insight?.kind}
        </span>
        <span>{post.template_id}</span>
      </div>
      <textarea
        className="post-preview min-h-40 w-full rounded border border-zinc-200 bg-zinc-50 p-3 text-sm"
        value={text}
        onChange={(e) => setText(e.target.value)}
        dir="rtl"
      />
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>{text.length} / 280</span>
        <span>{insight?.strategy}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-zinc-500">موعد النشر</label>
        <input
          type="datetime-local"
          className="rounded border border-zinc-300 px-2 py-1 text-sm"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
        />
        <button
          disabled={busy}
          className="rounded bg-emerald-600 px-3 py-1 text-sm text-white disabled:opacity-50"
          onClick={() =>
            run(() =>
              api.approve(post.id, {
                scheduled_at: new Date(when).toISOString(),
                text: text !== post.text ? text : null,
              }),
            )
          }
        >
          اعتماد
        </button>
        <button
          disabled={busy}
          className="rounded border border-zinc-300 px-3 py-1 text-sm disabled:opacity-50"
          onClick={() => run(() => api.reject(post.id, ""))}
        >
          رفض
        </button>
      </div>
      {err && <div className="text-xs text-red-700">{err}</div>}
    </article>
  );
}

function CalendarSection({ calendar }: { calendar: Record<string, Post[]> }) {
  const days = Object.keys(calendar);
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">التقويم</h2>
      {days.length === 0 && <p className="text-sm text-zinc-500">لا منشورات معتمدة أو منشورة في هذه الفترة.</p>}
      <div className="space-y-3">
        {days.map((d) => (
          <div key={d} className="rounded-lg border border-zinc-200 bg-white p-3">
            <div className="mb-2 text-sm font-semibold tabular-nums">{d}</div>
            <ul className="space-y-1 text-sm">
              {calendar[d].map((p) => (
                <li key={p.id} className="flex items-center gap-2">
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${
                      p.status === "published" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
                    }`}
                  >
                    {STATUS_AR[p.status]}
                  </span>
                  <span className="text-zinc-500 tabular-nums">{fmt(p.published_at ?? p.scheduled_at)}</span>
                  <span className="truncate">{p.text.split("\n")[0]}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function JobsSection({ jobs }: { jobs: JobRun[] }) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">حالة المهام</h2>
      <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-zinc-500">
            <tr>
              <th className="p-2 text-right">المهمة</th>
              <th className="p-2 text-right">البداية</th>
              <th className="p-2 text-right">الحالة</th>
              <th className="p-2 text-right">التفاصيل</th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && (
              <tr>
                <td className="p-2 text-zinc-500" colSpan={4}>
                  لم تُشغَّل أي مهمة بعد.
                </td>
              </tr>
            )}
            {jobs.map((j) => (
              <tr key={j.id} className="border-t border-zinc-100">
                <td className="p-2">{j.job}</td>
                <td className="p-2 tabular-nums">{fmt(j.started_at)}</td>
                <td className="p-2">
                  {j.ok === null ? "قيد التشغيل" : j.ok ? "نجحت" : "فشلت"}
                </td>
                <td className="p-2 font-mono text-xs text-zinc-600" dir="ltr">
                  {j.detail.split("\n")[0].slice(0, 120)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
