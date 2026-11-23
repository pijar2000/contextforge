"""Persists work items between Airflow tasks. The in-process runner does not need it."""

import json
from pathlib import Path

import numpy as np

from contextforge.ingestion.workitem import WorkItem


class StagingStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _dir(self, run_id: str) -> Path:
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, run_id: str, items: list[WorkItem]) -> None:
        directory = self._dir(run_id)
        (directory / "items.json").write_text(
            json.dumps([i.to_dict() for i in items]), encoding="utf-8"
        )
        vectors = directory / "vectors"
        vectors.mkdir(exist_ok=True)
        for item in items:
            if item.vectors is not None:
                np.save(vectors / f"{item.document_id}.npy", item.vectors)

    def load(self, run_id: str) -> list[WorkItem]:
        directory = self._dir(run_id)
        path = directory / "items.json"
        if not path.exists():
            return []
        items = [WorkItem.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]
        for item in items:
            vec_path = directory / "vectors" / f"{item.document_id}.npy"
            if vec_path.exists():
                item.vectors = np.load(vec_path)
        return items

    def save_json(self, run_id: str, name: str, payload: dict) -> None:
        (self._dir(run_id) / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")

    def load_json(self, run_id: str, name: str) -> dict:
        path = self._dir(run_id) / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
