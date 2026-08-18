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
  height?: string;
  initialCenter?: [number, number];
  initialZoom?: number;
  selectedDistrict?: string;
  labelOffsets?: Record<string, [latitudeDelta: number, longitudeDelta: number]>;
  storageKey?: string;
  showLegend?: boolean;
  onDistrictClick?: (districtName: string) => void;
  onShelterClick?: (shelter: Shelter) => void;
};

const PANE_Z_INDEX = {
  cityFill: 310,
  shelterRadii: 350,
  districtBoundaries: 450,
  cityBoundary: 460,
  selectedRadius: 470,
  shelterClusters: 600,
  shelterMarkers: 650,
  districtLabels: 800,
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
  height = '680px',
  initialCenter = DEFAULT_CENTER,
  initialZoom = DEFAULT_ZOOM,
  selectedDistrict,
  labelOffsets = {},
  storageKey = DEFAULT_STORAGE_KEY,
  showLegend = true,
  onDistrictClick,
  onShelterClick,
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
        <Pane name="daegu-fill" style={{ zIndex: PANE_Z_INDEX.cityFill }} />
        <Pane name="shelter-radii" style={{ zIndex: PANE_Z_INDEX.shelterRadii }} />
        <Pane name="district-boundaries" style={{ zIndex: PANE_Z_INDEX.districtBoundaries }} />
        <Pane name="city-boundary" style={{ zIndex: PANE_Z_INDEX.cityBoundary }} />
        <Pane name="selected-radius" style={{ zIndex: PANE_Z_INDEX.selectedRadius }} />
        <Pane name="shelter-clusters" style={{ zIndex: PANE_Z_INDEX.shelterClusters }} />
        <Pane name="shelter-markers" style={{ zIndex: PANE_Z_INDEX.shelterMarkers }} />
        <Pane name="district-labels" style={{ zIndex: PANE_Z_INDEX.districtLabels }} />

        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
          maxZoom={20}
        />

        <GeoJSON
          data={cityBoundary as GeoJsonObject}
          pane="daegu-fill"
          interactive={false}
          style={{
            color: 'transparent',
            weight: 0,
            fill: true,
            fillColor: '#f3f7e8',
            fillOpacity: 0.28,
          }}
        />
        <ShelterRadiusLayer shelters={shelters} />
        <GeoJSON
          key={`districts-${selectedDistrict ?? 'none'}`}
          data={districtBoundaries as GeoJsonObject}
          pane="district-boundaries"
          style={(feature) => ({
            color: selectedDistrict === feature?.properties?.district_name ? '#26313a' : '#35414a',
            weight: selectedDistrict === feature?.properties?.district_name ? 1.8 : 1.5,
            opacity: 0.9,
            fill: true,
            fillColor: 'transparent',
            fillOpacity: 0,
          })}
          onEachFeature={onEachDistrict}
        />
        <GeoJSON
          data={cityBoundary as GeoJsonObject}
          pane="city-boundary"
          interactive={false}
          style={{ color: '#26313a', weight: 3.6, opacity: 0.98, fill: false }}
        />
        <ShelterClusterLayer shelters={shelters} onSelect={selectShelter} />
        <DistrictLabels districts={districtBoundaries} offsets={labelOffsets} />

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
          <b>지도 범례</b>
          <span><i className="portable-legend-city" />대구 전체 외곽선</span>
          <span><i className="portable-legend-district" />9개 구·군 경계</span>
          <span><i className="portable-legend-radius" />쉼터 500m 반경</span>
          <span><i className="portable-legend-cluster" />쉼터 군집</span>
        </div>
      )}
    </section>
  );
}
