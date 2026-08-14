"""Run the repository HTTP service or MCP server."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hack Hydra repository service")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="Run the local FastAPI service")
    serve.add_argument("--port", default=8765, type=int)
    serve.add_argument("--reload", action="store_true")
    mcp = subparsers.add_parser("mcp", help="Run repository tools over MCP stdio")
    mcp.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
    )
    index = subparsers.add_parser(
        "index", help="Analyze and index only HYDRA_REPOSITORY_ROOT"
    )
    index.add_argument("--revision", required=True, help="Explicit repository revision ID")
    index.add_argument(
        "--preview",
        action="store_true",
        help="Print the exact upload scope without contacting HydraDB",
    )
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
    import uvicorn

    uvicorn.run(
        "hydra_graph.api:app",
        host="127.0.0.1",
        port=getattr(args, "port", 8765),
        reload=getattr(args, "reload", False),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
