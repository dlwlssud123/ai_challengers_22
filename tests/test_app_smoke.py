from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_citywide_dashboard_renders_without_suseong_detail(monkeypatch):
    monkeypatch.setenv("SGIS_CONSUMER_KEY", "")
    monkeypatch.setenv("SGIS_CONSUMER_SECRET", "")
    monkeypatch.setenv("SAFETY_DATA_SERVICE_KEY", "")
    monkeypatch.setenv("KMA_AUTH_KEY", "")
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(app_path, default_timeout=30).run()
    assert not app.exception
    assert any("AI 폭염 도시처방" in title.value for title in app.markdown)
    assert any("대구 전체 행정동 현황" in heading.value for heading in app.subheader)
    assert not any("수성구 상세 분석" in heading.value for heading in app.subheader)
