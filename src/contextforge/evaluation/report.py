import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from contextforge.evaluation.runner import EvaluationResult


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def render_markdown(result: EvaluationResult) -> str:
    ks = result.config["ks"]
    headline_k = 5 if 5 in ks else ks[-1]
    lines = [
        "# Retrieval evaluation report",
        "",
        f"Generated: {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        "Configuration: " + ", ".join(f"`{k}={v}`" for k, v in result.config.items()
                                       if k not in ("queries_without_relevant_chunks",)),
        "",
        f"## Summary at K={headline_k}",
        "",
    ]
    headers = ["Strategy", f"Recall@{headline_k}", f"Precision@{headline_k}", f"HitRate@{headline_k}",
               "MRR", "Latency mean (ms)", "p50", "p95"]
    rows = []
    for name, s in result.summary.items():
        rows.append([name, f"{s[f'recall@{headline_k}']:.3f}", f"{s[f'precision@{headline_k}']:.3f}",
                     f"{s[f'hit_rate@{headline_k}']:.3f}", f"{s['mrr']:.3f}",
                     f"{s['latency_ms_mean']:.1f}", f"{s['latency_ms_p50']:.1f}", f"{s['latency_ms_p95']:.1f}"])
    lines += [_table(headers, rows), "", "## Metrics by K", ""]
    for metric in ("recall", "precision", "hit_rate"):
        lines += [f"### {metric}@K", ""]
        rows = [[name] + [f"{s[f'{metric}@{k}']:.3f}" for k in ks] for name, s in result.summary.items()]
        lines += [_table(["Strategy"] + [f"K={k}" for k in ks], rows), ""]

    if result.per_query:
        df = pl.DataFrame(
            [{"strategy": r["strategy"], "category": r["category"], "mrr": r["mrr"],
              "recall": r[f"recall@{headline_k}"]} for r in result.per_query]
        )
        agg = (df.group_by(["category", "strategy"])
                 .agg(pl.col("mrr").mean().alias("mrr"), pl.col("recall").mean().alias("recall"),
                      pl.len().alias("n"))
                 .sort(["category", "strategy"]))
        lines += [f"## By query category (Recall@{headline_k}, MRR)", ""]
        lines += [_table(["Category", "Strategy", "n", "Recall", "MRR"],
                         [[r["category"], r["strategy"], str(r["n"]), f"{r['recall']:.3f}", f"{r['mrr']:.3f}"]
                          for r in agg.iter_rows(named=True)]), ""]

    if "hybrid" in result.summary and "hybrid_rerank" in result.summary:
        a, b = result.summary["hybrid"], result.summary["hybrid_rerank"]
        lines += ["## Effect of reranking (hybrid_rerank minus hybrid)", ""]
        lines += [f"- MRR: {b['mrr'] - a['mrr']:+.3f}",
                  f"- Recall@{headline_k}: {b[f'recall@{headline_k}'] - a[f'recall@{headline_k}']:+.3f}",
                  f"- Precision@{headline_k}: {b[f'precision@{headline_k}'] - a[f'precision@{headline_k}']:+.3f}",
                  f"- Mean latency: {b['latency_ms_mean'] - a['latency_ms_mean']:+.1f} ms", ""]
    lines += [
        "## How to read this",
        "",
        f"The dataset has {result.config.get('queries_judged')} judged queries. Differences of a few "
        "hundredths between strategies are within what one or two queries can change, so treat them "
        "as indicative, not conclusive. Relevance is derived from expected keywords, which favours "
        "lexical methods; see docs/evaluation.md for the limitations.",
        "",
    ]
    return "\n".join(lines)


def write_report(result: EvaluationResult, directory: Path) -> tuple[Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict() | {"generated_at": datetime.now(UTC).isoformat(timespec="seconds")}
    json_path = directory / "latest.json"
    md_path = directory / "latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, md_path
