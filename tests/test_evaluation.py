from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from hydra_graph.config import HydraDBConfig
from hydra_graph.models import GraphIR
from pydantic import ValidationError

from demo.preflight import run_preflight
from evaluation.baseline import DeterministicTfidf, load_baseline_documents
from evaluation.gold import load_and_resolve_gold, load_gold, resolve_gold
from evaluation.metrics import score_observation
from evaluation.models import (
    AgentRunManifest,
    EvaluationRecord,
    RelationObservation,
    RetrievalObservation,
    RunMode,
)
from evaluation.reporting import completeness, read_jsonl, summarize_records, write_jsonl
from evaluation.runner import AblationRunner, FixtureHydraTransport, LiveHydraTransport

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "fixtures" / "evaluation"


def _json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _resolved():
    return load_and_resolve_gold(FIXTURES / "gold.json")


def _runner(*, mode: RunMode = RunMode.OFFLINE) -> tuple[AblationRunner, FixtureHydraTransport]:
    transport = FixtureHydraTransport(
        without_graph=_json("hydradb-without-graph.json"),
        with_graph=_json("hydradb-with-graph.json"),
        latency_ms=12.5,
    )
    return AblationRunner(mode=mode, hydra_transport=transport), transport


def _observations():
    gold = _resolved()
    runner, transport = _runner()
    observations = runner.run_question(
        run_id="offline-run",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
        limit=3,
    )
    return gold, observations, transport


def _records():
    gold, observations, _ = _observations()
    question = gold.questions[0]
    return tuple(
        EvaluationRecord(
            gold_digest=gold.digest,
            observation=observation,
            metrics=score_observation(question, observation),
        )
        for observation in observations
    )


def test_gold_manifest_resolves_exact_ids_relations_and_source_spans() -> None:
    gold = _resolved()

    assert [question.question.id for question in gold.questions] == [
        "authorization-flow",
        "authorization-test",
    ]
    flow = gold.questions[0]
    assert len(flow.required_node_ids) == 3
    assert [edge.predicate.value for edge in flow.required_relations] == ["CALLS", "CALLS"]
    assert {(item.path, item.start_line, item.start_column) for item in flow.required_evidence} == {
        ("eval_app/api.py", 5, 11),
        ("eval_app/auth.py", 5, 11),
    }


def test_gold_rejects_same_id_fact_or_evidence_tampering() -> None:
    manifest = load_gold(FIXTURES / "gold.json")
    graph = GraphIR.model_validate_json((FIXTURES / "graph-ir.json").read_text(encoding="utf-8"))
    relation = manifest.questions[0].required_relations[0]
    wrong_fact = relation.model_copy(update={"predicate": "TESTS"})
    wrong_question = manifest.questions[0].model_copy(
        update={"required_relations": (wrong_fact, *manifest.questions[0].required_relations[1:])}
    )
    with pytest.raises(ValueError, match="does not match its gold fact"):
        resolve_gold(manifest.model_copy(update={"questions": (wrong_question,)}), graph)

    evidence = relation.evidence[0].model_copy(update={"start_line": 4})
    wrong_evidence = relation.model_copy(update={"evidence": (evidence,)})
    wrong_question = manifest.questions[0].model_copy(
        update={
            "required_relations": (
                wrong_evidence,
                *manifest.questions[0].required_relations[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="does not match the Graph IR"):
        resolve_gold(manifest.model_copy(update={"questions": (wrong_question,)}), graph)


def test_gold_detects_stale_fixture_source_and_path_escape(tmp_path: Path) -> None:
    target = tmp_path / "evaluation"
    shutil.copytree(FIXTURES, target)
    source = target / "repo" / "eval_app" / "auth.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "return load_policy(user)", "return bool(load_policy(user))"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="stale"):
        load_and_resolve_gold(target / "gold.json")

    payload = json.loads((target / "gold.json").read_text(encoding="utf-8"))
    payload["graph_ir_path"] = "../outside.json"
    (target / "gold.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        load_and_resolve_gold(target / "gold.json", verify_fixture=False)


def test_tfidf_baseline_is_deterministic_and_has_no_fixture_favorites() -> None:
    documents = load_baseline_documents(FIXTURES / "corpus.json")
    forward = DeterministicTfidf(documents).search("authorization policy store", limit=4)
    reverse = DeterministicTfidf(tuple(reversed(documents))).search(
        "authorization policy store", limit=4
    )

    assert [(item.document.document_id, item.score) for item in forward] == [
        (item.document.document_id, item.score) for item in reverse
    ]
    assert forward[0].document.document_id in {"auth-authorize", "store-load-policy"}
    assert all(item.document.document_id != "unrelated-greeting" for item in forward)


def test_baseline_evidence_comes_from_corpus_not_gold_answer_key() -> None:
    documents = load_baseline_documents(FIXTURES / "corpus.json")
    gold = _resolved()
    altered_question = gold.questions[0].__class__(
        question=gold.questions[0].question,
        required_node_ids=gold.questions[0].required_node_ids,
        required_relations=gold.questions[0].required_relations,
        required_evidence=(),
    )
    runner, _ = _runner()

    observation = runner.run_question(
        run_id="baseline-independent-of-gold",
        question=altered_question,
        baseline_documents=documents,
        limit=3,
    )[0]

    assert observation.returned_evidence
    assert {
        (item.evidence_id, item.path, item.start_line, item.start_column)
        for item in observation.returned_evidence
    }.issubset(
        {
            (
                evidence.evidence_id,
                evidence.path,
                evidence.start_line,
                evidence.start_column,
            )
            for document in documents
            for evidence in document.evidence
        }
    )


def test_product_service_never_imports_the_evaluation_baseline() -> None:
    forbidden: list[str] = []
    for path in sorted((ROOT / "service").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            imports_evaluation = any(
                module == "evaluation" or module.startswith("evaluation.") for module in modules
            )
            if imports_evaluation:
                forbidden.append(str(path.relative_to(ROOT)))
    assert forbidden == []


def test_ablation_pairs_hydra_requests_and_scores_exact_grounding() -> None:
    gold, observations, transport = _observations()
    assert [item.condition.value for item in observations] == ["A", "B", "C"]
    left, right = transport.calls
    assert left["graph_context"] is False
    assert right["graph_context"] is True
    assert {key: value for key, value in left.items() if key != "graph_context"} == {
        key: value for key, value in right.items() if key != "graph_context"
    }

    graph_metrics = score_observation(gold.questions[0], observations[2])
    assert (graph_metrics.required_node_hits, graph_metrics.required_nodes) == (3, 3)
    assert (graph_metrics.exact_relation_hits, graph_metrics.required_exact_relations) == (2, 2)
    assert (graph_metrics.evidence_hits, graph_metrics.required_evidence) == (2, 2)
    assert graph_metrics.inferred_relation_hits == 0
    assert graph_metrics.unsupported_relations == 0


def test_live_mode_refuses_fixture_transport() -> None:
    with pytest.raises(ValueError, match="refuses fixture"):
        _runner(mode=RunMode.LIVE)


def test_malformed_relation_context_never_becomes_exact_evidence() -> None:
    response = _json("hydradb-with-graph.json")
    response["paths"][0]["hops"][0]["relation"]["context"] = "not-json"
    transport = FixtureHydraTransport(without_graph=response, with_graph=response)
    gold = _resolved()
    observations = AblationRunner(mode=RunMode.OFFLINE, hydra_transport=transport).run_question(
        run_id="malformed",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
    )

    relation = observations[2].returned_relations[0]
    assert relation.quality == "unknown"
    assert relation.evidence == ()
    metrics = score_observation(gold.questions[0], observations[2])
    assert metrics.exact_relation_hits == 1
    assert metrics.evidence_hits == 1
    assert metrics.unsupported_relations == 1


def test_unversioned_hydra_response_fails_closed() -> None:
    response = _json("hydradb-with-graph.json")
    response.pop("response_schema")
    transport = FixtureHydraTransport(without_graph=response, with_graph=response)
    gold = _resolved()
    observations = AblationRunner(mode=RunMode.OFFLINE, hydra_transport=transport).run_question(
        run_id="unversioned",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
    )

    assert observations[1].status == "error"
    assert observations[1].returned_node_ids == ()
    assert observations[1].returned_relations == ()


def test_metrics_reject_same_edge_id_with_changed_fact() -> None:
    gold, observations, _ = _observations()
    graph = observations[2]
    original = graph.returned_relations[0]
    forged = RelationObservation(
        edge_id=original.edge_id,
        source_id=original.source_id,
        predicate="TESTS",
        target_id=original.target_id,
        quality="exact",
        evidence=original.evidence,
    )
    tampered = graph.model_copy(
        update={"returned_relations": (forged, *graph.returned_relations[1:])}
    )

    metrics = score_observation(gold.questions[0], tampered)
    assert metrics.exact_relation_hits == 1
    assert metrics.unsupported_relations == 1


def test_jsonl_csv_and_markdown_keep_denominators_and_block_offline_claims(
    tmp_path: Path,
) -> None:
    records = _records()
    raw_path = tmp_path / "raw.jsonl"
    csv_path = tmp_path / "summary.csv"
    markdown_path = tmp_path / "summary.md"
    write_jsonl(raw_path, records)
    assert read_jsonl(raw_path) == records

    report = summarize_records(
        records,
        expected_question_ids=("authorization-flow",),
        csv_path=csv_path,
        markdown_path=markdown_path,
    )
    markdown = markdown_path.read_text(encoding="utf-8")
    assert report.complete is True
    assert report.live_results is False
    assert report.comparative_claims_allowed is False
    assert "2/2" in markdown
    assert "Comparative claims are not allowed" in markdown
    assert "% better" not in markdown.lower()
    assert "required_exact_relations" in csv_path.read_text(encoding="utf-8")


def test_offline_cli_writes_all_questions_without_live_claims(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "evaluation", "--offline", "--output", str(tmp_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    records = read_jsonl(tmp_path / "raw.jsonl")
    assert len(records) == 6
    assert all(record.observation.mode is RunMode.OFFLINE for record in records)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Comparative claims are not allowed" in summary
    assert "Comparative claims allowed: False" in result.stdout


def test_live_transport_uses_credentials_current_collection_and_revision_filter() -> None:
    raw = json.loads(
        (ROOT / "fixtures" / "hydradb" / "query_authorization.json").read_text(encoding="utf-8")
    )

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def query(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return raw

    client = RecordingClient()
    transport = LiveHydraTransport(
        config=HydraDBConfig(api_key="credential", database="repo_hack_hydra"),
        repository_id="hack-hydra",
        revision_id="rev-abc",
        client=client,  # type: ignore[arg-type]
        clock=lambda: 1.0,
    )
    gold = _resolved()
    runner = AblationRunner(
        mode=RunMode.LIVE,
        hydra_transport=transport,
        repository_id="hack-hydra",
        revision_id="rev-abc",
    )
    observations = runner.run_question(
        run_id="live-contract-test",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
        limit=3,
    )

    assert [item.status for item in observations[1:]] == ["ready", "ready"]
    assert [call["graph_context"] for call in client.calls] == [False, True]
    assert all(call["collection"] == "current" for call in client.calls)
    assert all(
        call["metadata_filters"] == {"repository_id": "hack-hydra", "revision_id": "rev-abc"}
        for call in client.calls
    )


def test_live_transport_rejects_unbound_repository_results() -> None:
    raw = json.loads(
        (ROOT / "fixtures" / "hydradb" / "query_authorization.json").read_text(encoding="utf-8")
    )

    class IgnoringFilterClient:
        def query(self, **_: Any) -> dict[str, Any]:
            return raw

    transport = LiveHydraTransport(
        config=HydraDBConfig(api_key="credential", database="repo_hack_hydra"),
        repository_id="different-repository",
        revision_id="rev-abc",
        client=IgnoringFilterClient(),  # type: ignore[arg-type]
        clock=lambda: 1.0,
    )
    body = {
        "query": "authorization",
        "query_by": "hybrid",
        "mode": "thinking",
        "graph_context": True,
        "max_results": 3,
        "collection": "current",
        "metadata_filters": {
            "repository_id": "different-repository",
            "revision_id": "rev-abc",
        },
    }

    result = transport.query(body)
    assert result.payload["status"] == "degraded"
    assert result.payload["chunks"] == []
    assert result.payload["paths"] == []


def test_live_cli_cannot_run_without_credentials_or_use_offline_fixtures(
    tmp_path: Path,
) -> None:
    output = tmp_path / "live-results"
    environment = {
        key: value
        for key, value in __import__("os").environ.items()
        if key not in {"HYDRA_DB_API_KEY", "HYDRA_DB_DATABASE"}
    }
    result = subprocess.run(
        [sys.executable, "-m", "evaluation", "--live", "--output", str(output)],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not output.exists()
    assert not (output / "raw.jsonl").exists()
    assert "requires HydraDB API key and database" in result.stderr
    assert "Traceback" not in result.stderr


def test_completeness_guard_rejects_missing_nonready_or_mixed_runs() -> None:
    records = _records()
    assert (
        completeness(records[:2], expected_question_ids=("authorization-flow",)).complete is False
    )
    degraded = records[2].model_copy(
        update={"observation": records[2].observation.model_copy(update={"status": "degraded"})}
    )
    assert (
        completeness(
            (*records[:2], degraded), expected_question_ids=("authorization-flow",)
        ).complete
        is False
    )
    mixed = records[2].model_copy(update={"gold_digest": "0" * 64})
    assert (
        completeness((*records[:2], mixed), expected_question_ids=("authorization-flow",)).complete
        is False
    )


def test_agent_templates_are_strict_and_observable_only() -> None:
    forbidden = {"reasoning", "hidden_reasoning", "chain_of_thought", "internal_traversal"}
    for name in ("codex.json", "claude-code.json"):
        payload = json.loads((ROOT / "evaluation" / "manifests" / name).read_text(encoding="utf-8"))
        manifest = AgentRunManifest.model_validate(payload)
        assert forbidden.isdisjoint(field.lower() for field in manifest.observable_fields)
        assert manifest.mcp_transport == "streamable-http"
        assert manifest.mcp_endpoint == "http://127.0.0.1:8765/mcp"
        assert "stdio" not in json.dumps(payload)
        with pytest.raises(ValidationError):
            AgentRunManifest.model_validate({**payload, "hidden_reasoning": "do not record"})

    payload = json.loads(
        (ROOT / "evaluation" / "manifests" / "codex.json").read_text(encoding="utf-8")
    )
    payload["observable_fields"].append("chain_of_thought")
    with pytest.raises(ValidationError, match="observable outcomes"):
        AgentRunManifest.model_validate(payload)


def test_retrieval_artifact_models_forbid_hidden_or_unknown_fields() -> None:
    observation = _observations()[1][0]
    with pytest.raises(ValidationError):
        RetrievalObservation.model_validate(
            {**observation.model_dump(mode="json"), "reasoning": "fabricated"}
        )


def test_demo_preflight_requires_credentials_verified_revision_and_live_results() -> None:
    checks = run_preflight(
        project_root=ROOT,
        environment={},
        health={"state": "unverified", "revision_verified": False, "revision_id": "current"},
        results_path=None,
    )
    failed = {check.name for check in checks if not check.passed}
    assert "HydraDB credentials" in failed
    assert "Verified live revision" in failed
    assert "Live A/B/C artifacts" in failed
    assert all(check.passed for check in checks if check.name.startswith("Agent manifest"))


def test_demo_preflight_requires_the_exact_gold_revision_and_current_collection() -> None:
    environment = {"HYDRA_DB_API_KEY": "set", "HYDRA_DB_DATABASE": "set"}
    wrong_revision = run_preflight(
        project_root=ROOT,
        environment=environment,
        health={
            "state": "ready",
            "revision_verified": True,
            "revision_id": "another-revision",
            "collection": "current",
        },
        results_path=None,
    )
    wrong_collection = run_preflight(
        project_root=ROOT,
        environment=environment,
        health={
            "state": "ready",
            "revision_verified": True,
            "revision_id": "eval-rev-1",
            "collection": "not-current",
        },
        results_path=None,
    )
    ready = run_preflight(
        project_root=ROOT,
        environment=environment,
        health={
            "state": "ready",
            "revision_verified": True,
            "revision_id": "eval-rev-1",
            "collection": "current",
        },
        results_path=None,
    )

    def verified(checks):
        return next(check for check in checks if check.name == "Verified live revision")

    assert verified(wrong_revision).passed is False
    assert verified(wrong_collection).passed is False
    assert verified(ready).passed is True


def test_demo_saves_shared_lens_before_edit_and_drift_review() -> None:
    runbook = (ROOT / "demo" / "five-minute-runbook.md").read_text(encoding="utf-8")

    save = runbook.index("Save and review the current authorization flow as the shared System Lens")
    edit = runbook.index('replace `if not authorize(user):` with `if user != "admin":`')
    drift = runbook.index("Open the shared System Lens")

    assert save < edit < drift


def test_live_completeness_requires_all_three_conditions() -> None:
    records = tuple(
        record.model_copy(
            update={"observation": record.observation.model_copy(update={"mode": RunMode.LIVE})}
        )
        for record in _records()
    )
    report = completeness(records, expected_question_ids=("authorization-flow",))
    assert report.complete is True
    assert report.live_results is True
    assert report.comparative_claims_allowed is True


def test_gold_models_reject_partial_or_reversed_spans() -> None:
    payload = _json("gold.json")
    evidence = payload["questions"][0]["required_relations"][0]["evidence"][0]
    evidence.pop("end_column")
    with pytest.raises(ValidationError):
        load_gold_from_payload(payload)

    payload = _json("gold.json")
    evidence = payload["questions"][0]["required_relations"][0]["evidence"][0]
    evidence["end_line"] = 4
    with pytest.raises(ValidationError, match="ends before"):
        load_gold_from_payload(payload)


def test_metric_models_reject_numerator_gaming() -> None:
    record = _records()[2]
    payload = record.metrics.model_dump(mode="json")
    payload["exact_relation_hits"] = payload["required_exact_relations"] + 1
    from evaluation.models import QuestionMetrics

    with pytest.raises(ValidationError, match="numerator exceeds"):
        QuestionMetrics.model_validate(payload)


def load_gold_from_payload(payload: dict[str, Any]):
    from evaluation.models import GoldManifest

    return GoldManifest.model_validate(payload)
