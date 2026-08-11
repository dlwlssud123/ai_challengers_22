from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_renders_and_runs_spatial_prescription():
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(app_path, default_timeout=30).run()
    assert not app.exception
    assert any("AI 폭염 도시처방" in title.value for title in app.markdown)
    assert len(app.button) >= 1

    app.button[0].click().run(timeout=60)
    assert not app.exception
    assert any("신규 쉼터 공간 처방 결과" in heading.value for heading in app.subheader)
