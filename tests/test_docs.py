from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _local_target(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    path_text = unquote(target.split("#", 1)[0])
    return (source.parent / path_text).resolve()


def test_human_docs_are_multi_page_and_indexed() -> None:
    pages = sorted(DOCS.glob("*.md"))
    assert len(pages) >= 15
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    for page in pages:
        if page.name != "README.md":
            assert f"({page.name})" in index, f"docs index does not link {page.name}"
    assert "Project documentation can be added here" not in index


def test_human_docs_have_no_broken_local_links() -> None:
    failures: list[str] = []
    for source in sorted(DOCS.glob("*.md")):
        content = source.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(content):
            target = _local_target(source, match.group(1))
            if target is not None and not target.exists():
                failures.append(f"{source.relative_to(ROOT)} -> {match.group(1)}")
    assert failures == []


def test_docs_keep_the_hydradb_truth_boundary_visible() -> None:
    index = (DOCS / "README.md").read_text(encoding="utf-8").casefold()
    limits = (DOCS / "limitations.md").read_text(encoding="utf-8").casefold()
    assert "hydradb" in index
    assert "no local" in index
    assert "live credentials" in limits
    assert "offline" in limits and "not performance evidence" in limits
