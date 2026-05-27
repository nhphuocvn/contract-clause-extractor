import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from extract import (
    BasicContractExtraction,
    ContractExtraction,
    build_comparison,
    build_output,
    compute_risk_summary,
    extract,
    extract_basic,
    load_standard_terms,
    read_contract_bytes,
    save_standard_terms,
)
from index import get_collection, index_folder
from query import DEFAULT_TOP_K, answer_question

load_dotenv()

st.set_page_config(page_title="Contract Extractor", layout="wide")
st.title("Contract Extractor")

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    st.error("OPENAI_API_KEY is not set. Add it to .env and restart.")
    st.stop()

client = OpenAI(api_key=api_key)


STANDARD_TERMS_PATH = "standard_terms.json"

if "standard_terms" not in st.session_state:
    st.session_state.standard_terms = load_standard_terms(STANDARD_TERMS_PATH)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


@st.cache_resource
def get_chroma_collection():
    return get_collection()


@st.cache_data(show_spinner=False)
def run_extraction(file_name: str, suffix: str, data: bytes, standard_terms_json: str):
    standard_terms = json.loads(standard_terms_json)
    text = read_contract_bytes(data, suffix)
    ai_ok = True
    ai_error = ""
    try:
        extraction, tokens = extract(client, text, standard_terms)
    except Exception as exc:
        ai_ok = False
        ai_error = f"{type(exc).__name__}: {exc}"
        extraction, tokens = extract_basic(client, text)
    deterministic = compute_risk_summary(extraction)
    return extraction, deterministic, tokens, ai_ok, ai_error


@st.cache_data(show_spinner=False)
def run_query(question: str, top_k: int, _version: int):
    collection = get_chroma_collection()
    return answer_question(client, collection, question, top_k=top_k)


# ---------------------------------------------------------------------------
# Styling / helpers
# ---------------------------------------------------------------------------


# For deterministic risk_summary flags (legacy levels)
LEVEL_STYLES = {
    "high":               {"bg": "#fff1f0", "border": "#ff4d4f", "label": "HIGH RISK"},
    "medium":             {"bg": "#fffbe6", "border": "#faad14", "label": "MEDIUM"},
    "review_recommended": {"bg": "#e6f4ff", "border": "#1890ff", "label": "REVIEW"},
    "low_protection":     {"bg": "#fffbe6", "border": "#faad14", "label": "LOW PROTECTION"},
    "low":                {"bg": "#f6ffed", "border": "#52c41a", "label": "LOW"},
}

# For AI findings (clean severity buckets)
SEVERITY_STYLES = {
    "high":          {"bg": "#fff1f0", "border": "#ff4d4f", "label": "HIGH"},
    "medium":        {"bg": "#fffbe6", "border": "#faad14", "label": "MEDIUM"},
    "low":           {"bg": "#e6f4ff", "border": "#1890ff", "label": "LOW"},
    "informational": {"bg": "#fafafa", "border": "#8c8c8c", "label": "INFO"},
}

# Overall AI risk badge colors
OVERALL_AI_STYLES = {
    "high":   {"bg": "#fff1f0", "border": "#ff4d4f", "label": "HIGH RISK"},
    "medium": {"bg": "#fffbe6", "border": "#faad14", "label": "MEDIUM RISK"},
    "low":    {"bg": "#f6ffed", "border": "#52c41a", "label": "LOW RISK"},
}


def badge_html(style: dict) -> str:
    return (
        f"<span style='background:{style['bg']};"
        f"border:1px solid {style['border']};"
        f"color:{style['border']};"
        f"padding:3px 12px;border-radius:12px;font-weight:600;font-size:13px;'>"
        f"{style['label']}</span>"
    )


def build_field_rows(e) -> list[dict]:
    rows = [{
        "Field": "parties",
        "Value": "; ".join(f"{p.name} ({p.role})" for p in e.parties.value),
        "Source quote": e.parties.source_quote,
    }]
    for fn in ["effective_date", "term_length", "auto_renewal", "payment_terms"]:
        f = getattr(e, fn)
        rows.append({"Field": fn, "Value": f.value, "Source quote": f.source_quote})
    for sub in ["for_cause", "for_convenience", "for_non_payment"]:
        f = getattr(e.termination_clauses, sub)
        rows.append({
            "Field": f"termination_clauses.{sub}",
            "Value": f.value,
            "Source quote": f.source_quote,
        })
    for fn in [
        "sla_commitments", "indemnity_cap", "limitation_of_liability",
        "governing_law", "confidentiality_period",
    ]:
        f = getattr(e, fn)
        rows.append({"Field": fn, "Value": f.value, "Source quote": f.source_quote})
    for sub in ["encryption", "data_residency", "certifications", "compliance_frameworks"]:
        f = getattr(e.data_protection, sub)
        rows.append({
            "Field": f"data_protection.{sub}",
            "Value": f.value,
            "Source quote": f.source_quote,
        })
    return rows


def render_ai_finding(f):
    style = SEVERITY_STYLES.get(f.severity, SEVERITY_STYLES["informational"])
    deviation_html = (
        f"<div style='margin-top:6px;color:#555;'><b>Deviation from standard:</b> {f.standard_deviation}</div>"
        if f.standard_deviation else ""
    )
    counter_html = (
        f"<div style='margin-top:4px;color:#555;'><b>Counter-position:</b> <i>{f.counter_position}</i></div>"
        if f.counter_position else ""
    )
    st.markdown(
        f"<div style='background:{style['bg']};"
        f"border-left:4px solid {style['border']};"
        f"padding:12px 16px;margin:8px 0;border-radius:4px;'>"
        f"<span style='background:{style['border']};color:white;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;'>{style['label']}</span> "
        f"<span style='color:#888;font-size:12px;'>· {f.category}</span>"
        f"<div style='font-weight:600;margin-top:6px;font-size:15px;'>{f.title}</div>"
        f"<div style='margin-top:4px;'>{f.finding}</div>"
        f"{deviation_html}{counter_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_deterministic_flag(flag):
    style = LEVEL_STYLES.get(flag.level, LEVEL_STYLES["low"])
    evidence_html = (
        f"<br><i style='color:#555;'>&ldquo;{flag.evidence}&rdquo;</i>"
        if flag.evidence else ""
    )
    st.markdown(
        f"<div style='background:{style['bg']};"
        f"border-left:4px solid {style['border']};"
        f"padding:10px 14px;margin:6px 0;border-radius:4px;'>"
        f"<b style='color:{style['border']};'>{style['label']}</b> &middot; "
        f"<code>{flag.rule}</code><br>{flag.message}{evidence_html}</div>",
        unsafe_allow_html=True,
    )


def render_contract(name, extraction, deterministic, tokens, ai_ok, ai_error):
    is_full = isinstance(extraction, ContractExtraction) and ai_ok
    ai = extraction.ai_risk_assessment if is_full else None
    ct = extraction.contract_type if is_full else None

    header_cols = st.columns([3, 1])
    with header_cols[0]:
        st.subheader(name)
    with header_cols[1]:
        if is_full:
            style = OVERALL_AI_STYLES.get(ai.overall_risk_level, OVERALL_AI_STYLES["low"])
            st.markdown(badge_html(style), unsafe_allow_html=True)
        else:
            st.markdown(
                badge_html({"bg": "#fafafa", "border": "#8c8c8c", "label": "FALLBACK"}),
                unsafe_allow_html=True,
            )

    st.caption(f"Tokens used: {tokens}")

    if is_full:
        st.markdown(
            f"**Contract type:** {ct.primary} "
            f"<span style='color:#888;font-size:13px;'>({ct.confidence} confidence)</span>",
            unsafe_allow_html=True,
        )
        st.caption(ct.rationale)
        if ct.applicable_fields:
            st.caption("Applicable fields: " + ", ".join(ct.applicable_fields))

        st.markdown("### Overall assessment")
        st.markdown(
            f"<div style='background:#fafafa;border-left:4px solid #1890ff;"
            f"padding:12px 16px;margin:8px 0;border-radius:4px;'>{ai.overall_assessment}</div>",
            unsafe_allow_html=True,
        )

        st.markdown(f"### Findings ({len(ai.findings)})")
        if ai.findings:
            for f in ai.findings:
                render_ai_finding(f)
        else:
            st.success("No findings — the contract is well-aligned with your standards.")
    else:
        st.warning(
            "AI risk assessment unavailable — using deterministic fallback rules below."
            + (f"  \n_Error: {ai_error}_" if ai_error else "")
        )

    with st.expander("Deterministic rule check (fallback / cross-check)"):
        if deterministic.flags:
            st.caption(f"{len(deterministic.flags)} flag(s) from hardcoded rules.")
            for flag in deterministic.flags:
                render_deterministic_flag(flag)
        else:
            st.caption("No flags from deterministic rules.")

    st.markdown("### Extracted fields")
    st.dataframe(build_field_rows(extraction), use_container_width=True, hide_index=True, height=600)

    st.download_button(
        "Download JSON",
        data=json.dumps(build_output(extraction, deterministic), indent=2),
        file_name=Path(name).with_suffix(".json").name,
        mime="application/json",
        key=f"dl-{name}",
    )


# ---------------------------------------------------------------------------
# Sidebar: mode + standard terms
# ---------------------------------------------------------------------------


mode = st.sidebar.radio("Mode", ["Contract extraction", "Portfolio search"])


def render_standards_form():
    thresholds = st.session_state.standard_terms.get("thresholds", {})
    prefs = st.session_state.standard_terms.get("preferences", {})

    with st.sidebar:
        st.markdown("---")
        st.markdown("### Company standards")
        st.caption("The AI compares each contract against these and proposes counter-positions for deviations.")

        with st.form("standards_form", clear_on_submit=False):
            auto_renewal_min = st.slider(
                "Auto-renewal notice (min days)", 30, 180,
                int(thresholds.get("auto_renewal_notice_min_days", 90)),
            )
            liability_min_months = st.slider(
                "Liability cap (min months of fees)", 3, 36,
                int(thresholds.get("liability_cap_min_months_of_fees", 12)),
            )
            liability_min_mult = st.slider(
                "Liability cap (min × annual fees)", 0.5, 5.0,
                float(thresholds.get("liability_cap_min_multiplier_of_annual_fees", 1.0)),
                0.5,
            )
            indemnity_min_mult = st.slider(
                "Indemnity cap (min × annual fees)", 1.0, 5.0,
                float(thresholds.get("indemnity_cap_min_multiplier_of_annual_fees", 2.0)),
                0.5,
            )
            sla_min_pct = st.slider(
                "SLA uptime (min %)", 95.0, 100.0,
                float(thresholds.get("sla_uptime_min_percent", 99.5)),
                0.1,
            )
            confid_min_yrs = st.slider(
                "Confidentiality (min years)", 1, 10,
                int(thresholds.get("confidentiality_period_min_years", 3)),
            )
            payment_max_days = st.slider(
                "Payment terms (max net days)", 15, 120,
                int(thresholds.get("payment_terms_max_net_days", 45)),
            )

            juris_default = "\n".join(prefs.get("preferred_governing_jurisdictions", []))
            jurisdictions = st.text_area(
                "Preferred jurisdictions (one per line)",
                value=juris_default,
                height=110,
            )
            certs_default = "\n".join(prefs.get("required_certifications", []))
            certifications = st.text_area(
                "Required certifications (one per line)",
                value=certs_default,
                height=80,
            )

            col1, col2 = st.columns(2)
            with col1:
                apply_btn = st.form_submit_button("Apply", use_container_width=True)
            with col2:
                save_btn = st.form_submit_button("Save to file", use_container_width=True)

        if apply_btn or save_btn:
            updated = {
                **st.session_state.standard_terms,
                "thresholds": {
                    "auto_renewal_notice_min_days": auto_renewal_min,
                    "liability_cap_min_months_of_fees": liability_min_months,
                    "liability_cap_min_multiplier_of_annual_fees": liability_min_mult,
                    "indemnity_cap_min_multiplier_of_annual_fees": indemnity_min_mult,
                    "sla_uptime_min_percent": sla_min_pct,
                    "confidentiality_period_min_years": confid_min_yrs,
                    "payment_terms_max_net_days": payment_max_days,
                    "termination_for_cause_notice_max_days": thresholds.get("termination_for_cause_notice_max_days", 30),
                    "termination_for_convenience_notice_max_days": thresholds.get("termination_for_convenience_notice_max_days", 90),
                },
                "preferences": {
                    **prefs,
                    "preferred_governing_jurisdictions": [
                        j.strip() for j in jurisdictions.splitlines() if j.strip()
                    ],
                    "required_certifications": [
                        c.strip() for c in certifications.splitlines() if c.strip()
                    ],
                },
            }
            st.session_state.standard_terms = updated
            run_extraction.clear()
            if save_btn:
                save_standard_terms(updated, STANDARD_TERMS_PATH)
                st.sidebar.success(f"Saved to {STANDARD_TERMS_PATH}")
            else:
                st.sidebar.success("Standards applied. Re-evaluation will run on next upload action.")


# ---------------------------------------------------------------------------
# MODE: Contract extraction
# ---------------------------------------------------------------------------


if mode == "Contract extraction":
    render_standards_form()

    uploads = st.file_uploader(
        "Upload contract files (.txt or .pdf)",
        type=["txt", "pdf"],
        accept_multiple_files=True,
    )

    if not uploads:
        st.info("Upload one or more contracts to begin.")
        st.stop()

    standard_terms_json = json.dumps(st.session_state.standard_terms, sort_keys=True)

    results = []
    for upload in uploads:
        suffix = Path(upload.name).suffix
        with st.spinner(f"Extracting {upload.name}..."):
            try:
                extraction, deterministic, tokens, ai_ok, ai_error = run_extraction(
                    upload.name, suffix, upload.getvalue(), standard_terms_json,
                )
            except Exception as exc:
                st.error(f"Failed to extract {upload.name}: {exc}")
                continue
        results.append((upload.name, extraction, deterministic, tokens, ai_ok, ai_error))

    if not results:
        st.stop()

    tab_labels = [r[0] for r in results]
    if len(results) >= 2:
        tab_labels.append("Compare")

    tabs = st.tabs(tab_labels)
    for i, (name, extraction, deterministic, tokens, ai_ok, ai_error) in enumerate(results):
        with tabs[i]:
            render_contract(name, extraction, deterministic, tokens, ai_ok, ai_error)

    if len(results) >= 2:
        with tabs[-1]:
            st.subheader("Side-by-side comparison")
            comparison = build_comparison([(n, e, d) for n, e, d, _, _, _ in results])
            compare_rows = []
            for row in comparison["rows"]:
                entry = {"Field": row["field"]}
                for cname, v in zip(comparison["contracts"], row["values"]):
                    entry[cname] = str(v)
                compare_rows.append(entry)
            st.dataframe(compare_rows, use_container_width=True, hide_index=True, height=550)

            st.download_button(
                "Download comparison JSON",
                data=json.dumps(comparison, indent=2),
                file_name="comparison_report.json",
                mime="application/json",
                key="dl-comparison",
            )


# ---------------------------------------------------------------------------
# MODE: Portfolio search
# ---------------------------------------------------------------------------


else:
    st.header("Portfolio search")
    st.caption(
        "Ask natural-language questions across all indexed contracts. "
        "Powered by ChromaDB vector search + GPT-4o-mini with source citations."
    )

    collection = get_chroma_collection()
    chunk_count = collection.count()

    with st.expander("Index a folder of contracts", expanded=(chunk_count == 0)):
        col1, col2 = st.columns([4, 1])
        with col1:
            folder_path = st.text_input(
                "Folder path",
                value="contracts",
                help="Directory containing .txt or .pdf contract files.",
            )
        with col2:
            st.write("")
            st.write("")
            do_index = st.button("Index folder", use_container_width=True)

        if do_index:
            folder = Path(folder_path)
            if not folder.is_dir():
                st.error(f"`{folder}` is not a directory.")
            else:
                with st.spinner(f"Indexing {folder}/..."):
                    try:
                        n_chunks, n_contracts = index_folder(folder, client)
                    except Exception as exc:
                        st.error(f"Indexing failed: {exc}")
                        n_chunks = n_contracts = 0

                if n_chunks > 0:
                    st.success(f"Indexed {n_chunks} chunks from {n_contracts} contract(s).")
                    run_query.clear()
                    chunk_count = collection.count()
                else:
                    st.warning("Nothing was indexed.")

    if chunk_count == 0:
        st.info("No contracts indexed yet. Expand the panel above to index a folder.")
        st.stop()

    st.caption(f"Collection contains **{chunk_count}** chunks.")

    question = st.text_input(
        "Ask a question about your contracts",
        placeholder="e.g. Which contract has the shorter auto-renewal notice period?",
    )
    top_k = st.slider("Top-K chunks to retrieve", 1, 15, DEFAULT_TOP_K)

    if question:
        with st.spinner("Searching..."):
            try:
                result = run_query(question, top_k, chunk_count)
            except Exception as exc:
                st.error(f"Query failed: {exc}")
                st.stop()

        st.markdown("### Answer")
        st.markdown(result["answer"])

        st.markdown("### Sources")
        for cite in result["citations"]:
            st.markdown(
                f"<div style='border-left:4px solid #1890ff;"
                f"padding:10px 14px;margin:6px 0;background:#f0f7ff;border-radius:4px;'>"
                f"<b>[{cite['index']}]</b> <code>{cite['contract']}</code> &middot; "
                f"Section {cite['section_number']}: {cite['section_title']} "
                f"<span style='color:#888;font-size:12px;'>(distance={cite['distance']:.3f})</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
