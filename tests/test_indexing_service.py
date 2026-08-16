from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from hydra_graph import indexing_service
from hydra_graph.discovery import discover_files
from hydra_graph.indexing_service import (
    IndexPreviewConflict,
    IndexPreviewStore,
    discovery_matches,
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


def test_discovery_matches_only_when_paths_and_content_agree(tmp_path: Path) -> None:
    write_app(tmp_path)
    original = discover_files(tmp_path)

    assert discovery_matches(original, discover_files(tmp_path)) is True

    write_app(tmp_path, 5)
    assert discovery_matches(original, discover_files(tmp_path)) is False

    write_app(tmp_path)
    (tmp_path / "extra.py").write_text("value = 1\n", encoding="utf-8")
    assert discovery_matches(original, discover_files(tmp_path)) is False


def test_prepared_index_cache_holds_one_entry_and_is_released(tmp_path: Path) -> None:
    write_app(tmp_path)
    repository_id = "local:example:00000000-0000-4000-8000-000000000000"
    prepared = prepare_automatic_index(tmp_path, repository_id)
    store = IndexPreviewStore(tmp_path, repository_id)

    first = store.issue(prepared).token
    assert store.prepared_for(first) is prepared
    assert store.prepared_for("other-token") is None

    # Card text is far too large to pool, so a new preview replaces the old one.
    second = store.issue(prepared).token
    assert store.prepared_for(first) is None
    assert store.prepared_for(second) is prepared

    store.consume(second, prepared)
    assert store.prepared_for(second) is None


def test_expired_preview_releases_the_cached_prepared_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_app(tmp_path)
    repository_id = "local:example:00000000-0000-4000-8000-000000000000"
    prepared = prepare_automatic_index(tmp_path, repository_id)
    store = IndexPreviewStore(tmp_path, repository_id)
    monkeypatch.setattr(indexing_service, "PREVIEW_TOKEN_TTL_SECONDS", -1)

    token = store.issue(prepared).token

    assert store.prepared_for(token) is None
    with pytest.raises(IndexPreviewConflict, match="expired"):
        store.consume(token, prepared)


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
