"use client";

import { useCallback, useEffect, useState } from "react";
import TokenGate from "@/components/TokenGate";
import { ApiError, api, getToken, setToken, type BacktestResponse, type Condition, type Library, type Rule } from "@/lib/api";

const STYLE_AR = { swing: "متأرجح", intraday: "يومي", scalp: "سريع" } as const;
const TF_BY_STYLE = { swing: ["4h", "1d"], intraday: ["1h", "15m"], scalp: ["15m", "5m"] } as const;
const METRIC_AR: Record<string, string> = {
  n_trades: "الإعدادات المطابقة",
  win_rate: "نسبة الربح",
  profit_factor: "معامل الربح",
  expectancy_r: "التوقّع (R)",
  total_r: "الصافي (R)",
  max_drawdown_pct: "أقصى تراجع ٪",
};
const CRITERION_AR: Record<string, string> = {
  profit_factor: "معامل الربح",
  max_drawdown_pct: "أقصى تراجع ٪",
  n_trades: "عدد الإعدادات",
  positive_fold_share: "نسبة الفترات الإيجابية",
};

const DEFAULT_RULE: Rule = {
  name: "my_rule",
  style: "swing",
  timeframe: "4h",
  side: "long",
  entry: [{ type: "breakout", n: 20 }],
  filters: [],
  stop: { type: "atr", n: 14, mult: 2 },
  target: { type: "fixed_r", r: 2 },
};

function num(v: string, fallback: number) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export default function Lab() {
  const [rule, setRule] = useState<Rule>(DEFAULT_RULE);
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [library, setLibrary] = useState<Library>({});
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needToken, setNeedToken] = useState(false);

  const loadLibrary = useCallback(async () => {
    if (!getToken()) {
      setNeedToken(true);
      return;
    }
    try {
      setLibrary(await api.labLibrary());
      setNeedToken(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setToken(null);
        setNeedToken(true);
      }
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(loadLibrary, 0);
    return () => clearTimeout(t);
  }, [loadLibrary]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.labBacktest(rule, "binance", symbol));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const update = (patch: Partial<Rule>) => setRule((r) => ({ ...r, ...patch }));
  const setEntry = (i: number, c: Condition) => update({ entry: rule.entry.map((x, j) => (j === i ? c : x)) });

  return (
    <main className="mx-auto max-w-5xl space-y-8 p-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">المختبر: اكتب قاعدتك واختبرها</h1>
        <span className="text-sm text-zinc-500">نتيجة تاريخية خارج العينة، بعد الرسوم والانزلاق</span>
      </header>
      {needToken && <TokenGate onSaved={loadLibrary} />}

      <section className="grid gap-6 md:grid-cols-[1fr_1.2fr]">
        <form
          className="space-y-4 rounded-lg border border-zinc-200 bg-white p-4"
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
        >
          <div className="flex flex-wrap gap-2 text-sm">
            <span className="text-zinc-500">ابدأ من قاعدة جاهزة:</span>
            {Object.entries(library).map(([k, v]) => (
              <button
                key={k}
                type="button"
                className="rounded border border-zinc-300 px-2 py-0.5 hover:bg-zinc-50"
                onClick={() => setRule(v.rule)}
              >
                {STYLE_AR[v.rule.style]} · {k}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <label className="space-y-1">
              <span className="text-zinc-500">الاسم (لاتيني)</span>
              <input
                className="w-full rounded border border-zinc-300 px-2 py-1"
                dir="ltr"
                value={rule.name}
                pattern="^[a-z][a-z0-9_]{1,40}$"
                onChange={(e) => update({ name: e.target.value })}
              />
            </label>
            <label className="space-y-1">
              <span className="text-zinc-500">الأداة</span>
              <select className="w-full rounded border border-zinc-300 px-2 py-1" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
                {["BTC/USDT", "ETH/USDT", "SOL/USDT"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-zinc-500">الأسلوب</span>
              <select
                className="w-full rounded border border-zinc-300 px-2 py-1"
                value={rule.style}
                onChange={(e) => {
                  const style = e.target.value as Rule["style"];
                  update({ style, timeframe: TF_BY_STYLE[style][0] });
                }}
              >
                {(Object.keys(STYLE_AR) as Rule["style"][]).map((s) => (
                  <option key={s} value={s}>
                    {STYLE_AR[s]}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-zinc-500">الإطار الزمني</span>
              <select className="w-full rounded border border-zinc-300 px-2 py-1" value={rule.timeframe} onChange={(e) => update({ timeframe: e.target.value })}>
                {TF_BY_STYLE[rule.style].map((tf) => (
                  <option key={tf}>{tf}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-zinc-500">الاتجاه</span>
              <select className="w-full rounded border border-zinc-300 px-2 py-1" value={rule.side} onChange={(e) => update({ side: e.target.value as Rule["side"] })}>
                <option value="long">صعود</option>
                <option value="short">هبوط</option>
                <option value="both">الاتجاهان</option>
              </select>
            </label>
          </div>

          <fieldset className="space-y-2 text-sm">
            <legend className="font-semibold">شروط الدخول (كلها معاً)</legend>
            {rule.entry.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 rounded border border-zinc-100 bg-zinc-50 p-2">
                <select
                  className="rounded border border-zinc-300 px-2 py-1"
                  value={c.type}
                  onChange={(e) => {
                    const t = e.target.value;
                    setEntry(
                      i,
                      t === "breakout" ? { type: "breakout", n: 20 } : t === "ma_cross" ? { type: "ma_cross", fast: 20, slow: 50, kind: "sma" } : { type: "rsi", n: 14, level: 30, op: "<" },
                    );
                  }}
                >
                  <option value="breakout">اختراق أعلى N شمعة</option>
                  <option value="ma_cross">تقاطع متوسطين</option>
                  <option value="rsi">مؤشر القوة النسبية</option>
                </select>
                {c.type === "breakout" && (
                  <label>
                    N <input className="w-16 rounded border border-zinc-300 px-1" type="number" min={2} max={500} value={c.n} onChange={(e) => setEntry(i, { ...c, n: num(e.target.value, 20) })} />
                  </label>
                )}
                {c.type === "ma_cross" && (
                  <>
                    <label>
                      سريع <input className="w-16 rounded border border-zinc-300 px-1" type="number" min={2} value={c.fast} onChange={(e) => setEntry(i, { ...c, fast: num(e.target.value, 20) })} />
                    </label>
                    <label>
                      بطيء <input className="w-16 rounded border border-zinc-300 px-1" type="number" min={3} value={c.slow} onChange={(e) => setEntry(i, { ...c, slow: num(e.target.value, 50) })} />
                    </label>
                    <select className="rounded border border-zinc-300 px-1 py-1" value={c.kind} onChange={(e) => setEntry(i, { ...c, kind: e.target.value as "sma" | "ema" })}>
                      <option value="sma">بسيط</option>
                      <option value="ema">أسي</option>
                    </select>
                  </>
                )}
                {c.type === "rsi" && (
                  <>
                    <label>
                      N <input className="w-16 rounded border border-zinc-300 px-1" type="number" min={2} value={c.n} onChange={(e) => setEntry(i, { ...c, n: num(e.target.value, 14) })} />
                    </label>
                    <select className="rounded border border-zinc-300 px-1 py-1" value={c.op} onChange={(e) => setEntry(i, { ...c, op: e.target.value as "<" | ">" })}>
                      <option value="<">أقل من</option>
                      <option value=">">أكبر من</option>
                    </select>
                    <input className="w-16 rounded border border-zinc-300 px-1" type="number" min={1} max={99} value={c.level} onChange={(e) => setEntry(i, { ...c, level: num(e.target.value, 30) })} />
                  </>
                )}
                {rule.entry.length > 1 && (
                  <button type="button" className="text-red-700" onClick={() => update({ entry: rule.entry.filter((_, j) => j !== i) })}>
                    حذف
                  </button>
                )}
              </div>
            ))}
            {rule.entry.length < 4 && (
              <button type="button" className="text-emerald-700" onClick={() => update({ entry: [...rule.entry, { type: "rsi", n: 14, level: 30, op: "<" }] })}>
                + شرط
              </button>
            )}
          </fieldset>

          <fieldset className="space-y-2 text-sm">
            <legend className="font-semibold">فلتر الاتجاه</legend>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={rule.filters.length > 0}
                onChange={(e) => update({ filters: e.target.checked ? [{ type: "trend", n: 200, kind: "sma" }] : [] })}
              />
              الإغلاق فوق المتوسط
              {rule.filters[0] && (
                <input className="w-20 rounded border border-zinc-300 px-1" type="number" min={2} value={rule.filters[0].n} onChange={(e) => update({ filters: [{ ...rule.filters[0], n: num(e.target.value, 200) }] })} />
              )}
            </label>
          </fieldset>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <fieldset className="space-y-1">
              <legend className="font-semibold">الوقف</legend>
              <select
                className="w-full rounded border border-zinc-300 px-2 py-1"
                value={rule.stop.type}
                onChange={(e) => update({ stop: e.target.value === "atr" ? { type: "atr", n: 14, mult: 2 } : { type: "pct", pct: 2 } })}
              >
                <option value="atr">مضاعف ATR</option>
                <option value="pct">نسبة مئوية</option>
              </select>
              {rule.stop.type === "atr" ? (
                <div className="flex gap-2">
                  <label>
                    N <input className="w-16 rounded border border-zinc-300 px-1" type="number" min={2} value={rule.stop.n} onChange={(e) => update({ stop: { type: "atr", n: num(e.target.value, 14), mult: (rule.stop as { mult: number }).mult } })} />
                  </label>
                  <label>
                    × <input className="w-16 rounded border border-zinc-300 px-1" type="number" step="0.1" min={0.1} value={rule.stop.mult} onChange={(e) => update({ stop: { type: "atr", n: (rule.stop as { n: number }).n, mult: num(e.target.value, 2) } })} />
                  </label>
                </div>
              ) : (
                <label>
                  ٪ <input className="w-16 rounded border border-zinc-300 px-1" type="number" step="0.1" min={0.1} value={rule.stop.pct} onChange={(e) => update({ stop: { type: "pct", pct: num(e.target.value, 2) } })} />
                </label>
              )}
            </fieldset>
            <fieldset className="space-y-1">
              <legend className="font-semibold">الهدف</legend>
              <label>
                R <input className="w-16 rounded border border-zinc-300 px-1" type="number" step="0.5" min={0.5} value={rule.target.r} onChange={(e) => update({ target: { type: "fixed_r", r: num(e.target.value, 2) } })} />
              </label>
            </fieldset>
          </div>

          <button disabled={busy} className="rounded bg-emerald-600 px-4 py-2 font-semibold text-white disabled:opacity-50">
            {busy ? "يعمل…" : "اختبر القاعدة"}
          </button>
          {error && <div className="text-sm text-red-700">{error}</div>}
        </form>

        <section className="space-y-4">
          {!result && <p className="text-sm text-zinc-500">النتيجة تظهر هنا: الفترات خارج العينة، المقاييس، ومعايير القبول.</p>}
          {result && (
            <>
              <div className="rounded-lg border border-zinc-200 bg-white p-4">
                <div className="text-sm text-zinc-500">{result.instrument} · {result.timeframe} · {result.bars} شمعة</div>
                <div className="mt-1 font-semibold">{result.rule_text_ar}</div>
                <div className="mt-1 font-mono text-xs text-zinc-500" dir="ltr">{result.rule_text}</div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(METRIC_AR).map(([k, label]) => (
                  <div key={k} className="rounded-lg border border-zinc-200 bg-white p-3">
                    <div className="text-xs text-zinc-500">{label}</div>
                    <div className="text-lg font-semibold tabular-nums">
                      {k === "win_rate" ? `${(result.oos[k] * 100).toFixed(1)}٪` : Number(result.oos[k]).toFixed(k === "n_trades" ? 0 : 2)}
                    </div>
                  </div>
                ))}
              </div>
              <div className={`rounded-lg border p-4 ${result.meets_criteria ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
                <div className="mb-2 font-semibold">{result.meets_criteria ? "تحقق معايير القبول على هذه الأداة" : "لا تحقق معايير القبول على هذه الأداة"}</div>
                <ul className="space-y-1 text-sm">
                  {result.criteria.map((c) => (
                    <li key={c.name} className="flex justify-between tabular-nums">
                      <span>{c.passed ? "✓" : "✗"} {CRITERION_AR[c.name] ?? c.name}</span>
                      <span>
                        {c.value.toFixed(2)} / {c.threshold}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-zinc-600">التفعيل الكامل يتطلب ثلاث أدوات وفترتي صعود وهبوط.</p>
              </div>
              <table className="w-full rounded-lg border border-zinc-200 bg-white text-sm">
                <thead className="text-zinc-500">
                  <tr>
                    <th className="p-2 text-right">فترة الاختبار</th>
                    <th className="p-2 text-right">إعدادات</th>
                    <th className="p-2 text-right">التوقّع R</th>
                    <th className="p-2 text-right">الصافي R</th>
                  </tr>
                </thead>
                <tbody>
                  {result.folds.map((f) => (
                    <tr key={f.test_start} className="border-t border-zinc-100 tabular-nums">
                      <td className="p-2">
                        {f.test_start.slice(0, 7)} → {f.test_end.slice(0, 7)}
                      </td>
                      <td className="p-2">{f.n_trades}</td>
                      <td className={`p-2 ${f.expectancy_r > 0 ? "text-emerald-700" : "text-red-700"}`}>{f.expectancy_r.toFixed(3)}</td>
                      <td className="p-2">{f.total_r.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </section>
    </main>
  );
}
