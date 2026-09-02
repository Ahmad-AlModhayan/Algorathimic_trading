"""Arabic post templates. Numbers in, sentences out, `lint_language()` on the way out.

Wording rules: results, not advice. "الإعداد يطابق القاعدة" never "اشتري". A failed gate is
content too: it shows the product does what it says.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from content.models import Insight, InsightKind, Post
from core.language import lint_language

X_MAX_CHARS = 280

DISCLAIMER = "نتيجة تاريخية لقاعدة محددة بعد الرسوم والانزلاق. لا تضمن نتائج مستقبلية."


@dataclass(frozen=True)
class Template:
    id: str
    kind: InsightKind
    body: str  # str.format placeholders from Insight.figures + header fields


TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in (
        Template(
            "result_v1",
            "result_summary",
            "{instrument} · {timeframe}\n"
            "القاعدة: {rule_text}\n"
            "{period}\n"
            "إعدادات مطابقة: {n_trades} · نسبة الربح {win_rate_pct}٪\n"
            "معامل الربح {profit_factor} · الصافي {total_r}R · أقصى تراجع {max_dd_pct}٪\n"
            "{disclaimer}",
        ),
        Template(
            "result_v2",
            "result_summary",
            "هل تصمد قاعدة «{rule_text}» على {instrument}؟\n"
            "{period} · {timeframe}\n"
            "{n_trades} إعداداً مطابقاً، {win_rate_pct}٪ منها رابح.\n"
            "الصافي بعد الرسوم: {total_r}R. أقصى تراجع: {max_dd_pct}٪.\n"
            "{disclaimer}",
        ),
        Template(
            "fees_v1",
            "fees_impact",
            "أثر الرسوم على {instrument} · {timeframe}\n"
            "القاعدة: {rule_text}\n"
            "قبل الرسوم: {gross_r}R · الرسوم: {fees_r}R · بعد الرسوم: {net_r}R\n"
            "الرسوم أكلت {fees_share_pct}٪ من النتيجة على {n_trades} إعداداً.\n"
            "{disclaimer}",
        ),
        Template(
            "gate_v1",
            "gate_outcome",
            "اختبار القبول · {instrument} · {timeframe}\n"
            "{rule_text}\n"
            "معامل الربح {profit_factor}/{profit_factor_threshold} · "
            "تراجع {max_drawdown_pct}/{max_drawdown_pct_threshold}٪ · "
            "إعدادات {n_trades}/{n_trades_threshold} · "
            "فترات إيجابية {positive_fold_share}/{positive_fold_share_threshold}\n"
            "{verdict}\n"
            "{disclaimer}",
        ),
        Template(
            "spread_v1",
            "fold_spread",
            "القاعدة نفسها، فترات مختلفة: {instrument} · {timeframe}\n"
            "{rule_text}\n"
            "{positive_folds} من {n_folds} فترات خارج العينة إيجابية.\n"
            "أفضل فترة {best_period}: {best_r}R · أسوأ فترة {worst_period}: {worst_r}R\n"
            "{disclaimer}",
        ),
    )
}


def templates_for(kind: InsightKind) -> list[Template]:
    return [t for t in TEMPLATES.values() if t.kind == kind]


def _period(start: datetime, end: datetime) -> str:
    return f"{start:%Y-%m} → {end:%Y-%m}"


def render(insight: Insight, template: Template) -> str:
    if template.kind != insight.kind:
        raise ValueError(
            f"template {template.id} is for {template.kind}, insight is {insight.kind}"
        )
    fields = {
        "instrument": insight.instrument.split(":")[-1],
        "timeframe": insight.timeframe,
        "rule_text": insight.rule_text,
        "period": _period(insight.period_start, insight.period_end),
        "disclaimer": DISCLAIMER,
        **insight.figures,
    }
    if insight.kind == "gate_outcome":
        fields["verdict"] = (
            "اجتازت كل المعايير"
            if insight.figures.get("passed")
            else (f"لم تجتز: {insight.figures.get('failed')}")
        )
    return template.body.format(**fields)


def compose_post(insight: Insight, template: Template | None = None) -> Post:
    """Render, lint, and length-check. Raises on advice language or overlong text."""
    template = template or templates_for(insight.kind)[0]
    text = lint_language(render(insight, template))
    if len(text) > X_MAX_CHARS:
        raise ValueError(f"post is {len(text)} chars, limit {X_MAX_CHARS}: {template.id}")
    return Post(insight_id=insight.id, template_id=template.id, text=text)


def compose_all(insights: list[Insight], pick: dict[InsightKind, str] | None = None) -> list[Post]:
    """One post per insight. `pick` maps kind -> template id; default is the first template."""
    posts = []
    for ins in insights:
        tid = (pick or {}).get(ins.kind)
        posts.append(compose_post(ins, TEMPLATES[tid] if tid else None))
    return posts
