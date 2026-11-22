"""The style sheet, read as text: what no browser test here can see. The rows of filter links on a phone (KI-74)."""

import re
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "style.css"
RULE = re.compile(r'\.filters a\[aria-current="true"\]\s*\{\s*order:\s*-1;\s*\}')


def narrow_blocks(css):
    """The bodies of the `@media (max-width: 40rem)` blocks, found by their braces."""
    bodies = []
    for start in re.finditer(r"@media \(max-width: 40rem\)\s*\{", css):
        depth, end = 1, start.end()
        while depth and end < len(css):
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        bodies.append(css[start.end():end - 1])
    return bodies


def test_the_chosen_filter_link_comes_first_in_its_row_under_40rem_only():
    css = CSS.read_text(encoding="utf-8")
    blocks = narrow_blocks(css)

    assert sum(len(RULE.findall(body)) for body in blocks) == 1
    for body in blocks:
        css = css.replace(body, "")
    assert not RULE.search(css)  # on a computer the order is as it was
