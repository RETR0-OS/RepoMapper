"""OAuth 2.1 provider whose durable records live in VS Code SecretStorage."""

from __future__ import annotations

import hashlib
import secrets
import time
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import BaseModel

from .managed import ManagedIpc

READ_ONLY_SCOPES = ("repository:read", "evidence:read", "observe:read")
ACCESS_TOKEN_SECONDS = 300
REFRESH_TOKEN_SECONDS = 86_400
AUTHORIZATION_CODE_SECONDS = 60


class StoredAccessToken(AccessToken):
    refresh_key: str


class StoredRefreshToken(RefreshToken):
    access_key: str


class ManagedOAuthProvider:
    """Use opaque rotating tokens without a process-lifetime grant cache."""

    def __init__(
        self,
        channel: ManagedIpc,
        *,
        repository_root: Path,
        repository_id: str,
        issuer_url: str,
    ) -> None:
        self._channel = channel
        self._repository_id = repository_id
        self._issuer_url = issuer_url.rstrip("/")
        self._projects: dict[str, dict[str, str]] = {}
        self._projects_lock = RLock()
        self.register_project(repository_root, repository_id)

    def register_project(self, repository_root: Path, repository_id: str) -> None:
        """Expose one already authenticated extension project for native consent."""

        root = repository_root.resolve()
        canonical = str(root)
        fingerprint_input = (
            canonical.lower().encode() if Path(canonical).drive else canonical.encode()
        )
        with self._projects_lock:
            self._projects[repository_id] = {
                "repository_id": repository_id,
                "project_name": root.name or repository_id,
                "root_fingerprint": hashlib.sha256(fingerprint_input).hexdigest(),
            }

    def registered_project_ids(self) -> tuple[str, ...]:
        with self._projects_lock:
            return tuple(sorted(self._projects))

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._load_model("client", client_id, OAuthClientInformationFull)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise RegistrationError("invalid_client_metadata", "client_id is required")
        if not client_info.client_name or len(client_info.client_name) > 200:
            raise RegistrationError("invalid_client_metadata", "A bounded client name is required")
        if not client_info.redirect_uris or not all(
            _safe_loopback_redirect(str(item)) for item in client_info.redirect_uris
        ):
            raise RegistrationError(
                "invalid_redirect_uri", "Only loopback HTTP redirect URIs are allowed"
            )
        self._store_model("client", client_info.client_id, client_info)

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        scopes = params.scopes or [READ_ONLY_SCOPES[0]]
        if not scopes or not set(scopes).issubset(READ_ONLY_SCOPES):
            raise AuthorizeError("invalid_scope", "Only read-only repository scopes are allowed")
        with self._projects_lock:
            projects = [dict(project) for project in self._projects.values()]
        response = self._channel.request(
            "oauth_consent",
            client_name=client.client_name or "MCP client",
            scopes=scopes,
            projects=projects,
        )
        if response.get("approved") is not True:
            raise AuthorizeError("access_denied", "Repository Map access was not approved")
        selected_repository = response.get("repository_id")
        if not isinstance(selected_repository, str):
            raise AuthorizeError("access_denied", "No Repository Map project was selected")
        with self._projects_lock:
            selected = self._projects.get(selected_repository)
        if selected is None:
            raise AuthorizeError("access_denied", "The selected project is no longer available")
        code_value = secrets.token_urlsafe(32)
        code = AuthorizationCode(
            code=code_value,
            scopes=scopes,
            expires_at=time.time() + AUTHORIZATION_CODE_SECONDS,
            client_id=str(client.client_id),
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=selected_repository,
        )
        self._store_model("code", code_value, code)
        return construct_redirect_uri(str(params.redirect_uri), code=code_value, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._load_model("code", authorization_code, AuthorizationCode)
        if code is None or code.client_id != client.client_id or code.expires_at <= time.time():
            if code is not None:
                self._delete("code", authorization_code)
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        loaded = await self.load_authorization_code(client, authorization_code.code)
        if loaded is None:
            raise TokenError("invalid_grant", "Authorization code is invalid or expired")
        self._delete("code", authorization_code.code)
        return self._issue_tokens(
            client_id=str(client.client_id),
            scopes=authorization_code.scopes,
            subject=authorization_code.subject or self._repository_id,
            resource=authorization_code.resource,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> StoredRefreshToken | None:
        token = self._load_model("refresh", refresh_token, StoredRefreshToken)
        if token is None or token.client_id != client.client_id:
            return None
        if token.expires_at is not None and token.expires_at <= int(time.time()):
            await self.revoke_token(token)
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: StoredRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        loaded = await self.load_refresh_token(client, refresh_token.token)
        if loaded is None:
            raise TokenError("invalid_grant", "Refresh token is invalid or expired")
        if not set(scopes).issubset(loaded.scopes):
            raise TokenError("invalid_scope", "Refresh cannot add scopes")
        await self.revoke_token(loaded)
        return self._issue_tokens(
            client_id=str(client.client_id),
            scopes=scopes,
            subject=loaded.subject or self._repository_id,
            resource=None,
        )

    async def load_access_token(self, token: str) -> StoredAccessToken | None:
        access = self._load_model("access", token, StoredAccessToken)
        if access is None:
            return None
        if access.expires_at is not None and access.expires_at <= int(time.time()):
            await self.revoke_token(access)
            return None
        with self._projects_lock:
            project_available = access.subject in self._projects
        if not project_available:
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, StoredAccessToken):
            self._delete_key(token.refresh_key)
            self._delete("access", token.token)
        elif isinstance(token, StoredRefreshToken):
            self._delete_key(token.access_key)
            self._delete("refresh", token.token)
        else:
            self._delete("access", token.token)
            self._delete("refresh", token.token)

    def _issue_tokens(
        self,
        *,
        client_id: str,
        scopes: list[str],
        subject: str,
        resource: str | None,
    ) -> OAuthToken:
        now = int(time.time())
        access_value = secrets.token_urlsafe(32)
        refresh_value = secrets.token_urlsafe(32)
        access_key = _record_key("access", access_value)
        refresh_key = _record_key("refresh", refresh_value)
        with self._projects_lock:
            project = self._projects.get(subject)
        if project is None:
            raise TokenError("invalid_grant", "The selected project is no longer available")
        access = StoredAccessToken(
            token=access_value,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + ACCESS_TOKEN_SECONDS,
            resource=resource,
            subject=subject,
            claims={
                "iss": self._issuer_url,
                "repository_root_fingerprint": project["root_fingerprint"],
            },
            refresh_key=refresh_key,
        )
        refresh = StoredRefreshToken(
            token=refresh_value,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + REFRESH_TOKEN_SECONDS,
            subject=subject,
            access_key=access_key,
        )
        self._store_key(access_key, access.model_dump_json())
        self._store_key(refresh_key, refresh.model_dump_json())
        return OAuthToken(
            access_token=access_value,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_SECONDS,
            scope=" ".join(scopes),
            refresh_token=refresh_value,
        )

    def _load_model(self, kind: str, identifier: str, model: type[BaseModel]):
        response = self._channel.request("oauth_get", key=_record_key(kind, identifier))
        value = response.get("value")
        if not isinstance(value, str):
            return None
        try:
            return model.model_validate_json(value)
        except ValueError:
            self._delete(kind, identifier)
            return None

    def _store_model(self, kind: str, identifier: str, model: BaseModel) -> None:
        self._store_key(_record_key(kind, identifier), model.model_dump_json())

    def _store_key(self, key: str, value: str) -> None:
        self._channel.request("oauth_put", key=key, value=value)

    def _delete(self, kind: str, identifier: str) -> None:
        self._delete_key(_record_key(kind, identifier))

    def _delete_key(self, key: str) -> None:
        self._channel.request("oauth_delete", key=key)


def _record_key(kind: str, identifier: str) -> str:
    digest = hashlib.sha256(identifier.encode()).hexdigest()
    return f"{kind}/{digest}"


def _safe_loopback_redirect(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )
