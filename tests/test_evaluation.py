from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

import pytest
from hydra_graph.config import HydraDBConfig
from hydra_graph.hydradb import HydraDBClient
from hydra_graph.models import GraphIR
from pydantic import ValidationError

from demo.preflight import run_preflight
from evaluation.baseline import (
    DeterministicTfidf,
    baseline_corpus_digest,
    load_baseline_documents,
    validate_baseline_documents,
)
from evaluation.gold import load_and_resolve_gold, load_gold, resolve_gold
from evaluation.metrics import score_observation
from evaluation.models import (
    AgentOutcomeRecord,
    AgentRunManifest,
    EvaluationRecord,
    EvaluationTarget,
    HydraDBRequestBody,
    RelationObservation,
    RetrievalObservation,
    RunMode,
)
from evaluation.reporting import (
    artifact_digest,
    completeness,
    read_agent_outcomes,
    read_jsonl,
    summarize_records,
    write_agent_outcomes,
    write_jsonl,
)
from evaluation.runner import (
    AblationRunner,
    FixtureHydraTransport,
    LiveHydraTransport,
    fixture_evaluation_target,
    repository_root_fingerprint,
)

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "fixtures" / "evaluation"


def _json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _resolved():
    return load_and_resolve_gold(FIXTURES / "gold.json")


def _runner(*, mode: RunMode = RunMode.OFFLINE) -> tuple[AblationRunner, FixtureHydraTransport]:
    gold = _resolved()
    transport = FixtureHydraTransport(
        without_graph=_json("hydradb-without-graph.json"),
        with_graph=_json("hydradb-with-graph.json"),
        latency_ms=12.5,
    )
    return (
        AblationRunner(
            mode=mode,
            hydra_transport=transport,
            target=fixture_evaluation_target(gold),
        ),
        transport,
    )


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
    corpus_digest = baseline_corpus_digest(load_baseline_documents(FIXTURES / "corpus.json"))
    return tuple(
        EvaluationRecord(
            gold_digest=gold.digest,
            baseline_corpus_digest=corpus_digest,
            observation=observation,
            metrics=score_observation(question, observation),
        )
        for observation in observations
    )


def _all_records() -> tuple[EvaluationRecord, ...]:
    gold = _resolved()
    runner, _ = _runner()
    return runner.run_suite(
        run_id="offline-run",
        gold=gold,
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
        limit=3,
    )


def _fixture_target() -> EvaluationTarget:
    return fixture_evaluation_target(_resolved())


def _live_target(
    *, repository_id: str = "hack-hydra", revision_id: str = "rev-abc"
) -> EvaluationTarget:
    return EvaluationTarget(
        database="repo_hack_hydra",
        repository_id=repository_id,
        revision_id=revision_id,
        repository_root_fingerprint="f" * 64,
    )


def _complete(records: tuple[EvaluationRecord, ...]):
    gold = _resolved()
    return completeness(
        records,
        expected_question_ids=("authorization-flow",),
        expected_gold_digest=gold.digest,
        expected_baseline_corpus_digest=baseline_corpus_digest(
            load_baseline_documents(FIXTURES / "corpus.json")
        ),
        expected_target=_fixture_target(),
    )


def _live_environment(*, database: str = "live-evaluation") -> dict[str, str]:
    return {
        "HYDRA_DB_API_KEY": "set",
        "HYDRA_DB_DATABASE": database,
        "HYDRA_DB_COLLECTION": "current",
        "HYDRA_REPOSITORY_ID": "evaluation-fixture",
        "HYDRA_REPOSITORY_ROOT": str((FIXTURES / "repo").resolve()),
    }


def _as_live_records(
    records: tuple[EvaluationRecord, ...] | None = None,
    *,
    target: EvaluationTarget | None = None,
    run_id: str | None = None,
) -> tuple[EvaluationRecord, ...]:
    source = records or _records()
    target = target or _fixture_target().model_copy(update={"database": "live-evaluation"})
    result = []
    for record in source:
        observation_payload = record.observation.model_dump(mode="json")
        observation_payload.update(
            {
                "mode": "live",
                "target": target.model_dump(mode="json"),
                "run_id": run_id or "live-run",
            }
        )
        plan = record.observation.request_plan
        if plan is not None:
            observation_payload["hydradb_request_body"] = {
                **plan.model_dump(mode="json"),
                "database": target.database,
                "type": "knowledge",
                "query_forceful_relations": True,
            }
        observation = RetrievalObservation.model_validate(observation_payload)
        result.append(record.model_copy(update={"observation": observation}))
    return tuple(result)


def _complete_live(records: tuple[EvaluationRecord, ...]):
    gold = _resolved()
    target = _fixture_target().model_copy(update={"database": "live-evaluation"})
    return completeness(
        records,
        expected_question_ids=("authorization-flow",),
        expected_gold_digest=gold.digest,
        expected_baseline_corpus_digest=baseline_corpus_digest(
            load_baseline_documents(FIXTURES / "corpus.json")
        ),
        expected_target=target,
    )


def _agent_outcomes(
    records: tuple[EvaluationRecord, ...],
    *,
    agent: Literal["codex", "claude-code"],
    model: str,
    retrieval_digest: str,
) -> tuple[AgentOutcomeRecord, ...]:
    return tuple(
        AgentOutcomeRecord(
            retrieval_artifact_digest=retrieval_digest,
            run_id=record.observation.run_id,
            agent=agent,
            model=model,
            question_id=record.observation.question_id,
            condition=record.observation.condition,
            task_completed=True,
            correct_files_changed=(),
            unnecessary_files_opened_or_edited=(),
            repository_tool_calls=1,
            hydradb_query_calls=(0 if record.observation.condition.value == "A" else 1),
            context_characters_returned=record.metrics.context_chars,
            tests_passed=True,
            outcome="completed",
            rework_count=0,
        )
        for record in records
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
    assert forward[0].document.document_id in {
        "node_851de3f73b36629e337e18f4",
        "node_9424c0b9af08602043e5dade",
    }
    assert {document.node_id for document in documents}.issubset(_resolved().graph.node_map())
    validate_baseline_documents(documents, _resolved())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("node_id", "node_fabricated", "unknown node"),
        ("document_id", "document-fabricated", "stable Graph IR node IDs"),
        ("content", "authorization policy " * 50, "source-derived"),
        ("evidence_id", "evidence_fabricated", "unknown evidence"),
        ("path", "../escape.py", "differs from Graph IR"),
        ("excerpt_hash", "0" * 64, "differs from Graph IR"),
    ),
)
def test_baseline_corpus_rejects_unresolved_or_fabricated_grounding(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    payload = json.loads((FIXTURES / "corpus.json").read_text(encoding="utf-8"))
    if field in {"node_id", "document_id", "content"}:
        payload[0][field] = value
    else:
        payload[0]["evidence"][0][field] = value
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_baseline_documents(load_baseline_documents(path), _resolved())

    if field == "node_id":
        payload = json.loads((FIXTURES / "corpus.json").read_text(encoding="utf-8"))
        payload.pop()
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="cover every Graph IR node"):
            validate_baseline_documents(load_baseline_documents(path), _resolved())


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
    observations = AblationRunner(
        mode=RunMode.OFFLINE,
        hydra_transport=transport,
        target=fixture_evaluation_target(gold),
    ).run_question(
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


def test_exact_relation_requires_byog_origin() -> None:
    response = _json("hydradb-with-graph.json")
    response["paths"][0]["hops"][0]["relation"]["origin"] = "automatic"
    transport = FixtureHydraTransport(without_graph=response, with_graph=response)
    gold = _resolved()
    observations = AblationRunner(
        mode=RunMode.OFFLINE,
        hydra_transport=transport,
        target=fixture_evaluation_target(gold),
    ).run_question(
        run_id="non-byog",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
    )

    relation = observations[2].returned_relations[0]
    assert relation.quality == "unknown"
    assert relation.evidence == ()
    metrics = score_observation(gold.questions[0], observations[2])
    assert metrics.exact_relation_hits == 1
    assert metrics.unsupported_relations == 1
    with pytest.raises(ValidationError, match="BYOG origin"):
        RelationObservation(
            edge_id="edge",
            source_id="source",
            predicate="CALLS",
            target_id="target",
            quality="exact",
        )


def test_unversioned_hydra_response_fails_closed() -> None:
    response = _json("hydradb-with-graph.json")
    response.pop("response_schema")
    transport = FixtureHydraTransport(without_graph=response, with_graph=response)
    gold = _resolved()
    observations = AblationRunner(
        mode=RunMode.OFFLINE,
        hydra_transport=transport,
        target=fixture_evaluation_target(gold),
    ).run_question(
        run_id="unversioned",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
    )

    assert observations[1].status == "error"
    assert observations[1].returned_node_ids == ()
    assert observations[1].returned_relations == ()


def test_context_cost_counts_additional_path_and_relation_text_once() -> None:
    response = _json("hydradb-with-graph.json")
    response["additional_context"] = [
        {"chunk_id": "extra-1", "content": "additional authorization context"}
    ]
    response["paths"][0]["summary"] = "request reaches the policy store"
    with_duplicate = json.loads(json.dumps(response))
    with_duplicate["relations"] = [json.loads(json.dumps(response["paths"][0]))]
    gold = _resolved()

    def graph_observation(payload: dict[str, Any]) -> RetrievalObservation:
        transport = FixtureHydraTransport(without_graph=payload, with_graph=payload)
        return AblationRunner(
            mode=RunMode.OFFLINE,
            hydra_transport=transport,
            target=fixture_evaluation_target(gold),
        ).run_question(
            run_id="context-cost",
            question=gold.questions[0],
            baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
        )[2]

    single = graph_observation(response)
    duplicate = graph_observation(with_duplicate)
    chunk_only_chars = sum(len(chunk["content"]) for chunk in response["chunks"])

    assert single.context_chars > chunk_only_chars
    assert single.context_chars == duplicate.context_chars
    assert single.context_tokens == duplicate.context_tokens

    repeated_id = json.loads(json.dumps(response))
    repeated_id["additional_context"].append(
        {
            "node_id": response["chunks"][0]["node_id"],
            "content": response["chunks"][0]["content"],
        }
    )
    repeated_id_observation = graph_observation(repeated_id)
    assert repeated_id_observation.context_chars == single.context_chars
    assert repeated_id_observation.context_tokens == single.context_tokens

    distinct_id = json.loads(json.dumps(response))
    distinct_id["additional_context"].append(
        {
            "chunk_id": "same-content-new-id",
            "content": response["chunks"][0]["content"],
        }
    )
    distinct_id_observation = graph_observation(distinct_id)
    repeated_content = response["chunks"][0]["content"]
    assert distinct_id_observation.context_chars == single.context_chars + len(repeated_content) + 1
    assert distinct_id_observation.context_tokens == single.context_tokens + len(
        repeated_content.split()
    )

    conflicting = json.loads(json.dumps(response))
    conflicting["additional_context"].append(
        {
            "node_id": response["chunks"][0]["node_id"],
            "content": "different content under the same ID",
        }
    )
    conflict = graph_observation(conflicting)
    assert conflict.status == "error"
    assert conflict.context_chars == 0
    assert conflict.returned_node_ids == ()
    assert any("conflicting context" in warning for warning in conflict.warnings)


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
        origin="byog",
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
        expected_gold_digest=_resolved().digest,
        expected_baseline_corpus_digest=baseline_corpus_digest(
            load_baseline_documents(FIXTURES / "corpus.json")
        ),
        expected_target=_fixture_target(),
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

    class RecordingHttpTransport:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            if kwargs["json_body"]["graph_context"] is False:
                without_graph = json.loads(json.dumps(raw))
                without_graph["data"]["graph_context"] = {
                    "query_paths": [],
                    "chunk_relations": [],
                    "chunk_id_to_group_ids": {},
                }
                return without_graph
            return raw

    http = RecordingHttpTransport()
    config = HydraDBConfig(
        api_key="credential",
        database="repo_hack_hydra",
        max_retries=0,
    )
    target = _live_target()
    client = HydraDBClient(config, transport=http)
    transport = LiveHydraTransport(
        config=config,
        target=target,
        client=client,
        clock=lambda: 1.0,
    )
    gold = _resolved()
    runner = AblationRunner(
        mode=RunMode.LIVE,
        hydra_transport=transport,
        target=target,
    )
    observations = runner.run_question(
        run_id="live-contract-test",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
        limit=3,
    )

    assert [item.status for item in observations[1:]] == ["ready", "ready"]
    wire_bodies = [call["json_body"] for call in http.calls]
    assert [body["graph_context"] for body in wire_bodies] == [False, True]
    assert all(body["collection"] == "current" for body in wire_bodies)
    assert all(
        body["metadata_filters"] == {"repository_id": "hack-hydra", "revision_id": "rev-abc"}
        for body in wire_bodies
    )
    assert all(body["database"] == "repo_hack_hydra" for body in wire_bodies)
    assert all(body["type"] == "knowledge" for body in wire_bodies)
    assert all(body["query_forceful_relations"] is True for body in wire_bodies)
    assert [
        observation.hydradb_request_body.model_dump(mode="json")
        for observation in observations[1:]
        if observation.hydradb_request_body is not None
    ] == wire_bodies
    assert all(observation.request_plan is not None for observation in observations[1:])


def test_live_transport_rejects_unbound_repository_results() -> None:
    raw = json.loads(
        (ROOT / "fixtures" / "hydradb" / "query_authorization.json").read_text(encoding="utf-8")
    )

    class IgnoringFilterClient:
        def query(self, **_: Any) -> dict[str, Any]:
            return raw

    transport = LiveHydraTransport(
        config=HydraDBConfig(api_key="credential", database="repo_hack_hydra"),
        target=_live_target(repository_id="different-repository"),
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


def test_live_transport_rejects_chunkless_path_before_scoring() -> None:
    raw = json.loads(
        (ROOT / "fixtures" / "hydradb" / "query_authorization.json").read_text(encoding="utf-8")
    )
    raw["data"]["chunks"] = []

    class PathOnlyClient:
        def query(self, **_: Any) -> dict[str, Any]:
            return raw

    target = _live_target()
    transport = LiveHydraTransport(
        config=HydraDBConfig(api_key="credential", database=target.database),
        target=target,
        client=PathOnlyClient(),  # type: ignore[arg-type]
        clock=lambda: 1.0,
    )
    gold = _resolved()
    observations = AblationRunner(
        mode=RunMode.LIVE,
        hydra_transport=transport,
        target=target,
    ).run_question(
        run_id="chunkless-live",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
        limit=3,
    )

    assert [item.status for item in observations[1:]] == ["degraded", "degraded"]
    assert all(item.returned_node_ids == () for item in observations[1:])
    assert all(item.returned_relations == () for item in observations[1:])
    assert all(
        score_observation(gold.questions[0], item).exact_relation_hits == 0
        for item in observations[1:]
    )


def test_live_condition_b_rejects_returned_graph_paths() -> None:
    raw = json.loads(
        (ROOT / "fixtures" / "hydradb" / "query_authorization.json").read_text(encoding="utf-8")
    )

    class LeakyClient:
        def query(self, **_: Any) -> dict[str, Any]:
            return raw

    target = _live_target()
    transport = LiveHydraTransport(
        config=HydraDBConfig(api_key="credential", database=target.database),
        target=target,
        client=LeakyClient(),  # type: ignore[arg-type]
        clock=lambda: 1.0,
    )
    gold = _resolved()
    observations = AblationRunner(
        mode=RunMode.LIVE,
        hydra_transport=transport,
        target=target,
    ).run_question(
        run_id="leaky-b",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
    )

    assert observations[1].status == "degraded"
    assert observations[1].returned_relations == ()
    assert observations[2].status == "ready"


def test_live_condition_c_rejects_non_byog_graph_before_scoring() -> None:
    raw = json.loads(
        (ROOT / "fixtures" / "hydradb" / "query_authorization.json").read_text(encoding="utf-8")
    )

    class AutomaticGraphClient:
        def query(self, **kwargs: Any) -> dict[str, Any]:
            response = json.loads(json.dumps(raw))
            graph = response["data"]["graph_context"]
            if kwargs["graph_context"] is False:
                graph.update(
                    {"query_paths": [], "chunk_relations": [], "chunk_id_to_group_ids": {}}
                )
            else:
                for group in (*graph["query_paths"], *graph["chunk_relations"]):
                    for triplet in group["triplets"]:
                        triplet["relation"]["origin"] = "automatic"
            return response

    target = _live_target()
    transport = LiveHydraTransport(
        config=HydraDBConfig(api_key="credential", database=target.database),
        target=target,
        client=AutomaticGraphClient(),  # type: ignore[arg-type]
        clock=lambda: 1.0,
    )
    gold = _resolved()
    observations = AblationRunner(
        mode=RunMode.LIVE,
        hydra_transport=transport,
        target=target,
    ).run_question(
        run_id="automatic-live",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
    )

    assert observations[1].status == "ready"
    assert observations[2].status == "degraded"
    assert observations[2].returned_node_ids == ()
    assert observations[2].returned_relations == ()
    assert score_observation(gold.questions[0], observations[2]).required_node_hits == 0


def test_live_condition_c_requires_a_grounded_byog_path() -> None:
    raw = json.loads(
        (ROOT / "fixtures" / "hydradb" / "query_authorization.json").read_text(encoding="utf-8")
    )

    class EmptyGraphClient:
        def query(self, **_: Any) -> dict[str, Any]:
            response = json.loads(json.dumps(raw))
            response["data"]["graph_context"] = {
                "query_paths": [],
                "chunk_relations": [],
                "chunk_id_to_group_ids": {},
            }
            return response

    target = _live_target()
    transport = LiveHydraTransport(
        config=HydraDBConfig(api_key="credential", database=target.database),
        target=target,
        client=EmptyGraphClient(),  # type: ignore[arg-type]
        clock=lambda: 1.0,
    )
    gold = _resolved()
    observations = AblationRunner(
        mode=RunMode.LIVE,
        hydra_transport=transport,
        target=target,
    ).run_question(
        run_id="empty-graph-live",
        question=gold.questions[0],
        baseline_documents=load_baseline_documents(FIXTURES / "corpus.json"),
    )

    assert observations[1].status == "ready"
    assert observations[2].status == "degraded"
    assert observations[2].returned_node_ids == ()
    assert observations[2].returned_relations == ()


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
        [
            sys.executable,
            "-m",
            "evaluation",
            "--live",
            "--output",
            str(output),
            "--run-id",
            "live-no-credentials",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not output.exists()
    assert not (output / "raw.jsonl").exists()
    assert "requires HYDRA_DB_DATABASE" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "run_id",
    (
        None,
        "   ",
        "offline-rehearsal",
        "judge-rehearsal",
        "offline-run",
        "replace-with-live-run-id",
    ),
)
def test_live_cli_requires_explicit_non_rehearsal_run_id(
    tmp_path: Path, run_id: str | None
) -> None:
    output = tmp_path / "live-results"
    command = [sys.executable, "-m", "evaluation", "--live", "--output", str(output)]
    if run_id is not None:
        command.extend(("--run-id", run_id))
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires an explicit non-rehearsal --run-id" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()


def test_completeness_guard_rejects_missing_nonready_or_mixed_runs() -> None:
    records = _records()
    assert _complete(records[:2]).complete is False
    degraded = records[2].model_copy(
        update={"observation": records[2].observation.model_copy(update={"status": "degraded"})}
    )
    assert _complete((*records[:2], degraded)).complete is False
    mixed = records[2].model_copy(update={"gold_digest": "0" * 64})
    assert _complete((*records[:2], mixed)).complete is False


def test_completeness_binds_current_gold_one_run_target_and_paired_bodies() -> None:
    records = _as_live_records()
    assert _complete_live(records).comparative_claims_allowed is True

    for invalid_run_id in ("   ", "replace-with-live-run-id", "offline-run"):
        invalid = tuple(
            record.model_copy(
                update={
                    "observation": record.observation.model_copy(update={"run_id": invalid_run_id})
                }
            )
            for record in records
        )
        assert _complete_live(invalid).comparative_claims_allowed is False
        payload = records[0].observation.model_dump(mode="json")
        payload["run_id"] = invalid_run_id
        with pytest.raises(ValidationError, match="concrete non-rehearsal"):
            RetrievalObservation.model_validate(payload)

    stale = tuple(record.model_copy(update={"gold_digest": "0" * 64}) for record in records)
    assert _complete_live(stale).comparative_claims_allowed is False

    stale_corpus = tuple(
        record.model_copy(update={"baseline_corpus_digest": "0" * 64}) for record in records
    )
    assert _complete_live(stale_corpus).comparative_claims_allowed is False

    mixed_run = (
        records[0],
        records[1].model_copy(
            update={
                "observation": records[1].observation.model_copy(update={"run_id": "other-run"})
            }
        ),
        records[2],
    )
    assert _complete_live(mixed_run).comparative_claims_allowed is False

    graph = records[2]
    assert graph.observation.request_plan is not None
    changed_plan = graph.observation.request_plan.model_copy(update={"query": "different query"})
    changed_body = HydraDBRequestBody(
        **changed_plan.model_dump(mode="json"),
        database=graph.observation.target.database,
    )
    changed_payload = graph.observation.model_dump(mode="json")
    changed_payload.update(
        {
            "request_plan": changed_plan.model_dump(mode="json"),
            "hydradb_request_body": changed_body.model_dump(mode="json"),
        }
    )
    changed_graph = graph.model_copy(
        update={"observation": RetrievalObservation.model_validate(changed_payload)}
    )
    assert _complete_live((*records[:2], changed_graph)).comparative_claims_allowed is False

    wrong_target = records[2].model_copy(
        update={
            "observation": records[2].observation.model_copy(
                update={
                    "target": records[2].observation.target.model_copy(
                        update={"database": "other-database"}
                    )
                }
            )
        }
    )
    assert _complete_live((*records[:2], wrong_target)).comparative_claims_allowed is False

    wrong_database_bodies = [records[0]]
    for record in records[1:]:
        assert record.observation.hydradb_request_body is not None
        wrong_body = record.observation.hydradb_request_body.model_copy(
            update={"database": "other-database"}
        )
        wrong_database_bodies.append(
            record.model_copy(
                update={
                    "observation": record.observation.model_copy(
                        update={"hydradb_request_body": wrong_body}
                    )
                }
            )
        )
    assert _complete_live(tuple(wrong_database_bodies)).comparative_claims_allowed is False


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

    outcome = AgentOutcomeRecord(
        retrieval_artifact_digest="a" * 64,
        run_id="codex-live-run",
        agent="codex",
        model="codex-model-v1",
        question_id="authorization-flow",
        condition="A",
        task_completed=True,
        repository_tool_calls=1,
        hydradb_query_calls=0,
        context_characters_returned=100,
        tests_passed=True,
        outcome="completed",
        rework_count=0,
    )
    with pytest.raises(ValidationError):
        AgentOutcomeRecord.model_validate(
            {**outcome.model_dump(mode="json"), "hidden_reasoning": "do not record"}
        )
    with pytest.raises(ValidationError, match="disagree"):
        AgentOutcomeRecord.model_validate({**outcome.model_dump(mode="json"), "outcome": "failed"})
    with pytest.raises(ValidationError, match="repository-relative"):
        AgentOutcomeRecord.model_validate(
            {
                **outcome.model_dump(mode="json"),
                "correct_files_changed": ["../outside.py"],
            }
        )
    with pytest.raises(ValidationError, match="condition A"):
        AgentOutcomeRecord.model_validate(
            {**outcome.model_dump(mode="json"), "hydradb_query_calls": 1}
        )
    with pytest.raises(ValidationError, match="conditions B/C"):
        AgentOutcomeRecord.model_validate(
            {
                **outcome.model_dump(mode="json"),
                "condition": "B",
                "hydradb_query_calls": 0,
            }
        )
    with pytest.raises(ValidationError, match="cannot exceed"):
        AgentOutcomeRecord.model_validate(
            {
                **outcome.model_dump(mode="json"),
                "condition": "C",
                "repository_tool_calls": 1,
                "hydradb_query_calls": 2,
            }
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
    assert all(not check.passed for check in checks if check.name.startswith("Agent manifest"))
    assert all(
        "does not prove an agent run" in check.detail or "target must validate" in check.detail
        for check in checks
        if check.name.startswith("Agent manifest")
    )


def test_demo_preflight_requires_the_exact_gold_revision_and_current_collection() -> None:
    environment = _live_environment()
    wrong_revision = run_preflight(
        project_root=ROOT,
        environment=environment,
        health={
            "state": "ready",
            "revision_verified": True,
            "revision_id": "another-revision",
            "collection": "current",
            "database": "live-evaluation",
            "repository_id": "evaluation-fixture",
            "repository_root_fingerprint": _fixture_target().repository_root_fingerprint,
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
            "database": "live-evaluation",
            "repository_id": "evaluation-fixture",
            "repository_root_fingerprint": _fixture_target().repository_root_fingerprint,
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
            "database": "live-evaluation",
            "repository_id": "evaluation-fixture",
            "repository_root_fingerprint": _fixture_target().repository_root_fingerprint,
        },
        results_path=None,
    )

    def verified(checks):
        return next(check for check in checks if check.name == "Verified live revision")

    assert verified(wrong_revision).passed is False
    assert verified(wrong_collection).passed is False
    assert verified(ready).passed is True


def test_demo_preflight_binds_live_artifacts_to_gold_database_repository_and_root(
    tmp_path: Path,
) -> None:
    records = _as_live_records(_all_records())
    results = tmp_path / "live.jsonl"
    write_jsonl(results, records)
    health = {
        "state": "ready",
        "revision_verified": True,
        "revision_id": "eval-rev-1",
        "collection": "current",
        "database": "live-evaluation",
        "repository_id": "evaluation-fixture",
        "repository_root_fingerprint": _fixture_target().repository_root_fingerprint,
    }
    ready = run_preflight(
        project_root=ROOT,
        environment=_live_environment(),
        health=health,
        results_path=results,
    )
    wrong_database = run_preflight(
        project_root=ROOT,
        environment=_live_environment(),
        health={**health, "database": "other-database"},
        results_path=results,
    )
    wrong_repository = run_preflight(
        project_root=ROOT,
        environment={**_live_environment(), "HYDRA_REPOSITORY_ID": "other-repository"},
        health=health,
        results_path=results,
    )
    wrong_root = run_preflight(
        project_root=ROOT,
        environment={**_live_environment(), "HYDRA_REPOSITORY_ROOT": str(tmp_path)},
        health=health,
        results_path=results,
    )
    wrong_health_repository = run_preflight(
        project_root=ROOT,
        environment=_live_environment(),
        health={**health, "repository_id": "other-repository"},
        results_path=results,
    )
    wrong_health_root = run_preflight(
        project_root=ROOT,
        environment=_live_environment(),
        health={**health, "repository_root_fingerprint": "0" * 64},
        results_path=results,
    )

    assert all(check.passed for check in ready if not check.name.startswith("Agent manifest"))
    assert all(not check.passed for check in ready if check.name.startswith("Agent manifest"))
    assert all(
        "no live retrieval/results_path" in check.detail
        for check in ready
        if check.name.startswith("Agent manifest")
    )
    assert (
        next(check for check in wrong_database if check.name == "Verified live revision").passed
        is False
    )
    assert (
        next(
            check for check in wrong_repository if check.name == "Configured evaluation target"
        ).passed
        is False
    )
    assert (
        next(check for check in wrong_root if check.name == "Configured evaluation target").passed
        is False
    )
    assert (
        next(
            check for check in wrong_health_repository if check.name == "Verified live revision"
        ).passed
        is False
    )
    assert (
        next(check for check in wrong_health_root if check.name == "Verified live revision").passed
        is False
    )
    assert (
        next(check for check in wrong_repository if check.name == "Live A/B/C artifacts").passed
        is False
    )


def test_preflight_recomputes_metrics_and_agent_manifests_require_bound_results(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    shutil.copytree(FIXTURES, project / "fixtures" / "evaluation")
    shutil.copytree(ROOT / "evaluation" / "manifests", project / "evaluation" / "manifests")
    gold = load_and_resolve_gold(project / "fixtures" / "evaluation" / "gold.json")
    target = EvaluationTarget(
        database="live-evaluation",
        repository_id=gold.manifest.repository_id,
        revision_id=gold.manifest.revision_id,
        repository_root_fingerprint=repository_root_fingerprint(gold.fixture_root),
    )
    agent_retrieval: dict[str, Path] = {}
    agent_outcomes: dict[str, Path] = {}
    for agent in ("codex", "claude-code"):
        run_id = f"{agent}-live-run"
        model = f"{agent}-test-model-v1"
        records = _as_live_records(_all_records(), target=target, run_id=run_id)
        retrieval_path = project / "artifacts" / f"{agent}-retrieval.jsonl"
        outcome_path = project / "artifacts" / f"{agent}-outcomes.jsonl"
        write_jsonl(retrieval_path, records)
        write_agent_outcomes(
            outcome_path,
            _agent_outcomes(
                records,
                agent=agent,
                model=model,
                retrieval_digest=artifact_digest(retrieval_path),
            ),
        )
        agent_retrieval[agent] = retrieval_path
        agent_outcomes[agent] = outcome_path
        manifest_path = project / "evaluation" / "manifests" / f"{agent}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(
            {
                "run_id": run_id,
                "model": model,
                "retrieval_results_path": retrieval_path.relative_to(project).as_posix(),
                "results_path": outcome_path.relative_to(project).as_posix(),
            }
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    environment = {
        **_live_environment(),
        "HYDRA_REPOSITORY_ROOT": str(gold.fixture_root),
    }
    health = {
        "state": "ready",
        "revision_verified": True,
        "revision_id": "eval-rev-1",
        "collection": "current",
        "database": "live-evaluation",
        "repository_id": "evaluation-fixture",
        "repository_root_fingerprint": target.repository_root_fingerprint,
    }
    ready = run_preflight(
        project_root=project,
        environment=environment,
        health=health,
        results_path=agent_retrieval["codex"],
    )

    valid_records = read_jsonl(agent_retrieval["codex"])
    fabricated_metrics = valid_records[0].metrics.model_copy(
        update={"context_chars": valid_records[0].metrics.context_chars + 1}
    )
    fabricated = (
        valid_records[0].model_copy(update={"metrics": fabricated_metrics}),
        *valid_records[1:],
    )
    fabricated_path = project / "artifacts" / "fabricated.jsonl"
    write_jsonl(fabricated_path, fabricated)
    rejected = run_preflight(
        project_root=project,
        environment=environment,
        health=health,
        results_path=fabricated_path,
    )
    stale_corpus_path = project / "artifacts" / "stale-corpus.jsonl"
    write_jsonl(
        stale_corpus_path,
        tuple(
            record.model_copy(update={"baseline_corpus_digest": "0" * 64})
            for record in valid_records
        ),
    )
    stale_corpus = run_preflight(
        project_root=project,
        environment=environment,
        health=health,
        results_path=stale_corpus_path,
    )

    assert all(check.passed for check in ready)
    artifact_check = next(check for check in rejected if check.name == "Live A/B/C artifacts")
    assert artifact_check.passed is False
    assert "recompute" in artifact_check.detail
    corpus_check = next(check for check in stale_corpus if check.name == "Live A/B/C artifacts")
    assert corpus_check.passed is False

    codex_outcomes = read_agent_outcomes(agent_outcomes["codex"])
    assert codex_outcomes[0].agent == "codex"

    write_agent_outcomes(
        agent_outcomes["codex"],
        (
            codex_outcomes[0].model_copy(update={"retrieval_artifact_digest": "0" * 64}),
            *codex_outcomes[1:],
        ),
    )
    digest_mismatch = run_preflight(
        project_root=project,
        environment=environment,
        health=health,
        results_path=agent_retrieval["codex"],
    )
    codex_digest_check = next(
        check for check in digest_mismatch if check.name == "Agent manifest codex.json"
    )
    assert codex_digest_check.passed is False
    assert "do not bind" in codex_digest_check.detail

    codex_manifest_path = project / "evaluation" / "manifests" / "codex.json"
    codex_manifest = json.loads(codex_manifest_path.read_text(encoding="utf-8"))
    codex_manifest["results_path"] = agent_retrieval["codex"].relative_to(project).as_posix()
    codex_manifest_path.write_text(json.dumps(codex_manifest), encoding="utf-8")
    masquerade = run_preflight(
        project_root=project,
        environment=environment,
        health=health,
        results_path=agent_retrieval["codex"],
    )
    codex_check = next(check for check in masquerade if check.name == "Agent manifest codex.json")
    assert codex_check.passed is False
    assert "invalid agent outcome record" in codex_check.detail

    with pytest.raises(ValueError, match="invalid agent outcome record"):
        read_agent_outcomes(agent_retrieval["codex"])


def test_documented_preflight_module_invocation_is_executable() -> None:
    runbook = (ROOT / "demo" / "five-minute-runbook.md").read_text(encoding="utf-8")
    assert "python -m demo.preflight --results" in runbook
    assert "python demo/preflight.py" not in runbook

    result = subprocess.run(
        [sys.executable, "-m", "demo.preflight", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--results" in result.stdout


def test_demo_saves_shared_lens_before_edit_and_drift_review() -> None:
    runbook = (ROOT / "demo" / "five-minute-runbook.md").read_text(encoding="utf-8")

    save = runbook.index("Save and review the current authorization flow as the shared System Lens")
    edit = runbook.index('replace `if not authorize(user):` with `if user != "admin":`')
    drift = runbook.index("Open the shared System Lens")

    assert save < edit < drift


def test_live_completeness_requires_all_three_conditions() -> None:
    records = _as_live_records()
    report = _complete_live(records)
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
