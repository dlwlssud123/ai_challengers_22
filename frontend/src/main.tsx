import React from 'react';
import ReactDOM from 'react-dom/client';
import { Activity, BarChart3, Bot, Download, MapPin, Moon, RefreshCw, Sun, Users } from 'lucide-react';
import './styles.css';

type ThemeMode = 'light' | 'dark';
type MetricMode = 'vulnerability' | 'accessibility';

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
  grid_unweighted_accessibility_index_exp_d_300?: number;
  grid_unweighted_accessibility_lack_score?: number;
  grid_population_weighted_accessibility_index?: number;
  grid_population_weighted_accessibility_lack_score?: number;
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

type Overview = {
  metadata: Record<string, unknown>;
  kpis: Kpis;
  boundaries: { type: 'FeatureCollection'; features: Feature[] };
  districts: District[];
  shelters: Array<{ shelter_id: string; name: string; address: string; latitude: number; longitude: number; capacity: number }>;
  shades: Array<{ facility_id: string; shelter_id: string; name: string; address: string; latitude: number; longitude: number; shelter_type: string }>;
};

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

function fmtNumber(value?: number) {
  return Number(value || 0).toLocaleString('ko-KR');
}

function fmtScore(value?: number) {
  return Number(value || 0).toFixed(1);
}

function rgba(color: number[] = [100, 116, 139, 160]) {
  const [r, g, b, a = 255] = color;
  return `rgba(${r}, ${g}, ${b}, ${a / 255})`;
}

function flattenCoordinates(feature: Feature): number[][][] {
  const { type, coordinates } = feature.geometry;
  if (type === 'Polygon') return coordinates;
  if (type === 'MultiPolygon') return coordinates.flat();
  return [];
}

function bounds(features: Feature[]) {
  const points = features.flatMap((feature) => flattenCoordinates(feature).flat());
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

function MapView({ data, selected, onSelect }: { data: Overview; selected?: string; onSelect: (d: District) => void }) {
  const b = bounds(data.boundaries.features);
  const width = 760;
  const height = 560;
  const pad = 28;
  const project = ([lon, lat]: number[]) => {
    const x = pad + ((lon - b.minX) / (b.maxX - b.minX || 1)) * (width - pad * 2);
    const y = height - pad - ((lat - b.minY) / (b.maxY - b.minY || 1)) * (height - pad * 2);
    return [x, y];
  };
  const pathFor = (feature: Feature) =>
    flattenCoordinates(feature)
      .map((ring) => ring.map((point, index) => {
        const [x, y] = project(point);
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(' ') + ' Z')
      .join(' ');

  return (
    <div className="map-stage">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="대구 행정동 지도">
        <defs>
          <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M 32 0 L 0 0 0 32" fill="none" stroke="currentColor" strokeOpacity="0.08" />
          </pattern>
        </defs>
        <rect width={width} height={height} fill="url(#grid)" className="map-grid" />
        {data.boundaries.features.map((feature) => {
          const props = feature.properties;
          const isActive = selected === props.sgis_adm_cd;
          return (
            <path
              key={props.sgis_adm_cd}
              d={pathFor(feature)}
              fill={rgba(props.fill_color)}
              stroke={isActive ? '#fff' : 'rgba(255,255,255,.72)'}
              strokeWidth={isActive ? 2.4 : 0.8}
              className="dong-path"
              onClick={() => onSelect(props)}
            >
              <title>{props.full_adm_name}</title>
            </path>
          );
        })}
        {data.shades.slice(0, 900).map((shade) => {
          const [x, y] = project([shade.longitude, shade.latitude]);
          return <rect key={shade.facility_id || shade.shelter_id} x={x - 2.2} y={y - 2.2} width="4.4" height="4.4" className="shade-dot"><title>{shade.name}</title></rect>;
        })}
        {data.shelters.slice(0, 900).map((shelter) => {
          const [x, y] = project([shelter.longitude, shelter.latitude]);
          return <circle key={shelter.shelter_id} cx={x} cy={y} r="2.2" className="shelter-dot"><title>{shelter.name}</title></circle>;
        })}
      </svg>
      <div className="map-legend">
        <b>지도 범례</b>
        <span><i className="swatch red" />높음</span>
        <span><i className="swatch amber" />주의</span>
        <span><i className="swatch blue" />낮음</span>
        <span><i className="swatch dot" />쉼터</span>
        <span><i className="swatch shade" />그늘막</span>
      </div>
    </div>
  );
}

function MetricCard({ icon, label, value, note }: { icon: React.ReactNode; label: string; value: string; note?: string }) {
  return <div className="metric-card"><div className="metric-icon">{icon}</div><div><span>{label}</span><b>{value}</b>{note && <small>{note}</small>}</div></div>;
}

function App() {
  const [theme, setTheme] = React.useState<ThemeMode>('dark');
  const [metric, setMetric] = React.useState<MetricMode>('vulnerability');
  const [overview, setOverview] = React.useState<Overview | null>(null);
  const [selected, setSelected] = React.useState<District | null>(null);
  const [budget, setBudget] = React.useState(50_000_000);
  const [unitCost, setUnitCost] = React.useState(10_000_000);
  const [maxFacilities, setMaxFacilities] = React.useState(5);
  const [allocation, setAllocation] = React.useState<any[]>([]);
  const [briefing, setBriefing] = React.useState<any | null>(null);
  const [loadingBrief, setLoadingBrief] = React.useState(false);

  React.useEffect(() => {
    api.overview(metric).then((next) => {
      setOverview(next);
      setSelected((current) => current || next.districts[0]);
    }).catch(console.error);
  }, [metric]);

  React.useEffect(() => {
    api.allocation({ budget, unit_cost: unitCost, max_facilities: maxFacilities })
      .then((payload) => setAllocation(payload.rows || []))
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

  if (!overview) return <div className={`app ${theme}`}><main className="loading-screen">대구 폭염 데이터를 불러오는 중입니다...</main></div>;
  const selectedFeature = overview.boundaries.features.find((f) => f.properties.sgis_adm_cd === selected?.sgis_adm_cd)?.properties || selected;

  return (
    <div className={`app ${theme}`}>
      <aside className="sidebar">
        <div className="brand">temper<span>AI</span>ture</div>
        <nav>
          <a className="active"><Activity size={19} />대시보드</a>
          <a><MapPin size={19} />행정동 지도</a>
          <a><BarChart3 size={19} />예산 배분</a>
          <a><Bot size={19} />정책 브리핑</a>
        </nav>
        <div className="sidebar-foot">대구광역시 폭염 대응 정책 지원 시스템<br />SGIS 경계 · API/파일 시설 데이터 · 100m 격자 접근성</div>
      </aside>
      <section className="workspace">
        <header className="topbar">
          <div><strong>대구광역시</strong><span> 행정동 폭염 대응 현황</span></div>
          <div className="top-actions">
            <button onClick={() => setMetric(metric === 'vulnerability' ? 'accessibility' : 'vulnerability')}><RefreshCw size={16} />{metric === 'vulnerability' ? '취약도' : '격자 접근성'}</button>
            <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}{theme === 'dark' ? '기본모드' : '다크모드'}</button>
            <a className="button" href="/api/download/dong-summary.csv"><Download size={16} />CSV</a>
          </div>
        </header>
        <main className="content">
          <section className="hero"><h1>AI 폭염 도시처방</h1><p>대구 150개 행정동의 고령인구, 녹지율, 무더위쉼터 접근성을 한 화면에서 비교합니다.</p></section>
          <section className="kpi-grid">
            <MetricCard icon={<MapPin />} label="행정동" value={`${overview.kpis.dong_count}개`} note="SGIS 전체 경계" />
            <MetricCard icon={<Users />} label="60세 이상 고령인구" value={`${fmtNumber(overview.kpis.elderly_population)}명`} />
            <MetricCard icon={<Activity />} label="무더위쉼터" value={`${fmtNumber(overview.kpis.shelter_count)}곳`} note="API 우선" />
            <MetricCard icon={<MapPin />} label="그늘막" value={`${fmtNumber(overview.kpis.shade_count)}곳`} note="API 우선" />
          </section>
          <section className="main-grid">
            <div className="card map-card"><div className="card-header"><b>{metric === 'vulnerability' ? '종합 취약도 지도' : '100m 격자 접근성 지도'}</b><span>행정동을 클릭하세요</span></div><MapView data={overview} selected={selected?.sgis_adm_cd} onSelect={setSelected} /></div>
            <aside className="card detail-card">
              <div className="card-header"><b>{selectedFeature?.full_adm_name || '행정동 선택'}</b></div>
              {selectedFeature && <div className="detail-body">
                <MetricCard icon={<Users />} label="고령인구" value={`${fmtNumber(selectedFeature.elderly_population_60_plus)}명`} note={`${fmtScore(selectedFeature.elderly_ratio_60_plus * 100)}%`} />
                <MetricCard icon={<Activity />} label="인구가중 접근성 부족" value={`${fmtScore(selectedFeature.grid_accessibility_lack_score)}점`} note={`평균거리 ${fmtNumber(selectedFeature.grid_mean_nearest_shelter_distance_m)}m`} />
                <MetricCard icon={<MapPin />} label="쉼터 수" value={`${fmtNumber(selectedFeature.shelter_count)}곳`} note={`녹지율 ${fmtScore(selectedFeature.green_ratio_percent)}%`} />
                <MetricCard icon={<BarChart3 />} label="종합 우선순위" value={`${fmtScore(selectedFeature.priority_score_existing_pipeline)}점`} />
                <button className="primary" onClick={runBriefing} disabled={loadingBrief}>{loadingBrief ? '생성 중...' : 'AI 폭염 대응 추천 받기'}</button>
                {briefing?.policy_recommendation && <div className="briefing"><b>{briefing.policy_recommendation.priority_level}</b><p>{briefing.policy_recommendation.summary}</p>{briefing.policy_recommendation.recommended_policies?.map((p: any, i: number) => <div key={i} className="policy"><strong>{p.policy_name}</strong><span>{p.reason}</span></div>)}</div>}
              </div>}
            </aside>
          </section>
          <section className="bottom-grid">
            <div className="card controls"><div className="card-header"><b>예산·시설 설치 시뮬레이션</b></div><label>시설 1곳 비용<input type="number" value={unitCost} step={1000000} onChange={(e) => setUnitCost(Number(e.target.value))} /></label><label>총예산<input type="number" value={budget} step={1000000} onChange={(e) => setBudget(Number(e.target.value))} /></label><label>최대 시설 수<input type="number" value={maxFacilities} onChange={(e) => setMaxFacilities(Number(e.target.value))} /></label></div>
            <div className="card table-card"><div className="card-header"><b>구·군별 신규 배분안</b></div><table><thead><tr><th>구·군</th><th>우선순위</th><th>기존 쉼터</th><th>신규</th><th>비용</th></tr></thead><tbody>{allocation.map((row) => <tr key={row.region_name}><td>{row.region_name}</td><td>{fmtScore(row.priority_score)}</td><td>{fmtNumber(row.existing_shelters)}</td><td>{fmtNumber(row.new_facilities)}</td><td>{fmtNumber(row.cost)}원</td></tr>)}</tbody></table></div>
          </section>
        </main>
      </section>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
