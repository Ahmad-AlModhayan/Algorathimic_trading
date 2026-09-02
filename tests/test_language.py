import pytest

from core.language import LanguageViolationError, find_banned, lint_language


def test_clean_text_passes():
    txt = (
        "BTC/USDT 4h: breakout(20) met your rule 37 times over 3 years. "
        "Net result after fees: +12.4%."
    )
    assert lint_language(txt) == txt
    assert lint_language("النتيجة بعد الرسوم: ١٢٪. الإعداد يطابق قاعدتك.") is not None


def test_advice_words_blocked_english():
    with pytest.raises(LanguageViolationError) as e:
        lint_language("We recommend you BUY here, strong signal.")
    assert set(e.value.terms) == {"recommend", "buy", "signal"}


def test_advice_words_blocked_arabic():
    with pytest.raises(LanguageViolationError):
        lint_language("توصية اليوم: اشتري بيتكوين")


def test_whole_word_only():
    assert find_banned("the buyer sees the result; signalling is fine") == ()
    assert find_banned("sell-off continues") == ("sell",)
