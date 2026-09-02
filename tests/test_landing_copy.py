"""Landing copy is user-facing: every string passes lint_language()."""

import json
from pathlib import Path

from core.language import lint_language

COPY = Path("lab/dashboard/content/landing.ar.json")


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def test_landing_copy_is_clean_and_complete():
    data = json.loads(COPY.read_text(encoding="utf-8"))
    strings = list(_strings(data))
    assert len(strings) > 20
    for s in strings:
        lint_language(s)
    for key in ("hero", "how", "what", "results", "preorder", "faq", "footer"):
        assert key in data, key
