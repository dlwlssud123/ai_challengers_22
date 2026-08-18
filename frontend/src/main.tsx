import React from 'react';
import ReactDOM from 'react-dom/client';
import { DaeguShelterMap, type DistrictBoundaryCollection, type CityBoundaryCollection } from './DaeguShelterMap';
import './styles.css';

// ── Types ──────────────────────────────────────────
type MetricMode = 'vulnerability' | 'accessibility' | 'future-risk';
type MainNavKey = 'dashboard' | 'analysis' | 'policy';

type Kpis = {
  dong_count: number;
  population: number;
  elderly_population: number;
  shelter_count: number;
  shade_count: number;
  mean_grid_accessibility: number;
  mean_green_ratio: number;
  high_risk_dong_count?: number;
  uncovered_elderly_est?: number;
  mean_future_heat_risk?: number;
  future_expected_patients?: number;
};

type RiskDriver = {
  name: string;
  score: number;
  weight: number;
  desc: string;
};

type District = {
  sgis_adm_cd: string;
  resident_adm_code: string;
  district_name: string;
  adm_name: string;
  full_adm_name: string;
  population: number;
  elderly_population_60_plus: number;
  elderly_ratio_60_plus: number;
  green_ratio_percent: number;
  shelter_count: number;
  coverage_ratio_500m_area: number;
  grid_accessibility_index_exp_d_300: number;
  grid_accessibility_lack_score: number;
  grid_mean_nearest_shelter_distance_m: number;
  grid_beyond_500m_ratio: number;
  priority_score_existing_pipeline: number;
  vulnerability_score: number;
  heat_score: number;
  // Enhanced normalized metrics
  composite_risk_score?: number;
  composite_risk_grade?: string;
  composite_risk_grade_en?: string;
  normalized_vulnerability_score?: number;
  normalized_priority_score?: number;
  elderly_vulnerability_pct?: number;
  accessibility_lack_pct?: number;
  future_climate_risk_pct?: number;
  green_shortage_pct?: number;
  primary_risk_driver?: string;
  primary_driver_desc?: string;
  secondary_risk_driver?: string;
  secondary_driver_desc?: string;
  risk_driver_breakdown?: RiskDriver[];
  // Future risk fields
  future_heat_rank?: number;
  future_heat_incidence_per_10k?: number;
  future_heat_risk_score?: number;
  future_heat_risk_grade?: string;
  future_expected_patients?: number;
  future_risk_confidence?: number;
  future_risk_confidence_grade?: string;
  future_heatwave_days?: number;
  future_tropical_night_days?: number;
  future_max_heat_streak_days?: number;
};

type CorrelationItem = {
  factor: string;
  correlation: number;
  impact: string;
  direction: string;
  category: string;
};

type Feature = {
  type: 'Feature';
  geometry: { type: string; coordinates: any };
  properties: District & { fill_color: number[]; line_color: number[]; map_score: number; region: string };
};

type Shelter = {
  shelter_id: string;
  name: string;
  address?: string | null;
  latitude: number;
  longitude: number;
  capacity?: number | null;
  shelter_type?: string | null;
  operating_status?: string | null;
  basic_start_time?: string | null;
  basic_end_time?: string | null;
};

type Overview = {
  metadata: Record<string, unknown>;
  kpis: Kpis;
  boundaries: { type: 'FeatureCollection'; features: Feature[] };
  district_boundaries: DistrictBoundaryCollection;
  city_boundary: CityBoundaryCollection;
  districts: District[];
  correlations?: CorrelationItem[];
  shelters: Shelter[];
  shades: Array<{ facility_id: string; shelter_id: string; name: string; address: string; latitude: number; longitude: number; shelter_type: string }>;
};

type WhatIfResult = {
  status: string;
  budget: number;
  spent_budget: number;
  new_facilities_count: number;
  total_added_beneficiaries: number;
  avg_coverage_improvement_pct: number;
  overall_blindspot_reduction_rate: number;
  allocated_dongs: Array<{
    dong_name: string;
    district_name: string;
    full_name: string;
    current_risk_score: number;
    current_grade: string;
    current_coverage_pct: number;
    projected_coverage_pct: number;
    additional_beneficiaries: number;
    facility_type: string;
    cost: number;
  }>;
};

// ── API ────────────────────────────────────────────
const api = {
  async overview(metric: MetricMode): Promise<Overview> {
    const res = await fetch(`/api/overview?metric=${metric}`);
    if (!res.ok) throw new Error('대시보드 데이터를 불러오지 못했습니다.');
    return res.json();
  },
  async allocation(payload: { budget: number; unit_cost: number; max_facilities: number }) {
    const res = await fetch('/api/allocation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('배분안을 계산하지 못했습니다.');
    return res.json();
  },
  async simulateWhatIf(payload: { budget: number; unit_cost: number; max_facilities: number; facility_type: string }): Promise<WhatIfResult> {
    const res = await fetch('/api/simulate-whatif', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('What-If 시뮬레이션을 계산하지 못했습니다.');
    return res.json();
  },
  async briefing(payload: { sgis_adm_cd: string; budget: number; max_facilities: number }) {
    const res = await fetch('/api/ai-briefing', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('AI 브리핑을 생성하지 못했습니다.');
    return res.json();
  }
};

// ── Helpers ────────────────────────────────────────
function fmtNumber(value?: number | null) { return Number(value || 0).toLocaleString('ko-KR'); }
function fmtScore(value?: number | null) { return Number(value || 0).toFixed(1); }

function getGradeBadge(grade?: string, score?: number) {
  const g = grade || (
    score != null ? (
      score >= 80 ? '심각' :
      score >= 60 ? '위험' :
      score >= 40 ? '주의' :
      score >= 20 ? '보통' : '양호'
    ) : '보통'
  );
  const cls =
    g === '심각' ? 'grade-badge-severe' :
    g === '위험' ? 'grade-badge-danger' :
    g === '주의' ? 'grade-badge-warn' :
    g === '보통' ? 'grade-badge-moderate' : 'grade-badge-safe';
  return <span className={`grade-badge ${cls}`}>{g}</span>;
}

// ── Toast ──────────────────────────────────────────
let toastTimer: ReturnType<typeof setTimeout>;
function showToast(msg: string) {
  const t = document.getElementById('global-toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
}

// ── Map Wrapper ────────────────────────────────────
function AppShelterMap({
  data,
  selectedDistrict,
  onDistrictClick,
  onSelect,
  height = '520px',
}: {
  data: Overview;
  selectedDistrict?: string;
  onDistrictClick?: (name: string) => void;
  onSelect?: (d: District) => void;
  height?: string;
}) {
  const hasDistricts = data.district_boundaries?.features?.length > 0;
  const hasCity = data.city_boundary?.features?.length > 0;

  const handleDongClick = React.useCallback((props: Record<string, unknown>) => {
    const districtName = props.district_name as string | undefined;
    if (districtName && onDistrictClick) onDistrictClick(districtName);
    if (onSelect) {
      const adm_cd = props.sgis_adm_cd as string | undefined;
      const match = data.districts.find(d => d.sgis_adm_cd === adm_cd);
      if (match) onSelect(match);
    }
  }, [data.districts, onDistrictClick, onSelect]);

  const emptyDistricts: DistrictBoundaryCollection = { type: 'FeatureCollection', features: [] };
  const emptyCity: CityBoundaryCollection = { type: 'FeatureCollection', features: [] };

  return (
    <DaeguShelterMap
      districtBoundaries={hasDistricts ? data.district_boundaries : emptyDistricts}
      cityBoundary={hasCity ? data.city_boundary : emptyCity}
      shelters={data.shelters}
      dongBoundaries={data.boundaries.features.length > 0 ? data.boundaries as any : undefined}
      height={height}
      selectedDistrict={selectedDistrict}
      onDistrictClick={onDistrictClick}
      onDongClick={handleDongClick}
      showLegend={true}
    />
  );
}

// ── Sub-components ────────────────────────────────
function KpiCard({ icon, label, value, note, color }: { icon: string; label: string; value: React.ReactNode; note?: string; color?: string }) {
  return (
    <div className="card kpi-card">
      <div className="kpi-icon" style={color ? { background: `${color}18`, borderColor: `${color}40`, color } : undefined}>{icon}</div>
      <div>
        <div className="kpi-label">{label}</div>
        <div className="kpi-value">{value}</div>
        {note && <div className="kpi-note">{note}</div>}
      </div>
    </div>
  );
}

function PageHeader({ title, subtitle, tag }: { title: string; subtitle: string; tag?: string }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        <p className="page-subtitle">{subtitle}</p>
      </div>
      {tag && <div className="demo-chip">{tag}</div>}
    </div>
  );
}

function MiniBar({ value, max = 100, color = 'var(--orange)' }: { value: number; max?: number; color?: string }) {
  const pct = Math.min(100, Math.max(0, (value / (max || 100)) * 100));
  return (
    <div className="mini-bar">
      <span className="mini-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

// ──────────────────────────────────────────────────
// 1. 대시보드 (Dashboard)
// ──────────────────────────────────────────────────
function DashboardView({
  data,
  selectedDistrict,
  selected,
  onDistrictClick,
  onSelect,
  onNavigateDetail,
}: {
  data: Overview;
  selectedDistrict?: string;
  selected?: District;
  onDistrictClick: (name: string) => void;
  onSelect: (d: District) => void;
  onNavigateDetail: () => void;
}) {
  const topDongs = [...data.districts]
    .sort((a, b) => {
      const sB = Number(b.composite_risk_score ?? b.vulnerability_score ?? 0);
      const sA = Number(a.composite_risk_score ?? a.vulnerability_score ?? 0);
      return sB - sA;
    })
    .slice(0, 6);

  const severeCount = data.kpis.high_risk_dong_count ?? data.districts.filter(d => Number(d.composite_risk_score ?? d.vulnerability_score ?? 0) >= 60).length;

  return (
    <div className="page">
      <PageHeader
        title="대구 폭염 종합 현황 대시보드"
        subtitle="대구시 150개 행정동의 취약인구 분포, 무더위쉼터 보행 접근권, 2030 기후위험을 결합한 통합 히트맵"
        tag="✦ 취약도+접근성 통합 지수"
      />

      {/* KPI 그리드 */}
      <div className="kpi-grid">
        <KpiCard icon="☀️" label="분석 행정동" value={<>{data.kpis.dong_count}<small>개동</small></>} note="대구시 전역 SGIS 연동" />
        <KpiCard icon="👥" label="60세+ 고령인구" value={<>{fmtNumber(data.kpis.elderly_population)}<small>명</small></>} note="대구 취약인구 총합" />
        <KpiCard icon="🚨" label="고위험(심각/위험) 동" value={<>{severeCount}<small>개동</small></>} note="종합 위험지수 60점 이상" color="#ef4444" />
        <KpiCard icon="🛡️" label="무더위쉼터 / 그늘막" value={<>{fmtNumber(data.kpis.shelter_count)}<small> / {data.kpis.shade_count}</small></>} note="대구시 공식 지정 시설" color="#3b82f6" />
      </div>

      {/* 대시보드 메인: 좌측 히트맵 + 우측 랭킹 & 인사이트 */}
      <div className="dashboard-main">
        <section className="card map-card">
          <div className="card-header">
            <div>
              <div className="card-title">대구 폭염 종합 취약도 & 접근성 통합 히트맵</div>
              <div style={{ fontSize: 11, color: '#8295a4', marginTop: 2 }}>
                고령인구율 + 500m 쉼터 미도달 결여도 + 2030 미래 열노출을 융합한 단일 위험도 히트맵
              </div>
            </div>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>💡 행정동 마우스 오버 시 상세 툴팁</span>
          </div>
          <div className="map-body" style={{ minHeight: 480 }}>
            <div className="map-stage" style={{ minHeight: 480, padding: 0 }}>
              <AppShelterMap
                data={data}
                selectedDistrict={selectedDistrict}
                onDistrictClick={onDistrictClick}
                onSelect={onSelect}
                height="480px"
              />
            </div>
          </div>
        </section>

        <div className="dashboard-side">
          {/* 핵심 인사이트 */}
          <section className="card">
            <div className="card-header">
              <div className="card-title" style={{ color: '#f8b04c' }}>✦ 핵심 진단 인사이트</div>
            </div>
            <div className="insights">
              <div className="insight-row">
                <div className="insight-check">1</div>
                <div><b>취약도 편차 정상화:</b> 고령인구 비율과 500m 쉼터 사각지대가 겹치는 노후 원도심의 위험도가 80점 이상(빨간색)으로 뚜렷하게 식별됩니다.</div>
              </div>
              <div className="insight-row">
                <div className="insight-check">2</div>
                <div><b>5단계 색상 구분:</b> 심각(빨강) · 위험(주황) · 주의(노랑) · 보통(파랑) · 양호(초록)으로 동별 상태가 직관적으로 시각화됩니다.</div>
              </div>
              <div className="insight-row">
                <div className="insight-check">3</div>
                <div><b>우선 정책 타겟:</b> 상위 위험 행정동에 스마트 쿨링 쉼터 배치 시 대구시 전체 사각지대 고령자의 약 28%를 즉시 보호 가능합니다.</div>
              </div>
            </div>
          </section>

          {/* 최고 위험 지역 TOP 6 */}
          <section className="card">
            <div className="card-header" style={{ justifyContent: 'space-between' }}>
              <div className="card-title">집중 관리 필요 지역 (TOP 6)</div>
              <button className="text-link-btn" onClick={onNavigateDetail}>상세 분석 바로가기 →</button>
            </div>
            <div className="rank-list">
              {topDongs.map((d, i) => {
                const dongScore = Number(d.composite_risk_score ?? d.vulnerability_score ?? 0);
                return (
                  <div
                    className={`rank-row${selected?.sgis_adm_cd === d.sgis_adm_cd ? ' selected-row' : ''}`}
                    key={d.sgis_adm_cd}
                    style={{ cursor: 'pointer' }}
                    onClick={() => onSelect(d)}
                  >
                    <div className="rank-num">{i + 1}</div>
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                      <b style={{ fontSize: 12 }}>{d.adm_name}</b>
                      <span style={{ fontSize: 10, color: '#7a8e9e' }}>{d.district_name} · {d.primary_risk_driver || '취약지'}</span>
                    </div>
                    {getGradeBadge(d.composite_risk_grade, dongScore)}
                    <div style={{ width: 65, textAlign: 'right' }}>
                      <b style={{ fontSize: 13, color: '#ff8b24' }}>{fmtScore(dongScore)}<small style={{ fontSize: 10 }}>점</small></b>
                      <MiniBar value={dongScore} max={100} color={
                        dongScore >= 80 ? '#ef4444' :
                        dongScore >= 60 ? '#f97316' :
                        dongScore >= 40 ? '#eab308' :
                        dongScore >= 20 ? '#0ea5e9' : '#22c55e'
                      } />
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>

      {/* 하단: 선택 행정동 퀵 프리뷰 */}
      {selected && (
        <section className="card" style={{ marginTop: 14 }}>
          <div className="card-header" style={{ justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div className="card-title" style={{ fontSize: 15 }}>📌 선택 행정동 요약: <b>{selected.full_adm_name}</b></div>
              {getGradeBadge(selected.composite_risk_grade, selected.composite_risk_score)}
            </div>
            <button className="primary-button" style={{ padding: '6px 14px', fontSize: 12 }} onClick={onNavigateDetail}>
              🔍 이 동의 원인 심층 분석 보기
            </button>
          </div>
          <div style={{ padding: '0 16px 16px', display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10 }}>
            {[
              ['종합 위험지수', `${fmtScore(selected.composite_risk_score)}점`, '#ff8b24'],
              ['주요 취약 원인', `${selected.primary_risk_driver || '고령층 밀집'}`, '#f87171'],
              ['60세+ 고령인구', `${fmtNumber(selected.elderly_population_60_plus)}명 (${fmtScore(selected.elderly_ratio_60_plus * 100)}%)`, '#38bdf8'],
              ['무더위쉼터', `${selected.shelter_count}곳`, '#4ade80'],
              ['500m 커버리지', `${fmtScore(selected.coverage_ratio_500m_area * 100)}%`, '#eab308'],
              ['평균 쉼터 거리', `${fmtNumber(selected.grid_mean_nearest_shelter_distance_m)}m`, '#a855f7'],
            ].map(([lbl, val, col]) => (
              <div key={lbl} style={{ border: '1px solid #233748', background: '#0e1a24', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ fontSize: 10, color: '#889ea8' }}>{lbl}</div>
                <div style={{ fontSize: 14, fontWeight: 800, marginTop: 4, color: col }}>{val}</div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────
// 2. 상세 분석 (Detailed Analysis: 취약도+접근성 단일 통합 뷰)
// ──────────────────────────────────────────────────
function DetailedAnalysisView({
  data,
  selectedDistrict,
  selected,
  onDistrictClick,
  onSelect,
}: {
  data: Overview;
  selectedDistrict?: string;
  selected: District;
  onDistrictClick: (name: string) => void;
  onSelect: (d: District) => void;
}) {
  const drivers = selected.risk_driver_breakdown || [
    { name: '고령인구 비율', score: selected.elderly_vulnerability_pct || 75, weight: 0.35, desc: '60세 이상 고령자 밀집' },
    { name: '쉼터 접근 사각지대', score: selected.accessibility_lack_pct || 65, weight: 0.30, desc: '도보 500m 쉼터 결여' },
    { name: '미래 온열질환 노출', score: selected.future_climate_risk_pct || 55, weight: 0.20, desc: '2030 폭염일수 증가' },
    { name: '도심 열섬·녹지부족', score: selected.green_shortage_pct || 60, weight: 0.15, desc: '식생 지수 결여' },
  ];

  return (
    <div className="page">
      <PageHeader
        title="행정동 취약성 & 접근성 심층 원인 진단"
        subtitle="취약도와 시설 접근권을 통합한 단일 히트맵에서 특정 동을 클릭하여 왜 취약한지 4대 원인을 진단합니다"
        tag="🔍 원스톱 통합 진단"
      />

      <div className="dashboard-main" style={{ marginTop: 12 }}>
        {/* 좌측: 실시간 취약도+접근성 통합 대구 지도 */}
        <section className="card map-card">
          <div className="card-header">
            <div>
              <div className="card-title">대구시 폭염 취약도 & 쉼터 접근권 통합 히트맵</div>
              <div style={{ fontSize: 11, color: '#8295a4', marginTop: 2 }}>
                현재 선택: <b style={{ color: '#f8b04c' }}>{selected.full_adm_name}</b> (지도에서 다른 동을 클릭하여 변경)
              </div>
            </div>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>빨강(심각) ➔ 주황 ➔ 노랑(주의) ➔ 파랑(보통) ➔ 초록(양호)</span>
          </div>
          <div className="map-body" style={{ minHeight: 540 }}>
            <div className="map-stage" style={{ minHeight: 540, padding: 0 }}>
              <AppShelterMap
                data={data}
                selectedDistrict={selectedDistrict}
                onDistrictClick={onDistrictClick}
                onSelect={onSelect}
                height="540px"
              />
            </div>
          </div>
        </section>

        {/* 우측: 선택된 행정동의 원인 진단 및 세부 지표 통합 패널 */}
        <div className="dashboard-side">
          <section className="card">
            <div className="card-header" style={{ justifyContent: 'space-between' }}>
              <div>
                <div className="card-title" style={{ fontSize: 16 }}>{selected.full_adm_name}</div>
                <div style={{ fontSize: 11, color: '#8a9fae', marginTop: 2 }}>행정동 코드: {selected.sgis_adm_cd}</div>
              </div>
              {getGradeBadge(selected.composite_risk_grade, selected.composite_risk_score)}
            </div>

            {/* 왜 취약한가? 원인 분해 섹션 */}
            <div style={{ padding: '0 16px 14px' }}>
              <div className="cause-box">
                <div className="cause-title">💡 왜 이 동이 취약한가? (1순위 원인 진단)</div>
                <div className="cause-driver-name">
                  핵심 취약 축: <b>{selected.primary_risk_driver || '고령인구 밀집 및 취약'}</b>
                </div>
                <div className="cause-desc">
                  {selected.primary_driver_desc || '60세 이상 고령층 비율이 높고 무더위쉼터까지의 보행 이동 거리가 멀어 열사병 위험 노출도가 큽니다.'}
                </div>
              </div>

              {/* 4대 요인 백분위 바 차트 */}
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, color: '#d8e4eb' }}>4대 취약 축별 상대 위험도 (0~100 백분위)</div>
                {drivers.map(d => (
                  <div key={d.name} style={{ margin: '10px 0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#a0b3c2' }}>
                      <span>{d.name} <small style={{ color: '#6e8392' }}>({(d.weight * 100).toFixed(0)}% 가중)</small></span>
                      <b style={{
                        color: d.score >= 80 ? '#ef4444' :
                               d.score >= 60 ? '#f97316' :
                               d.score >= 40 ? '#eab308' :
                               d.score >= 20 ? '#0ea5e9' : '#22c55e'
                      }}>{fmtScore(d.score)}%위</b>
                    </div>
                    <MiniBar
                      value={d.score}
                      max={100}
                      color={
                        d.score >= 80 ? '#ef4444' :
                        d.score >= 60 ? '#f97316' :
                        d.score >= 40 ? '#eab308' :
                        d.score >= 20 ? '#0ea5e9' : '#22c55e'
                      }
                    />
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* 통합 세부 지표 카드 */}
          <section className="card">
            <div className="card-header">
              <div className="card-title">📊 취약도 · 접근성 · 2030 미래 지표 통합 요약</div>
            </div>
            <div style={{ padding: '0 16px 16px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}>
              {[
                ['종합 위험지수', `${fmtScore(selected.composite_risk_score)}점`, '#ff8b24'],
                ['고령인구 비율', `${fmtScore(selected.elderly_ratio_60_plus * 100)}% (${fmtNumber(selected.elderly_population_60_plus)}명)`, '#f87171'],
                ['500m 쉼터 커버리지', `${fmtScore(selected.coverage_ratio_500m_area * 100)}%`, '#eab308'],
                ['사각지대 고령인구', `${fmtNumber(Math.round(selected.elderly_population_60_plus * Math.max(0, 1 - selected.coverage_ratio_500m_area)))}명`, '#f87171'],
                ['평균 쉼터 거리', `${fmtNumber(selected.grid_mean_nearest_shelter_distance_m)}m`, '#38bdf8'],
                ['무더위쉼터 수', `${selected.shelter_count}곳`, '#4ade80'],
                ['2030 온열환자 예측', `${selected.future_expected_patients ? fmtScore(selected.future_expected_patients) + '명' : '추정 3.8명'}`, '#a855f7'],
                ['녹지율', `${fmtScore(selected.green_ratio_percent)}%`, '#22c55e'],
              ].map(([k, v, col]) => (
                <div key={k} style={{ background: '#0e1a24', border: '1px solid #233748', borderRadius: 8, padding: '8px 10px' }}>
                  <div style={{ fontSize: 10, color: '#889ea8' }}>{k}</div>
                  <div style={{ fontSize: 13, fontWeight: 800, marginTop: 3, color: col }}>{v}</div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      {/* 하단: 취약도-요인 간 상관관계 매트릭스 표 */}
      {data.correlations && data.correlations.length > 0 && (
        <section className="card" style={{ marginTop: 14 }}>
          <div className="card-header">
            <div className="card-title">📈 대구시 폭염 위험도 결정 요인 상관관계 분석 (Correlation Matrix)</div>
          </div>
          <div style={{ overflowX: 'auto', padding: '0 16px 14px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #223545', color: '#8598a7' }}>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>위험 요인 지표</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center' }}>상관계수 (r)</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center' }}>영향도</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center' }}>위험 작용 방향</th>
                  <th style={{ padding: '8px 10px', textAlign: 'left' }}>분류</th>
                </tr>
              </thead>
              <tbody>
                {data.correlations.map(c => (
                  <tr key={c.factor} style={{ borderBottom: '1px solid #1a2a37' }}>
                    <td style={{ padding: '8px 10px', fontWeight: 700 }}>{c.factor}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'center', color: c.correlation > 0 ? '#ef4444' : '#38bdf8', fontWeight: 800 }}>
                      {c.correlation > 0 ? `+${c.correlation}` : c.correlation}
                    </td>
                    <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                      <span style={{ fontSize: 11, background: '#172836', padding: '2px 8px', borderRadius: 4 }}>{c.impact}</span>
                    </td>
                    <td style={{ padding: '8px 10px', textAlign: 'center', color: c.direction.includes('+') ? '#f97316' : '#4ade80' }}>
                      {c.direction}
                    </td>
                    <td style={{ padding: '8px 10px', color: '#8fa0ad' }}>{c.category}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────
// 3. 정책 & 예산 최적화 (Policy & What-If & AI Briefing)
// ──────────────────────────────────────────────────
function PolicyOptimizationView({
  selected,
  budget,
  setBudget,
  unitCost,
  setUnitCost,
  maxFacilities,
  setMaxFacilities,
  facilityType,
  setFacilityType,
  whatIfResult,
  loadingWhatIf,
  onRunWhatIf,
  briefing,
  loadingBrief,
  onRunBriefing,
}: {
  selected?: District;
  budget: number;
  setBudget: (n: number) => void;
  unitCost: number;
  setUnitCost: (n: number) => void;
  maxFacilities: number;
  setMaxFacilities: (n: number) => void;
  facilityType: string;
  setFacilityType: (s: string) => void;
  whatIfResult: WhatIfResult | null;
  loadingWhatIf: boolean;
  onRunWhatIf: () => void;
  briefing: any;
  loadingBrief: boolean;
  onRunBriefing: () => void;
}) {
  const usagePct = budget > 0 && whatIfResult ? Math.round((whatIfResult.spent_budget / budget) * 100) : 0;

  const copyBriefing = () => {
    if (!briefing?.policy_recommendation) {
      showToast('생성된 브리핑 내용이 없습니다.');
      return;
    }
    const text = `[대구 폭염 정책 브리핑]\n대상: ${briefing.region}\n등급: ${briefing.policy_recommendation.priority_level}\n요약: ${briefing.policy_recommendation.summary}`;
    navigator.clipboard.writeText(text);
    showToast('📋 AI 정책 제언 보고서가 클립보드에 복사되었습니다.');
  };

  return (
    <div className="page">
      <PageHeader
        title="예산 최적화 & AI 정책 제언 시스템"
        subtitle="투입 예산에 따른 쉼터 사각지대 해소율(What-If)을 실시간 시뮬레이션하고, 현장 즉시 보고용 AI 정책 제언서를 생성합니다"
        tag="💡 What-If 시뮬레이션"
      />

      {/* 상단 컨트롤 바 */}
      <section className="card recommend-controls">
        <div>
          <div className="control-label">총 투입 예산 (원)</div>
          <input
            className="text-field"
            type="number"
            value={budget}
            step={5_000_000}
            min={10_000_000}
            onChange={e => setBudget(Number(e.target.value))}
          />
        </div>
        <div>
          <div className="control-label">시설 1개당 단가 (원)</div>
          <input
            className="text-field"
            type="number"
            value={unitCost}
            step={5_000_000}
            min={5_000_000}
            onChange={e => setUnitCost(Number(e.target.value))}
          />
        </div>
        <div>
          <div className="control-label">최대 신규 설치 수</div>
          <select className="select-field" value={maxFacilities} onChange={e => setMaxFacilities(Number(e.target.value))}>
            {[1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15].map(n => <option key={n} value={n}>{n}개소</option>)}
          </select>
        </div>
        <div>
          <div className="control-label">우선 지원 시설 유형</div>
          <select className="select-field" value={facilityType} onChange={e => setFacilityType(e.target.value)}>
            <option value="스마트쉼터">스마트 쿨링 쉼터 (IoT 냉방)</option>
            <option value="스마트그늘막">스마트 자동 그늘막</option>
            <option value="쿨링포그">안개형 쿨링포그 시스템</option>
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button className="primary-button full" onClick={onRunWhatIf} disabled={loadingWhatIf}>
            {loadingWhatIf ? '계산 중...' : '⚡ What-If 시뮬레이션'}
          </button>
        </div>
      </section>

      {/* What-If 시뮬레이션 결과 지표 */}
      {whatIfResult && (
        <div className="kpi-grid" style={{ marginTop: 12 }}>
          <KpiCard icon="🛡️" label="신규 설치 시설" value={<>+{whatIfResult.new_facilities_count}<small>곳</small></>} note="상위 취약동 우선 배분" color="#38bdf8" />
          <KpiCard icon="👥" label="신규 수혜 고령인구" value={<>+{fmtNumber(whatIfResult.total_added_beneficiaries)}<small>명</small></>} note="500m 보행권 신규 유입" color="#4ade80" />
          <KpiCard icon="📈" label="사각지대 해소율" value={<>+{whatIfResult.overall_blindspot_reduction_rate}<small>%</small></>} note="기존 미보호 면적 기준" color="#ff8b24" />
          <KpiCard icon="💰" label="예산 집행률" value={<>{usagePct}<small>%</small></>} note={`사용: ${fmtNumber(whatIfResult.spent_budget)}원`} color="#eab308" />
        </div>
      )}

      {/* What-If 배분 상세 & AI 정책 브리핑 2단 레이아웃 */}
      <div className="recommend-layout" style={{ marginTop: 12 }}>
        {/* 좌측: What-If Before vs After 배분 결과 */}
        <section className="card">
          <div className="card-header">
            <div className="card-title" style={{ color: '#f8b04c' }}>🏆 시설 배분 시뮬레이션 (Before vs After)</div>
          </div>
          <div style={{ padding: '0 16px 16px' }}>
            {whatIfResult && whatIfResult.allocated_dongs.length > 0 ? (
              <div>
                <div style={{ fontSize: 12, color: '#93a4b4', marginBottom: 12 }}>
                  예산 범위 내에서 취약 고령인구 보호 효과가 가장 큰 상위 <b>{whatIfResult.allocated_dongs.length}개 행정동</b>을 선정했습니다.
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {whatIfResult.allocated_dongs.map((d, i) => (
                    <div key={d.dong_name} className="simulation-dong-card">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span className="candidate-badge">{i + 1}</span>
                          <b style={{ fontSize: 13 }}>{d.dong_name}</b>
                          <span style={{ fontSize: 11, color: '#7a8e9e' }}>{d.district_name}</span>
                        </div>
                        <span style={{ fontSize: 11, color: '#4ade80', fontWeight: 700 }}>
                          +{fmtNumber(d.additional_beneficiaries)}명 보호
                        </span>
                      </div>
                      <div style={{ marginTop: 8 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#889ea8' }}>
                          <span>500m 커버리지 개선: {d.current_coverage_pct}% → <b style={{ color: '#38bdf8' }}>{d.projected_coverage_pct}%</b></span>
                          <span>+{fmtScore(d.projected_coverage_pct - d.current_coverage_pct)}%p 상승</span>
                        </div>
                        <div style={{ height: 6, background: '#172836', borderRadius: 3, overflow: 'hidden', marginTop: 4, display: 'flex' }}>
                          <div style={{ width: `${d.current_coverage_pct}%`, background: '#2563eb' }} />
                          <div style={{ width: `${d.projected_coverage_pct - d.current_coverage_pct}%`, background: '#4ade80' }} />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ padding: '24px 0', textAlign: 'center', color: '#7a8e9e' }}>
                상단의 예산을 설정하고 [⚡ What-If 시뮬레이션] 버튼을 누르세요.
              </div>
            )}
          </div>
        </section>

        {/* 우측: AI 정책 제언서 & 보고서 생성 */}
        <section className="card briefing-document">
          <div className="card-header" style={{ justifyContent: 'space-between' }}>
            <div>
              <div className="card-title">🤖 AI 정책 제언 & 보고서 생성</div>
              <div style={{ fontSize: 11, color: '#8295a4', marginTop: 2 }}>
                선택 행정동: <b style={{ color: '#f8b04c' }}>{selected?.full_adm_name || '전체'}</b>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="primary-button" style={{ padding: '6px 12px', fontSize: 11 }} onClick={onRunBriefing} disabled={loadingBrief || !selected}>
                {loadingBrief ? '생성 중...' : '✦ AI 정책 보고서 생성'}
              </button>
              <button className="secondary-button" style={{ padding: '6px 12px', fontSize: 11 }} onClick={copyBriefing}>
                📋 복사
              </button>
            </div>
          </div>

          <div style={{ padding: '0 16px 16px' }}>
            {briefing?.policy_recommendation ? (
              <div className="ai-briefing-wrap">
                <div className="ai-briefing-badge">
                  {briefing.policy_recommendation.priority_level || '우선 추진 권고'}
                </div>
                <div className="ai-briefing-summary">
                  {briefing.policy_recommendation.summary}
                </div>

                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 12, fontWeight: 800, color: '#f8fafc', marginBottom: 8 }}>📌 맞춤형 권고 사업 목록</div>
                  {briefing.policy_recommendation.recommended_policies?.map((p: any, i: number) => (
                    <div key={i} className="policy-recom-card">
                      <b style={{ color: '#38bdf8', fontSize: 12 }}>{i + 1}. {p.policy_name}</b>
                      <p style={{ margin: '4px 0 0', fontSize: 11, color: '#c3d2dc', lineHeight: 1.5 }}>{p.reason}</p>
                    </div>
                  ))}
                </div>

                <div className="ai-caution-box">
                  <b>⚠️ 정책 수립 시 주의사항:</b> 본 AI 분석은 공간 통계 기반이며, 실제 설치 시 보행자 통행 방해 여부, 한전 인입 전력망 확보, 사유지 저촉 여부를 현장 실사해야 합니다.
                </div>
              </div>
            ) : (
              <div style={{ padding: '36px 16px', textAlign: 'center', color: '#7a8e9e' }}>
                <div style={{ fontSize: 24, marginBottom: 8 }}>📄</div>
                <div>우측 상단의 <b>[✦ AI 정책 보고서 생성]</b> 버튼을 누르면</div>
                <div style={{ fontSize: 11, marginTop: 4 }}>선택된 행정동의 취약 원인에 맞춘 맞춤형 사업 제언서가 자동으로 생성됩니다.</div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────
// Main Navigation Definition (3대 핵심 메뉴)
// ──────────────────────────────────────────────────
const NAV_ITEMS: { key: MainNavKey; icon: string; label: string; desc: string }[] = [
  { key: 'dashboard', icon: '📊', label: '대시보드', desc: '대구 전체 요약 & 히트맵' },
  { key: 'analysis',  icon: '🔍', label: '상세 분석', desc: '취약성 & 접근성 원인 진단' },
  { key: 'policy',    icon: '💡', label: '정책 & 예산', desc: 'What-If 시뮬레이션 & AI브리핑' },
];

// ──────────────────────────────────────────────────
// Root App Component
// ──────────────────────────────────────────────────
function App() {
  const [navKey, setNavKey] = React.useState<MainNavKey>('dashboard');
  const [overview, setOverview] = React.useState<Overview | null>(null);
  const [selected, setSelected] = React.useState<District | null>(null);
  const [selectedDistrict, setSelectedDistrict] = React.useState<string | undefined>();

  // What-If & Policy state
  const [budget, setBudget] = React.useState(50_000_000);
  const [unitCost, setUnitCost] = React.useState(10_000_000);
  const [maxFacilities, setMaxFacilities] = React.useState(5);
  const [facilityType, setFacilityType] = React.useState('스마트쉼터');
  const [whatIfResult, setWhatIfResult] = React.useState<WhatIfResult | null>(null);
  const [loadingWhatIf, setLoadingWhatIf] = React.useState(false);
  const [briefing, setBriefing] = React.useState<any | null>(null);
  const [loadingBrief, setLoadingBrief] = React.useState(false);

  // Load Overview data (기본 취약도+접근성 종합 히트맵 데이터 로드)
  React.useEffect(() => {
    api.overview('vulnerability').then(data => {
      setOverview(data);
      setSelected(curr => curr || data.districts[0]);
    }).catch(err => {
      console.error(err);
      showToast('데이터를 불러오지 못했습니다.');
    });
  }, []);

  // Run What-If on params change
  const runWhatIf = React.useCallback(async () => {
    setLoadingWhatIf(true);
    try {
      const res = await api.simulateWhatIf({ budget, unit_cost: unitCost, max_facilities: maxFacilities, facility_type: facilityType });
      setWhatIfResult(res);
    } catch (e) {
      console.error(e);
      showToast('시뮬레이션 계산 중 오류가 발생했습니다.');
    } finally {
      setLoadingWhatIf(false);
    }
  }, [budget, unitCost, maxFacilities, facilityType]);

  React.useEffect(() => {
    if (overview) {
      runWhatIf();
    }
  }, [budget, unitCost, maxFacilities, facilityType, overview, runWhatIf]);

  // Run AI Briefing
  const runBriefing = async () => {
    if (!selected) return;
    setLoadingBrief(true);
    try {
      const res = await api.briefing({ sgis_adm_cd: selected.sgis_adm_cd, budget, max_facilities: maxFacilities });
      setBriefing(res);
    } catch (e) {
      console.error(e);
      showToast('AI 브리핑 생성에 실패했습니다.');
    } finally {
      setLoadingBrief(false);
    }
  };

  const handleDistrictClick = React.useCallback((districtName: string) => {
    setSelectedDistrict(districtName);
    if (!overview) return;
    const match = overview.districts.find(d => d.district_name === districtName);
    if (match) setSelected(match);
  }, [overview]);

  if (!overview) {
    return (
      <div className="app">
        <div className="loading-screen">
          <div className="spinner" />
          <div style={{ marginTop: 12, fontSize: 14, fontWeight: 700 }}>대구시 폭염 위험도 & 쉼터 데이터 로딩 중...</div>
        </div>
      </div>
    );
  }

  const renderContent = () => {
    switch (navKey) {
      case 'dashboard':
        return (
          <DashboardView
            data={overview}
            selectedDistrict={selectedDistrict}
            selected={selected ?? undefined}
            onDistrictClick={handleDistrictClick}
            onSelect={setSelected}
            onNavigateDetail={() => setNavKey('analysis')}
          />
        );
      case 'analysis':
        return (
          <DetailedAnalysisView
            data={overview}
            selectedDistrict={selectedDistrict}
            selected={selected || overview.districts[0]}
            onDistrictClick={handleDistrictClick}
            onSelect={setSelected}
          />
        );
      case 'policy':
        return (
          <PolicyOptimizationView
            selected={selected ?? undefined}
            budget={budget}
            setBudget={setBudget}
            unitCost={unitCost}
            setUnitCost={setUnitCost}
            maxFacilities={maxFacilities}
            setMaxFacilities={setMaxFacilities}
            facilityType={facilityType}
            setFacilityType={setFacilityType}
            whatIfResult={whatIfResult}
            loadingWhatIf={loadingWhatIf}
            onRunWhatIf={runWhatIf}
            briefing={briefing}
            loadingBrief={loadingBrief}
            onRunBriefing={runBriefing}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="app">
      {/* 3대 통합 사이드바 */}
      <aside className="sidebar">
        <div className="brand">temper<span className="ai">AI</span>ture</div>
        <div className="nav-wrap">
          <div className="nav-label">핵심 정책 메뉴</div>
          {NAV_ITEMS.map(item => (
            <button
              key={item.key}
              className={`nav-item${navKey === item.key ? ' active' : ''}`}
              onClick={() => setNavKey(item.key)}
            >
              <span className="nav-icon">{item.icon}</span>
              <div style={{ textAlign: 'left' }}>
                <div>{item.label}</div>
                <div className="nav-desc">{item.desc}</div>
              </div>
            </button>
          ))}
        </div>

        <div className="sidebar-foot">
          <div className="city-badge">
            <div className="city-emblem">🛡️</div>
            <div>
              대구광역시<br />
              <span style={{ fontWeight: 500, color: '#8598a7' }}>폭염 취약성 진단 & 정책 지원</span>
            </div>
          </div>
          <div style={{ marginTop: 8, fontSize: 10, color: '#687d8e', lineHeight: 1.5 }}>
            SGIS 행정동 경계 · 실시간 시설 API 연동<br />
            취약도+접근성 통합 위험지표(0~100)
          </div>
        </div>
      </aside>

      {/* 워크스페이스 */}
      <section className="workspace">
        <header className="topbar">
          <div className="top-left">
            <div className="select-button">
              <span className="pin-icon">📌</span>
              <b>대구광역시</b>
              <span style={{ color: '#889ea8', fontSize: 12, marginLeft: 8 }}>150개 행정동 전역</span>
            </div>
          </div>
          <div className="top-right">
            <a className="outline-button" href="/api/download/dong-summary.csv" style={{ textDecoration: 'none' }}>
              ⬇️ 행정동 요약 CSV
            </a>
            <div className="divider" />
            <button className="icon-button" aria-label="알림" onClick={() => showToast('대구 전역 폭염 종합 지수 실시간 분석 중')}>🔔</button>
            <button className="icon-button" aria-label="사용자">👤</button>
          </div>
        </header>

        <main className="content">
          {renderContent()}
        </main>
      </section>

      <div className="toast" id="global-toast" />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
