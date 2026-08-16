from __future__ import annotations

import shutil
import subprocess
from contextlib import suppress
from pathlib import Path

import pytest
from hydra_graph.discovery import discover_files

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sample_repo"


def test_discovery_respects_both_ignore_files_and_secret_content() -> None:
    report = discover_files(FIXTURE)
    paths = {item.path for item in report.files}
    ignored = {item.path: item.reason for item in report.ignored}

    assert "app/service.py" in paths
    assert "ignored.py" not in paths
    assert "generated.py" not in paths
    assert ignored["ignored.py"] == "ignore-rule"
    assert ignored["generated.py"] == "ignore-rule"
    assert ignored["secret.py"] == "secret-content"


def test_discovery_blocks_secret_names_binary_large_and_symlink_files(tmp_path: Path) -> None:
    (tmp_path / ".env.production").write_text("TOKEN=not-visible", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"hello\x00world")
    (tmp_path / "large.txt").write_text("x" * 32, encoding="utf-8")
    (tmp_path / "safe.py").write_text("answer = 42\n", encoding="utf-8")
    with suppress(OSError):
        (tmp_path / "linked.py").symlink_to(tmp_path / "safe.py")

    report = discover_files(tmp_path, max_file_bytes=16)
    reasons = {item.path: item.reason for item in report.ignored}
    assert reasons[".env.production"] == "secret-name"
    assert reasons["binary.dat"] == "binary"
    assert reasons["large.txt"] == "oversized"
    if (tmp_path / "linked.py").is_symlink():
        assert reasons["linked.py"] == "symlink"
    assert {item.path for item in report.files} == {"safe.py"}


def test_explicit_deny_globs_are_enforced(tmp_path: Path) -> None:
    (tmp_path / "public.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "private.py").write_text("value = 2\n", encoding="utf-8")
    report = discover_files(tmp_path, deny_globs=("private.py",))
    assert [item.path for item in report.files] == ["public.py"]
    assert report.ignored_counts == {"ignore-rule": 1}


def test_secret_detection_does_not_reject_harmless_short_placeholders(tmp_path: Path) -> None:
    (tmp_path / "config.py").write_text('api_key = "example"\n', encoding="utf-8")
    report = discover_files(tmp_path)
    assert [item.path for item in report.files] == ["config.py"]


def test_git_discovery_honors_nested_ignores_but_keeps_tracked_files(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("Git is required for the nested ignore contract")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".gitignore").write_text("*.py\n", encoding="utf-8")
    (nested / "ignored.py").write_text("ignored = True\n", encoding="utf-8")
    (nested / "tracked.py").write_text("tracked = True\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-f", "nested/tracked.py"],
        check=True,
    )

    report = discover_files(tmp_path)
    paths = {item.path for item in report.files}
    reasons = {item.path: item.reason for item in report.ignored}

    assert "nested/tracked.py" in paths
    assert "nested/ignored.py" not in paths
    assert reasons["nested/ignored.py"] == "ignore-rule"
    assert reasons["nested/.gitignore"] == "control-file"
