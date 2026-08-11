"""Small Streamlit formatting and presentation helpers."""

from __future__ import annotations

from typing import Any

import streamlit as st


def format_people(value: float) -> str:
    return f"{value:,.0f}명"


def format_rate(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_before_after(before: dict[str, float], after: dict[str, float]) -> None:
    """Render the three most decision-relevant before/after KPIs."""

    columns = st.columns(3)
    columns[0].metric(
        "추정 보호 커버리지",
        format_rate(after["coverage_rate"]),
        f"{(after['coverage_rate'] - before['coverage_rate']) * 100:+.1f}%p",
    )
    columns[1].metric(
        "추정 접근 취약 고령인구",
        format_people(after["estimated_uncovered_elderly"]),
        format_people(after["estimated_uncovered_elderly"] - before["estimated_uncovered_elderly"]),
        delta_color="inverse",
    )
    columns[2].metric(
        "고위험 사각지대",
        f"{after['blind_spot_count']:.0f}개",
        f"{after['blind_spot_count'] - before['blind_spot_count']:+.0f}개",
        delta_color="inverse",
    )


def render_policy_brief(brief: Any, source: str) -> None:
    st.caption(f"브리핑 생성 방식: {source}")
    st.markdown(brief.executive_summary)
    st.markdown("**우선 검토 지역**")
    for item in brief.priority_areas:
        st.markdown(f"- {item}")
    st.markdown("**권고 조치**")
    for item in brief.recommended_actions:
        st.markdown(f"- {item}")
    st.markdown("**기대 공간효과**")
    st.markdown(brief.expected_spatial_effect)
    st.markdown("**한계**")
    for item in brief.limitations:
        st.markdown(f"- {item}")


