import pytest

from content.insights import extract_insights
from content.models import Insight
from content.templates import (
    TEMPLATES,
    X_MAX_CHARS,
    compose_all,
    compose_post,
    render,
    templates_for,
)
from core.language import LanguageViolationError
from tests.content_helpers import sample_insight, wf_result


def test_extract_insights_covers_all_kinds():
    ins = extract_insights(wf_result(), "4h")
    kinds = {i.kind for i in ins}
    assert kinds == {"result_summary", "fees_impact", "gate_outcome", "fold_spread"}
    rs = next(i for i in ins if i.kind == "result_summary")
    assert rs.figures["n_trades"] == 15 and rs.figures["n_folds"] == 3
    assert rs.instrument == "binance:BTC/USDT" and rs.timeframe == "4h"
    assert rs.rule_text.startswith("close > high(20)")
    gate = next(i for i in ins if i.kind == "gate_outcome")
    assert gate.figures["passed"] is False and "n_trades" in str(gate.figures["failed"])


def test_extract_insights_empty_when_no_folds():
    wf = wf_result()
    wf.folds.clear()
    assert extract_insights(wf, "4h") == []


@pytest.mark.parametrize("template_id", list(TEMPLATES))
def test_every_template_renders_clean_and_within_limit(template_id):
    t = TEMPLATES[template_id]
    post = compose_post(sample_insight(t.kind), t)
    assert post.template_id == template_id and post.status == "pending_review"
    assert len(post.text) <= X_MAX_CHARS
    assert "{" not in post.text and "}" not in post.text
    assert "BTC/USDT" in post.text and "4h" in post.text


def test_template_kind_mismatch_rejected():
    with pytest.raises(ValueError):
        render(sample_insight("fees_impact"), templates_for("result_summary")[0])


def test_advice_language_is_blocked_at_compose():
    bad = Insight(
        kind="result_summary",
        strategy="s",
        instrument="binance:BTC/USDT",
        timeframe="4h",
        rule_text="اشتري عند الاختراق",
        period_start=sample_insight().period_start,
        period_end=sample_insight().period_end,
        figures=sample_insight().figures,
    )
    with pytest.raises(LanguageViolationError):
        compose_post(bad)


def test_compose_all_respects_pick():
    ins = extract_insights(wf_result(), "4h")
    posts = compose_all(ins, pick={"result_summary": "result_v2"})
    by_kind = {p.template_id for p in posts}
    assert "result_v2" in by_kind and "result_v1" not in by_kind
    assert len(posts) == len(ins)


def test_gate_verdict_wording():
    passed = sample_insight("gate_outcome")
    passed.figures["passed"] = True
    assert "اجتازت" in compose_post(passed).text
    assert "لم تجتز" in compose_post(sample_insight("gate_outcome")).text
