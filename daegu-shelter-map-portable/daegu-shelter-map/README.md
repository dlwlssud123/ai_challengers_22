# 재사용 가능한 대구 무더위쉼터 지도

현재 프로젝트의 지도만 다른 React 웹으로 옮길 수 있도록 대시보드 의존성을 제거한 패키지입니다.

## 포함 파일

- `DaeguShelterMap.tsx`: 독립 지도 컴포넌트
- `daegu-shelter-map.css`: 지도 전용 스타일
- `IntegrationExample.tsx`: API 연결 예제
- `INTEGRATION_PROMPT.md`: 다른 웹 프로젝트에서 AI 코딩 도구에 전달할 프롬프트

## 설치

```bash
npm install leaflet react-leaflet leaflet.markercluster
npm install -D @types/leaflet @types/leaflet.markercluster
```

두 지도 파일을 대상 프로젝트의 컴포넌트 폴더에 복사하고 다음처럼 사용합니다.

```tsx
<DaeguShelterMap
  districtBoundaries={payload.district_boundaries}
  cityBoundary={payload.city_boundary}
  shelters={payload.shelters}
  height="720px"
/>
```

현재 프로젝트에서는 다음 API 응답을 그대로 연결할 수 있습니다.

```text
GET /api/overview?metric=vulnerability
```

필수 데이터 계약:

```ts
type DistrictBoundaryProperties = {
  district_name: string;
  label_latitude: number;
  label_longitude: number;
};

type Shelter = {
  shelter_id: string;
  name: string;
  latitude: number;
  longitude: number;
  address?: string | null;
  capacity?: number | null;
};
```

`districtBoundaries`는 정확히 9개 구·군 feature, `cityBoundary`는 9개 구·군을 union한 대구 전체 feature여야 합니다.

## Next.js 사용 시

Leaflet은 브라우저 전용이므로 컴포넌트를 동적 import 하여 SSR을 끕니다.

```tsx
import dynamic from 'next/dynamic';

const Map = dynamic(
  () => import('./DaeguShelterMap').then((module) => module.DaeguShelterMap),
  { ssr: false },
);
```

## 고정된 지도 규칙

- CartoDB Positron basemap
- 대구 내부 fill `#F3F7E8`, opacity `0.28`
- 모든 쉼터에 실제 거리 `L.circle(radius: 500)`
- 500m Circle과 MarkerCluster는 별도 레이어
- pane 순서: fill 310, radius 350, 구·군 450, 대구 외곽 460, cluster 600, marker 650, label 800
- 구·군 라벨은 `pointer-events: none`

타일과 API는 대상 웹의 CSP/CORS 정책에서 허용되어야 합니다.
