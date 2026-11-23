from collections.abc import Callable, Sequence

from contextforge.common.models import Hit

Scorer = Callable[[str, Sequence[str]], Sequence[float]]


class CrossEncoderScorer:
    """Scores (query, passage) pairs with a cross-encoder; the model loads on first use."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def __call__(self, query: str, passages: Sequence[str]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        scores = self._model.predict([(query, p) for p in passages], show_progress_bar=False)
        return [float(s) for s in scores]


class Reranker:
    def __init__(self, scorer: Scorer, name: str = "cross-encoder"):
        self._scorer = scorer
        self.name = name

    def rerank(self, query: str, hits: list[Hit], top_n: int | None = None) -> list[Hit]:
        """Re-order the first `top_n` hits by cross-encoder score; the remainder keep their order
        after them so the caller can still fill a larger top-K."""
        if not hits:
            return []
        head = hits[:top_n] if top_n else list(hits)
        tail = hits[len(head):]
        scores = self._scorer(query, [h.text for h in head])
        scored = []
        for hit, score in zip(head, scores, strict=True):
            hit.signals["rerank_score"] = float(score)
            hit.signals["pre_rerank_score"] = hit.score
            scored.append((float(score), hit))
        scored.sort(key=lambda pair: -pair[0])
        reordered = [h for _, h in scored]
        for score, hit in scored:
            hit.score = score
        return reordered + tail
