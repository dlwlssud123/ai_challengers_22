from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

from src.integration import run_policy_analysis
from src.mock_data import available_regions


st.set_page_config(page_title="폭염 정책 나침반", page_icon="☀️", layout="wide")
with st.sidebar:
    theme_mode = st.segmented_control(
        "화면 모드",
        options=["기본", "다크"],
        default="기본",
        help="발표 환경에 맞춰 밝은 화면과 어두운 화면을 전환합니다.",
    )

theme = {
    "기본": {
        "page": "#fffdf9", "surface": "#ffffff", "surface_soft": "#fff7ed",
        "border": "#fed7aa", "text": "#292524", "muted": "#78716c",
        "card": "#fffaf5", "shadow": "rgba(124,45,18,.08)",
    },
    "다크": {
        "page": "#11100f", "surface": "#1c1917", "surface_soft": "#29211d",
        "border": "#7c2d12", "text": "#fafaf9", "muted": "#d6d3d1",
        "card": "#231a16", "shadow": "rgba(0,0,0,.35)",
    },
}[theme_mode]

st.markdown(f"""
<style>
[data-testid="stAppViewContainer"] {{background:{theme['page']}; color:{theme['text']};}}
[data-testid="stHeader"] {{background:transparent;}}
[data-testid="stSidebar"] {{background:{theme['surface']}; border-right:1px solid {theme['border']};}}
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3 {{color:{theme['text']};}}
.block-container {{padding-top:2rem; padding-bottom:3rem; max-width:1280px;}}
[data-testid="stMetric"] {{background:{theme['surface_soft']}; border:1px solid {theme['border']}; border-radius:14px; padding:14px; box-shadow:0 8px 24px {theme['shadow']};}}
[data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {{color:{theme['text']};}}
.stDataFrame, [data-testid="stExpander"] {{border-radius:12px; overflow:hidden; border-color:{theme['border']};}}
.hero {{padding:1.2rem 1.4rem; border-radius:18px; background:linear-gradient(120deg,#7c2d12,#ea580c); color:white; margin-bottom:1rem;}}
.hero h1 {{margin:0 0 .3rem 0 !important; color:white !important; font-size:clamp(1.55rem,4vw,2rem);}}.hero p {{margin:0; opacity:.9; color:white !important;}}
.policy-card {{border-left:5px solid #ea580c; background:{theme['card']}; color:{theme['text']}; padding:1rem 1.1rem; border-radius:8px; margin:.7rem 0; box-shadow:0 8px 24px {theme['shadow']};}}
.policy-card small {{color:{theme['muted']};}}

@media (max-width: 900px) {{
  .block-container {{padding:1.2rem 1rem 2rem;}}
  [data-testid="stHorizontalBlock"] {{flex-wrap:wrap; gap:.75rem;}}
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{min-width:calc(50% - .75rem); flex:1 1 calc(50% - .75rem);}}
}}
@media (max-width: 640px) {{
  .block-container {{padding:.8rem .65rem 1.5rem;}}
  .hero {{padding:1rem; border-radius:14px;}}
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{min-width:100%; flex:1 1 100%;}}
  [data-testid="stMetric"] {{padding:11px;}}
  .policy-card {{padding:.85rem; overflow-wrap:anywhere;}}
  [data-testid="stDataFrame"] {{overflow-x:auto;}}
}}
</style>
""", unsafe_allow_html=True)
st.markdown('<section class="hero"><h1>폭염 정책 나침반</h1><p>취약지역과 대응시설 사각지대를 찾아, 예산 안에서 우선 정책을 제안합니다.</p></section>', unsafe_allow_html=True)

with st.sidebar:
    st.header("분석 조건")
    region = st.selectbox("대상 행정동", available_regions())
    budget_million = st.number_input("가용 예산 (백만원)", min_value=0, max_value=500, value=50, step=1)
    max_facilities = st.number_input("설치 가능 시설 수", min_value=0, max_value=10, value=2, step=1)
    use_mock = st.toggle("Mock 모드", value=True, help="모델과 API 없이 시연용 데이터로 실행합니다.")
    run_clicked = st.button("정책 분석 실행", type="primary", width="stretch")
    st.caption("개인정보를 입력하지 않으며 API 키는 화면에 표시하지 않습니다.")

if run_clicked:
    try:
        with st.spinner("취약도, 접근성, 입지와 정책을 통합 분석하고 있습니다..."):
            st.session_state["analysis_result"] = run_policy_analysis(region, int(budget_million * 1_000_000), int(max_facilities), use_mock)
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error("분석을 완료하지 못했습니다. 입력값과 데이터 연결 상태를 확인해 주세요.")

result = st.session_state.get("analysis_result")
if not result:
    st.info("왼쪽에서 조건을 확인한 뒤 **정책 분석 실행**을 눌러 주세요. Mock 모드는 API 키 없이 동작합니다.")
    st.stop()

vul, acc, opt, policy = result["vulnerability"], result["accessibility"], result["optimization"], result["policy_recommendation"]
st.caption(f"분석 대상: {result['region']} · 분석 모드: {'시연 데이터' if result['analysis_mode'] == 'mock' else '실데이터'}")
metrics = st.columns(4)
metrics[0].metric("폭염 취약도", f"{vul['vulnerability_score']:.1f}점", vul["vulnerability_grade"])
metrics[1].metric("시설 접근성", f"{acc['facility_score']:.1f}점")
metrics[2].metric("접근 취약인구", f"{acc['underserved_population']:,}명")
metrics[3].metric("가장 가까운 쉼터", f"{acc['nearest_shelter_distance_m']:,}m")

left, right = st.columns([1, 1.4])
with left:
    st.subheader("주요 취약 원인")
    causes = pd.DataFrame(vul["main_causes"])
    causes["기여도(%)"] = (causes["contribution"] * 100).round(1)
    st.bar_chart(causes.set_index("name")["기여도(%)"], color="#ea580c", horizontal=True)
    st.dataframe(causes.rename(columns={"name": "요인", "value": "관측값"})[["요인", "관측값", "기여도(%)"]], hide_index=True, width="stretch")

with right:
    st.subheader("시설과 추천 입지")
    existing, recommended = pd.DataFrame(acc["existing_facilities"]), pd.DataFrame(opt["recommended_locations"])
    layers = []
    if not existing.empty:
        layers.append(pdk.Layer("ScatterplotLayer", existing, get_position="[longitude, latitude]", get_fill_color=[37, 99, 235, 190], get_radius=90, pickable=True))
    if not recommended.empty:
        layers.append(pdk.Layer("ScatterplotLayer", recommended, get_position="[longitude, latitude]", get_fill_color=[234, 88, 12, 220], get_radius=120, pickable=True))
    center = acc["map_center"]
    st.pydeck_chart(pdk.Deck(map_style=None, initial_view_state=pdk.ViewState(latitude=center["latitude"], longitude=center["longitude"], zoom=13), layers=layers, tooltip={"html": "<b>{name}</b><br/>{type}{facility_type}<br/>{reason}"}), width="stretch")
    st.caption("● 파랑: 기존 시설　● 주황: 신규 추천 후보")

st.subheader("설치 전후 What-if 비교")
before, after = opt["before"], opt["after"]
c1, c2, c3 = st.columns(3)
c1.metric("시설 서비스권", f"{after['coverage_rate']:.1f}%", f"{after['coverage_rate'] - before['coverage_rate']:+.1f}%p")
c2.metric("접근 취약인구", f"{after['underserved_population']:,}명", f"{after['underserved_population'] - before['underserved_population']:+,}명", delta_color="inverse")
c3.metric("사각지대", f"{after['blind_spot_count']}곳", f"{after['blind_spot_count'] - before['blind_spot_count']:+d}곳", delta_color="inverse")
st.bar_chart(pd.DataFrame({"설치 전": [before["coverage_rate"]], "설치 후": [after["coverage_rate"]]}, index=["서비스권 비율(%)"]), color=["#94a3b8", "#ea580c"])

st.subheader("예산 내 추천 시설")
st.caption(f"총 예상비용 {opt['total_estimated_cost'] / 1_000_000:,.0f}백만원 / 입력 예산 {opt['budget'] / 1_000_000:,.0f}백만원")
if recommended.empty:
    st.warning("현재 예산과 시설 수 조건으로 선택 가능한 후보가 없습니다.")
else:
    shown = recommended.copy()
    shown["estimated_cost"] = shown["estimated_cost"].map(lambda value: f"{value / 1_000_000:,.0f}백만원")
    shown["additional_covered_population"] = shown["additional_covered_population"].map(lambda value: f"{value:,}명")
    st.dataframe(shown.rename(columns={"name": "후보지", "facility_type": "시설", "estimated_cost": "예상비용", "additional_covered_population": "추가 접근인구", "reason": "선정 근거"})[["후보지", "시설", "예상비용", "추가 접근인구", "선정 근거"]], hide_index=True, width="stretch")

st.subheader("정책 우선순위와 실행 근거")
st.info(f"우선순위 **{policy['priority_level']}** · {policy['summary']}")
for item in policy["recommended_policies"]:
    actions = "<br>".join(f"• {action}" for action in item["action_plan"])
    st.markdown(f'<div class="policy-card"><b>{item["policy_name"]}</b> — {item["target_location"]}<br><small>{item["reason"]}</small><br><br>{actions}<br><br><b>기대효과</b> {item["expected_effect"]}</div>', unsafe_allow_html=True)

with st.expander("데이터·분석 한계 및 실행 경고"):
    for limitation in policy["limitations"]:
        st.write(f"- {limitation}")
    for warning in result["warnings"]:
        st.warning(warning)
