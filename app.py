"""Streamlit entry point for AI 폭염 도시처방."""

from __future__ import annotations

import logging

import pandas as pd
import pydeck as pdk
import streamlit as st

from src.analysis.district_allocation import allocate_facilities_by_priority
from src.config import CACHE_DIR, Settings
from src.data.http import DataSourceError, JsonCache
from src.data.kma_history import fetch_hottest_daegu_day
from src.pipeline import AnalysisArtifacts, run_analysis
from src.sgis_client import SGISClientError, load_daegu_heatmap_geojson
from src.ui.daegu_overview import merge_daegu_boundaries


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
st.set_page_config(page_title="AI 폭염 도시처방", page_icon="🌡️", layout="wide")
with st.sidebar:
    theme_mode = st.segmented_control(
        "화면 모드",
        options=["기본", "다크"],
        default="기본",
        help="밝은 화면과 어두운 화면을 전환합니다.",
    )

theme = {
    "기본": {
        "page": "#fffdf9", "surface": "#ffffff", "soft": "#fff7ed",
        "border": "#fed7aa", "text": "#292524", "muted": "#78716c",
        "shadow": "rgba(124,45,18,.08)",
    },
    "다크": {
        "page": "#11100f", "surface": "#1c1917", "soft": "#29211d",
        "border": "#7c2d12", "text": "#fafaf9", "muted": "#d6d3d1",
        "shadow": "rgba(0,0,0,.35)",
    },
}[theme_mode]

st.markdown(
    f"""
    <style>
    [data-testid="stAppViewContainer"] {{background:{theme['page']}; color:{theme['text']};}}
    [data-testid="stHeader"] {{background:transparent;}}
    [data-testid="stSidebar"] {{background:{theme['surface']}; border-right:1px solid {theme['border']};}}
    [data-testid="stAppViewContainer"] p,
    [data-testid="stAppViewContainer"] label,
    [data-testid="stAppViewContainer"] h1,
    [data-testid="stAppViewContainer"] h2,
    [data-testid="stAppViewContainer"] h3 {{color:{theme['text']};}}
    .block-container {{padding-top:1.5rem; padding-bottom:2rem; max-width:1400px;}}
    div[data-testid="stMetric"] {{background:{theme['soft']};border:1px solid {theme['border']};padding:12px;border-radius:12px;box-shadow:0 8px 24px {theme['shadow']};}}
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {{color:{theme['text']};}}
    .hero {{padding:1.2rem 1.4rem;border-radius:18px;background:linear-gradient(120deg,#7c2d12,#ea580c);color:white;margin-bottom:1rem;}}
    .hero h1 {{margin:0 0 .3rem 0!important;color:white!important;font-size:clamp(1.55rem,4vw,2rem);}}
    .hero p {{margin:0;color:white!important;opacity:.92;}}
    .policy-card {{border-left:5px solid #ea580c;background:{theme['soft']};padding:1rem 1.1rem;border-radius:8px;margin:.7rem 0;box-shadow:0 8px 24px {theme['shadow']};}}
    .policy-card small {{color:{theme['muted']};}}
    @media (max-width:900px) {{
      .block-container {{padding:1.1rem .9rem 2rem;}}
      [data-testid="stHorizontalBlock"] {{flex-wrap:wrap;gap:.75rem;}}
      [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{min-width:calc(50% - .75rem);flex:1 1 calc(50% - .75rem);}}
    }}
    @media (max-width:640px) {{
      .block-container {{padding:.75rem .55rem 1.5rem;}}
      .hero {{padding:1rem;border-radius:14px;}}
      [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{min-width:100%;flex:1 1 100%;}}
      div[data-testid="stMetric"] {{padding:10px;}}
      .policy-card {{padding:.85rem;overflow-wrap:anywhere;}}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3_600, show_spinner=False)
def cached_analysis(cache_schema_version: str) -> AnalysisArtifacts:
    return run_analysis(Settings.from_env())


@st.cache_data(ttl=21_600, show_spinner=False)
def cached_hottest_day(cache_schema_version: str) -> tuple[dict, str, str]:
    runtime_settings = Settings.from_env()
    return fetch_hottest_daegu_day(
        cache=JsonCache(CACHE_DIR),
        timeout=runtime_settings.api_timeout_seconds,
        surface_api_url=runtime_settings.kma_surface_api_url,
        auth_key=runtime_settings.kma_auth_key,
    )


@st.cache_data(ttl=21_600, show_spinner=False)
def cached_daegu_boundaries() -> tuple[dict | None, str, str | None]:
    try:
        return load_daegu_heatmap_geojson(), "SGIS 대구 행정동 실시간 경계", None
    except (SGISClientError, ValueError) as exc:
        return None, "저장된 대체 경계", str(exc)


st.markdown(
    '<section class="hero"><h1>🌡️ AI 폭염 도시처방</h1>'
    '<p>대구 구·군별 폭염 취약도와 실시간 기상 위험, 공공 무더위쉼터 현황을 한눈에 확인합니다.</p></section>',
    unsafe_allow_html=True,
)

settings = Settings.from_env()
with st.sidebar:
    st.header("히트맵 기준")
    heatmap_label = st.radio(
        "표시 지수",
        ["극한폭염 정책 우선순위", "사회·건강 취약도", "쉼터 수 부족도"],
        index=0,
    )
    st.header("시설 설치 시뮬레이션")
    unit_cost = st.number_input(
        "시설 1곳당 가상비용", min_value=1_000_000, max_value=100_000_000,
        value=settings.default_shelter_cost_krw, step=1_000_000,
    )
    budget = st.number_input(
        "총예산", min_value=0, max_value=2_000_000_000,
        value=settings.default_shelter_cost_krw * 5, step=1_000_000,
    )
    max_facilities = st.number_input(
        "최대 설치 시설 수", min_value=0, max_value=100, value=5, step=1,
    )

heatmap_metric = {
    "극한폭염 정책 우선순위": "policy",
    "사회·건강 취약도": "vulnerability",
    "쉼터 수 부족도": "shelter_gap",
}[heatmap_label]

try:
    with st.spinner("대구 행정동과 공공데이터를 불러오는 중입니다..."):
        artifacts = cached_analysis("citywide-shelters-v2")
except Exception as exc:
    st.error(f"분석 데이터를 준비하지 못했습니다: {exc}")
    st.info("`python scripts/build_dataset.py`와 `python scripts/validate_data.py`로 원인을 확인하세요.")
    st.stop()

if artifacts.metadata["is_demo"]:
    st.warning(
        "데이터 모드: **실제 시설 + DEMO SAMPLE 인구·경계·동별기상** — "
        "지도상의 행정동 격자·인구·기상은 시연용이며 실제 행정통계가 아닙니다."
    )
else:
    st.success("데이터 모드: 실제 공공데이터")
weather_context = artifacts.metadata.get("weather_context") or {}
weather_period = weather_context.get("period")
st.caption(
    f"기준시점: {artifacts.metadata['analysis_timestamp']} · "
    f"기상 관측: {weather_period or 'DEMO/참고자료'}"
)
if artifacts.metadata.get("shelter_warning"):
    st.warning(f"쉼터 API 대신 기존 로컬 자료를 사용 중입니다: {artifacts.metadata['shelter_warning']}")
if artifacts.metadata.get("weather_warning"):
    st.info(f"기상청 최신 관측은 아직 연결 대기 중입니다: {artifacts.metadata['weather_warning']}")

hottest_day = None
hottest_warning = None
if settings.kma_auth_key:
    try:
        hottest_day, hottest_mode, hottest_fetched_at = cached_hottest_day("weather-nuri-v1")
    except DataSourceError as exc:
        hottest_warning = str(exc)
scenario_heat_score = (
    float(hottest_day["heat_hazard_score"])
    if hottest_day
    else weather_context.get("heat_hazard_score")
)

weather_columns = st.columns(3)
weather_columns[0].metric(
    "현재 대구 기온",
    f"{weather_context.get('temperature_c', 0):.1f}°C" if weather_context.get("temperature_c") is not None else "-",
)
weather_columns[1].metric(
    "관측기간 중 가장 더운 날",
    hottest_day.get("date", "-") if hottest_day else "조회 실패",
)
weather_columns[2].metric(
    "당일 최고기온",
    f"{hottest_day['maximum_temperature_c']:.1f}°C" if hottest_day else "-",
    f"극한폭염 위험 {scenario_heat_score:.1f}/100" if scenario_heat_score is not None else None,
)
if hottest_warning:
    st.warning(hottest_warning)

st.subheader("대구 전체 행정동 현황")
st.caption(
    "기존 SGIS 행정경계를 기준으로 모든 행정동을 선택할 수 있습니다. "
    "9개 구·군의 팀 취약도와 기상청 실시간 폭염 위험, 공공 쉼터 현황을 함께 표시합니다."
)
raw_daegu_boundaries, overview_source, overview_warning = cached_daegu_boundaries()
overview_geojson = merge_daegu_boundaries(
    raw_daegu_boundaries,
    artifacts.areas,
    artifacts.metadata.get("team_vulnerability"),
    getattr(artifacts, "citywide_shelters", None)
    if artifacts.metadata.get("shelter_source_mode") in {"live", "cache"}
    else None,
    scenario_heat_score,
    include_dong_detail=False,
    heatmap_metric=heatmap_metric,
)
selected_overview_region = st.session_state.get("overview_selected_region")
for feature in overview_geojson.get("features", []):
    properties = feature.get("properties") or {}
    if properties.get("region") == selected_overview_region:
        properties["line_color"] = [255, 255, 255, 255]
        properties["line_width"] = 5
    else:
        properties["line_width"] = 1

overview_map_column, overview_info_column = st.columns([2.2, 1])
with overview_map_column:
    overview_layer = pdk.Layer(
        "GeoJsonLayer",
        id="daegu-administrative-boundaries",
        data=overview_geojson,
        pickable=True,
        auto_highlight=True,
        filled=True,
        stroked=True,
        opacity=0.82,
        get_fill_color="properties.fill_color",
        get_line_color="properties.line_color",
        get_line_width="properties.line_width",
        line_width_min_pixels=1,
    )
    overview_event = st.pydeck_chart(
        pdk.Deck(
            map_style=None,
            initial_view_state=pdk.ViewState(latitude=35.87, longitude=128.60, zoom=10.55),
            layers=[overview_layer],
            tooltip={
                "html": (
                    "<b>{region}</b><br/>행정동 코드 {adm_cd}<br/>"
                    "{analysis_status}<br/>{map_metric_label} {map_score_display}<br/>"
                    "행정동 쉼터 {shelter_display}"
                ),
                "style": {"backgroundColor": "#292524", "color": "white"},
            },
        ),
        height=460,
        width="stretch",
        on_select="rerun",
        selection_mode="single-object",
        key="daegu_overview_map",
    )
    selected_objects = overview_event.selection.get("objects", {}).get(
        "daegu-administrative-boundaries", []
    )
    if selected_objects:
        selected_object = selected_objects[0]
        clicked_properties = selected_object.get("properties", selected_object)
        clicked_region = clicked_properties.get("region")
        if clicked_region:
            st.session_state["overview_selected_region"] = clicked_region
            st.session_state["overview_selected_properties"] = clicked_properties

with overview_info_column:
    overview_properties = st.session_state.get("overview_selected_properties")
    if overview_properties:
        st.markdown(f"### {overview_properties['region']}")
        st.caption(f"행정동 코드: {overview_properties['adm_cd']}")
        if overview_properties.get("has_district_analysis"):
            st.success(overview_properties["analysis_status"])
            st.metric("극한폭염 정책 우선순위", overview_properties["priority_display"])
            st.metric("사회·건강 취약도", overview_properties.get("vulnerability_display", "-"))
            st.metric("등급", overview_properties.get("district_grade", "-"))
            st.metric("행정동 공공 API 쉼터", overview_properties.get("shelter_display", "데이터 연결 필요"))
            if not overview_properties.get("shelter_count_available"):
                st.warning("배포 환경에서 무더위쉼터 API가 연결되지 않아 행정동별 시설 수를 표시할 수 없습니다.")
            st.caption(
                f"고령인구 비율 {overview_properties.get('elderly_ratio', 0):.1f}% · "
                f"온열질환자 {overview_properties.get('heat_illness_count', 0):.0f}명 · "
                "취약도는 구·군 단위로 동일하지만 쉼터 수는 선택한 행정동 경계 기준입니다."
            )
        else:
            st.info("현재는 행정경계 정보만 연결된 지역입니다.")
            st.write("표시 가능한 정보")
            st.write("- 행정동명")
            st.write("- 공식 행정동 코드")
            st.write("- 실제 행정경계")
            st.warning("취약도·인구·쉼터 분석은 해당 구의 원천데이터 연결 후 표시됩니다.")
    else:
        st.info("지도에서 행정동을 클릭하면 해당 지역 정보를 표시합니다.")
    st.caption(f"경계 출처: {overview_source}")
    if overview_warning:
        st.warning(f"SGIS 실시간 경계를 불러오지 못해 저장된 대체 경계를 표시합니다: {overview_warning}")

source_mode = artifacts.metadata.get("shelter_source_mode")
source_label = {"live": "실시간 API", "cache": "마지막 정상 캐시", "local_csv": "로컬 대체 자료"}.get(
    source_mode, str(source_mode or "알 수 없음")
)
st.caption(
    f"쉼터 데이터: {source_label} · 대구 전체 {artifacts.metadata.get('citywide_shelter_count', 0):,}곳 · "
    f"수집시각 {artifacts.metadata.get('shelter_fetched_at') or '-'}"
)

st.subheader("예산·시설 설치 대시보드")
district_rows: dict[str, dict] = {}
for feature in overview_geojson.get("features", []):
    properties = feature.get("properties") or {}
    district_name = properties.get("district_name")
    if not district_name:
        continue
    row = district_rows.setdefault(
        district_name,
        {
            "region_name": district_name,
            "priority_score": float(properties.get("priority_score") or 0),
            "existing_shelters": 0,
        },
    )
    if properties.get("shelter_count") is not None:
        row["existing_shelters"] += int(properties["shelter_count"])

allocation = allocate_facilities_by_priority(
    list(district_rows.values()),
    budget=int(budget),
    unit_cost=int(unit_cost),
    max_facilities=int(max_facilities),
)
allocation_columns = st.columns(3)
allocation_columns[0].metric("설치 가능 시설", f"{int(allocation['new_facilities'].sum()) if not allocation.empty else 0}곳")
allocation_columns[1].metric("예상 사용 예산", f"{int(allocation['cost'].sum()) if not allocation.empty else 0:,.0f}원")
allocation_columns[2].metric("잔여 예산", f"{int(budget - allocation['cost'].sum()) if not allocation.empty else int(budget):,.0f}원")
if allocation.empty:
    st.info("예산과 최대 설치 수를 늘리면 구·군별 배분안을 표시합니다.")
else:
    display_allocation = allocation.rename(
        columns={
            "region_name": "구·군",
            "priority_score": "극한폭염 우선순위",
            "existing_shelters": "기존 쉼터",
            "new_facilities": "신규 배분",
            "cost": "예상 비용",
        }
    )
    st.dataframe(
        display_allocation.style.format({"극한폭염 우선순위": "{:.1f}", "예상 비용": "{:,.0f}원"}),
        hide_index=True,
        width="stretch",
    )
    st.caption("현재 단계는 구·군 우선순위 기반 예산 배분안이며, 정확한 설치 지점은 후보지·도로망·토지규제 데이터가 추가돼야 확정할 수 있습니다.")

with st.expander("분석 기준과 데이터 출처"):
    st.markdown(
        "구·군 정책 우선순위는 팀 사회·건강 취약도 65%와 기상청 관측기간 최고 폭염 위험 35%를 결합합니다. "
        "구·군 결과이므로 같은 구·군의 행정동에는 동일한 점수가 표시됩니다."
    )
    st.json(weather_context, expanded=False)
    if hottest_day:
        st.json(hottest_day, expanded=False)
