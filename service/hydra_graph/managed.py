"""Private managed-runtime IPC used by the bundled VS Code service."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, TextIO

from .config import DEFAULT_API_URL
from .diagnostics import log_event
from .hydradb import CredentialProvider, HydraCredentials, HydraDBUnavailable
from .ids import normalize_repository_id

MANAGED_PROTOCOL = "hack-hydra.managed-ipc.v2"
MAX_IPC_LINE = 32_768
# One repository query reads the sync status two or three times, and each read asked
# VS Code whether credentials exist. The answer changes only when the user edits the
# project binding, so a short cache removes the repeated round trips without letting
# a removed binding look configured for longer than a moment.
CONFIGURED_CACHE_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class ManagedStart:
    repository_root: Path
    repository_id: str
    control_key: str
    api_url: str = DEFAULT_API_URL
    collection: str = "current"
    evolution_collection: str = "evolution"


class ManagedIpc:
    """One serialized request/response channel over the child process pipes."""

    def __init__(self, reader: TextIO, writer: TextIO) -> None:
        self._reader = reader
        self._writer = writer
        self._lock = Lock()

    @classmethod
    def bootstrap(cls, reader: TextIO, writer: TextIO) -> tuple[ManagedIpc, ManagedStart]:
        channel = cls(reader, writer)
        channel._write(
            {
                "protocol": MANAGED_PROTOCOL,
                "type": "service_hello",
                "pid": os.getpid(),
            }
        )
        message = channel._read()
        if message.get("protocol") != MANAGED_PROTOCOL or message.get("type") != "service_start":
            raise RuntimeError("Managed service did not receive a valid startup handshake")
        root_value = message.get("repository_root")
        repository_value = message.get("repository_id")
        control_key = message.get("control_key")
        if not isinstance(root_value, str) or not root_value:
            raise RuntimeError("Managed startup repository root is invalid")
        if not isinstance(repository_value, str):
            raise RuntimeError("Managed startup repository ID is invalid")
        if not isinstance(control_key, str) or len(control_key) < 32:
            raise RuntimeError("Managed startup control key is invalid")
        root = Path(root_value).resolve()
        if not root.is_dir():
            raise RuntimeError("Managed startup repository root does not exist")
        api_url = message.get("api_url", DEFAULT_API_URL)
        collection = message.get("collection", "current")
        evolution = message.get("evolution_collection", "evolution")
        settings = (api_url, collection, evolution)
        if not all(isinstance(item, str) and item.strip() for item in settings):
            raise RuntimeError("Managed startup collection or API URL is invalid")
        return channel, ManagedStart(
            repository_root=root,
            repository_id=normalize_repository_id(repository_value),
            control_key=control_key,
            api_url=api_url.rstrip("/"),
            collection=collection,
            evolution_collection=evolution,
        )

    def request(self, message_type: str, **payload: Any) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        # One lock serializes every round trip, and VS Code answers on a single
        # thread, so this wait is a real part of the time a query costs.
        started = time.monotonic()
        waited_for_lock = 0.0
        with self._lock:
            waited_for_lock = (time.monotonic() - started) * 1_000
            self._write(
                {
                    "protocol": MANAGED_PROTOCOL,
                    "type": message_type,
                    "request_id": request_id,
                    **payload,
                }
            )
            response = self._read()
        log_event(
            "ipc",
            type=message_type,
            ms=(time.monotonic() - started) * 1_000,
            lock_ms=waited_for_lock,
        )
        if response.get("protocol") != MANAGED_PROTOCOL:
            raise HydraDBUnavailable("Managed credential channel returned an invalid protocol")
        if response.get("request_id") != request_id or response.get("type") != "response":
            raise HydraDBUnavailable("Managed credential channel returned an invalid response")
        if response.get("ok") is not True:
            raise HydraDBUnavailable("HydraDB credentials are unavailable for this project")
        return response

    def notify(self, message_type: str, **payload: Any) -> None:
        with self._lock:
            self._write(
                {
                    "protocol": MANAGED_PROTOCOL,
                    "type": message_type,
                    **payload,
                }
            )

    def _write(self, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(dict(payload), separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_IPC_LINE:
            raise RuntimeError("Managed IPC message exceeds its size limit")
        self._writer.write(serialized + "\n")
        self._writer.flush()

    def _read(self) -> dict[str, Any]:
        raw = self._reader.readline(MAX_IPC_LINE + 1)
        if not raw or len(raw.encode("utf-8")) > MAX_IPC_LINE:
            raise HydraDBUnavailable("Managed credential channel closed or exceeded its limit")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HydraDBUnavailable("Managed credential channel returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HydraDBUnavailable("Managed credential channel returned a non-object")
        return payload


class ManagedCredentialProvider(CredentialProvider):
    """Acquire one credential lease from VS Code for each HydraDB operation."""

    def __init__(
        self,
        channel: ManagedIpc,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._channel = channel
        self._monotonic = monotonic
        self._configured: dict[str, tuple[float, bool]] = {}
        self._configured_lock = Lock()

    def configured(self, repository_id: str) -> bool:
        project = normalize_repository_id(repository_id)
        now = self._monotonic()
        with self._configured_lock:
            cached = self._configured.get(project)
            if cached is not None and cached[0] > now:
                return cached[1]
        try:
            response = self._channel.request("credential_status", repository_id=project)
        except HydraDBUnavailable:
            self._forget(project)
            return False
        answer = response.get("configured") is True
        with self._configured_lock:
            self._configured[project] = (now + CONFIGURED_CACHE_SECONDS, answer)
        return answer

    @contextmanager
    def acquire(self, repository_id: str) -> Iterator[HydraCredentials]:
        project = normalize_repository_id(repository_id)
        try:
            response = self._channel.request("credential_request", repository_id=project)
        except HydraDBUnavailable:
            # A refused lease is the strongest proof that the binding is gone, so the
            # cached "configured" answer must not outlive it.
            self._forget(project)
            raise
        api_key = response.get("api_key")
        database = response.get("database")
        if (
            not isinstance(api_key, str)
            or len(api_key.strip()) < 8
            or not isinstance(database, str)
            or not database.strip()
        ):
            raise HydraDBUnavailable("Managed credential channel returned invalid credentials")
        credentials = HydraCredentials(api_key=api_key.strip(), database=database.strip())
        del response, api_key, database
        try:
            yield credentials
        finally:
            del credentials

    def _forget(self, repository_id: str) -> None:
        with self._configured_lock:
            self._configured.pop(repository_id, None)
