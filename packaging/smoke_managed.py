"""Start the frozen managed service and verify its public protocol surface."""

from __future__ import annotations

import argparse
import json
import queue
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib import error, request

IPC_PROTOCOL = "hack-hydra.managed-ipc.v2"
SERVICE_PROTOCOL = "hack-hydra.managed-service.v2"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    executable = args.bundle.resolve() / (
        "hydra-graph.exe" if args.target.startswith("win32-") else "hydra-graph"
    )
    if not executable.is_file():
        raise SystemExit(f"managed executable is missing: {executable}")
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="repository-map-smoke-") as root:
        process = subprocess.Popen(
            [str(executable), "serve", "--managed", "--port", str(port)],
            cwd=args.bundle.resolve(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            assert process.stdin is not None and process.stdout is not None
            hello = _read_json_line(process, process.stdout, timeout=30)
            if hello.get("protocol") != IPC_PROTOCOL or hello.get("type") != "service_hello":
                raise RuntimeError(f"managed hello is invalid: {hello}")
            process.stdin.write(
                json.dumps(
                    {
                        "protocol": IPC_PROTOCOL,
                        "type": "service_start",
                        "repository_root": root,
                        "repository_id": "git:packaging-smoke:0123456789abcdefabcd",
                        "control_key": "x" * 43,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            process.stdin.flush()
            ready = _read_json_line(process, process.stdout, timeout=30)
            while ready.get("type") in {"credential_status", "credential_request"}:
                is_status = ready.get("type") == "credential_status"
                process.stdin.write(
                    json.dumps(
                        {
                            "protocol": IPC_PROTOCOL,
                            "type": "response",
                            "request_id": ready.get("request_id"),
                            "ok": is_status,
                            **({"configured": False} if is_status else {}),
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                process.stdin.flush()
                ready = _read_json_line(process, process.stdout, timeout=30)
            if ready.get("type") != "service_ready" or ready.get("port") != port:
                raise RuntimeError(f"managed ready is invalid: {ready}")
            version = _get_json(f"http://127.0.0.1:{port}/version", timeout=30)
            if (
                version.get("service") != "repository-map"
                or version.get("protocol") != SERVICE_PROTOCOL
            ):
                raise RuntimeError(f"managed version is invalid: {version}")
            metadata = _get_json(
                f"http://127.0.0.1:{port}/.well-known/oauth-authorization-server",
                timeout=10,
            )
            if metadata.get("code_challenge_methods_supported") != ["S256"]:
                raise RuntimeError("frozen OAuth metadata does not require PKCE S256")
            _require_unauthorized_mcp(port)
            _require_quiet_ipc(process)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            if process.returncode not in {0, -15, 1} and process.stderr is not None:
                raise RuntimeError(process.stderr.read()[-4_000:])
    print(f"managed service smoke passed on {args.target}")
    return 0


def _read_json_line(
    process: subprocess.Popen[str], stream: object, *, timeout: float
) -> dict[str, object]:
    output: queue.Queue[str] = queue.Queue(maxsize=1)
    thread = threading.Thread(target=lambda: output.put(stream.readline()), daemon=True)  # type: ignore[attr-defined]
    thread.start()
    try:
        line = output.get(timeout=timeout)
    except queue.Empty as exc:
        stderr = (
            process.stderr.read()[-4_000:] if process.poll() is not None and process.stderr else ""
        )
        raise RuntimeError(f"managed service IPC timed out: {stderr}") from exc
    if not line:
        stderr = process.stderr.read()[-4_000:] if process.stderr else ""
        raise RuntimeError(f"managed service IPC closed: {stderr}")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise RuntimeError("managed service IPC returned a non-object")
    return value


def _require_quiet_ipc(process: subprocess.Popen[str]) -> None:
    """Fail when served HTTP traffic wrote anything but IPC frames to stdout.

    VS Code parses every stdout line as a protocol frame, so an access log or a
    stray print there breaks the extension after the first request.
    """

    assert process.stdout is not None
    output: queue.Queue[str] = queue.Queue(maxsize=1)
    thread = threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True)  # type: ignore[union-attr]
    thread.start()
    try:
        line = output.get(timeout=2)
    except queue.Empty:
        return
    if not line.strip():
        return
    sample = line.strip()[:200]
    try:
        frame = json.loads(line)
    except json.JSONDecodeError:
        raise RuntimeError(f"managed stdout carried non-IPC output: {sample!r}") from None
    if not isinstance(frame, dict) or frame.get("protocol") != IPC_PROTOCOL:
        raise RuntimeError(f"managed stdout carried a foreign frame: {sample!r}")


def _get_json(url: str, *, timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with request.urlopen(url, timeout=1) as response:
                value = json.load(response)
                if not isinstance(value, dict):
                    raise RuntimeError("service returned a non-object")
                return value
        except (error.URLError, TimeoutError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def _require_unauthorized_mcp(port: int) -> None:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "packaging-smoke", "version": "1"},
            },
        }
    ).encode()
    call = request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        request.urlopen(call, timeout=5)
    except error.HTTPError as exc:
        if exc.code == 401:
            return
        raise
    raise RuntimeError("frozen MCP accepted an unauthenticated request")


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
