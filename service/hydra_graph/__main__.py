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
    index = subparsers.add_parser(
        "index", help="Analyze and index only HYDRA_REPOSITORY_ROOT"
    )
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
            result = services.evolution.capture_checkpoint(
                args.slot, revision_id=args.revision
            )
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

    uvicorn.run(
        "hydra_graph.api:app",
        host="127.0.0.1",
        port=getattr(args, "port", 8765),
        reload=getattr(args, "reload", False),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
