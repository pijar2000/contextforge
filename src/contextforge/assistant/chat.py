"""Retrieval-grounded answers.

Retrieval (with access control) happens first; the model only ever sees chunks the user may
read. Without an LLM the assistant returns ranked excerpts with citations instead.
"""

import re
from dataclasses import dataclass, field

from contextforge.access_control.models import User
from contextforge.assistant.llm import LLMError, OpenAICompatibleClient
from contextforge.common.models import Hit
from contextforge.retrieval import HybridRetriever, tokenize

INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
_STOPWORDS = set(
    "a an and are as at be by can do does for from how i in is it of on or our that the this to "
    "was we what when where which who why with you your".split()
)
_CITATION = re.compile(r"\[(\d+)\]")

SYSTEM_PROMPT = f"""You answer questions about internal company documents.
Use ONLY the numbered context passages. Cite the passages you use as [1], [2], ...
If the passages do not contain the answer, reply with exactly {INSUFFICIENT} and nothing else.
Never cite a number that is not in the context. Do not use outside knowledge."""


@dataclass
class ChatAnswer:
    question: str
    mode: str  # "llm" | "extractive" | "insufficient"
    answer: str | None
    citations: list[dict] = field(default_factory=list)
    excerpts: list[dict] = field(default_factory=list)
    warning: str | None = None
    timings_ms: dict = field(default_factory=dict)


def best_excerpt(text: str, query: str, max_chars: int = 320) -> str:
    """Pick the sentence(s) with the most query-term overlap."""
    terms = {t for t in tokenize(query) if t not in _STOPWORDS}
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if not sentences:
        return text[:max_chars]
    scored = sorted(
        range(len(sentences)),
        key=lambda i: (-len(terms & set(tokenize(sentences[i]))), i),
    )
    out = sentences[scored[0]]
    return out if len(out) <= max_chars else out[: max_chars - 1].rstrip() + "…"


class Assistant:
    def __init__(self, retriever: HybridRetriever, llm: OpenAICompatibleClient | None = None):
        self.retriever = retriever
        self.llm = llm

    def _supported(self, question: str, hits: list[Hit]) -> bool:
        """Cheap guard: at least one content word of the question must appear in the evidence.
        It rejects retrieval noise before spending an LLM call; it does not judge correctness."""
        terms = {t for t in tokenize(question) if t not in _STOPWORDS}
        if not terms:
            return bool(hits)
        evidence = set().union(*(set(tokenize(h.text + " " + (h.section_title or ""))) for h in hits)) if hits else set()
        return bool(terms & evidence)

    def answer(self, question: str, user: User, top_k: int = 5, mode: str = "hybrid", rerank: bool = False) -> ChatAnswer:
        response = self.retriever.search(question, user, mode=mode, top_k=top_k, rerank=rerank)
        hits = response.hits
        timings = dict(response.timings_ms)
        if not hits or not self._supported(question, hits):
            return ChatAnswer(question, "insufficient", None, timings_ms=timings,
                              warning="No accessible documents matched the question.")

        excerpts = [
            {"index": i, "excerpt": best_excerpt(h.text, question), **h.citation()}
            for i, h in enumerate(hits, start=1)
        ]
        if self.llm is None:
            return ChatAnswer(question, "extractive", None, [h.citation() for h in hits], excerpts,
                              warning="No LLM configured; showing the most relevant excerpts.",
                              timings_ms=timings)

        context = "\n\n".join(
            f"[{i}] ({h.source_path}{', p.' + str(h.page_number) if h.page_number else ''}"
            f"{', ' + h.section_title if h.section_title else ''})\n{h.text}"
            for i, h in enumerate(hits, start=1)
        )
        try:
            raw = self.llm.complete(SYSTEM_PROMPT, f"Context:\n{context}\n\nQuestion: {question}")
        except LLMError as exc:
            return ChatAnswer(question, "extractive", None, [h.citation() for h in hits], excerpts,
                              warning=f"{exc}. Showing excerpts instead.", timings_ms=timings)

        if raw.strip().startswith(INSUFFICIENT):
            return ChatAnswer(question, "insufficient", None, excerpts=excerpts, timings_ms=timings,
                              warning="The retrieved documents do not contain enough information.")

        cited = sorted({int(n) for n in _CITATION.findall(raw)})
        invalid = [n for n in cited if not 1 <= n <= len(hits)]
        text = _CITATION.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= len(hits) else "", raw)
        valid = [n for n in cited if n not in invalid]
        warning = None
        if invalid:
            warning = f"Removed references to nonexistent sources: {invalid}."
        elif not valid:
            warning = "The model did not cite any source; treat this answer with caution."
        citations = [hits[n - 1].citation() | {"index": n} for n in valid]
        return ChatAnswer(question, "llm", text, citations, excerpts, warning, timings)
