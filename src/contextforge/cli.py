"""Command-line entry point: `contextforge <command>` (or `python -m contextforge.cli`)."""

import argparse
import json
import sys
from pathlib import Path

from contextforge.common.config import get_settings
from contextforge.common.logging import configure_logging
from contextforge.connectors.filesystem import FilesystemConnector
from contextforge.services import Services, build_services, prepare_backends


def _services(args) -> Services:
    settings = get_settings()
    if getattr(args, "local", False):
        settings = settings.model_copy(update={"backend": "local"})
    configure_logging(settings.log_level)
    services = build_services(settings)
    prepare_backends(services)
    return services


def _user(services: Services, user_id: str):
    user = services.users.get(user_id)
    if user is None:
        known = ", ".join(u.user_id for u in services.users.all_users())
        sys.exit(f"unknown user {user_id!r}; known users: {known}")
    return user


def cmd_init(args) -> int:
    services = _services(args)
    print(json.dumps({"initialized": True, "health": services.ping()}, indent=2))
    return 0


def cmd_ingest(args) -> int:
    services = _services(args)
    settings = services.settings
    root = Path(args.path or settings.source_root)
    connector = FilesystemConnector(settings.source_root, settings.source_name,
                                    subpath=root if args.path else None)
    summary = services.pipeline.run(connector, settings.tenant_id, force=args.force, trigger="cli")
    print(json.dumps(summary.to_dict(), indent=2))
    return 1 if summary.failed else 0


def cmd_search(args) -> int:
    services = _services(args)
    if args.local:
        services.pipeline.run(
            FilesystemConnector(services.settings.source_root, services.settings.source_name),
            services.settings.tenant_id,
        )
    user = _user(services, args.user)
    resp = services.retriever.search(args.query, user, args.mode, args.top_k, args.rerank)
    print(f"mode={resp.mode} rerank={resp.rerank} timings_ms={resp.timings_ms} counts={resp.counts}\n")
    for rank, h in enumerate(resp.hits, start=1):
        page = f" p.{h.page_number}" if h.page_number else ""
        print(f"{rank}. [{h.score:.4f}] {h.source_path}{page} | {h.section_title or '-'} (v{h.document_version})")
        print("   " + h.text[:240].replace("\n", " ") + ("..." if len(h.text) > 240 else ""))
    if not resp.hits:
        print("no accessible results")
    return 0


def cmd_reindex(args) -> int:
    services = _services(args)
    item = services.pipeline.reindex_document(args.document_id)
    print(json.dumps({"status": item.status, "chunks": len(item.chunks), "error": item.error}, indent=2))
    return 1 if item.error else 0


def cmd_evaluate(args) -> int:
    from contextforge.evaluation import evaluate, load_dataset, write_report

    services = _services(args)
    settings = services.settings
    if args.local:
        # In-memory indexes start empty, so index the sample corpus first.
        summary = services.pipeline.run(
            FilesystemConnector(settings.source_root, settings.source_name), settings.tenant_id
        )
        print(f"indexed {summary.processed} documents ({summary.failed} failed)", file=sys.stderr)
    user = _user(services, args.user)
    queries = load_dataset(settings.evaluation_dataset)
    result = evaluate(
        services.retriever,
        services.session_factory,
        user,
        queries,
        strategies=args.strategies.split(",") if args.strategies else None,
        repeats=args.repeats,
        config={
            "embedding_model": services.embedder.name,
            "chunk_strategy": settings.chunk_strategy,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "rrf_k": settings.rrf_k,
            "backend": settings.backend,
            "reranker_model": settings.reranker_model,
        },
    )
    json_path, md_path = write_report(result, settings.evaluation_report_dir)
    print(f"wrote {json_path} and {md_path}")
    return 0


def cmd_hash_key(args) -> int:
    from contextforge.access_control.directory import UserDirectory

    print(UserDirectory.digest(args.api_key))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contextforge")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--local", action="store_true",
                       help="use the in-memory backend (no Docker services; nothing persists)")
        p.set_defaults(fn=fn)
        return p

    add("init", cmd_init, "create buckets, collections and indices")
    p = add("ingest", cmd_ingest, "scan the source directory and index new/changed documents")
    p.add_argument("--path", help="sub-directory to ingest (default: SOURCE_ROOT)")
    p.add_argument("--force", action="store_true", help="re-index unchanged documents too")
    p = add("search", cmd_search, "run a search as a given user")
    p.add_argument("query")
    p.add_argument("--user", default="alice")
    p.add_argument("--mode", choices=["bm25", "vector", "hybrid"], default="hybrid")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--rerank", action="store_true")
    p = add("reindex", cmd_reindex, "rebuild one document from its archived raw file")
    p.add_argument("document_id")
    p = add("evaluate", cmd_evaluate, "run the retrieval evaluation and write reports")
    p.add_argument("--user", default="alice", help="evaluation runs as this (administrator) user")
    p.add_argument("--strategies", help="comma-separated subset of bm25,vector,hybrid,hybrid_rerank")
    p.add_argument("--repeats", type=int, default=1, help="repeat each query; latency uses the fastest")
    p = sub.add_parser("hash-key", help="print the SHA-256 digest to put in config/users.yaml")
    p.add_argument("api_key")
    p.set_defaults(fn=cmd_hash_key)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
