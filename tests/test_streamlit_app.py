"""End-to-end smoke test for the recruiter-facing Streamlit interface."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_demo_renders_verified_report() -> None:
    entrypoint = Path(__file__).parents[1] / "streamlit_app.py"
    app = AppTest.from_file(entrypoint, default_timeout=60).run()

    assert not app.exception
    analyze_button = next(button for button in app.button if button.label == "Analyze release")
    analyze_button.click().run()

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Changed files"] == "2"
    assert metrics["Risk findings"] == "1"
    assert metrics["Candidate tests"] == "1"
