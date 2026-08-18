"""Minimal Streamlit client for the finalized clusters API contract.

It is intentionally a hand-off screen rather than the final visual mock-up:
the web team can replace this view while keeping the JSON contract unchanged.
"""

from __future__ import annotations

import json
import os

import pandas as pd
import requests
import streamlit as st


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(page_title="폭염 취약 군집 분석", layout="wide")
st.title("대구광역시 폭염 취약 군집 분석")
st.caption("DBSCAN + SHAP · 전체 행정동 스냅샷 분석")

with st.sidebar:
    st.subheader("연결 상태")
    st.code(BACKEND_URL)
    if st.button("API 상태 확인"):
        try:
            response = requests.get(f"{BACKEND_URL}/health", timeout=5)
            response.raise_for_status()
            st.success("Backend 연결됨")
        except requests.RequestException as exc:
            st.error(f"연결 실패: {exc}")

st.info(
    "시설 추가 시뮬레이션 후에는 변경된 접근성·위험도까지 반영한 모든 행정동 records를 다시 전송하세요. "
    "DBSCAN은 개별 행정동 한 건을 predict하지 않습니다."
)

template = {
    "records": [
        {
            "dong_code": f"27110{index:05d}",
            "district_name": "예시구",
            "dong_name": f"예시동{index + 1}",
            "features": {
                "heat_exposure": 35 + (index // 6) * 35 + index % 3,
                "elderly_concentration": 12 + (index // 6) * 14 + index % 2,
                "green_deficit": 28 + (index // 6) * 45 + index % 3,
                "access_deficit": 20 + (index // 6) * 42 + index % 2,
                "future_heat_illness_risk": 30 + (index // 6) * 38 + index % 3,
                "response_facility_shortage": 25 + (index // 6) * 44 + index % 2,
            },
        }
        for index in range(12)
    ]
}
payload_text = st.text_area(
    "분석 요청 JSON (최소 12개 행정동)",
    value=json.dumps(template, ensure_ascii=False, indent=2),
    height=320,
)

if st.button("군집 분석 실행", type="primary"):
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        st.error(f"JSON 형식 오류: {exc}")
    else:
        with st.spinner("DBSCAN 파라미터 탐색과 SHAP 설명을 계산 중입니다..."):
            try:
                response = requests.post(
                    f"{BACKEND_URL}/api/v1/clusters", json=payload, timeout=120
                )
                response.raise_for_status()
                st.session_state["cluster_result"] = response.json()
            except requests.HTTPError:
                detail = response.json().get("detail", response.text)
                st.error(f"분석 요청 실패: {detail}")
            except requests.RequestException as exc:
                st.error(f"Backend 통신 실패: {exc}")

result = st.session_state.get("cluster_result")
if result:
    metadata = result["metadata"]
    dbscan = metadata["dbscan"]
    a, b, c, d = st.columns(4)
    a.metric("군집 수", dbscan["cluster_count_excluding_noise"])
    b.metric("노이즈 비율", f"{dbscan['noise_ratio']:.1%}")
    c.metric("Silhouette", f"{dbscan['silhouette_score']:.3f}")
    d.metric("Macro-F1", f"{metadata['surrogate_validation']['macro_f1']:.3f}")

    left, right = st.columns((1, 2))
    with left:
        st.subheader("전역 SHAP 중요도")
        importance = pd.DataFrame(result["global_feature_importance"])
        st.bar_chart(importance.set_index("label")["mean_abs_shap"])
        st.subheader("해석 주의")
        for warning in metadata["warnings"]:
            st.caption(f"• {warning}")
    with right:
        st.subheader("행정동별 시설 추천")
        assignments = pd.DataFrame(result["assignments"])
        st.dataframe(
            assignments[
                [
                    "global_installation_priority",
                    "district_name",
                    "dong_name",
                    "cluster_name",
                    "main_causes",
                    "recommended_facilities",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("군집 프로파일")
    st.json(result["clusters"])
