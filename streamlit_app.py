"""Interactive Streamlit interface for ReleaseGuard."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

from releaseguard.adapters.git_local import RepositoryAccessError
from releaseguard.adapters.github_public import PublicGitHubImporter
from releaseguard.bootstrap import build_analyzer
from releaseguard.config import Settings
from releaseguard.demo import DemoRepositoryFactory
from releaseguard.domain.models import ReadinessReport, ReadinessStatus, RiskLevel

st.set_page_config(
    page_title="ReleaseGuard · Release readiness",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1180px; padding-top: 2.4rem; padding-bottom: 4rem;}
    [data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.2);}
    .rg-kicker {font-size:.78rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
      color:#18a999; margin-bottom:.65rem;}
    .rg-title {font-size:clamp(2.4rem,6vw,4.4rem); line-height:.96; font-weight:760;
      letter-spacing:-.045em; margin:0 0 1rem;}
    .rg-subtitle {font-size:1.12rem; line-height:1.65; color:#7f8998; max-width:760px;
      margin-bottom:2rem;}
    .rg-card {border:1px solid rgba(128,128,128,.22); border-radius:16px; padding:1.2rem 1.3rem;
      background:rgba(128,128,128,.045); margin:.5rem 0 1rem;}
    .rg-ready {border-left:5px solid #2bb673;} .rg-review {border-left:5px solid #f2a93b;}
    .rg-blocked {border-left:5px solid #e35d6a;}
    .rg-status {font-size:1.4rem; font-weight:720; margin-bottom:.3rem;}
    .rg-muted {color:#7f8998; font-size:.92rem;}
    .rg-pill {display:inline-block; border:1px solid rgba(128,128,128,.28); border-radius:999px;
      padding:.23rem .62rem; margin:.12rem .2rem .12rem 0; font-size:.82rem;}
    div[data-testid="stMetric"] {border:1px solid rgba(128,128,128,.2); border-radius:14px;
      padding:1rem; background:rgba(128,128,128,.035);}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def demo_factory() -> DemoRepositoryFactory:
    return DemoRepositoryFactory()


@st.cache_resource
def github_importer() -> PublicGitHubImporter:
    return PublicGitHubImporter(timeout_seconds=45, history_depth=50)


def workspace_root() -> Path:
    return Path(tempfile.gettempdir()) / "releaseguard-streamlit"


def run_analysis(repository: Path, base_ref: str, head_ref: str) -> ReadinessReport:
    session_id = st.session_state.setdefault("releaseguard_session_id", uuid4().hex)
    root = workspace_root()
    settings = Settings(
        environment="production",
        repository_root=root,
        checkpoint_database=root / "checkpoints" / f"{session_id}.sqlite3",
        embedding_provider="hashing",
        trace_exporter="none",
        git_timeout_seconds=60,
        max_diff_bytes=750_000,
        max_index_files=2_000,
        max_source_file_bytes=250_000,
        retrieval_max_documents=350,
        retrieval_max_file_bytes=20_000,
        retrieval_top_k=8,
    )
    return build_analyzer(settings).execute(repository, base_ref, head_ref)


def display_status(report: ReadinessReport) -> None:
    styles = {
        ReadinessStatus.READY: ("rg-ready", "Ready", "No deterministic blocker detected"),
        ReadinessStatus.REVIEW_REQUIRED: (
            "rg-review",
            "Review required",
            "High-risk change surfaces need human review",
        ),
        ReadinessStatus.BLOCKED: (
            "rg-blocked",
            "Blocked",
            "A critical policy finding must be resolved",
        ),
    }
    css_class, label, explanation = styles[report.status]
    st.markdown(
        f"<div class='rg-card {css_class}'><div class='rg-status'>{label}</div>"
        f"<div>{report.summary}</div><div class='rg-muted'>{explanation}</div></div>",
        unsafe_allow_html=True,
    )


def report_payload(report: ReadinessReport, source_label: str) -> dict[str, Any]:
    payload = report.model_dump(mode="json")
    local_repository = payload["repository"]
    payload["repository"] = source_label
    for evidence in payload["evidence"]:
        if evidence["repository"] == local_repository:
            evidence["repository"] = source_label
    return payload


def render_report(report: ReadinessReport, source_label: str) -> None:
    display_status(report)
    changed_lines = sum(
        (item.additions or 0) + (item.deletions or 0) for item in report.changed_files
    )
    cols = st.columns(4)
    cols[0].metric("Changed files", len(report.changed_files))
    cols[1].metric("Risk findings", len(report.findings))
    cols[2].metric("Changed lines", changed_lines)
    cols[3].metric("Candidate tests", len(report.impact.candidate_tests) if report.impact else 0)

    overview, impact_tab, evidence_tab, context_tab, report_tab = st.tabs(
        ["Overview", "Impact", "Evidence", "Retrieved context", "Full report"]
    )
    with overview:
        st.subheader("What changed")
        if report.changed_files:
            st.dataframe(
                [
                    {
                        "file": item.path,
                        "status": item.status.value,
                        "added": item.additions,
                        "deleted": item.deletions,
                    }
                    for item in report.changed_files
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("The selected refs do not contain changed files.")

        st.subheader("Why it was classified this way")
        if not report.findings:
            st.success("No configured high-risk path rules matched this change.")
        for finding in report.findings:
            icon = {
                RiskLevel.CRITICAL: "🔴",
                RiskLevel.HIGH: "🟠",
                RiskLevel.MEDIUM: "🟡",
                RiskLevel.LOW: "🟢",
            }[finding.level]
            with st.expander(
                f"{icon} {finding.title} · {finding.level.value.upper()}", expanded=True
            ):
                st.write(finding.rationale)
                st.markdown("**Recommended checks**")
                for check in finding.recommended_checks:
                    st.markdown(f"- {check}")

    with impact_tab:
        if report.impact is None:
            st.info("Static impact information is unavailable for this run.")
        else:
            impact = report.impact
            st.caption(f"Indexed {impact.indexed_file_count} Python files at the candidate commit.")
            groups = (
                ("Changed modules", impact.changed_modules),
                ("Direct dependents", impact.direct_dependents),
                ("Transitive dependents", impact.transitive_dependents),
                ("Candidate tests", impact.candidate_tests),
            )
            for title, values in groups:
                st.markdown(f"**{title}**")
                if values:
                    st.markdown(
                        " ".join(f"<span class='rg-pill'>{value}</span>" for value in values),
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("None found")
            with st.expander("Impact-analysis boundaries"):
                for limitation in impact.limitations:
                    st.markdown(f"- {limitation}")

    with evidence_tab:
        st.caption("Every risk finding must point to immutable evidence from the candidate commit.")
        st.dataframe(
            [
                {
                    "evidence ID": item.id,
                    "kind": item.kind.value,
                    "location": item.locator,
                    "summary": item.summary,
                }
                for item in report.evidence
            ],
            hide_index=True,
            use_container_width=True,
        )

    with context_tab:
        if not report.retrieved_context:
            st.info("No repository context was selected for this comparison.")
        for item in report.retrieved_context:
            with st.expander(f"{item.path} · score {item.fusion_score:.4f}"):
                st.code(item.excerpt, language="python")

    with report_tab:
        payload = report_payload(report, source_label)
        serialized = json.dumps(payload, indent=2)
        st.download_button(
            "Download verified JSON report",
            data=serialized,
            file_name=f"{report.analysis_id}.json",
            mime="application/json",
            type="primary",
        )
        st.json(payload, expanded=False)
        with st.expander("Honest limitations"):
            for limitation in report.limitations:
                st.markdown(f"- {limitation}")


st.markdown("<div class='rg-kicker'>Evidence before confidence</div>", unsafe_allow_html=True)
st.markdown("<div class='rg-title'>ReleaseGuard</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='rg-subtitle'>Compare two versions of a codebase. See what changed, what depends "
    "on it, which tests matter, and whether the evidence supports releasing it.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Analyze a change")
    source_mode = st.radio(
        "Source",
        ("Built-in demo", "Public GitHub repository"),
        help="The hosted app cannot access private or local repositories.",
    )
    if source_mode == "Built-in demo":
        st.info(
            "A payment service expands refund permissions. ReleaseGuard traces the affected "
            "service, API, and tests."
        )
        base_ref = "baseline"
        head_ref = "candidate"
        repository_url = ""
    else:
        repository_url = st.text_input(
            "Public repository URL",
            placeholder="https://github.com/owner/repository",
        )
        base_ref = st.text_input("Base ref", value="main")
        head_ref = st.text_input("Candidate ref", placeholder="branch, tag, or commit SHA")
        st.caption("For safety and speed, only recent public GitHub history is imported.")

    analyze = st.button("Analyze release", type="primary", use_container_width=True)
    st.divider()
    st.caption("No OpenAI API. No hosted model. Analysis is deterministic and evidence-backed.")
    st.link_button(
        "View source on GitHub", "https://github.com/subtler/releaseguard", use_container_width=True
    )

if analyze:
    try:
        with st.spinner("Collecting immutable evidence and tracing impact…"):
            if source_mode == "Built-in demo":
                repository = demo_factory().create(workspace_root())
                source_label = "bundled://demo-payment-service"
            else:
                if not repository_url or not head_ref:
                    raise RepositoryAccessError(
                        "Provide both a public repository URL and candidate ref."
                    )
                imported = github_importer().import_repository(repository_url, workspace_root())
                repository = imported.path
                source_label = imported.canonical_url
            result = run_analysis(repository, base_ref, head_ref)
            st.session_state["releaseguard_report"] = result.model_dump(mode="json")
            st.session_state["releaseguard_source_label"] = source_label
    except RepositoryAccessError as exc:
        st.error(str(exc))
    except Exception:
        st.error(
            "Analysis could not complete. Check that both refs exist in the recent repository "
            "history."
        )

if "releaseguard_report" in st.session_state:
    render_report(
        ReadinessReport.model_validate(st.session_state["releaseguard_report"]),
        str(st.session_state["releaseguard_source_label"]),
    )
else:
    st.markdown("### Start with the built-in example")
    steps = st.columns(3)
    steps[0].markdown("**1 · Compare**\n\nSelect a baseline and candidate version.")
    steps[1].markdown("**2 · Trace**\n\nFollow dependencies to affected code and tests.")
    steps[2].markdown("**3 · Decide**\n\nReview an evidence-backed readiness result.")
