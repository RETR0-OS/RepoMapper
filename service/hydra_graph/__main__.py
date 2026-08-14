"""Run the repository HTTP service or MCP server."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hack Hydra repository service")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="Run the local FastAPI service")
    serve.add_argument("--port", default=8765, type=int)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument(
        "--managed",
        action="store_true",
        help="Use the private VS Code IPC credential broker instead of environment credentials",
    )
    mcp = subparsers.add_parser(
        "mcp",
        help=(
            "Run a standalone MCP process; it cannot feed Observe in a different service "
            "process (use the service's /mcp endpoint for shared events)"
        ),
    )
    mcp.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
    )
    index = subparsers.add_parser("index", help="Analyze and index only HYDRA_REPOSITORY_ROOT")
    index.add_argument("--revision", required=True, help="Explicit repository revision ID")
    index.add_argument(
        "--preview",
        action="store_true",
        help="Print the exact upload scope without contacting HydraDB",
    )
    checkpoint = subparsers.add_parser(
        "checkpoint", help="Capture one verified local before/after checkpoint"
    )
    checkpoint.add_argument("slot", choices=("before", "after"))
    checkpoint.add_argument("--revision", required=True)
    publish = subparsers.add_parser(
        "evolution-publish", help="Preview or publish a captured deterministic delta"
    )
    publish.add_argument("--before", required=True)
    publish.add_argument("--after", required=True)
    publish.add_argument("--confirm", action="store_true")
    compare = subparsers.add_parser(
        "compare", help="Query one before/after change event from HydraDB evolution Knowledge"
    )
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)
    compare.add_argument("--focus")
    lens = subparsers.add_parser(
        "lens-open", help="Open one shared lens through sequential evolution/current queries"
    )
    lens.add_argument("--lens", required=True)
    args = parser.parse_args(argv)
    command = args.command or "serve"
    if command == "mcp":
        from .mcp_server import create_mcp_server

        create_mcp_server().run(transport=args.transport)
        return 0
    if command == "index":
        from .api import create_container, prepare_index

        services = create_container()
        _, cards, preview = prepare_index(services, revision_id=args.revision)
        if args.preview:
            print(json.dumps(preview, indent=2))
            return 0
        result = services.sync.sync(cards, revision_id=args.revision).as_dict()
        print(json.dumps({"preview": preview, "sync": result}, indent=2))
        return 0 if result["status"] == "ready" else 1
    if command in {"checkpoint", "evolution-publish", "compare", "lens-open"}:
        from .api import create_container

        services = create_container()
        assert services.evolution is not None
        if command == "checkpoint":
            result = services.evolution.capture_checkpoint(args.slot, revision_id=args.revision)
        elif command == "evolution-publish":
            result = services.evolution.publish_delta(
                before_revision_id=args.before,
                after_revision_id=args.after,
                confirm=args.confirm,
            )
        elif command == "compare":
            result = services.evolution.compare(
                before_revision_id=args.before,
                after_revision_id=args.after,
                focus=args.focus,
            )
        else:
            result = services.evolution.open_lens(lens=args.lens)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in {"captured", "preview", "ready"} else 1
    import uvicorn

    if getattr(args, "managed", False):
        if getattr(args, "reload", False):
            parser.error("--managed cannot be combined with --reload")
        from .api import create_app, create_container
        from .config import HydraDBConfig
        from .managed import ManagedCredentialProvider, ManagedIpc
        from .mcp_oauth import ManagedOAuthProvider
        from .security import ManagedSecurity

        channel, start = ManagedIpc.bootstrap(sys.stdin, sys.stdout)
        config = HydraDBConfig(
            api_key=None,
            database="",
            collection=start.collection,
            evolution_collection=start.evolution_collection,
            api_url=start.api_url,
        )
        provider = ManagedCredentialProvider(channel)
        container = create_container(
            config,
            repository_id=start.repository_id,
            repository_root=start.repository_root,
            credential_provider=provider,
        )
        port = getattr(args, "port", 8765)
        issuer_url = f"http://127.0.0.1:{port}"
        oauth_provider = ManagedOAuthProvider(
            channel,
            repository_root=start.repository_root,
            repository_id=start.repository_id,
            issuer_url=issuer_url,
        )
        managed_app = create_app(
            container,
            managed_security=ManagedSecurity(start.control_key),
            mcp_oauth_provider=oauth_provider,
            mcp_issuer_url=issuer_url,
        )
        channel.notify(
            "service_ready",
            port=port,
            repository_id=start.repository_id,
        )
        uvicorn.run(
            managed_app,
            host="127.0.0.1",
            port=port,
        )
        return 0

    uvicorn.run(
        "hydra_graph.api:app",
        host="127.0.0.1",
        port=getattr(args, "port", 8765),
        reload=getattr(args, "reload", False),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
