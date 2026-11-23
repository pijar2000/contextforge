"""Streamlit dashboard. It talks to the ContextForge API only; it never touches the databases."""

import os

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="ContextForge", layout="wide")
st.title("ContextForge")

with st.sidebar:
    st.header("Connection")
    api_url = st.text_input("API URL", API_URL)
    api_key = st.text_input("API key", type="password", help="Development keys are listed in the README.")


def call(method: str, path: str, **kwargs):
    try:
        response = httpx.request(
            method, f"{api_url}{path}", headers={"X-API-Key": api_key}, timeout=300, **kwargs
        )
    except httpx.HTTPError as exc:
        st.error(f"Cannot reach the API at {api_url}: {exc}")
        return None
    if response.status_code >= 400:
        st.error(f"{response.status_code}: {response.json().get('detail', response.text)}")
        return None
    return response.json() if response.content else {}


if not api_key:
    st.info("Enter an API key in the sidebar to begin.")
    st.stop()

me = call("GET", "/me")
if me is None:
    st.stop()
st.sidebar.success(f"{me['user_id']} ({', '.join(me['roles'])})")

tab_overview, tab_docs, tab_search, tab_eval = st.tabs(
    ["Overview", "Documents", "Search playground", "Evaluation"]
)

with tab_overview:
    stats = call("GET", "/stats")  # administrators only
    if stats:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Documents", stats["documents_total"])
        c2.metric("Indexed chunks", stats["chunks_indexed"])
        c3.metric("Indexed versions", stats["indexed_document_versions"])
        c4.metric("Failed documents", stats["documents_failed"])
        c5.metric("Last ingestion", (stats["last_ingestion_at"] or "never")[:19])
        st.subheader("Documents by status")
        st.bar_chart(pd.Series(stats["documents_by_status"], name="documents"))
        st.subheader("Recent ingestion runs")
        st.dataframe(pd.DataFrame(stats["recent_runs"]), use_container_width=True)
    if me["roles"] and "administrator" in me["roles"]:
        if st.button("Run ingestion now"):
            result = call("POST", "/documents/ingest", json={"force": False})
            if result:
                st.json(result)

with tab_docs:
    status = st.selectbox("Status filter", ["", "indexed", "processing", "failed", "empty"])
    page = call("GET", "/documents", params={"limit": 200, "status": status or None})
    if page:
        df = pd.DataFrame(page["items"])
        if df.empty:
            st.write("No documents visible to this user.")
        else:
            st.dataframe(
                df[["source_path", "file_type", "status", "current_version", "indexed_version",
                    "allowed_groups", "last_ingested_at"]],
                use_container_width=True,
            )
            failed = df[df["status"] == "failed"]
            if not failed.empty:
                st.subheader("Processing errors")
                for _, row in failed.iterrows():
                    st.code(f"{row['source_path']}\n{row.get('last_error')}")
            chosen = st.selectbox("Document", df["source_path"])
            doc_id = df.loc[df["source_path"] == chosen, "document_id"].iloc[0]
            detail = call("GET", f"/documents/{doc_id}")
            if detail:
                st.write("Versions")
                st.dataframe(pd.DataFrame(detail["versions"]), use_container_width=True)
            if "administrator" in me["roles"] and st.button("Re-index this document"):
                result = call("POST", f"/documents/{doc_id}/reindex")
                if result:
                    st.json(result)

with tab_search:
    query = st.text_input("Query", placeholder='e.g. how long are audit logs kept?  (use "quotes" for exact phrases)')
    col1, col2, col3 = st.columns(3)
    mode = col1.selectbox("Mode", ["hybrid", "bm25", "vector"])
    top_k = col2.slider("Top-K", 1, 20, 5)
    rerank = col3.checkbox("Cross-encoder rerank", help="Loads a model on first use.")
    compare = st.checkbox("Compare all retrieval methods side by side")

    def render(label: str, body: dict):
        st.markdown(f"**{label}**  \n`{body['timings_ms'].get('total_ms')} ms` · {body['counts']}")
        for i, hit in enumerate(body["hits"], start=1):
            page_info = f", p.{hit['page_number']}" if hit["page_number"] else ""
            with st.expander(f"{i}. {hit['source_path']}{page_info} · {hit['section_title'] or '-'} · {hit['score']:.4f}"):
                st.write(hit["text"])
                st.caption(f"chunk {hit['chunk_id']} · v{hit['document_version']}")
                st.json(hit["signals"])

    if query:
        if compare:
            variants = [("BM25", "bm25", False), ("Vector", "vector", False),
                        ("Hybrid (RRF)", "hybrid", False), ("Hybrid + rerank", "hybrid", True)]
            cols = st.columns(len(variants))
            for col, (label, m, r) in zip(cols, variants, strict=True):
                body = call("POST", "/search", json={"query": query, "mode": m, "top_k": top_k, "rerank": r})
                with col:
                    if body:
                        render(label, body)
        else:
            body = call("POST", "/search", json={"query": query, "mode": mode, "top_k": top_k, "rerank": rerank})
            if body:
                render(f"{mode}{' + rerank' if rerank else ''}", body)
                if st.button("Ask the assistant about this"):
                    answer = call("POST", "/chat", json={"question": query, "mode": mode, "top_k": top_k, "rerank": rerank})
                    if answer:
                        if answer.get("warning"):
                            st.warning(answer["warning"])
                        if answer.get("answer"):
                            st.write(answer["answer"])
                        for ex in answer.get("excerpts", []):
                            st.caption(f"[{ex['index']}] {ex['source_path']}: {ex['excerpt']}")

with tab_eval:
    report = call("GET", "/evaluation/results")
    if report:
        ks = report["config"]["ks"]
        k = st.selectbox("K", ks, index=ks.index(5) if 5 in ks else 0)
        rows = [{"strategy": name, f"Recall@{k}": s[f"recall@{k}"], f"Precision@{k}": s[f"precision@{k}"],
                 f"HitRate@{k}": s[f"hit_rate@{k}"], "MRR": s["mrr"], "latency mean (ms)": s["latency_ms_mean"],
                 "latency p95 (ms)": s["latency_ms_p95"]} for name, s in report["summary"].items()]
        df = pd.DataFrame(rows).set_index("strategy")
        st.dataframe(df, use_container_width=True)
        st.bar_chart(df[[f"Recall@{k}", f"Precision@{k}", "MRR"]])
        st.bar_chart(df[["latency mean (ms)", "latency p95 (ms)"]])
        st.caption(f"Generated {report.get('generated_at')} · {report['config'].get('queries_judged')} judged queries")
        with st.expander("Configuration"):
            st.json(report["config"])
    else:
        st.write("Run `contextforge evaluate` to produce a report.")
