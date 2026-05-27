import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from extract import (
    build_comparison,
    build_output,
    compute_risk_summary,
    extract,
    read_contract_bytes,
)

load_dotenv()

st.set_page_config(page_title="Contract Extractor", layout="wide")
st.title("Contract Extractor")

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    st.error("OPENAI_API_KEY is not set. Add it to .env and restart.")
    st.stop()

client = OpenAI(api_key=api_key)


@st.cache_data(show_spinner=False)
def run_extraction(file_name: str, suffix: str, data: bytes):
    text = read_contract_bytes(data, suffix)
    extraction, tokens = extract(client, text)
    risk = compute_risk_summary(extraction)
    return extraction, risk, tokens


LEVEL_STYLES = {
    "high":               {"bg": "#fff1f0", "border": "#ff4d4f", "label": "HIGH RISK"},
    "medium":             {"bg": "#fffbe6", "border": "#faad14", "label": "MEDIUM"},
    "review_recommended": {"bg": "#e6f4ff", "border": "#1890ff", "label": "REVIEW"},
    "low_protection":     {"bg": "#fffbe6", "border": "#faad14", "label": "LOW PROTECTION"},
    "low":                {"bg": "#f6ffed", "border": "#52c41a", "label": "LOW"},
}


def badge_html(level: str) -> str:
    style = LEVEL_STYLES.get(level, LEVEL_STYLES["low"])
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


def render_contract(name, extraction, risk, tokens):
    header_cols = st.columns([3, 1])
    with header_cols[0]:
        st.subheader(name)
    with header_cols[1]:
        st.markdown(badge_html(risk.overall_risk), unsafe_allow_html=True)
    st.caption(f"Tokens used: {tokens}")

    if risk.flags:
        st.markdown("**Risk flags**")
        for flag in risk.flags:
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
    else:
        st.success("No risk flags identified.")

    st.markdown("**Extracted fields**")
    st.dataframe(build_field_rows(extraction), use_container_width=True, hide_index=True, height=600)

    st.download_button(
        "Download JSON",
        data=json.dumps(build_output(extraction, risk), indent=2),
        file_name=Path(name).with_suffix(".json").name,
        mime="application/json",
        key=f"dl-{name}",
    )


uploads = st.file_uploader(
    "Upload contract files (.txt or .pdf)",
    type=["txt", "pdf"],
    accept_multiple_files=True,
)

if not uploads:
    st.info("Upload one or more contracts to begin.")
    st.stop()

results = []
for upload in uploads:
    suffix = Path(upload.name).suffix
    with st.spinner(f"Extracting {upload.name}..."):
        try:
            extraction, risk, tokens = run_extraction(
                upload.name, suffix, upload.getvalue()
            )
        except Exception as exc:
            st.error(f"Failed to extract {upload.name}: {exc}")
            continue
    results.append((upload.name, extraction, risk, tokens))

if not results:
    st.stop()

tab_labels = [r[0] for r in results]
if len(results) >= 2:
    tab_labels.append("Compare")

tabs = st.tabs(tab_labels)
for i, (name, extraction, risk, tokens) in enumerate(results):
    with tabs[i]:
        render_contract(name, extraction, risk, tokens)

if len(results) >= 2:
    with tabs[-1]:
        st.subheader("Side-by-side comparison")
        comparison = build_comparison([(n, e, r) for n, e, r, _ in results])
        compare_rows = []
        for row in comparison["rows"]:
            entry = {"Field": row["field"]}
            for cname, v in zip(comparison["contracts"], row["values"]):
                entry[cname] = str(v)
            compare_rows.append(entry)
        st.dataframe(compare_rows, use_container_width=True, hide_index=True, height=500)

        st.download_button(
            "Download comparison JSON",
            data=json.dumps(comparison, indent=2),
            file_name="comparison_report.json",
            mime="application/json",
            key="dl-comparison",
        )
