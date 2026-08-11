"""Streamlit entry point for AI 폭염 도시처방."""

from __future__ import annotations

from html import escape
import logging

import pandas as pd
import pydeck as pdk
import streamlit as st
from streamlit_folium import st_folium

from src.analysis.accessibility import total_coverage_metrics
from src.analysis.optimizer import optimize_candidates
from src.analysis.simulation import SimulationResult, simulate_installation
from src.config import Settings
from src.pipeline import AnalysisArtifacts, run_analysis
from src.sgis_client import SGISClientError, load_daegu_heatmap_geojson
from src.spatial_policy import build_policy_payload, recommend_spatial_policy
from src.ui.components import format_people, format_rate, render_before_after
from src.ui.daegu_overview import merge_daegu_boundaries
from src.ui.map import build_map, nearest_area_name


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
    iframe[title="streamlit_folium.st_folium"] {{border-radius:14px;}}
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
      iframe[title="streamlit_folium.st_folium"] {{max-height:70vh;}}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3_600, show_spinner=False)
def cached_analysis(radius_m: int, threshold: float) -> AnalysisArtifacts:
    return run_analysis(Settings.from_env(), access_radius_m=radius_m, risk_threshold=threshold)


@st.cache_data(ttl=21_600, show_spinner=False)
def cached_daegu_boundaries() -> tuple[dict | None, str, str | None]:
    try:
        return load_daegu_heatmap_geojson(), "SGIS 대구 행정동 실시간 경계", None
    except (SGISClientError, ValueError) as exc:
        return None, "수성구 분석 스냅샷 경계", str(exc)


settings = Settings.from_env()
st.markdown(
    '<section class="hero"><h1>🌡️ AI 폭염 도시처방</h1>'
    '<p>취약지역과 대응시설 사각지대를 진단하고, 한정된 예산 안에서 신규 쉼터 후보를 추천합니다.</p></section>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("분석 조건")
    st.text_input("SGIS 인구 기준연도", value=str(settings.analysis_year), disabled=True)
    access_radius = st.select_slider("쉼터 접근반경", options=[300, 500, 700], value=500, format_func=lambda v: f"{v}m")
    threshold = st.slider("정책 우선순위 임계값", 0, 100, 60, 5)
    scenario_cost = st.number_input(
        "공간 후보지역 기본비용 (가상)",
        min_value=1_000_000,
        max_value=100_000_000,
        value=settings.default_shelter_cost_krw,
        step=1_000_000,
        help="실제 설치비가 아닌 MVP 시나리오 가상비용입니다.",
    )
    budget = st.number_input(
        "총예산",
        min_value=0,
        max_value=1_000_000_000,
        value=settings.default_shelter_cost_krw * 3,
        step=1_000_000,
    )
    max_facilities = st.number_input(
        "최대 설치 시설 수",
        min_value=0,
        max_value=20,
        value=3,
        step=1,
    )
    execute = st.button("AI 도시처방 실행", type="primary", width="stretch")
    if execute:
        st.session_state["optimization_enabled"] = True

try:
    with st.spinner("GIS 접근권역과 사각지대를 계산하는 중입니다..."):
        artifacts = cached_analysis(int(access_radius), float(threshold))
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
    if "DEMO" in str(artifacts.metadata["candidate_mode"]):
        st.warning("신규 후보지는 실제 설치 확정 시설이 아닌 공간 분석용 DEMO입니다.")
weather_context = artifacts.metadata.get("weather_context") or {}
weather_period = weather_context.get("period")
st.caption(
    f"기준시점: {artifacts.metadata['analysis_timestamp']} · "
    f"기상 관측: {weather_period or 'DEMO/참고자료'} · 후보 모드: {artifacts.metadata['candidate_mode']}"
)
if artifacts.metadata.get("shelter_warning"):
    st.warning(f"쉼터 API 대신 기존 로컬 자료를 사용 중입니다: {artifacts.metadata['shelter_warning']}")
if artifacts.metadata.get("weather_warning"):
    st.info(f"기상청 최신 관측은 아직 연결 대기 중입니다: {artifacts.metadata['weather_warning']}")

st.subheader("대구 전체 행정동 현황")
st.caption(
    "기존 SGIS 행정경계를 기준으로 모든 행정동을 선택할 수 있습니다. "
    "9개 구·군에는 팀 취약도 분석을, 수성구 23개 행정동에는 상세 공간분석을 연결했습니다."
)
raw_daegu_boundaries, overview_source, overview_warning = cached_daegu_boundaries()
overview_geojson = merge_daegu_boundaries(
    raw_daegu_boundaries,
    artifacts.areas,
    artifacts.metadata.get("team_vulnerability"),
    artifacts.metadata.get("district_shelter_counts"),
    weather_context.get("heat_hazard_score"),
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
                    "{analysis_status}<br/>정책 우선순위 {priority_display}"
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
        if clicked_properties.get("has_analysis") and clicked_properties.get("adm_name"):
            st.session_state["selected_adm_name"] = clicked_properties["adm_name"]

with overview_info_column:
    overview_properties = st.session_state.get("overview_selected_properties")
    if overview_properties:
        st.markdown(f"### {overview_properties['region']}")
        st.caption(f"행정동 코드: {overview_properties['adm_cd']}")
        if overview_properties.get("has_analysis"):
            st.success("수성구 상세 분석 데이터가 연결된 지역입니다.")
            st.metric("정책 우선순위", overview_properties["priority_display"])
            st.metric("65세 이상 인구", overview_properties["elderly_display"])
            st.caption("아래 수성구 상세지도도 같은 행정동으로 선택됩니다.")
        elif overview_properties.get("has_district_analysis"):
            st.success(overview_properties["analysis_status"])
            st.metric("실시간 정책 우선순위", overview_properties["priority_display"])
            st.metric("사회·건강 취약도", overview_properties.get("vulnerability_display", "-"))
            st.metric("등급", overview_properties.get("district_grade", "-"))
            st.metric("공공 API 쉼터", f"{overview_properties.get('shelter_count', 0):,}곳")
            st.caption(
                f"고령인구 비율 {overview_properties.get('elderly_ratio', 0):.1f}% · "
                f"온열질환자 {overview_properties.get('heat_illness_count', 0):.0f}명 · "
                "현재 구·군 단위 결과이므로 같은 구의 행정동은 동일 점수로 표시됩니다."
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
        st.warning(f"SGIS 실시간 경계를 불러오지 못해 저장된 수성구 경계를 표시합니다: {overview_warning}")

st.divider()
st.subheader("수성구 상세 분석")

before_metrics = total_coverage_metrics(artifacts.areas)
top_area = artifacts.areas.nlargest(1, "priority_score").iloc[0]
kpi_columns = st.columns(4)
kpi_columns[0].metric("폭염 대응 우선지역", str(top_area["adm_name"]), f"{top_area['priority_score']:.1f}/100")
kpi_columns[1].metric("추정 접근 취약 고령인구", format_people(before_metrics["estimated_uncovered_elderly"]))
kpi_columns[2].metric("현재 추정 쉼터 커버리지", format_rate(before_metrics["coverage_rate"]))
kpi_columns[3].metric("기존 쉼터", f"{len(artifacts.shelters):,}곳")

scenario_candidates = artifacts.candidates.copy()
demo_mask = scenario_candidates["facility_type"].astype(str).str.contains("DEMO", na=False)
scenario_candidates.loc[demo_mask, "cost"] = float(scenario_cost)
simulation: SimulationResult | None = None
optimization = None
if st.session_state.get("optimization_enabled"):
    with st.spinner("예산 제약 최대커버리지 조합을 계산하는 중입니다..."):
        optimization = optimize_candidates(
            scenario_candidates,
            artifacts.blindspots,
            budget=float(budget),
            radius_m=float(access_radius),
            existing_shelters=artifacts.shelters,
            max_facilities=int(max_facilities),
        )
        simulation = simulate_installation(
            artifacts.areas,
            artifacts.shelters,
            scenario_candidates,
            artifacts.blindspots,
            optimization,
            radius_m=float(access_radius),
        )

st.subheader("위험 진단과 공간 처방")
map_column, detail_column = st.columns([2.2, 1])
with map_column:
    fmap = build_map(
        artifacts.areas,
        artifacts.shelters,
        artifacts.blindspots,
        radius_m=float(access_radius),
        selected_candidates=simulation.selected_candidates if simulation else None,
        after_shelters=simulation.after_shelters if simulation else None,
        dark_mode=theme_mode == "다크",
    )
    map_state = st_folium(
        fmap,
        height=580,
        use_container_width=True,
        returned_objects=["last_object_clicked"],
        key=f"heat-map-{access_radius}-{threshold}-{bool(simulation)}",
    )
    clicked = map_state.get("last_object_clicked") if map_state else None
    if clicked:
        clicked_name = nearest_area_name(
            artifacts.areas, float(clicked["lat"]), float(clicked["lng"])
        )
        if clicked_name:
            st.session_state["selected_adm_name"] = clicked_name

with detail_column:
    names = artifacts.areas.sort_values("priority_score", ascending=False)["adm_name"].astype(str).tolist()
    selected_default = st.session_state.get("selected_adm_name", names[0])
    if selected_default not in names:
        selected_default = names[0]
    selected_name = st.selectbox("행정동 선택", names, index=names.index(selected_default))
    st.session_state["selected_adm_name"] = selected_name
    row = artifacts.areas.loc[artifacts.areas["adm_name"].astype(str) == selected_name].iloc[0]
    st.metric("폭염 대응 정책 우선순위", f"{row['priority_score']:.1f}/100")
    st.progress(float(row["priority_score"]) / 100)
    detail_scores = pd.DataFrame(
        {
            "요인": ["기상 위험", "고령 취약성", "접근성 부족"],
            "점수": [row["heat_score"], row["vulnerability_score"], row["access_score"]],
        }
    )
    st.dataframe(detail_scores.style.format({"점수": "{:.1f}"}), hide_index=True, width="stretch")
    factors = detail_scores.sort_values("점수", ascending=False)["요인"].head(2).tolist()
    st.markdown("**주요 원인**")
    for factor in factors:
        st.markdown(f"- {factor}")
    st.caption(
        f"탐색적 정책유형: {row['cluster_name']} · 최근접 쉼터 {row['nearest_shelter_distance']:.0f}m"
    )
    st.info("이 점수는 의료적 진단이나 질환 발생 확률이 아닌 정책 우선순위 지표입니다.")

if simulation is None:
    st.info("사이드바의 ‘AI 도시처방 실행’을 누르면 예산 내 신규 후보와 설치 전·후 KPI가 계산됩니다.")
else:
    st.subheader("신규 쉼터 공간 처방 결과")
    if simulation.selected_candidates.empty:
        st.warning("현재 예산·임계값·접근반경 조건에서 추가 보호효과가 있는 후보가 선택되지 않았습니다.")
    else:
        recommendation = simulation.selected_candidates.copy()
        recommendation.insert(0, "순위", range(1, len(recommendation) + 1))
        recommendation = recommendation.rename(
            columns={
                "name": "후보지명",
                "facility_type": "시설유형",
                "cost": "비용",
                "incremental_covered_elderly": "신규 보호 추정 고령인구",
            }
        )
        st.dataframe(
            recommendation[["순위", "후보지명", "시설유형", "비용", "신규 보호 추정 고령인구"]].style.format(
                {"비용": "{:,.0f}원", "신규 보호 추정 고령인구": "{:,.0f}명"}
            ),
            hide_index=True,
            width="stretch",
        )
    st.caption(
        f"최적화 엔진: {optimization.solver} · 선택 비용 {optimization.total_cost:,.0f}원 / "
        f"예산 {budget:,.0f}원"
    )
    render_before_after(simulation.before_metrics, simulation.after_metrics)

with st.expander("왜 이 지역이 위험한가?", expanded=False):
    st.dataframe(
        artifacts.areas[
            ["adm_name", "heat_score", "vulnerability_score", "access_score", "priority_score", "cluster_name"]
        ].sort_values("priority_score", ascending=False).style.format(
            {column: "{:.1f}" for column in ["heat_score", "vulnerability_score", "access_score", "priority_score"]}
        ),
        hide_index=True,
        width="stretch",
    )

with st.expander("분석 방법"):
    st.markdown(
        "기상 위험 35%, 고령 취약성 35%, 접근성 부족 30%를 결합한 설명 가능한 정책 우선순위입니다. "
        "접근권역은 EPSG:5179에서 직선거리 buffer로 계산하며, 행정동 고령인구는 내부에 균등분포한다고 가정합니다. "
        "KMeans는 위험 예측이 아니라 정책 대응 유형을 탐색적으로 구분합니다."
    )
    st.json(artifacts.cluster_profiles, expanded=False)

with st.expander("데이터 출처"):
    st.write("실제 원본 파일")
    for source in artifacts.metadata["actual_sources"]:
        st.markdown(f"- `{source}`")
    if weather_context:
        st.write("기상 데이터 맥락")
        st.json(weather_context)
    if artifacts.metadata["is_demo"]:
        st.warning("행정동 경계·고령인구·동별 기상은 현재 DEMO SAMPLE입니다.")
    else:
        st.info("행정동 경계·인구와 동별 기상은 실제 공공데이터 입력입니다.")

with st.expander("한계"):
    for limitation in [
        "행정동 내 고령인구 균등분포 가정",
        "직선거리 기반 접근권역이며 실제 도로·보행장애물 미반영",
        "실제 시설 이용률과 온열질환 인과효과를 측정하지 않음",
        "공간 후보지역은 실제 토지·시설 설치 가능성 및 규제를 검토하지 않음",
        "실제 후보 비용이 없으면 MVP 시나리오 가상비용 사용",
        "데이터셋 간 기준년도 차이가 있을 수 있음",
    ]:
        st.markdown(f"- {limitation}")

with st.expander("정책 우선순위와 실행 근거", expanded=simulation is not None):
    if simulation is None:
        st.caption("도시처방 실행 후 계산된 수치만 이용해 브리핑을 생성합니다.")
    else:
        payload = build_policy_payload(
            artifacts,
            simulation,
            row,
            budget=int(budget),
            max_facilities=int(max_facilities),
        )
        policy, policy_warning = recommend_spatial_policy(payload)
        st.info(f"우선순위 **{policy['priority_level']}** · {policy['summary']}")
        for item in policy["recommended_policies"]:
            actions = "<br>".join(f"• {escape(str(action))}" for action in item["action_plan"])
            policy_name = escape(str(item["policy_name"]))
            target_location = escape(str(item["target_location"]))
            reason = escape(str(item["reason"]))
            expected_effect = escape(str(item["expected_effect"]))
            st.markdown(
                f'<div class="policy-card"><b>{policy_name}</b> — '
                f'{target_location}<br><small>{reason}</small><br><br>'
                f'{actions}<br><br><b>기대효과</b> {expected_effect}</div>',
                unsafe_allow_html=True,
            )
        for limitation in policy["limitations"]:
            st.caption(f"• {limitation}")
        if policy_warning:
            st.warning(policy_warning)
