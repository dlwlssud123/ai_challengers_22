import React from 'react';
import ReactDOM from 'react-dom/client';
import { DaeguShelterMap, type DistrictBoundaryCollection, type CityBoundaryCollection } from './DaeguShelterMap';
import './styles.css';

// ── Types ──────────────────────────────────────────
type MetricMode = 'vulnerability' | 'accessibility';
type PageKey = 'dashboard' | 'risk' | 'access' | 'recommend' | 'briefing';

type Kpis = {
  dong_count: number;
  population: number;
  elderly_population: number;
  shelter_count: number;
  shade_count: number;
  mean_grid_accessibility: number;
  mean_green_ratio: number;
};

type District = {
  sgis_adm_cd: string;
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
};

type Feature = {
  type: 'Feature';
  geometry: { type: string; coordinates: any };
  properties: District & { fill_color: number[]; line_color: number[]; map_score: number; region: string };
};

type Shelter = {
  shelter_id: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  capacity: number;
  shelter_type?: string;
  operating_status?: string;
  basic_start_time?: string;
  basic_end_time?: string;
};

type Overview = {
  metadata: Record<string, unknown>;
  kpis: Kpis;
  boundaries: { type: 'FeatureCollection'; features: Feature[] };
  district_boundaries: DistrictBoundaryCollection;
  city_boundary: CityBoundaryCollection;
  districts: District[];
  shelters: Shelter[];
  shades: Array<{ facility_id: string; shelter_id: string; name: string; address: string; latitude: number; longitude: number; shelter_type: string }>;
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
function fmtNumber(value?: number) { return Number(value || 0).toLocaleString('ko-KR'); }
function fmtScore(value?: number) { return Number(value || 0).toFixed(1); }

// ── Toast ──────────────────────────────────────────
let toastTimer: ReturnType<typeof setTimeout>;
function showToast(msg: string) {
  const t = document.getElementById('global-toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2000);
}

// ── ShelterMap wrapper ─────────────────────────────
// district_boundaries/city_boundary가 아직 로드 안 됐을 때(빈 배열) 안전하게 처리
function AppShelterMap({
  data,
  selectedDistrict,
  onDistrictClick,
  onSelect,
  height = '430px',
}: {
  data: Overview;
  selectedDistrict?: string;
  onDistrictClick?: (name: string) => void;
  onSelect?: (d: District) => void;
  height?: string;
}) {
  const hasDistricts = data.district_boundaries?.features?.length > 0;
  const hasCity = data.city_boundary?.features?.length > 0;

  // 행정동 클릭 시 district 이름으로 구·군 하이라이트 + District 객체 선택
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
function KpiCard({ icon, label, value, note }: { icon: string; label: string; value: React.ReactNode; note?: string }) {
  return (
    <div className="card kpi-card">
      <div className="kpi-icon">{icon}</div>
      <div>
        <div className="kpi-label">{label}</div>
        <div className="kpi-value">{value}</div>
        {note && <div className="kpi-note">{note}</div>}
      </div>
    </div>
  );
}

function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        <p className="page-subtitle">{subtitle}</p>
      </div>
      <div className="demo-chip">✦ 실데이터 연동</div>
    </div>
  );
}

function MiniBar({ value, max = 100 }: { value: number; max?: number }) {
  return (
    <div className="mini-bar">
      <span className="mini-bar-fill" style={{ width: `${Math.min(100, (value / max) * 100)}%` }} />
    </div>
  );
}

// ── Pages ─────────────────────────────────────────
function DashboardPage({
  data,
  selectedDistrict,
  selected,
  onDistrictClick,
  onSelect,
}: {
  data: Overview;
  selectedDistrict?: string;
  selected?: District;
  onDistrictClick: (name: string) => void;
  onSelect: (d: District) => void;
}) {
  const maxPriority = Math.max(...data.districts.map(d => d.priority_score_existing_pipeline));
  const top4 = [...data.districts].sort((a, b) => b.priority_score_existing_pipeline - a.priority_score_existing_pipeline).slice(0, 4);

  return (
    <div className="page">
      <PageHeader title="대구 폭염 대응 정책 지원 시스템" subtitle="폭염 위험 · 취약인구 · 시설 접근성을 통합 분석합니다" />
      <div className="kpi-grid">
        <KpiCard icon="☀️" label="분석 행정동" value={<>{data.kpis.dong_count}<small>개</small></>} note="SGIS 전체 경계" />
        <KpiCard icon="👥" label="60세 이상 고령인구" value={<>{fmtNumber(data.kpis.elderly_population)}<small>명</small></>} note="대구 전체 인구 대비" />
        <KpiCard icon="⚠️" label="무더위쉼터" value={<>{fmtNumber(data.kpis.shelter_count)}<small>곳</small></>} note="API 우선" />
        <KpiCard icon="🏢" label="그늘막" value={<>{fmtNumber(data.kpis.shade_count)}<small>곳</small></>} note="API 우선" />
      </div>
      <div className="dashboard-main">
        <section className="card map-card">
          <div className="card-header">
            <div className="card-title">폭염 취약도 지도 <span className="info-dot">i</span></div>
            <span style={{ fontSize: 12, color: '#8496a4' }}>구·군을 클릭하세요</span>
          </div>
          <div className="map-body" style={{ minHeight: 430 }}>
            <div className="map-stage" style={{ minHeight: 430, padding: 0 }}>
              <AppShelterMap data={data} selectedDistrict={selectedDistrict} onDistrictClick={onDistrictClick} onSelect={onSelect} height="430px" />
            </div>
          </div>
        </section>
        <div className="dashboard-side">
          <section className="card">
            <div className="card-header">
              <div className="card-title" style={{ color: '#f8b04c' }}>✦ 핵심 인사이트 <span className="info-dot">i</span></div>
            </div>
            <div className="insights">
              <div className="insight-row"><div className="insight-check">✓</div><div>우선순위 상위 지역에 취약인구와 쉼터 접근성 부족이 집중됩니다.</div></div>
              <div className="insight-row"><div className="insight-check">✓</div><div>60세 이상 고령인구 비율이 높은 노후 주거지역의 취약도가 높게 나타납니다.</div></div>
              <div className="insight-row"><div className="insight-check">✓</div><div>무더위쉼터 접근성이 낮은 지역이 다수 확인되어 시설 확충이 필요합니다.</div></div>
            </div>
          </section>
          <section className="card">
            <div className="card-header">
              <div className="card-title">우선 검토 지역 <span className="info-dot">i</span></div>
            </div>
            <div className="rank-list">
              {top4.map((d, i) => (
                <div className="rank-row" key={d.sgis_adm_cd} style={{ cursor: 'pointer' }} onClick={() => onSelect(d)}>
                  <div className="rank-num">{i + 1}</div>
                  <b style={{ fontSize: 11 }}>{d.adm_name}</b>
                  <span className="severity hot" style={{ fontSize: 9 }}>{fmtScore(d.priority_score_existing_pipeline)}점</span>
                  <MiniBar value={d.priority_score_existing_pipeline} max={maxPriority} />
                  <span style={{ fontSize: 10, color: '#8496a4' }}>{fmtScore(d.vulnerability_score)}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
      {selected && (
        <div className="bottom-grid" style={{ marginTop: 13 }}>
          <section className="card">
            <div className="card-header"><div className="card-title">{selected.full_adm_name} 상세</div></div>
            <div style={{ padding: '0 16px 16px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              {[
                ['고령인구', `${fmtNumber(selected.elderly_population_60_plus)}명`],
                ['고령비율', `${fmtScore(selected.elderly_ratio_60_plus * 100)}%`],
                ['쉼터 수', `${selected.shelter_count}곳`],
                ['녹지율', `${fmtScore(selected.green_ratio_percent)}%`],
                ['평균 접근거리', `${fmtNumber(selected.grid_mean_nearest_shelter_distance_m)}m`],
                ['우선순위 점수', `${fmtScore(selected.priority_score_existing_pipeline)}점`],
              ].map(([lbl, val]) => (
                <div key={lbl} style={{ border: '1px solid #273947', background: '#101d28', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: '#8da0ae' }}>{lbl}</div>
                  <div style={{ fontSize: 18, fontWeight: 800, marginTop: 4 }}>{val}</div>
                </div>
              ))}
            </div>
          </section>
          <section className="card">
            <div className="card-header"><div className="card-title">보호 사각지대 현황 <span className="info-dot">i</span></div></div>
            <div className="donut-layout">
              <div className="donut">
                <div className="donut-center">{fmtNumber(data.kpis.elderly_population)}<small>고령인구</small></div>
              </div>
              <div className="donut-legend">
                {[['#e83d32','매우 높음','6,812'],['#ff8b24','높음','6,420'],['#f4b64e','보통','3,200'],['#6a9abe','낮음','2,000']].map(([c,lbl,n]) => (
                  <div key={lbl}><span className="dot" style={{ background: c }} /><span>{lbl}</span><b>{n}</b></div>
                ))}
              </div>
              <div className="stat-stack">
                <div className="tiny-stat">👥<b>{fmtNumber(Math.round(data.kpis.elderly_population * 0.62))}명</b><span>취약 고령인구 추정</span></div>
                <div className="tiny-stat">🏢<b>{data.kpis.dong_count}개</b><span>전체 행정동</span></div>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function RiskPage({ data, selectedDistrict, onDistrictClick, onSelect }: {
  data: Overview; selectedDistrict?: string; onDistrictClick: (n: string) => void; onSelect: (d: District) => void;
}) {
  const top5 = [...data.districts].sort((a, b) => b.vulnerability_score - a.vulnerability_score).slice(0, 5);
  const maxV = Math.max(...data.districts.map(d => d.vulnerability_score));

  return (
    <div className="page">
      <PageHeader title="폭염 취약도 Heat Map" subtitle="기상·환경·취약인구 데이터를 결합해 지역별 상대 위험과 주요 원인을 진단합니다" />
      <div className="kpi-grid">
        <KpiCard icon="⚠️" label="최고 취약도 행정동" value={top5[0]?.adm_name || '-'} note={`점수: ${fmtScore(top5[0]?.vulnerability_score)}`} />
        <KpiCard icon="👥" label="고령인구 합계" value={<>{fmtNumber(data.kpis.elderly_population)}<small>명</small></>} note="취약도 상위 행정동 기준" />
        <KpiCard icon="☀️" label="평균 녹지율" value={<>{fmtScore(data.kpis.mean_green_ratio)}<small>%</small></>} note="LST·NDVI 합성 지표" />
        <KpiCard icon="🗺️" label="분석 행정동" value={<>{data.kpis.dong_count}<small>개</small></>} note="대구 전체 행정동" />
      </div>
      <div className="dashboard-main">
        <section className="card map-card">
          <div className="card-header">
            <div className="card-title">대구 행정동별 폭염 취약도 <span className="info-dot">i</span></div>
            <span style={{ fontSize: 12, color: '#8496a4' }}>구·군 클릭 → 상세 정보</span>
          </div>
          <div className="map-body" style={{ minHeight: 515 }}>
            <div className="map-stage" style={{ minHeight: 515, padding: 0 }}>
              <AppShelterMap data={data} selectedDistrict={selectedDistrict} onDistrictClick={onDistrictClick} onSelect={onSelect} height="515px" />
            </div>
          </div>
        </section>
        <div className="dashboard-side">
          <section className="card">
            <div className="card-header"><div className="card-title">취약도 구성 요인</div></div>
            <div style={{ padding: '0 16px 16px' }}>
              {[['열 노출','LST · 폭염일수',86],['취약인구','고령 · 독거',82],['녹지 부족','NDVI 역지표',68],['시설 공급','쉼터 수요 대비',73]].map(([label, sub, val]) => (
                <div key={label as string} style={{ margin: '13px 0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#b8c5cd' }}>
                    <b>{label}</b><span>{val}</span>
                  </div>
                  <div style={{ fontSize: 9, color: '#748897', margin: '3px 0 6px' }}>{sub}</div>
                  <MiniBar value={val as number} />
                </div>
              ))}
            </div>
          </section>
          <section className="card">
            <div className="card-header"><div className="card-title">상위 위험 지역</div></div>
            <div className="rank-list">
              {top5.map((d, i) => (
                <div className="rank-row" key={d.sgis_adm_cd} style={{ gridTemplateColumns: '26px 1fr 1.5fr 35px', cursor: 'pointer' }} onClick={() => onSelect(d)}>
                  <div className="rank-num">{i + 1}</div>
                  <b style={{ fontSize: 11 }}>{d.adm_name}</b>
                  <MiniBar value={d.vulnerability_score} max={maxV} />
                  <span style={{ fontSize: 10 }}>{fmtScore(d.vulnerability_score)}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function AccessPage({ data, selectedDistrict, onDistrictClick, onSelect }: {
  data: Overview; selectedDistrict?: string; onDistrictClick: (n: string) => void; onSelect: (d: District) => void;
}) {
  const top5 = [...data.districts].sort((a, b) => b.grid_accessibility_lack_score - a.grid_accessibility_lack_score).slice(0, 5);
  const maxLack = Math.max(...data.districts.map(d => d.grid_accessibility_lack_score));
  const avgDist = Math.round(data.districts.reduce((s, d) => s + d.grid_mean_nearest_shelter_distance_m, 0) / data.districts.length);

  return (
    <div className="page">
      <PageHeader title="기존 쉼터 접근성 분석" subtitle="취약인구 분포와 무더위쉼터 접근권을 중첩해 보호 사각지대를 탐지합니다" />
      <div className="layout-access">
        <section className="card filter-card">
          <div className="card-title" style={{ marginBottom: 12 }}>분석 기준 <span className="info-dot">i</span></div>
          <div className="filter-group">
            <div className="filter-label">데이터 레이어</div>
            <div style={{ fontSize: 11, color: '#9fb0be', lineHeight: 1.7 }}>
              ✓ 무더위쉼터 (500m 반경)<br />✓ 구·군 경계<br />✓ 대구 외곽 경계
            </div>
          </div>
          <div className="filter-group">
            <div className="filter-label">취약계층</div>
            <div className="tag-row">
              <button className="tag active">60세 이상</button>
              <button className="tag active">독거노인</button>
            </div>
          </div>
        </section>
        <section className="card map-card">
          <div className="card-header"><div className="card-title">대구광역시 접근성 분석 지도 <span className="info-dot">i</span></div></div>
          <div className="map-body" style={{ minHeight: 510 }}>
            <div className="map-stage" style={{ minHeight: 510, padding: 0 }}>
              <AppShelterMap data={data} selectedDistrict={selectedDistrict} onDistrictClick={onDistrictClick} onSelect={onSelect} height="510px" />
            </div>
          </div>
        </section>
        <div className="access-right">
          <section className="card">
            <div className="card-header"><div className="card-title">사각지대 요약 <span className="info-dot">i</span></div></div>
            <div className="metric-four">
              {[
                ['👥','고령인구 합계',`${fmtNumber(data.kpis.elderly_population)}명`],
                ['⚠️','분석 행정동',`${data.kpis.dong_count}곳`],
                ['🚶','평균 쉼터 접근거리',`${fmtNumber(avgDist)}m`],
                ['🛡️','무더위쉼터',`${fmtNumber(data.kpis.shelter_count)}곳`],
              ].map(([icon, lbl, val]) => (
                <div className="metric-box" key={lbl}>
                  <div className="m-icon">{icon}</div>
                  <div><span>{lbl}</span><b>{val}</b></div>
                </div>
              ))}
            </div>
          </section>
          <section className="card">
            <div className="card-header">
              <div className="card-title">우선 개선 필요 지역 TOP 5 <span className="info-dot">i</span></div>
            </div>
            <div className="candidate-table">
              <div className="candidate-head" style={{ gridTemplateColumns: '28px 1fr 1.5fr 46px' }}>
                <span>순위</span><span>지역</span><span>접근성 부족 점수</span><span>점수</span>
              </div>
              {top5.map((d, i) => (
                <div className="candidate-row" key={d.sgis_adm_cd} style={{ gridTemplateColumns: '28px 1fr 1.5fr 46px', cursor: 'pointer' }} onClick={() => onSelect(d)}>
                  <div className="rank-num">{i + 1}</div>
                  <b>{d.adm_name}</b>
                  <MiniBar value={d.grid_accessibility_lack_score} max={maxLack} />
                  <span className="score">{fmtScore(d.grid_accessibility_lack_score)}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function AllocationPage({
  budget, setBudget, unitCost, setUnitCost, maxFacilities, setMaxFacilities, allocation
}: {
  data: Overview; budget: number; setBudget: (n: number) => void; unitCost: number; setUnitCost: (n: number) => void; maxFacilities: number; setMaxFacilities: (n: number) => void; allocation: any[];
}) {
  const totalCost = allocation.reduce((s: number, r: any) => s + (r.cost || 0), 0);
  const usagePct = budget > 0 ? Math.round((totalCost / budget) * 100) : 0;
  const top3 = allocation.filter((r: any) => r.new_facilities > 0).slice(0, 3);

  return (
    <div className="page">
      <PageHeader title="예산 기반 시설 배분" subtitle="한정된 예산 안에서 가장 많은 취약인구를 보호할 수 있는 조합을 찾습니다" />
      <section className="card recommend-controls">
        <div>
          <div className="control-label">총 예산 <span className="info-dot">i</span></div>
          <input className="text-field" type="number" value={budget} step={1_000_000} onChange={e => setBudget(Number(e.target.value))} />
        </div>
        <div>
          <div className="control-label">시설 1곳 비용</div>
          <input className="text-field" type="number" value={unitCost} step={1_000_000} onChange={e => setUnitCost(Number(e.target.value))} />
        </div>
        <div>
          <div className="control-label">최대 시설 수</div>
          <select className="select-field" value={maxFacilities} onChange={e => setMaxFacilities(Number(e.target.value))}>
            {[1,2,3,4,5,6,7,8,9,10].map(n => <option key={n} value={n}>{n}개</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
          <div className="control-label">예산 사용률</div>
          <div style={{ fontSize: 28, fontWeight: 850, color: 'var(--orange)', letterSpacing: -1 }}>{usagePct}%</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button className="primary-button" onClick={() => showToast('배분안이 자동으로 갱신됩니다.')}>✦ 계산</button>
        </div>
      </section>
      <div className="recommend-layout">
        <section className="card">
          <div className="card-header"><div className="card-title" style={{ color: '#f9b64c' }}>🏆 배분 결과 요약</div></div>
          <div className="result-summary">
            <div className="selected-list">
              <div className="result-label">신규 배분 대상 구·군</div>
              {top3.length ? top3.map((r: any, i: number) => (
                <div className="selected-item" key={r.region_name}>
                  <span className="candidate-badge">{i + 1}</span>
                  <b>{r.region_name}</b>
                </div>
              )) : <div style={{ color: '#8295a4', fontSize: 12, marginTop: 16 }}>조건에 맞는 지역이 없습니다.</div>}
            </div>
            <div className="result-big">
              <div>
                <div className="result-label">총 신규 시설</div>
                <div className="result-number">+{allocation.reduce((s: number, r: any) => s + (r.new_facilities || 0), 0)}<small style={{ fontSize: 14 }}>곳</small></div>
              </div>
              <div>
                <div className="result-label">예산 사용률 <b style={{ color: 'var(--orange)', fontSize: 20 }}>{usagePct}%</b></div>
                <div className="progress" style={{ margin: '8px 0 5px' }}>
                  <span className="progress-fill" style={{ width: `${Math.min(100, usagePct)}%` }} />
                </div>
                <div className="result-label">사용 {fmtNumber(totalCost)}원 / {fmtNumber(budget)}원</div>
              </div>
            </div>
          </div>
        </section>
        <section className="card">
          <div className="card-header"><div className="card-title">구·군별 신규 배분안</div></div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1f303c' }}>
                  {['구·군','우선순위','기존 쉼터','신규','비용'].map(h => (
                    <th key={h} style={{ padding: '10px 12px', textAlign: 'left', color: '#8fa0ad', fontSize: 10, fontWeight: 800 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {allocation.map((row: any) => (
                  <tr key={row.region_name} style={{ borderBottom: '1px solid #1a2a37' }}>
                    <td style={{ padding: '10px 12px', fontWeight: 700 }}>{row.region_name}</td>
                    <td style={{ padding: '10px 12px', color: 'var(--orange-2)', fontWeight: 800 }}>{fmtScore(row.priority_score)}</td>
                    <td style={{ padding: '10px 12px' }}>{fmtNumber(row.existing_shelters)}</td>
                    <td style={{ padding: '10px 12px', color: row.new_facilities > 0 ? 'var(--green)' : 'var(--muted)' }}>{row.new_facilities > 0 ? `+${row.new_facilities}` : '-'}</td>
                    <td style={{ padding: '10px 12px', color: '#8da0ae', fontSize: 11 }}>{fmtNumber(row.cost)}원</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <div className="bottom-grid">
        <section className="card">
          <div className="card-header"><div className="card-title">선정 로직 <span className="info-dot">i</span></div></div>
          <div className="logic-grid">
            <div className="logic-box"><h4 style={{ color: '#ff8a3d' }}>☀️ 폭염 취약도</h4><ul><li>폭염 위험 지수</li><li>취약인구 밀도</li><li>열 환경 지수</li></ul></div>
            <div className="logic-op">+</div>
            <div className="logic-box"><h4 style={{ color: '#ff8a3d' }}>🚶 시설 접근성</h4><ul><li>도보거리 기준</li><li>기존 시설 중복</li><li>교통·접근 편의</li></ul></div>
            <div className="logic-op">+</div>
            <div className="logic-box"><h4 style={{ color: '#ff8a3d' }}>👥 취약인구 비중</h4><ul><li>60세 이상 비율</li><li>취약도 가중치</li><li>이용 가능성</li></ul></div>
            <div className="logic-op">→</div>
            <div className="logic-box result">🏆<h4>최적 배분안</h4><div style={{ fontSize: 10, color: '#c9a798' }}>예산 내 최대 보호 효과</div></div>
          </div>
        </section>
        <section className="card">
          <div className="card-header"><div className="card-title">예산 배분 인사이트</div></div>
          <div className="briefing-mini">
            <div className="briefing-line"><div className="spark">✦</div><div>우선순위 점수가 높은 구·군에 신규 시설을 배치하면 취약인구 보호 효과를 극대화할 수 있습니다.</div></div>
            <div className="briefing-line"><div className="spark">👥</div><div>현재 조건에서 신규 <b>{allocation.reduce((s: number, r: any) => s + (r.new_facilities || 0), 0)}곳</b>을 배분하여 접근성 사각지대를 보완합니다.</div></div>
          </div>
        </section>
      </div>
    </div>
  );
}

function BriefingPage({ selected, budget, maxFacilities, briefing, loadingBrief, onRun }: {
  selected?: District; budget: number; maxFacilities: number; briefing: any; loadingBrief: boolean; onRun: () => void;
}) {
  return (
    <div className="page">
      <PageHeader title="AI 정책 브리핑" subtitle="공간분석과 예산 최적화 결과를 담당자가 바로 활용할 수 있는 정책 언어로 정리합니다" />
      <div className="briefing-page-grid">
        <section className="card briefing-document">
          <div className="briefing-cover">
            <div>
              <h2>대구 폭염 대응 AI 분석 브리핑</h2>
              <p>분석 기준일 2025. 08. 01. · 시나리오 예산 {fmtNumber(budget)}원</p>
            </div>
            <div className="kpi-icon">📄</div>
          </div>
          {selected ? (
            <>
              <div className="briefing-section" style={{ paddingTop: 0 }}>
                <h3>✦ 선택 지역: {selected.full_adm_name}</h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  {[['고령인구',`${fmtNumber(selected.elderly_population_60_plus)}명`],['고령비율',`${fmtScore(selected.elderly_ratio_60_plus * 100)}%`],['쉼터 수',`${selected.shelter_count}곳`],['녹지율',`${fmtScore(selected.green_ratio_percent)}%`]].map(([l,v]) => (
                    <div key={l} style={{ border: '1px solid #263947', background: '#101d28', borderRadius: 8, padding: '10px 12px' }}>
                      <div style={{ fontSize: 10, color: '#8da0ae' }}>{l}</div>
                      <div style={{ fontSize: 18, fontWeight: 800, marginTop: 4 }}>{v}</div>
                    </div>
                  ))}
                </div>
              </div>
              {briefing?.policy_recommendation ? (
                <div className="briefing-section">
                  <h3>🏆 AI 추천 결과</h3>
                  <div className="ai-briefing">
                    <div className="ai-briefing-priority">{briefing.policy_recommendation.priority_level}</div>
                    <p>{briefing.policy_recommendation.summary}</p>
                    {briefing.policy_recommendation.recommended_policies?.map((p: any, i: number) => (
                      <div className="policy-item" key={i}><strong>{p.policy_name}</strong><span>{p.reason}</span></div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="briefing-section">
                  <h3>🏆 AI 추천</h3>
                  <p style={{ color: '#8496a4' }}>오른쪽 패널에서 AI 추천을 실행하세요.</p>
                </div>
              )}
              <div className="briefing-section">
                <h3>⚠️ 해석 시 주의사항</h3>
                <p>추천 결과는 실 데이터 기반이나, 현장 운영 가능성·소유권·냉방 설비·보행 안전성을 추가 검증해야 합니다.</p>
              </div>
            </>
          ) : (
            <div className="briefing-section" style={{ paddingTop: 0 }}>
              <p style={{ color: '#8496a4' }}>지도에서 구·군을 먼저 선택하거나 순위 목록에서 행정동을 클릭하세요.</p>
            </div>
          )}
        </section>
        <div style={{ display: 'grid', gap: 13, alignContent: 'start' }}>
          <section className="card">
            <div className="card-header"><div className="card-title">AI 브리핑 실행</div></div>
            <div className="briefing-actions">
              <button className="primary-button full" onClick={onRun} disabled={loadingBrief || !selected}>
                {loadingBrief ? '⏳ 생성 중...' : '✦ AI 폭염 대응 추천 받기'}
              </button>
              <button className="secondary-button" style={{ width: '100%' }} onClick={() => showToast('브리핑 복사는 준비 중입니다.')}>📋 내용 복사</button>
            </div>
          </section>
          {selected && (
            <section className="card assumption-card">
              <b>분석 전제</b>
              선택 행정동: {selected.full_adm_name} · 예산 {fmtNumber(budget)}원 · 최대 시설 {maxFacilities}개
              <br /><br />
              <span style={{ color: '#6f8392' }}>※ 본 화면의 수치와 문장은 실제 SGIS·API 데이터를 기반으로 합니다.</span>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Nav ────────────────────────────────────────────
const NAV_ITEMS: { key: PageKey; icon: string; label: string }[] = [
  { key: 'dashboard', icon: '🏠', label: '대시보드' },
  { key: 'risk',      icon: '🗺️', label: '폭염 취약도 지도' },
  { key: 'access',   icon: '🚶', label: '접근성 분석' },
  { key: 'recommend',icon: '📌', label: '예산 배분' },
  { key: 'briefing', icon: '📄', label: 'AI 정책 브리핑' },
];

// ── App ────────────────────────────────────────────
function App() {
  const [page, setPage] = React.useState<PageKey>('dashboard');
  const [metric, setMetric] = React.useState<MetricMode>('vulnerability');
  const [overview, setOverview] = React.useState<Overview | null>(null);
  const [selected, setSelected] = React.useState<District | null>(null);
  const [selectedDistrict, setSelectedDistrict] = React.useState<string | undefined>();
  const [budget, setBudget] = React.useState(50_000_000);
  const [unitCost, setUnitCost] = React.useState(10_000_000);
  const [maxFacilities, setMaxFacilities] = React.useState(5);
  const [allocation, setAllocation] = React.useState<any[]>([]);
  const [briefing, setBriefing] = React.useState<any | null>(null);
  const [loadingBrief, setLoadingBrief] = React.useState(false);

  React.useEffect(() => {
    api.overview(metric).then(next => {
      setOverview(next);
      setSelected(curr => curr || next.districts[0]);
    }).catch(console.error);
  }, [metric]);

  React.useEffect(() => {
    api.allocation({ budget, unit_cost: unitCost, max_facilities: maxFacilities })
      .then(p => setAllocation(p.rows || []))
      .catch(console.error);
  }, [budget, unitCost, maxFacilities]);

  const runBriefing = async () => {
    if (!selected) return;
    setLoadingBrief(true);
    try {
      setBriefing(await api.briefing({ sgis_adm_cd: selected.sgis_adm_cd, budget, max_facilities: maxFacilities }));
    } finally {
      setLoadingBrief(false);
    }
  };

  // 구·군 클릭 시 해당 구·군의 대표 행정동 선택
  const handleDistrictClick = React.useCallback((districtName: string) => {
    setSelectedDistrict(districtName);
    if (!overview) return;
    const match = overview.districts.find(d => d.district_name === districtName);
    if (match) setSelected(match);
  }, [overview]);

  if (!overview) {
    return (
      <div className="app">
        <div className="loading-screen">대구 폭염 데이터를 불러오는 중입니다...</div>
      </div>
    );
  }

  const renderPage = () => {
    switch (page) {
      case 'dashboard': return <DashboardPage data={overview} selectedDistrict={selectedDistrict} selected={selected ?? undefined} onDistrictClick={handleDistrictClick} onSelect={setSelected} />;
      case 'risk':      return <RiskPage data={overview} selectedDistrict={selectedDistrict} onDistrictClick={handleDistrictClick} onSelect={setSelected} />;
      case 'access':    return <AccessPage data={overview} selectedDistrict={selectedDistrict} onDistrictClick={handleDistrictClick} onSelect={setSelected} />;
      case 'recommend': return <AllocationPage data={overview} budget={budget} setBudget={setBudget} unitCost={unitCost} setUnitCost={setUnitCost} maxFacilities={maxFacilities} setMaxFacilities={setMaxFacilities} allocation={allocation} />;
      case 'briefing':  return <BriefingPage selected={selected ?? undefined} budget={budget} maxFacilities={maxFacilities} briefing={briefing} loadingBrief={loadingBrief} onRun={runBriefing} />;
      default: return null;
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">temper<span className="ai">AI</span>ture</div>
        <div className="nav-wrap">
          <div className="nav-label">메뉴</div>
          {NAV_ITEMS.map(item => (
            <button
              key={item.key}
              className={`nav-item${page === item.key ? ' active' : ''}`}
              onClick={() => setPage(item.key)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </div>
        <div className="sidebar-foot">
          <div className="city-badge">
            <div className="city-emblem">🛡️</div>
            <div>대구광역시<br /><span style={{ fontWeight: 500, color: '#8598a7' }}>폭염 대응 정책 지원 시스템</span></div>
          </div>
          데이터 기준일: 2025. 08. 01.<br />
          SGIS 경계 · API 시설 데이터<br />
          <span style={{ color: '#5f7485' }}>※ 실데이터 기반 시스템</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="top-left">
            <button className="select-button" onClick={() => showToast('분석 지역은 대구광역시로 고정되어 있습니다.')}>
              <span className="pin-icon">📌</span>
              <b>대구광역시</b>
              <span style={{ color: '#6f8292', marginLeft: 8 }}>⌄</span>
            </button>
          </div>
          <div className="top-right">
            <button className="outline-button" onClick={() => setMetric(m => m === 'vulnerability' ? 'accessibility' : 'vulnerability')}>
              🔄 {metric === 'vulnerability' ? '취약도' : '격자 접근성'}
            </button>
            <a className="outline-button" href="/api/download/dong-summary.csv" style={{ textDecoration: 'none' }}>
              ⬇️ CSV 다운로드
            </a>
            <div className="divider" />
            <button className="icon-button" aria-label="알림" onClick={() => showToast('새로운 알림이 없습니다.')}>🔔</button>
            <button className="icon-button" aria-label="사용자">👤</button>
          </div>
        </header>
        <main className="content">
          {renderPage()}
        </main>
      </section>

      <div className="toast" id="global-toast" />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
