from __future__ import annotations

import json
from pathlib import Path

from hydra_graph.analyzer import analyze_repository
from hydra_graph.discovery import discover_files
from hydra_graph.entrypoints import detect_entry_points


def build(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def reasons_for(root: Path, path: str) -> set[str]:
    found = detect_entry_points(discover_files(root))
    return {item.reason for item in found if item.path == path}


def test_a_main_guard_marks_the_file_and_the_functions_it_calls(tmp_path: Path) -> None:
    build(
        tmp_path,
        {
            "cli.py": (
                "def run():\n"
                "    return 1\n\n\n"
                "def unused():\n"
                "    return 2\n\n\n"
                'if __name__ == "__main__":\n'
                "    run()\n"
            )
        },
    )

    found = detect_entry_points(discover_files(tmp_path))
    guarded = {item.qualified_name for item in found if item.reason == "python-main-guard-call"}

    assert "python-main-guard" in reasons_for(tmp_path, "cli.py")
    assert guarded == {"cli.run"}
    assert all(item.manifest_path == "cli.py" for item in found)


def test_a_dunder_main_module_is_an_entry_point(tmp_path: Path) -> None:
    build(tmp_path, {"pkg/__main__.py": "print(1)\n", "pkg/__init__.py": ""})

    assert "python-main-module" in reasons_for(tmp_path, "pkg/__main__.py")


def test_a_console_script_resolves_only_to_a_discovered_module(tmp_path: Path) -> None:
    build(
        tmp_path,
        {
            "pyproject.toml": (
                "[project]\nname = 'demo'\n\n"
                "[project.scripts]\n"
                'demo = "app.cli:main"\n'
                'ghost = "not_here.cli:main"\n'
            ),
            "app/__init__.py": "",
            "app/cli.py": "def main():\n    return 1\n",
        },
    )

    found = detect_entry_points(discover_files(tmp_path))
    scripts = {item.qualified_name for item in found if item.reason == "python-console-script"}

    assert scripts == {"app.cli.main"}


def test_package_json_bin_main_and_start_resolve_relative_to_that_manifest(
    tmp_path: Path,
) -> None:
    build(
        tmp_path,
        {
            "web/package.json": json.dumps(
                {
                    "bin": {"demo": "./cli.js"},
                    "main": "index.js",
                    "scripts": {"start": "node server.js --port 3000"},
                }
            ),
            "web/cli.js": "//\n",
            "web/index.js": "//\n",
            "web/server.js": "//\n",
        },
    )

    found = {(item.path, item.reason) for item in detect_entry_points(discover_files(tmp_path))}

    assert ("web/cli.js", "node-package-bin") in found
    assert ("web/index.js", "node-package-main") in found
    assert ("web/server.js", "node-package-start") in found


def test_container_and_procfile_tokens_resolve_only_to_real_files(tmp_path: Path) -> None:
    build(
        tmp_path,
        {
            "Dockerfile": 'ENTRYPOINT ["python", "serve.py"]\nCMD ["--verbose"]\n',
            "Procfile": "web: python worker.py\n",
            "serve.py": "print(1)\n",
            "worker.py": "print(2)\n",
        },
    )

    found = {(item.path, item.reason) for item in detect_entry_points(discover_files(tmp_path))}

    assert ("serve.py", "container-entrypoint") in found
    assert ("worker.py", "procfile-process") in found
    # "--verbose" and "python" name no repository file, so they prove nothing.
    assert not any(reason == "container-cmd" for _, reason in found)


def test_a_malformed_manifest_is_skipped_without_raising(tmp_path: Path) -> None:
    build(
        tmp_path,
        {
            "pyproject.toml": "[project\nbroken",
            "package.json": "{not json",
            "app.py": "print(1)\n",
        },
    )

    assert detect_entry_points(discover_files(tmp_path)) == ()


def test_detection_is_deterministic_across_repeated_runs(tmp_path: Path) -> None:
    build(
        tmp_path,
        {
            "pkg/__main__.py": "print(1)\n",
            "pkg/__init__.py": "",
            "Procfile": "web: python pkg/__main__.py\n",
        },
    )
    report = discover_files(tmp_path)

    assert detect_entry_points(report) == detect_entry_points(report)


def test_entry_points_reach_graph_nodes_without_changing_other_node_ids(
    tmp_path: Path,
) -> None:
    plain = {"app/__init__.py": "", "app/service.py": "def serve():\n    return 1\n"}
    build(tmp_path, plain)
    before = analyze_repository(tmp_path, repository_id="sample", revision_id="r1")

    guard = 'def go():\n    return 1\n\n\nif __name__ == "__main__":\n    go()\n'
    build(tmp_path, {"app/cli.py": guard})
    after = analyze_repository(tmp_path, repository_id="sample", revision_id="r1")

    marked = {node.qualified_name for node in after.nodes if node.attributes.get("is_entry_point")}
    assert marked == {"app.cli", "app.cli.go"}
    assert {node.id for node in before.nodes} <= {node.id for node in after.nodes}
    assert all(
        node.attributes.get("entry_reasons") == ["python-main-guard"]
        for node in after.nodes
        if node.qualified_name == "app.cli"
    )


def test_a_non_python_entry_file_becomes_a_node_that_imports_cannot_reach(
    tmp_path: Path,
) -> None:
    # `import web.index` must never resolve onto `web/index.js`. An exact edge that no
    # parser proved is worse than a missing one.
    build(
        tmp_path,
        {
            "web/package.json": json.dumps({"main": "index.js"}),
            "web/index.js": "//\n",
            "app/__init__.py": "",
            "app/main.py": "import web.index\n",
        },
    )

    graph = analyze_repository(tmp_path, repository_id="sample", revision_id="r1")
    by_id = graph.node_map()
    javascript = [node for node in graph.nodes if node.path == "web/index.js"]

    assert javascript and javascript[0].attributes["is_entry_point"] is True
    assert {node.path for node in graph.nodes} >= {"web/index.js", "web"}
    assert not any(
        by_id[edge.target_id].path == "web/index.js" and edge.predicate.value == "IMPORTS"
        for edge in graph.edges
    )
