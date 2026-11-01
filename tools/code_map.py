r"""The list of the modules of `app/` in `docs/code-map.md`, built from their docstrings.

Run it from the repository root after adding, renaming or describing a module:

    .venv\Scripts\python.exe tools\code_map.py

`--check` changes nothing and exits with 1 when the file is out of date (`tests/test_code_map.py` does the same).
A module is described by the first sentence of its docstring, so that sentence says what the module holds.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "docs" / "code-map.md"
START = "<!-- code-map:start (built by tools/code_map.py from the docstrings; do not edit by hand) -->"
END = "<!-- code-map:end -->"
MAX_SUMMARY = 200

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z«`(])")
_BLOCK = re.compile(r"(<!-- code-map:start[^\n]*-->\n)(.*?)(<!-- code-map:end -->)", re.S)


def summary(source: str) -> str | None:
    """The first sentence of the module docstring on one line; None when there is no docstring."""
    doc = ast.get_docstring(ast.parse(source))
    if not doc:
        return None
    text = " ".join(doc.split("\n\n", 1)[0].split())
    return _SENTENCE_END.split(text, maxsplit=1)[0] if text else None


def modules(app_dir: Path = ROOT / "app") -> list[tuple[str, str | None]]:
    """Every module of the application (not `__init__.py`) with its summary, in the order of the paths."""
    found = []
    for path in sorted(app_dir.rglob("*.py")):
        if path.name == "__init__.py" or "__pycache__" in path.parts:
            continue
        found.append((path.relative_to(app_dir.parent).as_posix(), summary(path.read_text(encoding="utf-8"))))
    return sorted(found)


def render(listed: list[tuple[str, str | None]]) -> str:
    return "\n".join(f"- `{path}` — {text or '(no docstring)'}" for path, text in listed)


def rewrite(text: str, block: str) -> str:
    """The map file with the part between the markers replaced by `block`."""
    if not _BLOCK.search(text):
        raise ValueError(f"{START!r} and {END!r} are not in the file")
    return _BLOCK.sub(lambda match: f"{match.group(1)}{block}\n{match.group(3)}", text, count=1)


def main(argv: list[str]) -> int:
    current = MAP.read_text(encoding="utf-8")
    listed = modules()
    fresh = rewrite(current, render(listed))
    if "--check" in argv:
        if fresh != current:
            print(r"docs/code-map.md is out of date: run .venv\Scripts\python.exe tools\code_map.py")
            return 1
        return 0
    if fresh != current:
        MAP.write_text(fresh, encoding="utf-8", newline="\n")
    print(f"docs/code-map.md: {len(listed)} modules")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
