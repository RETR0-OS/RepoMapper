"""Small, transport-injectable adapter for direct HydraDB API v2 calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, parse, request

from .config import HydraDBConfig

JsonObject = dict[str, Any]


class HydraDBError(RuntimeError):
    """Base error for HydraDB operations."""


class HydraDBUnavailable(HydraDBError):
    """HydraDB cannot currently serve this operation."""


class HydraDBAPIError(HydraDBError):
    """HydraDB returned an unsuccessful response."""

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class HydraDBContractError(HydraDBError, ValueError):
    """A request violates the public HydraDB v2 contract."""


@dataclass(frozen=True, slots=True)
class HydraCredentials:
    """One short-lived credential lease for one HydraDB operation."""

    api_key: str
    database: str


class CredentialProvider(Protocol):
    def configured(self, repository_id: str) -> bool: ...

    def acquire(self, repository_id: str) -> AbstractContextManager[HydraCredentials]: ...


class StaticCredentialProvider:
    """Developer/test provider for the legacy environment-configured runtime."""

    def __init__(self, config: HydraDBConfig) -> None:
        self._config = config

    def configured(self, repository_id: str) -> bool:
        del repository_id
        return self._config.configured

    @contextmanager
    def acquire(self, repository_id: str) -> Iterator[HydraCredentials]:
        del repository_id
        if not self._config.configured:
            raise HydraDBUnavailable(
                "HydraDB is unavailable because credentials are not configured for this project"
            )
        assert self._config.api_key is not None
        credentials = HydraCredentials(
            api_key=self._config.api_key,
            database=self._config.database,
        )
        try:
            yield credentials
        finally:
            del credentials


class Transport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        form: Mapping[str, str] | None = None,
        timeout: float,
    ) -> Mapping[str, Any]: ...


class UrllibTransport:
    """Dependency-free JSON and multipart HTTP transport."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        form: Mapping[str, str] | None = None,
        timeout: float,
    ) -> Mapping[str, Any]:
        if json_body is not None and form is not None:
            raise ValueError("A request cannot have both JSON and multipart bodies")
        target = url
        if query:
            target = f"{url}?{parse.urlencode(query)}"
        request_headers = dict(headers)
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif form is not None:
            body, content_type = _encode_multipart(form)
            request_headers["Content-Type"] = content_type
        http_request = request.Request(
            target, data=body, headers=request_headers, method=method.upper()
        )
        try:
            with request.urlopen(http_request, timeout=timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            payload = _decode_json(raw)
            code, message = _error_details(payload)
            raise HydraDBAPIError(
                message or f"HydraDB returned HTTP {exc.code}", code=code, status=exc.code
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise HydraDBUnavailable("HydraDB is unavailable") from exc
        payload = _decode_json(raw)
        if not isinstance(payload, Mapping):
            raise HydraDBAPIError("HydraDB returned a non-object response")
        return payload


class HydraDBClient:
    """Owned boundary around current HydraDB v2 endpoint naming."""

    def __init__(
        self,
        config: HydraDBConfig,
        *,
        repository_id: str = "default",
        credential_provider: CredentialProvider | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.repository_id = repository_id
        self._credential_provider = credential_provider or StaticCredentialProvider(config)
        self._transport = transport or UrllibTransport()
        self._sleep = sleep

    def ingest(
        self,
        *,
        app_knowledge: Sequence[Mapping[str, Any]],
        graph_payload: Mapping[str, Mapping[str, Any]],
        collection: str | None = None,
        upsert: bool = True,
    ) -> JsonObject:
        sources = [dict(item) for item in app_knowledge]
        _validate_ingest(sources, graph_payload)
        with self._credentials() as credentials:
            form = {
                "type": "knowledge",
                "database": credentials.database,
                "collection": collection or self.config.collection,
                "upsert": "true" if upsert else "false",
                "app_knowledge": json.dumps(sources, separators=(",", ":")),
                "graph_payload": json.dumps(graph_payload, separators=(",", ":")),
            }
            return self._call("POST", "/context/ingest", credentials=credentials, form=form)

    def ingest_evolution(
        self,
        *,
        app_knowledge: Sequence[Mapping[str, Any]],
        graph_payload: Mapping[str, Mapping[str, Any]],
        upsert: bool = True,
    ) -> JsonObject:
        """Ingest immutable deltas or shared lenses into one explicit collection."""

        return self.ingest(
            app_knowledge=app_knowledge,
            graph_payload=graph_payload,
            collection=self.config.evolution_collection,
            upsert=upsert,
        )

    def query(
        self,
        *,
        query: str,
        collection: str | None = None,
        collections: Sequence[str] | Mapping[str, float] | None = None,
        query_type: str = "knowledge",
        query_by: str = "hybrid",
        mode: str = "thinking",
        graph_context: bool = True,
        max_results: int = 10,
        metadata_filters: Mapping[str, Any] | None = None,
        query_forceful_relations: bool = True,
    ) -> JsonObject:
        if not query.strip():
            raise HydraDBContractError("query must not be blank")
        if not 1 <= max_results <= 50:
            raise HydraDBContractError("max_results must be between 1 and 50")
        if collection is not None and collections is not None:
            raise HydraDBContractError("Use collection or collections, not both")
        with self._credentials() as credentials:
            body: JsonObject = {
                "database": credentials.database,
                "query": query,
                "type": query_type,
                "query_by": query_by,
                "mode": mode,
                "graph_context": graph_context,
                "query_forceful_relations": query_forceful_relations,
                "max_results": max_results,
            }
            if collections is not None:
                body["collections"] = collections
            else:
                body["collection"] = collection or self.config.collection
            if metadata_filters:
                body["metadata_filters"] = dict(metadata_filters)
            return self._call("POST", "/query", credentials=credentials, json_body=body)

    def query_evolution(
        self,
        *,
        query: str,
        query_type: str = "knowledge",
        query_by: str = "hybrid",
        mode: str = "thinking",
        graph_context: bool = True,
        max_results: int = 10,
        metadata_filters: Mapping[str, Any] | None = None,
        query_forceful_relations: bool = True,
    ) -> JsonObject:
        """Query only the configured evolution collection; never traverse current."""

        return self.query(
            query=query,
            collection=self.config.evolution_collection,
            query_type=query_type,
            query_by=query_by,
            mode=mode,
            graph_context=graph_context,
            max_results=max_results,
            metadata_filters=metadata_filters,
            query_forceful_relations=query_forceful_relations,
        )

    def status(self, ids: Sequence[str]) -> JsonObject:
        clean_ids = _clean_ids(ids)
        with self._credentials() as credentials:
            return self._call(
                "GET",
                "/context/status",
                credentials=credentials,
                query={"database": credentials.database, "ids": ",".join(clean_ids)},
            )

    def delete(self, ids: Sequence[str]) -> JsonObject:
        with self._credentials() as credentials:
            return self._call(
                "DELETE",
                "/context",
                credentials=credentials,
                json_body={
                    "database": credentials.database,
                    "ids": _clean_ids(ids),
                    "type": "knowledge",
                },
            )

    def relations(
        self,
        source_id: str,
        *,
        collection: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> JsonObject:
        if not source_id.strip():
            raise HydraDBContractError("source_id must not be blank")
        if not 1 <= limit <= 500:
            raise HydraDBContractError("limit must be between 1 and 500")
        with self._credentials() as credentials:
            params = {
                "database": credentials.database,
                "collection": collection or self.config.collection,
                "id": source_id,
                "limit": str(limit),
            }
            if cursor is not None:
                params["cursor"] = cursor
            return self._call("GET", "/context/relations", credentials=credentials, query=params)

    @property
    def configured(self) -> bool:
        return self._credential_provider.configured(self.repository_id)

    @property
    def credential_provider(self) -> CredentialProvider:
        return self._credential_provider

    def database_fingerprint(self) -> str | None:
        try:
            with self._credentials() as credentials:
                return hmac.new(
                    credentials.api_key.encode("utf-8"),
                    credentials.database.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
        except HydraDBUnavailable:
            return None

    def _credentials(self) -> AbstractContextManager[HydraCredentials]:
        return self._credential_provider.acquire(self.repository_id)

    def _call(
        self,
        method: str,
        path: str,
        *,
        credentials: HydraCredentials,
        query: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        form: Mapping[str, str] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        headers = {
            "Authorization": f"Bearer {credentials.api_key}",
            "API-Version": "2",
            "Accept": "application/json",
        }
        headers.update(extra_headers or {})
        attempts = self.config.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._transport.request(
                    method=method,
                    url=f"{self.config.api_url}{path}",
                    headers=headers,
                    query=query,
                    json_body=json_body,
                    form=form,
                    timeout=self.config.request_timeout_seconds,
                )
                result = dict(response)
                _raise_envelope_error(result)
                return result
            except HydraDBAPIError as exc:
                if exc.status not in {429, 500, 502, 503} or attempt == attempts - 1:
                    raise
            except HydraDBUnavailable:
                if attempt == attempts - 1:
                    raise
            delay = self.config.retry_backoff_seconds * (2**attempt)
            # Small jitter prevents callers from retrying in lockstep. Tests can
            # use a zero backoff and injected sleep for deterministic behavior.
            self._sleep(delay + (random.random() * delay * 0.1 if delay else 0))
        raise AssertionError("unreachable")


def response_data(response: Mapping[str, Any]) -> JsonObject:
    """Return v2 envelope data while accepting direct payloads in test doubles."""

    data = response.get("data", response)
    if not isinstance(data, Mapping):
        raise HydraDBAPIError("HydraDB response data must be an object")
    return dict(data)


def _validate_ingest(
    sources: Sequence[Mapping[str, Any]], graph_payload: Mapping[str, Mapping[str, Any]]
) -> None:
    if not sources:
        raise HydraDBContractError("At least one app_knowledge source is required")
    source_ids = [str(item.get("id", "")).strip() for item in sources]
    if any(not source_id for source_id in source_ids):
        raise HydraDBContractError("Every app_knowledge source requires an id")
    if len(source_ids) != len(set(source_ids)):
        raise HydraDBContractError("app_knowledge source ids must be unique")
    graph_ids = set(graph_payload)
    unknown = graph_ids.difference(source_ids)
    if unknown:
        raise HydraDBContractError(
            "graph_payload keys must match sources in the same request: "
            + ", ".join(sorted(unknown))
        )
    for source_id, graph in graph_payload.items():
        entities = graph.get("entities", {})
        relations = graph.get("relations", [])
        if not isinstance(entities, Mapping) or not isinstance(relations, Sequence):
            raise HydraDBContractError(f"Invalid graph_payload for {source_id}")
        if len(entities) > 5_000 or len(relations) > 10_000:
            raise HydraDBContractError(f"HydraDB BYOG limits exceeded for {source_id}")
        for entity in entities.values():
            if not isinstance(entity, Mapping) or not str(entity.get("name", "")).strip():
                raise HydraDBContractError(f"Every entity in {source_id} requires a name")
            if len(str(entity["name"])) > 256:
                raise HydraDBContractError("HydraDB entity names are limited to 256 characters")
        degree: dict[str, int] = {}
        for relation in relations:
            if not isinstance(relation, Mapping):
                raise HydraDBContractError(f"Invalid relation in {source_id}")
            relation_source = str(relation.get("source", ""))
            relation_target = str(relation.get("target", ""))
            if relation_source not in entities or relation_target not in entities:
                raise HydraDBContractError("BYOG relations must reference local entity handles")
            predicate = str(relation.get("predicate", ""))
            if not predicate or len(predicate) > 256:
                raise HydraDBContractError("BYOG predicates must contain 1 to 256 characters")
            if len(str(relation.get("context", ""))) > 2_000:
                raise HydraDBContractError("BYOG relation context is limited to 2000 characters")
            degree[relation_source] = degree.get(relation_source, 0) + 1
            degree[relation_target] = degree.get(relation_target, 0) + 1
        if any(value > 500 for value in degree.values()):
            raise HydraDBContractError("BYOG entity degree is limited to 500")


def _clean_ids(ids: Sequence[str]) -> list[str]:
    clean = [item.strip() for item in ids if item.strip()]
    if not clean:
        raise HydraDBContractError("At least one source id is required")
    if any("," in item for item in clean):
        raise HydraDBContractError("HydraDB source ids cannot contain commas")
    return clean


def _raise_envelope_error(response: Mapping[str, Any]) -> None:
    if response.get("success") is not False:
        return
    code, message = _error_details(response)
    raise HydraDBAPIError(message or "HydraDB operation failed", code=code)


def _error_details(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None
    detail = payload.get("error") or payload.get("detail") or payload
    if isinstance(detail, Mapping):
        return _optional_string(detail.get("code") or detail.get("error_code")), _optional_string(
            detail.get("message")
        )
    return None, _optional_string(detail)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HydraDBAPIError("HydraDB returned invalid JSON") from exc


def _encode_multipart(form: Mapping[str, str]) -> tuple[bytes, str]:
    boundary = f"hydra-graph-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in form.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
