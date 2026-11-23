"""Stage functions invoked by the Airflow DAG (and runnable without Airflow).

Each function does one stage for every pending work item of a run. State between stages lives in
the staging directory, keyed by run id, so tasks can run in separate processes. The logic itself
is the same IngestionPipeline code used by `contextforge ingest`.
"""

import re
import time
from datetime import datetime

from contextforge.common.config import get_settings
from contextforge.common.logging import bind_context, configure_logging
from contextforge.connectors.filesystem import FilesystemConnector
from contextforge.ingestion.staging import StagingStore
from contextforge.ingestion.workitem import FAILED
from contextforge.services import Services, build_services, prepare_backends
from contextforge.storage.models import utcnow


def safe_run_id(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", run_id)[-60:]


def _setup(run_id: str) -> tuple[Services, StagingStore, str]:
    settings = get_settings()
    configure_logging(settings.log_level)
    rid = safe_run_id(run_id)
    bind_context(run_id=rid)
    services = build_services(settings)
    return services, StagingStore(settings.staging_dir), rid


def scan_sources(run_id: str, force: bool | str = False) -> dict:
    """Tasks 1-2: scan the source and detect new, modified, unchanged and deleted documents."""
    force = str(force).lower() == "true"  # Airflow templates render params as strings
    services, staging, rid = _setup(run_id)
    prepare_backends(services)
    settings = services.settings
    connector = FilesystemConnector(settings.source_root, settings.source_name)
    detection = services.pipeline.detect(connector, settings.tenant_id, rid, force=force)
    staging.save(rid, detection.items)
    meta = {
        "run_id": rid,
        "scanned": detection.scanned,
        "skipped": detection.skipped,
        "deleted_document_ids": detection.deleted_document_ids,
        "started_monotonic": time.monotonic(),
        "started_at": utcnow().isoformat(),
    }
    staging.save_json(rid, "detection", meta)
    return {k: meta[k] for k in ("run_id", "scanned", "skipped")} | {
        "to_process": len(detection.items),
        "to_delete": len(detection.deleted_document_ids),
    }


def _run_stage(run_id: str, stage: str) -> dict:
    services, staging, rid = _setup(run_id)
    items = staging.load(rid)
    stage_fn = getattr(services.pipeline, stage)
    for item in items:
        stage_fn(item)
    staging.save(rid, items)
    return {"run_id": rid, "stage": stage, "items": len(items),
            "failed": sum(1 for i in items if i.status == FAILED)}


def extract_documents(run_id: str) -> dict:
    return _run_stage(run_id, "extract")


def normalize_documents(run_id: str) -> dict:
    return _run_stage(run_id, "normalize")


def chunk_documents(run_id: str) -> dict:
    return _run_stage(run_id, "chunk")


def embed_documents(run_id: str) -> dict:
    return _run_stage(run_id, "embed")


def update_vector_index(run_id: str) -> dict:
    return _run_stage(run_id, "index_vector")


def update_keyword_index(run_id: str) -> dict:
    return _run_stage(run_id, "index_keyword")


def validate_and_commit(run_id: str) -> dict:
    """Tasks 9: verify both indexes hold every chunk, then switch documents to the new version
    and apply deletions. Failed items keep serving their previous indexed version."""
    services, staging, rid = _setup(run_id)
    items = staging.load(rid)
    for item in items:
        services.pipeline.validate(item)
        services.pipeline.commit(item)
    meta = staging.load_json(rid, "detection")
    deleted = services.pipeline.delete_documents(meta.get("deleted_document_ids", []))
    staging.save(rid, items)
    staging.save_json(rid, "deleted", {"count": deleted})
    return {"run_id": rid, "committed": sum(1 for i in items if i.status != FAILED), "deleted": deleted}


def record_metrics(run_id: str) -> dict:
    """Task 10: persist run counters to PostgreSQL."""
    from contextforge.ingestion.pipeline import DetectionResult

    services, staging, rid = _setup(run_id)
    items = staging.load(rid)
    meta = staging.load_json(rid, "detection")
    deleted = staging.load_json(rid, "deleted").get("count", 0)
    detection = DetectionResult(items=items, scanned=meta["scanned"], skipped=meta["skipped"])
    summary = services.pipeline.summarize(
        rid, services.settings.tenant_id, detection, items, deleted,
        started=meta["started_monotonic"],
    )
    services.pipeline.record_run(summary, "airflow", datetime.fromisoformat(meta["started_at"]))
    return summary.to_dict()
