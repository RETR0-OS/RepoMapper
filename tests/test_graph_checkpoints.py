from __future__ import annotations

import json
from pathlib import Path

import pytest
from hydra_graph.analyzer import analyze_repository
from hydra_graph.checkpoints import CheckpointSlot, CheckpointStore


def _graph(root: Path, revision: str, source: str = "def work():\n    return 1\n"):
    (root / "module.py").write_text(source, encoding="utf-8")
    return analyze_repository(root, repository_id="checkpoints", revision_id=revision)


def test_checkpoint_store_keeps_only_atomic_before_and_after_slots(tmp_path: Path) -> None:
    before = _graph(tmp_path, "before")
    after = _graph(tmp_path, "after", "def work():\n    return 2\n")
    store = CheckpointStore(tmp_path, repository_id="checkpoints")

    before_ref = store.capture(CheckpointSlot.BEFORE, before)
    after_ref = store.capture("after", after)
    loaded_before, loaded_after = store.load_pair(
        before_revision_id="before", after_revision_id="after"
    )

    assert loaded_before == before
    assert loaded_after == after
    assert before_ref.checkpoint_schema == "hack-hydra.graph-checkpoint.v1"
    assert after_ref.graph_hash != before_ref.graph_hash
    checkpoint_dir = tmp_path / ".hydra-graph" / "checkpoints"
    assert sorted(path.name for path in checkpoint_dir.iterdir()) == [
        "after.json",
        "before.json",
    ]
    assert not list(checkpoint_dir.glob("*.tmp"))


def test_oversized_capture_does_not_replace_prior_valid_slot(tmp_path: Path) -> None:
    before = _graph(tmp_path, "before")
    measuring_store = CheckpointStore(tmp_path, repository_id="checkpoints")
    reference = measuring_store.capture("before", before)
    target = tmp_path / ".hydra-graph" / "checkpoints" / "before.json"
    original = target.read_bytes()
    bounded_store = CheckpointStore(
        tmp_path,
        repository_id="checkpoints",
        max_checkpoint_bytes=reference.byte_size,
    )
    oversized = _graph(
        tmp_path,
        "larger",
        "\n".join(f"def work_{index}():\n    return {index}\n" for index in range(30)),
    )

    with pytest.raises(ValueError, match="local analysis limit"):
        bounded_store.capture("before", oversized)

    assert target.read_bytes() == original
    assert bounded_store.load_pair  # The store intentionally has no query/search API.
    assert not hasattr(bounded_store, "query")
    assert not hasattr(bounded_store, "search")


def test_checkpoint_load_rejects_corruption_and_wrong_revision(tmp_path: Path) -> None:
    before = _graph(tmp_path, "before")
    after = _graph(tmp_path, "after", "def work():\n    return 2\n")
    store = CheckpointStore(tmp_path, repository_id="checkpoints")
    store.capture("before", before)
    store.capture("after", after)

    with pytest.raises(ValueError, match="another revision"):
        store.load_pair(before_revision_id="wrong", after_revision_id="after")

    target = tmp_path / ".hydra-graph" / "checkpoints" / "after.json"
    target.write_text("{partial", encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint is invalid"):
        store.load_pair(before_revision_id="before", after_revision_id="after")


def test_checkpoint_rejects_inside_directory_slot_symlink(tmp_path: Path) -> None:
    graph = _graph(tmp_path, "before")
    checkpoint_dir = tmp_path / ".hydra-graph" / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    innocent = checkpoint_dir / "innocent.json"
    innocent.write_text(json.dumps({"keep": True}), encoding="utf-8")
    slot = checkpoint_dir / "before.json"
    try:
        slot.symlink_to(innocent.name)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")
    store = CheckpointStore(tmp_path, repository_id="checkpoints")

    with pytest.raises(ValueError, match="symbolic link"):
        store.capture("before", graph)
    with pytest.raises(ValueError, match="symbolic link"):
        store.clear()

    assert json.loads(innocent.read_text(encoding="utf-8")) == {"keep": True}


def test_checkpoint_clear_removes_only_owned_slots(tmp_path: Path) -> None:
    before = _graph(tmp_path, "before")
    after = _graph(tmp_path, "after", "def work():\n    return 2\n")
    store = CheckpointStore(tmp_path, repository_id="checkpoints")
    store.capture("before", before)
    store.capture("after", after)
    unrelated = tmp_path / ".hydra-graph" / "checkpoints" / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    store.clear()

    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert not (unrelated.parent / "before.json").exists()
    assert not (unrelated.parent / "after.json").exists()
