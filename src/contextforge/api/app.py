import logging
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from contextforge.access_control.models import User, can_access
from contextforge.api.schemas import (
    ChatRequest,
    DocumentDetail,
    DocumentOut,
    DocumentPage,
    HitOut,
    IngestRequest,
    SearchRequest,
    SearchResponseOut,
    VersionOut,
)
from contextforge.common.config import Settings, get_settings
from contextforge.common.logging import bind_context, clear_context, configure_logging
from contextforge.connectors.filesystem import FilesystemConnector
from contextforge.ingestion.pipeline import PipelineError
from contextforge.retrieval import RetrievalError
from contextforge.services import Services, build_services, prepare_backends
from contextforge.storage import Repository, session_scope
from contextforge.storage.models import Document

logger = logging.getLogger(__name__)


def create_app(services: Services | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="ContextForge",
        version="0.1.0",
        description="Document ingestion, hybrid retrieval and evaluation API. "
        "Authenticate with the X-API-Key header.",
    )
    app.state.services = services

    def svc() -> Services:
        if app.state.services is None:  # lazy so `import` never needs running backends
            app.state.services = build_services(settings)
            prepare_backends(app.state.services)
        return app.state.services

    def current_user(
        x_api_key: str | None = Header(default=None, description="Development API key"),
        services: Services = Depends(svc),
    ) -> User:
        user = services.users.authenticate(x_api_key)
        if user is None:
            raise HTTPException(status_code=401, detail="Missing or invalid API key")
        return user

    def admin_user(user: User = Depends(current_user)) -> User:
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Administrator role required")
        return user

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        clear_context()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        bind_context(request_id=request_id)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        logger.info("%s %s -> %s in %.1f ms", request.method, request.url.path, response.status_code,
                    (time.perf_counter() - started) * 1000)
        return response

    def doc_out(doc: Document, user: User) -> DocumentOut:
        data = DocumentOut(
            document_id=doc.document_id, source_path=doc.source_path, file_name=doc.file_name,
            file_type=doc.file_type, title=doc.title, status=doc.status,
            current_version=doc.current_version, indexed_version=doc.indexed_version,
            size_bytes=doc.size_bytes, content_hash=doc.content_hash, owner_id=doc.owner_id,
            allowed_groups=list(doc.allowed_groups or []), last_ingested_at=doc.last_ingested_at,
            last_error=doc.last_error if user.is_admin else None,
        )
        return data

    def visible(doc: Document | None, user: User) -> bool:
        return doc is not None and can_access(user, doc.tenant_id, doc.owner_id, doc.allowed_groups)

    # ------------------------------------------------------------------ health / metrics
    @app.get("/health", tags=["ops"])
    def health(services: Services = Depends(svc)):
        checks = services.ping()
        ok = all(checks.values())
        return {"status": "ok" if ok else "degraded", "checks": checks}

    @app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
    def metrics(services: Services = Depends(svc)):
        return services.metrics.render_prometheus()

    @app.get("/stats", tags=["ops"])
    def stats(user: User = Depends(current_user), services: Services = Depends(svc)):
        """Tenant-level counters for the dashboard. Counts reflect the whole tenant, so they are
        restricted to administrators."""
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Administrator role required")
        with session_scope(services.session_factory) as session:
            repo = Repository(session)
            data = repo.stats(user.tenant_id)
            data["recent_runs"] = [
                {"run_id": r.run_id, "status": r.status, "started_at": r.started_at,
                 "docs_scanned": r.docs_scanned, "docs_processed": r.docs_processed,
                 "docs_skipped": r.docs_skipped, "docs_failed": r.docs_failed,
                 "docs_deleted": r.docs_deleted, "chunks_created": r.chunks_created,
                 "duration_seconds": r.duration_seconds}
                for r in repo.latest_runs(user.tenant_id)
            ]
        return data

    @app.get("/me", tags=["auth"])
    def me(user: User = Depends(current_user)):
        return {"user_id": user.user_id, "tenant_id": user.tenant_id, "roles": list(user.roles)}

    # ------------------------------------------------------------------ documents
    @app.post("/documents/ingest", tags=["documents"])
    def ingest(body: IngestRequest, user: User = Depends(admin_user), services: Services = Depends(svc)):
        root = Path(services.settings.source_root).resolve()
        target = (root / body.source_path).resolve() if body.source_path else root
        if target != root and root not in target.parents:
            raise HTTPException(status_code=400, detail="source_path must stay inside SOURCE_ROOT")
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"directory not found: {body.source_path}")
        # Relative paths (and therefore document ids and ACL rules) are always relative to the root.
        connector = FilesystemConnector(root, services.settings.source_name, subpath=target)
        try:
            summary = services.pipeline.run(connector, user.tenant_id, force=body.force, trigger="api")
        except PipelineError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return summary.to_dict()

    @app.get("/documents", response_model=DocumentPage, tags=["documents"])
    def list_documents(
        limit: int = Query(20, ge=1, le=200),
        offset: int = Query(0, ge=0),
        status: str | None = None,
        user: User = Depends(current_user),
        services: Services = Depends(svc),
    ):
        with session_scope(services.session_factory) as session:
            docs = Repository(session).list_documents(user.tenant_id, status)
        # ACLs are JSON lists, so authorization is applied in Python before paging.
        docs = [d for d in docs if d.status != "deleted" and visible(d, user)]
        page = docs[offset : offset + limit]
        return DocumentPage(total=len(docs), limit=limit, offset=offset, items=[doc_out(d, user) for d in page])

    @app.get("/documents/{document_id}", response_model=DocumentDetail, tags=["documents"])
    def get_document(document_id: str, user: User = Depends(current_user), services: Services = Depends(svc)):
        with session_scope(services.session_factory) as session:
            repo = Repository(session)
            doc = repo.get_document(document_id)
            # Same 404 for "missing" and "forbidden" so existence is not revealed.
            if not visible(doc, user) or doc.status == "deleted":
                raise HTTPException(status_code=404, detail="Document not found")
            versions = [
                VersionOut(version=v.version, status=v.status, content_hash=v.content_hash,
                           chunk_count=v.chunk_count, page_count=v.page_count, indexed_at=v.indexed_at,
                           error=v.error if user.is_admin else None)
                for v in repo.list_versions(document_id)
            ]
            return DocumentDetail(**doc_out(doc, user).model_dump(), versions=versions)

    @app.post("/documents/{document_id}/reindex", tags=["documents"])
    def reindex(document_id: str, user: User = Depends(admin_user), services: Services = Depends(svc)):
        with session_scope(services.session_factory) as session:
            doc = Repository(session).get_document(document_id)
            if doc is None or doc.tenant_id != user.tenant_id or doc.status == "deleted":
                raise HTTPException(status_code=404, detail="Document not found")
        try:
            item = services.pipeline.reindex_document(document_id)
        except PipelineError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"document_id": document_id, "status": item.status, "version": item.version,
                "chunks": len(item.chunks), "error": item.error}

    @app.delete("/documents/{document_id}", status_code=204, tags=["documents"])
    def delete_document(document_id: str, user: User = Depends(admin_user), services: Services = Depends(svc)):
        """Removes the document from both indexes. The source file is untouched, so a later
        ingestion run will re-add it unless the file is also removed from the source."""
        with session_scope(services.session_factory) as session:
            doc = Repository(session).get_document(document_id)
            if doc is None or doc.tenant_id != user.tenant_id or doc.status == "deleted":
                raise HTTPException(status_code=404, detail="Document not found")
        services.pipeline.delete_documents([document_id])

    # ------------------------------------------------------------------ search / chat
    @app.post("/search", response_model=SearchResponseOut, tags=["retrieval"])
    def search(body: SearchRequest, user: User = Depends(current_user), services: Services = Depends(svc)):
        try:
            resp = services.retriever.search(body.query, user, body.mode, body.top_k, body.rerank,
                                             body.document_version)
        except RetrievalError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("search failed")
            raise HTTPException(status_code=503, detail=f"Search backend unavailable: {exc}") from exc
        hits = [HitOut(chunk_id=h.chunk_id, document_id=h.document_id, document_version=h.document_version,
                       chunk_index=h.chunk_index, source_path=h.source_path, section_title=h.section_title,
                       page_number=h.page_number, score=h.score, text=h.text, signals=h.signals)
                for h in resp.hits]
        return SearchResponseOut(query=resp.query, mode=resp.mode, rerank=resp.rerank, hits=hits,
                                 timings_ms=resp.timings_ms, counts=resp.counts)

    @app.post("/chat", tags=["retrieval"])
    def chat(body: ChatRequest, user: User = Depends(current_user), services: Services = Depends(svc)):
        try:
            answer = services.assistant.answer(body.question, user, body.top_k, body.mode, body.rerank)
        except RetrievalError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(answer)

    # ------------------------------------------------------------------ evaluation
    @app.get("/evaluation/results", tags=["evaluation"])
    def evaluation_results(user: User = Depends(current_user), services: Services = Depends(svc)):
        import json

        path = Path(services.settings.evaluation_report_dir) / "latest.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No evaluation report yet. Run `contextforge evaluate`.")
        return json.loads(path.read_text(encoding="utf-8"))

    return app


def get_app() -> FastAPI:
    """Uvicorn factory: `uvicorn contextforge.api.app:get_app --factory`."""
    return create_app()
