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
        ["취약도", "쉼터 300m 커버 범위"],
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
    "취약도": "vulnerability",
    "쉼터 300m 커버 범위": "shelter_coverage",
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
# if artifacts.metadata.get("shelter_warning"):
#     warning_msg = artifacts.metadata['shelter_warning']
#     if "time out" in warning_msg.lower() or "connection" in warning_msg.lower() or "retries" in warning_msg.lower() or "timed out" in warning_msg.lower():
#         short_msg = "공공데이터 센터 통신 지연으로 인해 안정성을 위해 준비된 대구시 안전 쉼터 로컬 데이터(1,127곳)로 즉시 대체 구동합니다. (정상 작동)"
#     else:
#         short_msg = warning_msg
#     st.warning(f"ℹ️ {short_msg}")
# if artifacts.metadata.get("weather_warning"):
#     warning_msg = artifacts.metadata['weather_warning']
#     if "time out" in warning_msg.lower() or "connection" in warning_msg.lower() or "retries" in warning_msg.lower() or "timed out" in warning_msg.lower():
#         short_msg = "기상청 서버 통신 지연으로 인해 대구지역 기상 관측 참고 스냅샷 데이터(27.2°C, 습도 51%)로 즉시 대체 구동합니다. (정상 작동)"
#     else:
#         short_msg = warning_msg
#     st.info(f"ℹ️ {short_msg}")

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
    # 쉼터 데이터를 순수 pandas DataFrame으로 변환 (geometry 직렬화 에러 방지)
    shelters_gdf = artifacts.citywide_shelters.copy()
    if shelters_gdf.crs != "EPSG:4326":
        shelters_gdf = shelters_gdf.to_crs("EPSG:4326")
    
    shelters_df = pd.DataFrame(shelters_gdf)
    shelters_df["lon"] = shelters_gdf.geometry.x
    shelters_df["lat"] = shelters_gdf.geometry.y
    if "geometry" in shelters_df.columns:
        shelters_df = shelters_df.drop(columns="geometry")
    
    # 툴팁 필드 일치 (행정동 툴팁과 key 통일)
    shelters_df["region"] = shelters_df["name"]
    shelters_df["adm_cd"] = shelters_df["address"]
    shelters_df["analysis_status"] = "무더위쉼터 (공공 API)"
    shelters_df["map_metric_label"] = "수용인원:"
    shelters_df["map_score_display"] = shelters_df["capacity"].astype(int).astype(str) + "명"
    shelters_df["shelter_display"] = ""
    
    # 1. 무더위 쉼터 위치 포인트 레이어 (순수 DataFrame 기반)
    shelter_layer = pdk.Layer(
        "ScatterplotLayer",
        id="daegu-shelter-locations",
        data=shelters_df,
        get_position=["lon", "lat"],
        get_color=[234, 88, 12, 230],  # 오렌지색
        get_radius=80,
        radius_min_pixels=4,           # 줌아웃 시 최소 4px 크기 유지
        radius_max_pixels=12,
        pickable=True,
        auto_highlight=True,
    )

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
    
    # 2. 쉼터 300m 커버 버퍼 레이어 (표시 지수에서 '쉼터 300m 커버 범위' 선택 시에만 렌더링)
    layers = [overview_layer, shelter_layer]
    if heatmap_metric == "shelter_coverage":
        buffer_layer = pdk.Layer(
            "ScatterplotLayer",
            id="daegu-shelter-buffers",
            data=shelters_df,
            get_position=["lon", "lat"],
            get_radius=300,                     # 반경 300m 버퍼
            get_fill_color=[34, 197, 94, 60],   # 연한 연두색 반투명
            get_line_color=[34, 197, 94, 180],  # 연두색 선
            stroked=True,
            filled=True,
            pickable=False,                     # 툴팁 방해 방지
        )
        # 레이어 겹침 우선순위: 배경 행정동 -> 300m 버퍼 원 -> 쉼터 점 마커
        layers = [overview_layer, buffer_layer, shelter_layer]

    overview_event = st.pydeck_chart(
        pdk.Deck(
            map_style=None,
            initial_view_state=pdk.ViewState(latitude=35.87, longitude=128.60, zoom=10.55),
            layers=layers,
            tooltip={
                "html": (
                    "<b>{region}</b><br/>행정동 코드 {adm_cd}<br/>"
                    "{analysis_status}<br/>"
                    "<b>동별 쉼터 접근성:</b> {shelter_accessibility_display}<br/>"
                    "{map_metric_label} {map_score_display}<br/>"
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
        st.success(overview_properties.get("analysis_status", "분석 연결 완료"))
        st.metric("종합 취약도", overview_properties.get("priority_display", "-"))
        st.metric("동별 쉼터 접근성", overview_properties.get("shelter_accessibility_display", "-"))
        st.metric("행정동 고령인구", overview_properties.get("elderly_display", "데이터 연결 필요"))
        st.metric("등급", overview_properties.get("district_grade", "-"))
        st.metric("행정동 공공 API 쉼터", overview_properties.get("shelter_display", "데이터 연결 필요"))
        if not overview_properties.get("shelter_count_available"):
            st.warning("배포 환경에서 무더위쉼터 API가 연결되지 않아 행정동별 시설 수를 표시할 수 없습니다.")
        st.caption(
            f"고령인구 비율 {overview_properties.get('elderly_ratio', 0):.1f}% · "
            f"온열질환자 {overview_properties.get('heat_illness_count', 0):.0f}명 · "
            "취약도는 사회·기상·쉼터 부족을 종합한 실시간 취약도이며, 쉼터 접근성은 고령인구 대비 쉼터 공급 능력을 대구시 내에서 상대 비교하여 정규화(Min-Max)한 점수입니다."
        )
        
        # AI 버튼 부착
        st.markdown("---")
        st.subheader("🤖 AI 폭염 도시처방 브리핑")
        
        if st.button("AI 폭염 대응 추천 받기", key="run_ai_analysis_btn"):
            with st.spinner("AI가 행정동별 폭염 취약성과 쉼터 분포를 바탕으로 최적의 대책을 수립 중입니다..."):
                try:
                    from src.alan_client import AlanPolicyClient
                    client = AlanPolicyClient()
                    
                    reg_name = overview_properties['region']
                    coverage_str = str(overview_properties.get("coverage_ratio_display", "50.0%")).replace("%", "")
                    try:
                        coverage_rate = float(coverage_str)
                    except ValueError:
                        coverage_rate = 50.0
                        
                    elderly_val = int(overview_properties.get("elderly_population") or 0)
                    vul_score = float(overview_properties.get("vulnerability_score") or 50.0)
                    
                    candidates = [
                        {
                            "name": f"{reg_name} 행정복지센터 부근 보행축",
                            "facility_type": "스마트쉼터",
                            "estimated_cost": 28_000_000,
                            "additional_covered_population": int(elderly_val * 0.15),
                            "reason": "보행 약자 통행량이 많으나 그늘이 부족한 지역 중심 가로"
                        },
                        {
                            "name": f"{reg_name} 인근 근린공원 진입광장",
                            "facility_type": "그늘막",
                            "estimated_cost": 12_000_000,
                            "additional_covered_population": int(elderly_val * 0.08),
                            "reason": "쉼터 접근 사각지대에 인접하여 고령층의 야외 보행 중 대피가 필요한 지점"
                        }
                    ]
                    
                    partial = {
                        "region": reg_name,
                        "vulnerability": {
                            "vulnerability_score": vul_score,
                            "vulnerability_grade": "위험" if vul_score >= 80 else "주의" if vul_score >= 50 else "보통",
                            "main_causes": [
                                {"name": "고령인구 비율", "value": float(overview_properties.get("elderly_ratio", 0.0)), "contribution": 0.35},
                                {"name": "열지수 및 기상 위험", "value": float(overview_properties.get("heat_score", 50.0)), "contribution": 0.30},
                                {"name": "쉼터 접근 사각지대", "value": 100.0 - coverage_rate, "contribution": 0.20},
                            ],
                            "vulnerable_population": elderly_val
                        },
                        "accessibility": {
                            "facility_score": float(overview_properties.get("access_score", 50.0)),
                            "nearest_shelter_distance_m": float(str(overview_properties.get("nearest_shelter_distance_display", "500")).replace("m", "").replace("쉼터 없음", "999") or 500.0),
                            "underserved_population": int(elderly_val * (1.0 - coverage_rate / 100.0)),
                            "coverage_rate": coverage_rate,
                            "blind_spot": coverage_rate < 80.0,
                            "blind_spot_count": 2,
                            "existing_facilities": [],
                            "map_center": {"latitude": 35.85, "longitude": 128.60}
                        },
                        "optimization": {
                            "budget": int(budget),
                            "max_facilities": int(max_facilities),
                            "total_estimated_cost": 40_000_000,
                            "recommended_locations": candidates,
                            "before": {
                                "coverage_rate": coverage_rate,
                                "underserved_population": int(elderly_val * (1.0 - coverage_rate / 100.0)),
                                "blind_spot_count": 2
                            },
                            "after": {
                                "coverage_rate": min(100.0, coverage_rate + 15.0),
                                "underserved_population": max(0, int(elderly_val * (0.85 - coverage_rate / 100.0))),
                                "blind_spot_count": 0
                            }
                        }
                    }
                    
                    ai_result_brief = client.recommend_policy(partial)
                    st.session_state["ai_briefing_result"] = {
                        "status": "success",
                        "region": reg_name,
                        "policy_recommendation": ai_result_brief
                    }
                except Exception as e:
                    st.error(f"AI 호출 오류: {e}")
                    
        ai_briefing = st.session_state.get("ai_briefing_result")
        if ai_briefing and ai_briefing.get("region") == overview_properties['region']:
            policy = ai_briefing.get("policy_recommendation", {})
            st.success("✅ AI 처방 브리핑 생성 완료")
            st.markdown(f"**📝 종합 상황 요약:**\n{policy.get('summary', '-')}")
            st.markdown(f"**🚨 대응 조치 우선순위:** `{policy.get('priority_level', '보통')}`")
            
            st.markdown("**💡 추천 대응 정책:**")
            for idx, p_item in enumerate(policy.get("recommended_policies", [])):
                st.markdown(f"**{idx+1}. {p_item.get('policy_name', '추천 정책')}** (설치 예정지: `{p_item.get('target_location', '-')}`)")
                st.markdown(f"- *추천 사유:* {p_item.get('reason', '-')}")
                st.markdown(f"- *기대 효과:* {p_item.get('expected_effect', '-')}")
                if p_item.get("action_plan"):
                    st.markdown("- *구체적 실행 방안:*")
                    for plan in p_item.get("action_plan", []):
                        st.markdown(f"  - {plan}")
            
            if policy.get("limitations"):
                st.markdown("**⚠️ 활용 상의 한계점:**")
                for lim in policy.get("limitations", []):
                    st.markdown(f"- {lim}")
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
