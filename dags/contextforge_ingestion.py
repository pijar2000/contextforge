"""Scheduled ingestion and re-indexing.

The DAG only sequences stages. All logic is in `contextforge.orchestration.tasks`, which runs in
a dedicated virtualenv (CONTEXTFORGE_PYTHON) because ContextForge needs SQLAlchemy 2 while the
Airflow image pins SQLAlchemy 1.4.

Trigger a full re-index manually with the DAG conf {"force": true}.
"""

import os
from datetime import datetime, timedelta

from airflow.decorators import dag, task

PYTHON = os.environ.get("CONTEXTFORGE_PYTHON", "/opt/contextforge-venv/bin/python")

DEFAULT_ARGS = {
    "owner": "data-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}


@task.external_python(python=PYTHON)
def run_stage(stage: str, run_id: str, force: str = "False"):
    # Runs inside the ContextForge virtualenv. Everything it needs must be imported here because
    # the function body is shipped to that interpreter without this module's globals.
    from contextforge.orchestration import tasks

    if stage == "scan_sources":
        return tasks.scan_sources(run_id, force)
    return getattr(tasks, stage)(run_id)


def stage_task(stage: str, timeout_minutes: int, **kwargs):
    return run_stage.override(
        task_id=stage, execution_timeout=timedelta(minutes=timeout_minutes)
    )(stage=stage, **kwargs)


@dag(
    dag_id="contextforge_ingestion",
    description="Incremental document ingestion into Qdrant, OpenSearch and PostgreSQL",
    schedule="0 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,  # staging state is per run, but two runs would race on the same documents
    default_args=DEFAULT_ARGS,
    params={"force": False},
    tags=["contextforge"],
)
def contextforge_ingestion():
    run_id = "{{ run_id }}"
    force = "{{ params.force }}"

    scan = stage_task("scan_sources", 15, run_id=run_id, force=force)
    extract = stage_task("extract_documents", 60, run_id=run_id)
    normalize = stage_task("normalize_documents", 30, run_id=run_id)
    chunk = stage_task("chunk_documents", 30, run_id=run_id)
    embed = stage_task("embed_documents", 120, run_id=run_id)
    vector = stage_task("update_vector_index", 30, run_id=run_id)
    keyword = stage_task("update_keyword_index", 30, run_id=run_id)
    validate = stage_task("validate_and_commit", 30, run_id=run_id)
    metrics = stage_task("record_metrics", 10, run_id=run_id)

    scan >> extract >> normalize >> chunk >> embed >> vector >> keyword >> validate >> metrics


contextforge_ingestion()
