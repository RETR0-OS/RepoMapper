from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from hydra_graph.discovery import discover_files
from hydra_graph.indexing_service import (
    IndexPreviewConflict,
    IndexPreviewStore,
    prepare_automatic_index,
)


def write_app(root: Path, value: int = 1) -> None:
    (root / "app.py").write_text(f"def value():\n    return {value}\n", encoding="utf-8")


def test_non_git_revision_is_a_deterministic_analyzed_content_digest(tmp_path: Path) -> None:
    write_app(tmp_path)
    first = prepare_automatic_index(tmp_path, "local:example:00000000-0000-4000-8000-000000000000")
    second = prepare_automatic_index(tmp_path, "local:example:00000000-0000-4000-8000-000000000000")

    assert first.revision_source == "content-digest"
    assert first.revision_id == second.revision_id
    assert first.snapshot_hash == second.snapshot_hash

    write_app(tmp_path, 2)
    changed = prepare_automatic_index(
        tmp_path, "local:example:00000000-0000-4000-8000-000000000000"
    )
    assert changed.revision_id != first.revision_id
    assert changed.snapshot_hash != first.snapshot_hash


def test_clean_git_revision_uses_full_commit_and_dirty_uses_content(tmp_path: Path) -> None:
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git is unavailable")
    write_app(tmp_path)
    commands = [
        ["git", "init"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Repository Map Test"],
        ["git", "add", "app.py"],
        ["git", "commit", "-m", "Initial"],
    ]
    for command in commands:
        subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

    clean = prepare_automatic_index(tmp_path, "git:example:0123456789abcdefabcd")
    assert clean.revision_source == "git-clean"
    assert clean.revision_id == head

    write_app(tmp_path, 2)
    dirty = prepare_automatic_index(tmp_path, "git:example:0123456789abcdefabcd")
    assert dirty.revision_source == "content-digest"
    assert dirty.revision_id.startswith("content:")


def test_preview_token_is_project_bound_single_use_and_snapshot_bound(tmp_path: Path) -> None:
    write_app(tmp_path)
    repository_id = "local:example:00000000-0000-4000-8000-000000000000"
    prepared = prepare_automatic_index(tmp_path, repository_id)
    store = IndexPreviewStore(tmp_path, repository_id)
    token = store.issue(prepared).token

    assert store.consume(token, prepared).revision_id == prepared.revision_id
    with pytest.raises(IndexPreviewConflict, match="already used"):
        store.consume(token, prepared)

    second = store.issue(prepared).token
    write_app(tmp_path, 3)
    changed = prepare_automatic_index(tmp_path, repository_id)
    with pytest.raises(IndexPreviewConflict, match="changed"):
        store.consume(second, changed)


def test_internal_state_is_never_analyzed_or_revisioned(tmp_path: Path) -> None:
    write_app(tmp_path)
    state = tmp_path / ".hydra-graph"
    state.mkdir()
    (state / "identity.json").write_text('{"repository_id":"opaque"}', encoding="utf-8")
    first = prepare_automatic_index(tmp_path, "local:example:00000000-0000-4000-8000-000000000000")
    (state / "manifest.json").write_text('{"database":"must-not-leak"}', encoding="utf-8")
    second = prepare_automatic_index(tmp_path, "local:example:00000000-0000-4000-8000-000000000000")

    assert {item.path for item in discover_files(tmp_path).files} == {"app.py"}
    assert first.revision_id == second.revision_id
    assert all(".hydra-graph" not in str(card.model_dump()) for card in second.cards)
