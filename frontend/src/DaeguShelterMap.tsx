import React from 'react';
import L from 'leaflet';
import 'leaflet.markercluster';
import type { FeatureCollection, GeoJsonObject, Geometry } from 'geojson';
import {
  Circle,
  GeoJSON,
  MapContainer,
  Marker,
  Pane,
  TileLayer,
  useMap,
  useMapEvents,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet.markercluster/dist/MarkerCluster.css';
import './daegu-shelter-map.css';

export type DistrictBoundaryProperties = {
  district_name: string;
  label_latitude: number;
  label_longitude: number;
  [key: string]: unknown;
};

export type DistrictBoundaryCollection = FeatureCollection<Geometry, DistrictBoundaryProperties>;
export type CityBoundaryCollection = FeatureCollection<Geometry, { name?: string }>;

export type Shelter = {
  shelter_id: string;
  name: string;
  latitude: number;
  longitude: number;
  address?: string | null;
  capacity?: number | null;
  shelter_type?: string | null;
  operating_status?: string | null;
  basic_operation_days?: string | null;
  basic_start_time?: string | null;
  basic_end_time?: string | null;
  weekday_open?: boolean | null;
  weekend_open?: boolean | null;
  night_open?: boolean | null;
  [key: string]: unknown;
};

export type DaeguShelterMapProps = {
  districtBoundaries: DistrictBoundaryCollection;
  cityBoundary: CityBoundaryCollection;
  shelters: Shelter[];
  /** 행정동 단위 GeoJSON — properties에 fill_color(number[]) 포함 */
  dongBoundaries?: FeatureCollection;
  height?: string;
  initialCenter?: [number, number];
  initialZoom?: number;
  selectedDistrict?: string;
  labelOffsets?: Record<string, [latitudeDelta: number, longitudeDelta: number]>;
  storageKey?: string;
  showLegend?: boolean;
  metricMode?: string;
  onDistrictClick?: (districtName: string) => void;
  onShelterClick?: (shelter: Shelter) => void;
  /** 행정동 클릭 시 해당 feature.properties 전달 */
  onDongClick?: (properties: Record<string, unknown>) => void;
};

const PANE_Z_INDEX = {
  cityFill: 310,
  dongBoundaries: 320,
  shelterRadii: 325,
  districtBoundaries: 315,
  cityBoundary: 470,
  selectedRadius: 470,
  shelterClusters: 600,
  shelterMarkers: 650,
  dongLabels: 430,
  districtLabels: 440,
} as const;

const DEFAULT_CENTER: [number, number] = [35.9669, 128.6258];
const DEFAULT_ZOOM = 9;
const DEFAULT_STORAGE_KEY = 'daegu-shelter-map-viewport';

function escapeHtml(value: unknown) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/** 점수에 따른 5색 히트맵 색상 및 등급 (지도 폴리곤, 툴팁, 범례 완전 일치 단일 함수) */
export function getScoreGradeAndColor(scoreVal: unknown): {
  grade: string;
  color: string;
  badgeClass: string;
  score: number;
} {
  const num = Number(scoreVal);
  if (isNaN(num)) {
    return { grade: '보통', color: 'rgba(2, 132, 199, 0.88)', badgeClass: 'vuln-moderate', score: 30 };
  }
  // 1. 심각 (80~100점): 선명한 빨강
  if (num >= 80) {
    return { grade: '심각', color: 'rgba(220, 38, 38, 0.88)', badgeClass: 'vuln-severe', score: num };
  }
  // 2. 위험 (60~80점): 선명한 주황
  if (num >= 60) {
    return { grade: '위험', color: 'rgba(249, 115, 22, 0.88)', badgeClass: 'vuln-danger', score: num };
  }
  // 3. 주의 (40~60점): 선명한 노랑/황색
  if (num >= 40) {
    return { grade: '주의', color: 'rgba(234, 179, 8, 0.88)', badgeClass: 'vuln-warn', score: num };
  }
  // 4. 보통 (20~40점): 선명한 하늘색/파랑
  if (num >= 20) {
    return { grade: '보통', color: 'rgba(2, 132, 199, 0.88)', badgeClass: 'vuln-moderate', score: num };
  }
  // 5. 양호 (0~20점): 선명한 초록
  return { grade: '양호', color: 'rgba(22, 163, 74, 0.88)', badgeClass: 'vuln-safe', score: num };
}

function rgbaFromArray(colorValue: unknown): string | null {
  if (!Array.isArray(colorValue) || colorValue.length < 3) return null;
  const nums = colorValue.map(Number);
  const r = nums[0];
  const g = nums[1];
  const b = nums[2];
  const a = nums.length >= 4 ? nums[3] : 255;
  if (![r, g, b, a].every(Number.isFinite)) return null;
  return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + Math.max(0, Math.min(1, a / 255)) + ')';
}

function getAccessibilityGrade(accessScoreVal: unknown): {
  grade: string;
  badgeClass: string;
  score: number;
} {
  const num = Number(accessScoreVal);
  if (isNaN(num)) return { grade: '보통', badgeClass: 'vuln-moderate', score: 30 };
  if (num <= 20) return { grade: '심각', badgeClass: 'vuln-severe', score: num };
  if (num <= 40) return { grade: '위험', badgeClass: 'vuln-danger', score: num };
  if (num <= 60) return { grade: '주의', badgeClass: 'vuln-warn', score: num };
  if (num <= 80) return { grade: '보통', badgeClass: 'vuln-moderate', score: num };
  return { grade: '양호', badgeClass: 'vuln-safe', score: num };
}

export function getFeatureColor(props: any): string {
  const apiColor = rgbaFromArray(props?.fill_color);
  if (apiColor) return apiColor;
  const score = props?.map_score ?? props?.composite_risk_score ?? props?.vulnerability_score;
  return getScoreGradeAndColor(score).color;
}

function createShelterPopup(shelter: Shelter) {
  const capacity = shelter.capacity == null
    ? null
    : `${Number(shelter.capacity).toLocaleString('ko-KR')}명`;
  const hours = [shelter.basic_start_time, shelter.basic_end_time].filter(Boolean).join('~');

  return `
    <article class="portable-shelter-popup">
      <h3>${escapeHtml(shelter.name)}</h3>
      <div class="portable-shelter-popup__summary">
        ${capacity ? `<strong>수용인원 ${escapeHtml(capacity)}</strong>` : ''}
        <span>분석 반경 500m</span>
      </div>
      ${shelter.address ? `<p><b>주소</b><span>${escapeHtml(shelter.address)}</span></p>` : ''}
      ${shelter.shelter_type ? `<p><b>유형</b><span>${escapeHtml(shelter.shelter_type)}</span></p>` : ''}
      ${shelter.operating_status ? `<p><b>운영</b><span>${escapeHtml(shelter.operating_status)}</span></p>` : ''}
      ${hours ? `<p><b>시간</b><span>${escapeHtml(hours)}</span></p>` : ''}
    </article>
  `;
}

function createShelterIcon() {
  return L.divIcon({
    className: 'portable-shelter-marker',
    html: '<span aria-hidden="true"></span>',
    iconSize: [14, 14],
    iconAnchor: [7, 7],
    popupAnchor: [0, -8],
  });
}

function createClusterIcon(cluster: L.MarkerCluster) {
  const count = cluster.getChildCount();
  const sizeName = count < 10 ? 'small' : count < 50 ? 'medium' : 'large';
  const size = count < 10 ? 38 : count < 50 ? 46 : 56;
  return L.divIcon({
    className: `portable-shelter-cluster portable-shelter-cluster--${sizeName}`,
    html: `<span>${count}</span>`,
    iconSize: [size, size],
  });
}

function ShelterRadiusLayer({ shelters }: { shelters: Shelter[] }) {
  const map = useMap();

  React.useEffect(() => {
    const renderer = L.canvas({ pane: 'shelter-radii', padding: 0.5 });
    const layer = L.layerGroup();

    shelters.forEach((shelter) => {
      if (!Number.isFinite(shelter.latitude) || !Number.isFinite(shelter.longitude)) return;
      L.circle([shelter.latitude, shelter.longitude], {
        radius: 500,
        pane: 'shelter-radii',
        renderer,
        color: '#43c8cc',
        weight: 1,
        opacity: 0.65,
        fill: true,
        fillColor: '#43c8cc',
        fillOpacity: 0.015,
        interactive: false,
      }).addTo(layer);
    });

    layer.addTo(map);
    return () => {
      layer.clearLayers();
      map.removeLayer(layer);
      if (map.hasLayer(renderer)) map.removeLayer(renderer);
    };
  }, [map, shelters]);

  return null;
}

function ShelterClusterLayer({
  shelters,
  onSelect,
}: {
  shelters: Shelter[];
  onSelect: (shelter: Shelter) => void;
}) {
  const map = useMap();

  React.useEffect(() => {
    const group = L.markerClusterGroup({
      maxClusterRadius: 50,
      disableClusteringAtZoom: 16,
      zoomToBoundsOnClick: true,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      removeOutsideVisibleBounds: true,
      chunkedLoading: true,
      clusterPane: 'shelter-clusters',
      iconCreateFunction: createClusterIcon,
    });
    const icon = createShelterIcon();

    shelters.forEach((shelter) => {
      if (!Number.isFinite(shelter.latitude) || !Number.isFinite(shelter.longitude)) return;
      const marker = L.marker([shelter.latitude, shelter.longitude], {
        icon,
        keyboard: true,
        pane: 'shelter-markers',
        title: shelter.name,
      });
      marker.bindTooltip(escapeHtml(shelter.name), {
        direction: 'top',
        offset: [0, -8],
        className: 'portable-shelter-tooltip',
      });
      marker.bindPopup(createShelterPopup(shelter), {
        minWidth: 220,
        maxWidth: 310,
        className: 'portable-shelter-leaflet-popup',
      });
      marker.on('click', () => onSelect(shelter));
      group.addLayer(marker);
    });

    group.addTo(map);
    return () => {
      group.clearLayers();
      map.removeLayer(group);
    };
  }, [map, onSelect, shelters]);

  return null;
}

function DistrictLabels({
  districts,
  offsets,
}: {
  districts: DistrictBoundaryCollection;
  offsets: NonNullable<DaeguShelterMapProps['labelOffsets']>;
}) {
  return districts.features.map((feature) => {
    const { district_name: name, label_latitude: latitude, label_longitude: longitude } = feature.properties;
    const [latitudeDelta = 0, longitudeDelta = 0] = offsets[name] ?? [];
    if (!name || !Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
    return (
      <Marker
        key={name}
        position={[latitude + latitudeDelta, longitude + longitudeDelta]}
        pane="district-labels"
        interactive={false}
        icon={L.divIcon({
          className: 'portable-district-label',
          html: `<span>${escapeHtml(name)}</span>`,
          iconSize: [84, 24],
          iconAnchor: [42, 12],
        })}
      />
    );
  });
}

function ViewportPersistence({ storageKey }: { storageKey: string }) {
  const map = useMapEvents({ moveend: persist, zoomend: persist });

  function persist() {
    try {
      const center = map.getCenter();
      window.sessionStorage.setItem(storageKey, JSON.stringify({
        center: [center.lat, center.lng],
        zoom: map.getZoom(),
      }));
    } catch {
      // Storage is optional.
    }
  }

  return null;
}

/** 폴리곤/멀티폴리곤 좌표 평균으로 centroid 계산 */
function computeCentroid(geometry: any): [number, number] | null {
  try {
    const type: string = geometry?.type ?? '';
    const coords = geometry?.coordinates;
    if (!coords) return null;
    let allPts: number[][] = [];
    if (type === 'Polygon') {
      allPts = coords[0] ?? [];
    } else if (type === 'MultiPolygon') {
      for (const poly of coords) allPts.push(...(poly[0] ?? []));
    }
    if (!allPts.length) return null;
    const sumLat = allPts.reduce((s: number, p: number[]) => s + (p[1] ?? 0), 0);
    const sumLon = allPts.reduce((s: number, p: number[]) => s + (p[0] ?? 0), 0);
    return [sumLat / allPts.length, sumLon / allPts.length];
  } catch {
    return null;
  }
}

/**
 * 행정동 이름 라벨 — zoom >= 12 일 때만 표시
 * pointer-events: none 으로 코우즈를 뒷에 있는 feature에서 받는다
 */
function DongLabels({ dongs }: { dongs: FeatureCollection }) {
  const map = useMap();
  const [zoom, setZoom] = React.useState(map.getZoom());
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) });

  // zoom 12 미만이면 레이블 숨김
  if (zoom < 12) return null;

  return (
    <>
      {dongs.features.map((feature, i) => {
        const centroid = computeCentroid(feature.geometry);
        if (!centroid) return null;
        const name = String((feature.properties as any)?.adm_name ?? '');
        if (!name) return null;
        return (
          <Marker
            key={i}
            position={[centroid[0] - 0.0015, centroid[1]]}
            pane="dong-labels"
            interactive={false}
            icon={L.divIcon({
              className: 'portable-dong-label',
              html: `<span>${escapeHtml(name)}</span>`,
              iconSize: [64, 18],
              iconAnchor: [32, 9],
            })}
          />
        );
      })}
    </>
  );
}

function readViewport(
  storageKey: string,
  fallbackCenter: [number, number],
  fallbackZoom: number,
) {
  if (typeof window === 'undefined') return { center: fallbackCenter, zoom: fallbackZoom };
  try {
    const stored = JSON.parse(window.sessionStorage.getItem(storageKey) || 'null');
    if (
      Array.isArray(stored?.center)
      && stored.center.length === 2
      && stored.center.every(Number.isFinite)
      && Number.isFinite(stored.zoom)
    ) {
      return stored as { center: [number, number]; zoom: number };
    }
  } catch {
    // Use the supplied viewport.
  }
  return { center: fallbackCenter, zoom: fallbackZoom };
}

export function DaeguShelterMap({
  districtBoundaries,
  cityBoundary,
  shelters,
  dongBoundaries,
  height = '680px',
  initialCenter = DEFAULT_CENTER,
  initialZoom = DEFAULT_ZOOM,
  selectedDistrict,
  labelOffsets = {},
  storageKey = DEFAULT_STORAGE_KEY,
  showLegend = true,
  metricMode = 'vulnerability',
  onDistrictClick,
  onShelterClick,
  onDongClick,
}: DaeguShelterMapProps) {
  const viewport = React.useMemo(
    () => readViewport(storageKey, initialCenter, initialZoom),
    [initialCenter, initialZoom, storageKey],
  );
  const [selectedShelter, setSelectedShelter] = React.useState<Shelter | null>(null);
  const selectShelter = React.useCallback((shelter: Shelter) => {
    setSelectedShelter(shelter);
    onShelterClick?.(shelter);
  }, [onShelterClick]);
  const onEachDistrict = React.useCallback((feature: any, layer: L.Layer) => {
    const districtName = String(feature?.properties?.district_name ?? '');
    if (districtName && onDistrictClick) layer.on('click', () => onDistrictClick(districtName));
  }, [onDistrictClick]);
  const onEachDong = React.useCallback((feature: any, layer: L.Layer) => {
    const props = feature?.properties ?? {};
    const name = String(props.adm_name ?? props.full_adm_name ?? '');
    
    const scoreRaw = props.map_score ?? props.composite_risk_score ?? props.vulnerability_score;
    const isAccessibility = metricMode === 'accessibility';
    const { grade, badgeClass, score } = isAccessibility
      ? getAccessibilityGrade(scoreRaw)
      : getScoreGradeAndColor(scoreRaw);
    const cScoreStr = score.toFixed(1);

    const pDriver = isAccessibility ? (
      Number(props.shelter_count ?? 0) <= 0 ? '행정동 내 무더위쉼터 없음' :
      score <= 20 ? '쉼터 접근성 심각 부족' :
      score <= 40 ? '쉼터 접근거리 과다' :
      score <= 60 ? '일부 격자 접근성 부족' : '쉼터 접근성 양호'
    ) : props.primary_risk_driver || (
      score >= 80 ? '쉼터 사각지대 및 고령화' :
      score >= 60 ? '쉼터 접근거리 과다' :
      score >= 40 ? '도심 열섬 및 녹지 결여' : '양호한 열환경'
    );
    const scoreLabel = isAccessibility
      ? '쉼터 접근성'
      : metricMode === 'future-risk'
        ? '온열질환 위험'
        : '종합 취약도';
    const shelters = props.shelter_count ?? 0;
    const coverage = props.coverage_ratio_500m_area != null
      ? (Number(props.coverage_ratio_500m_area) * 100).toFixed(1) + '%' : '-';
    const elderly = props.elderly_population_60_plus != null
      ? Number(props.elderly_population_60_plus).toLocaleString('ko-KR') + '명' : '-';
    const dist = props.grid_mean_nearest_shelter_distance_m != null
      ? Math.round(Number(props.grid_mean_nearest_shelter_distance_m)).toLocaleString('ko-KR') + 'm' : '-';

    if (name) {
      layer.bindTooltip(
        `<div class="dong-info-tooltip">
          <div class="dit-header">
            <div>
              <b class="dit-name">${escapeHtml(name)}</b>
              <span class="dit-district">${escapeHtml(props.district_name || '')}</span>
            </div>
            <span class="dit-grade ${badgeClass}">${grade}</span>
          </div>
          <div class="dit-driver">
            <span class="dit-driver-badge">주요 원인</span>
            <span>${escapeHtml(pDriver)}</span>
          </div>
          <div class="dit-grid">
            <div class="dit-row"><span>${scoreLabel}</span><b class="highlight">${cScoreStr}점</b></div>
            <div class="dit-row"><span>쉼터 커버리지</span><b>${coverage}</b></div>
            <div class="dit-row"><span>무더위쉼터</span><b>${shelters}곳</b></div>
            <div class="dit-row"><span>고령인구(60+)</span><b>${elderly}</b></div>
            <div class="dit-row"><span>평균 접근거리</span><b>${dist}</b></div>
            <div class="dit-row"><span>녹지비율</span><b>${props.green_ratio_percent != null ? Number(props.green_ratio_percent).toFixed(1) + '%' : '-'}</b></div>
          </div>
          <div class="dit-hint">클릭 시 우측 원인 진단으로 이동</div>
        </div>`,
        {
          direction: 'top',
          sticky: true,
          className: 'portable-dong-tooltip',
          offset: [0, -6],
        },
      );
    }
    if (onDongClick) {
      layer.on('click', () => onDongClick(feature?.properties ?? {}));
    }
  }, [metricMode, onDongClick]);

  return (
    <section
      className="daegu-shelter-map"
      style={{ '--daegu-map-height': height } as React.CSSProperties}
      aria-label="대구광역시 무더위쉼터 지도"
    >
      <MapContainer
        center={viewport.center}
        zoom={viewport.zoom}
        minZoom={8}
        maxZoom={19}
        scrollWheelZoom
        doubleClickZoom
        touchZoom
        preferCanvas
      >
        <Pane name="daegu-fill"         style={{ zIndex: PANE_Z_INDEX.cityFill, pointerEvents: 'none' }} />
        <Pane name="dong-boundaries"    style={{ zIndex: PANE_Z_INDEX.dongBoundaries, pointerEvents: 'auto' }} />
        <Pane name="shelter-radii"      style={{ zIndex: PANE_Z_INDEX.shelterRadii, pointerEvents: 'none' }} />
        <Pane name="district-boundaries" style={{ zIndex: PANE_Z_INDEX.districtBoundaries, pointerEvents: 'none' }} />
        <Pane name="city-boundary"      style={{ zIndex: PANE_Z_INDEX.cityBoundary, pointerEvents: 'none' }} />
        <Pane name="selected-radius"    style={{ zIndex: PANE_Z_INDEX.selectedRadius, pointerEvents: 'none' }} />
        <Pane name="shelter-clusters"   style={{ zIndex: PANE_Z_INDEX.shelterClusters }} />
        <Pane name="shelter-markers"    style={{ zIndex: PANE_Z_INDEX.shelterMarkers }} />
        <Pane name="dong-labels"        style={{ zIndex: PANE_Z_INDEX.dongLabels }} />
        <Pane name="district-labels"    style={{ zIndex: PANE_Z_INDEX.districtLabels }} />

        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
          maxZoom={20}
        />

        {/* ① 대구 전체 내부 배경 */}
        <GeoJSON
          data={cityBoundary as GeoJsonObject}
          pane="daegu-fill"
          interactive={false}
          style={{
            color: 'transparent',
            weight: 0,
            fill: false,
          }}
        />

        {/* ② 행정동 경계 — 5색 히트맵 선명하게 렌더링 */}
        {dongBoundaries && dongBoundaries.features.length > 0 && (
          <GeoJSON
            key={`dongs-${dongBoundaries.features.length}-${String((dongBoundaries.features[0]?.properties as any)?.map_score ?? '')}`}
            data={dongBoundaries as GeoJsonObject}
            pane="dong-boundaries"
            style={(feature: any) => ({
              fillColor: getFeatureColor(feature?.properties),
              fillOpacity: 0.85,
              color: 'rgba(255,255,255,0.42)',
              weight: 0.45,
              opacity: 0.72,
              fill: true,
            })}
            onEachFeature={onEachDong}
          />
        )}

        <ShelterRadiusLayer shelters={shelters} />

        {/* ③ 구·군 경계 — fill 없음, 두꺼운 실선 */}
        <GeoJSON
          key={`districts-${selectedDistrict ?? 'none'}`}
          data={districtBoundaries as GeoJsonObject}
          pane="district-boundaries"
          style={(feature: any) => {
            const isSelected = selectedDistrict === feature?.properties?.district_name;
            return {
              color: isSelected ? 'rgba(255,90,43,0.92)' : 'rgba(15,31,44,0.38)',
              weight: isSelected ? 2.4 : 1.1,
              opacity: isSelected ? 0.95 : 0.42,
              dashArray: undefined,
              fill: false,
              fillOpacity: 0,
            };
          }}
          interactive={false}
          onEachFeature={onEachDistrict}
        />

        {/* ④ 대구 외곽선 — 가장 두꺼운 실선 */}
        <GeoJSON
          data={cityBoundary as GeoJsonObject}
          pane="city-boundary"
          interactive={false}
          style={{ color: 'transparent', weight: 0, opacity: 0, fill: false }}
        />
        <ShelterClusterLayer shelters={shelters} onSelect={selectShelter} />
        <DistrictLabels districts={districtBoundaries} offsets={labelOffsets} />
        {dongBoundaries && dongBoundaries.features.length > 0 && (
          <DongLabels dongs={dongBoundaries} />
        )}

        {selectedShelter && (
          <Circle
            center={[selectedShelter.latitude, selectedShelter.longitude]}
            radius={500}
            pane="selected-radius"
            interactive={false}
            pathOptions={{
              color: '#118d98',
              weight: 3,
              opacity: 1,
              fillColor: '#43c8cc',
              fillOpacity: 0.085,
            }}
          />
        )}
        <ViewportPersistence storageKey={storageKey} />
      </MapContainer>

      {showLegend && (
        <div className="portable-map-legend" aria-hidden="true">
          <b>폭염 취약도 등급</b>
          <span><i className="portable-legend-vuln-severe" />심각 (80~100)</span>
          <span><i className="portable-legend-vuln-high" />위험 (60~80)</span>
          <span><i className="portable-legend-vuln-mid" />주의 (40~60)</span>
          <span><i className="portable-legend-vuln-moderate" />보통 (20~40)</span>
          <span><i className="portable-legend-vuln-low" />양호 (0~20)</span>
          <hr style={{ border: 'none', borderTop: '1px solid rgba(255,255,255,0.12)', margin: '4px 0' }} />
          <span><i className="portable-legend-radius" />쉼터 500m 반경</span>
          <span><i className="portable-legend-cluster" />쉼터 군집</span>
        </div>
      )}
    </section>
  );
}
