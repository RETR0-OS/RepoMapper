"""Authentication boundary for the extension-managed loopback service."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

MANAGED_SERVICE_PROTOCOL = "hack-hydra.managed-service.v1"
MAX_CLOCK_SKEW_SECONDS = 30
PROJECT_TOKEN_TTL_SECONDS = 300
MAX_REQUEST_BYTES = 1_048_576
MAX_REQUESTS_PER_MINUTE = 240


@dataclass(frozen=True, slots=True)
class ProjectGrant:
    repository_root: Path
    repository_id: str
    expires_at: int


class ManagedSecurity:
    """Validate signed window attachment and issue short-lived project grants."""

    def __init__(
        self,
        control_key: str,
        *,
        permitted_hosts: set[str] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        if len(control_key) < 32:
            raise ValueError("Managed control key is invalid")
        self._key = control_key.encode("utf-8")
        self._now = now
        self._hosts = permitted_hosts or {"127.0.0.1", "localhost", "[::1]", "::1"}
        self._tokens: dict[str, ProjectGrant] = {}
        self._nonces: dict[str, int] = {}
        self._requests: dict[str, deque[int]] = defaultdict(deque)
        self._lock = RLock()

    @staticmethod
    def canonical_root(value: str | Path) -> Path:
        root = Path(value).resolve()
        if not root.is_dir():
            raise ValueError("Project root must be an existing directory")
        return root

    @classmethod
    def challenge_message(
        cls,
        *,
        repository_root: str | Path,
        repository_id: str,
        timestamp: int,
        nonce: str,
    ) -> bytes:
        root = str(cls.canonical_root(repository_root)).replace("\\", "/")
        if os.name == "nt":
            root = root.lower()
        return (
            f"{MANAGED_SERVICE_PROTOCOL}\n{timestamp}\n{nonce}\n{root}\n{repository_id}"
        ).encode()

    def sign_challenge(
        self,
        *,
        repository_root: str | Path,
        repository_id: str,
        timestamp: int,
        nonce: str,
    ) -> str:
        signature = hmac.new(
            self._key,
            self.challenge_message(
                repository_root=repository_root,
                repository_id=repository_id,
                timestamp=timestamp,
                nonce=nonce,
            ),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")

    def attach(
        self,
        *,
        repository_root: str,
        repository_id: str,
        timestamp: int,
        nonce: str,
        signature: str,
    ) -> tuple[str, ProjectGrant]:
        now = int(self._now())
        if abs(now - timestamp) > MAX_CLOCK_SKEW_SECONDS:
            raise ValueError("Attachment challenge expired")
        if not 16 <= len(nonce) <= 128 or not nonce.isascii():
            raise ValueError("Attachment nonce is invalid")
        expected = self.sign_challenge(
            repository_root=repository_root,
            repository_id=repository_id,
            timestamp=timestamp,
            nonce=nonce,
        )
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Attachment signature is invalid")
        root = self.canonical_root(repository_root)
        with self._lock:
            self._prune(now)
            if nonce in self._nonces:
                raise ValueError("Attachment challenge was already used")
            self._nonces[nonce] = now + MAX_CLOCK_SKEW_SECONDS
            token = secrets.token_urlsafe(32)
            grant = ProjectGrant(
                repository_root=root,
                repository_id=repository_id,
                expires_at=now + PROJECT_TOKEN_TTL_SECONDS,
            )
            self._tokens[token] = grant
        return token, grant

    def authorize(self, authorization: str | None) -> ProjectGrant:
        if not authorization or not authorization.startswith("Bearer "):
            raise ValueError("A project access token is required")
        token = authorization[7:]
        now = int(self._now())
        with self._lock:
            self._prune(now)
            grant = self._tokens.get(token)
            if grant is None:
                raise ValueError("Project access token is invalid or expired")
            requests = self._requests[token]
            while requests and requests[0] <= now - 60:
                requests.popleft()
            if len(requests) >= MAX_REQUESTS_PER_MINUTE:
                raise RuntimeError("Project request rate limit exceeded")
            requests.append(now)
            return grant

    def host_is_allowed(self, host_header: str | None) -> bool:
        if not host_header:
            return False
        host = host_header.strip().lower()
        if host.startswith("["):
            closing = host.find("]")
            hostname = host[: closing + 1] if closing >= 0 else host
        else:
            hostname = host.split(":", 1)[0]
        return hostname in self._hosts

    def _prune(self, now: int) -> None:
        for token, grant in tuple(self._tokens.items()):
            if grant.expires_at <= now:
                self._tokens.pop(token, None)
                self._requests.pop(token, None)
        for nonce, expires_at in tuple(self._nonces.items()):
            if expires_at <= now:
                self._nonces.pop(nonce, None)
