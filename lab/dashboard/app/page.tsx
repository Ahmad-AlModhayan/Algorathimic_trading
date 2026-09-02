import Link from "next/link";
import LandingPing from "@/components/LandingPing";
import copy from "@/content/landing.ar.json";
import { API, type PublicResult } from "@/lib/api";

const CHECKOUT = process.env.NEXT_PUBLIC_CHECKOUT_URL ?? "";
const PRICE = process.env.NEXT_PUBLIC_PREORDER_PRICE ?? "";
const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME ?? "مختبر الاستراتيجيات";

export const dynamic = "force-dynamic";

async function latestResults(): Promise<PublicResult[]> {
  try {
    const r = await fetch(`${API}/api/public/results?limit=3`, { cache: "no-store" });
    if (!r.ok) return [];
    return (await r.json()) as PublicResult[];
  } catch {
    return [];
  }
}

function Cta({ label }: { label: string }) {
  if (!CHECKOUT) {
    return <span className="inline-block rounded-md bg-zinc-200 px-5 py-3 text-zinc-600">{copy.preorder.unavailable}</span>;
  }
  return (
    <a
      href={CHECKOUT}
      className="inline-block rounded-md bg-emerald-600 px-5 py-3 font-semibold text-white hover:bg-emerald-700"
    >
      {label}
    </a>
  );
}

export default async function Landing() {
  const results = await latestResults();
  return (
    <main className="mx-auto max-w-4xl space-y-20 px-6 py-12">
      <LandingPing />

      <section className="space-y-5">
        <div className="text-sm font-semibold text-emerald-700">{copy.hero.eyebrow}</div>
        <h1 className="text-3xl font-bold leading-snug md:text-4xl">{copy.hero.title}</h1>
        <p className="max-w-2xl text-lg leading-relaxed text-zinc-600">{copy.hero.subtitle}</p>
        <div className="flex flex-wrap items-center gap-4">
          <Cta label={copy.hero.cta} />
          {PRICE && <span className="text-lg font-semibold tabular-nums">{PRICE}</span>}
        </div>
        <p className="text-xs text-zinc-500">{copy.hero.cta_note}</p>
      </section>

      <section>
        <h2 className="mb-6 text-2xl font-bold">{copy.how.title}</h2>
        <ol className="grid gap-4 md:grid-cols-3">
          {copy.how.steps.map((s) => (
            <li key={s.n} className="rounded-lg border border-zinc-200 bg-white p-5">
              <div className="mb-2 text-2xl font-bold text-emerald-700">{s.n}</div>
              <div className="mb-1 font-semibold">{s.title}</div>
              <p className="text-sm leading-relaxed text-zinc-600">{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className="mb-6 text-2xl font-bold">{copy.what.title}</h2>
        <ul className="grid gap-3 md:grid-cols-2">
          {copy.what.items.map((item) => (
            <li key={item} className="flex gap-3 rounded-lg border border-zinc-200 bg-white p-4 text-sm leading-relaxed">
              <span className="text-emerald-700">✓</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-2 text-2xl font-bold">{copy.results.title}</h2>
        <p className="mb-6 text-zinc-600">{copy.results.subtitle}</p>
        <div className="grid gap-4 md:grid-cols-3">
          {results.length === 0 && (
            <figure className="rounded-lg border border-zinc-200 bg-white p-4 md:col-span-1">
              <pre className="whitespace-pre-wrap font-sans text-sm leading-7">{copy.results.example}</pre>
              <figcaption className="mt-2 text-xs text-zinc-400">{copy.results.example_label}</figcaption>
            </figure>
          )}
          {results.map((r, i) => (
            <figure key={i} className="rounded-lg border border-zinc-200 bg-white p-4">
              <pre className="whitespace-pre-wrap font-sans text-sm leading-7">{r.text}</pre>
              {r.published_at && (
                <figcaption className="mt-2 text-xs text-zinc-400 tabular-nums">
                  {new Date(r.published_at).toLocaleDateString("ar-SA")}
                </figcaption>
              )}
            </figure>
          ))}
        </div>
        {results.length === 0 && <p className="mt-3 text-sm text-zinc-500">{copy.results.empty}</p>}
      </section>

      <section id="preorder" className="rounded-xl border border-emerald-200 bg-emerald-50 p-8">
        <h2 className="mb-2 text-2xl font-bold">{copy.preorder.title}</h2>
        <div className="mb-4 flex items-baseline gap-3">
          {PRICE && <span className="text-3xl font-bold tabular-nums">{PRICE}</span>}
          <span className="text-sm text-zinc-600">{copy.preorder.price_label}</span>
        </div>
        <ul className="mb-6 space-y-2 text-sm">
          {copy.preorder.includes.map((item) => (
            <li key={item} className="flex gap-2">
              <span className="text-emerald-700">•</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
        <Cta label={copy.preorder.cta} />
        <p className="mt-4 text-xs text-zinc-600">{copy.preorder.counter_label}</p>
      </section>

      <section>
        <h2 className="mb-6 text-2xl font-bold">{copy.faq.title}</h2>
        <div className="space-y-3">
          {copy.faq.items.map((f) => (
            <details key={f.q} className="rounded-lg border border-zinc-200 bg-white p-4">
              <summary className="cursor-pointer font-semibold">{f.q}</summary>
              <p className="mt-2 text-sm leading-relaxed text-zinc-600">{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      <footer className="space-y-3 border-t border-zinc-200 pt-6 text-xs text-zinc-500">
        <p>{copy.footer.disclaimer}</p>
        <div className="flex items-center justify-between">
          <span>{BRAND}</span>
          <span className="flex gap-4">
            <Link href="/lab" className="hover:underline">
              المختبر
            </Link>
            <Link href="/admin" className="hover:underline">
              {copy.footer.admin}
            </Link>
          </span>
        </div>
      </footer>
    </main>
  );
}
