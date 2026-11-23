import re
import shutil
from pathlib import Path

import pytest

from contextforge.common.config import Settings
from contextforge.connectors.filesystem import FilesystemConnector
from contextforge.reranking import Reranker
from contextforge.services import build_services, prepare_backends

REPO = Path(__file__).resolve().parents[1]
SAMPLE_DOCS = REPO / "datasets" / "sample_documents"
KEYS = {name: f"cf-dev-{name}" for name in ("alice", "bob", "carol", "dave", "erin", "frank")}


def overlap_scorer(query, passages):
    """Deterministic stand-in for a cross-encoder: number of shared lowercase words."""
    q = set(re.findall(r"\w+", query.lower()))
    return [float(len(q & set(re.findall(r"\w+", p.lower())))) for p in passages]


def supported_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.suffix.lower() in {".md", ".txt", ".html", ".docx", ".pdf"}]


@pytest.fixture
def source_dir(tmp_path):
    target = tmp_path / "docs"
    shutil.copytree(SAMPLE_DOCS, target)
    return target


@pytest.fixture
def services(tmp_path, source_dir):
    settings = Settings(
        _env_file=None,
        backend="local",
        embedding_backend="hashing",
        source_root=source_dir,
        access_policy_file=REPO / "config" / "access_policies.yaml",
        users_file=REPO / "config" / "users.yaml",
        staging_dir=tmp_path / "staging",
        evaluation_report_dir=tmp_path / "reports",
        evaluation_dataset=REPO / "datasets" / "evaluation" / "queries.json",
    )
    svc = build_services(settings, reranker=Reranker(overlap_scorer, "overlap"))
    prepare_backends(svc)
    return svc


@pytest.fixture
def connector(source_dir, services):
    return FilesystemConnector(source_dir, services.settings.source_name)


@pytest.fixture
def run_ingest(services, connector):
    def run(force=False):
        return services.pipeline.run(connector, services.settings.tenant_id, force=force)

    return run


@pytest.fixture
def users(services):
    return {u.user_id: u for u in services.users.all_users()}
