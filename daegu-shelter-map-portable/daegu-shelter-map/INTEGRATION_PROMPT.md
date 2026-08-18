# 다른 웹 프로젝트에 전달할 구현 프롬프트

아래 프롬프트를 대상 웹 프로젝트를 열어 둔 AI 코딩 도구에 그대로 전달한다.

---

이 프로젝트에 첨부한 `DaeguShelterMap.tsx`와 `daegu-shelter-map.css`를 실제 실행되는 페이지에 통합해줘.

먼저 현재 프로젝트가 React/Vite, Next.js, Remix 또는 다른 프레임워크인지 확인하고 기존 라우팅·스타일·데이터 로딩 방식을 유지해라. 예시 코드만 제시하지 말고 실제 페이지에 연결하고 빌드와 실행 검증까지 완료해라.

## 데이터 연결

지도 컴포넌트에는 다음 세 데이터를 전달한다.

```ts
districtBoundaries // 정확히 9개 구·군 GeoJSON FeatureCollection
cityBoundary       // 위 9개 geometry를 union한 대구 전체 GeoJSON
shelters           // shelter_id, name, latitude, longitude를 가진 쉼터 배열
```

기존 API가 다음 구조를 제공하면 그대로 사용한다.

```json
{
  "district_boundaries": { "type": "FeatureCollection", "features": [] },
  "city_boundary": { "type": "FeatureCollection", "features": [] },
  "shelters": []
}
```

구·군 feature의 properties에는 아래 값이 반드시 있어야 한다.

```json
{
  "district_name": "달서구",
  "label_latitude": 35.0,
  "label_longitude": 128.0
}
```

API 이름이나 응답 구조가 다르면 adapter 함수만 추가하고 지도 컴포넌트 내부 규칙은 변경하지 마라. 정적 파일을 사용한다면 같은 구조의 JSON/GeoJSON을 import하거나 fetch해라.

## 설치 의존성

```bash
npm install leaflet react-leaflet leaflet.markercluster
npm install -D @types/leaflet @types/leaflet.markercluster
```

Next.js라면 Leaflet 컴포넌트를 `dynamic(..., { ssr: false })`로 불러오고 필요한 경우 파일 상단에 `use client`를 추가해라.

## 절대 유지할 지도 규칙

1. Basemap은 CartoDB Positron을 사용한다.
2. 대구 전체 geometry 내부에만 `#F3F7E8`, opacity `0.28` fill을 적용한다.
3. 대구 밖에는 mask, polygon fill 또는 흐림 overlay를 만들지 않는다.
4. 화면에는 대구 전체 외곽선과 정확히 9개 구·군 경계만 표시한다. 읍·면·동·리 경계를 추가하지 않는다.
5. 대구 외곽선은 `3.6px`, 구·군 경계는 기본 `1.5px`로 유지한다.
6. 모든 쉼터에 `L.circle({ radius: 500 })`을 생성한다. `CircleMarker`의 pixel radius를 쓰지 않는다.
7. 500m Circle은 MarkerCluster에 넣지 않고 독립 Canvas 레이어에 둔다.
8. MarkerCluster에는 marker만 넣는다. `maxClusterRadius: 50`, `disableClusteringAtZoom: 16`, `zoomToBoundsOnClick: true`, `spiderfyOnMaxZoom: true`를 유지한다.
9. pane z-index는 `fill 310 < radius 350 < district 450 < city 460 < cluster 600 < marker 650 < label 800`을 보장한다.
10. 구·군 라벨은 marker와 cluster보다 앞에 렌더링하고 `pointer-events: none`으로 뒤쪽 cluster 클릭을 방해하지 않게 한다.
11. 라벨은 representative point 기반 `label_latitude`, `label_longitude`를 사용한다.
12. 사용자가 지도를 이동하거나 확대·축소해도 500m Circle, 구·군 경계, 대구 fill, 라벨을 제거하거나 다시 cluster 안에 넣지 않는다.
13. 쉼터 마커에는 이름 tooltip과 실제 데이터가 있는 항목만 표시하는 popup을 유지한다.
14. 전역 CSS를 오염시키지 말고 `.daegu-shelter-map` 아래로 스타일을 제한한다.

## 페이지 통합

- 부모 컨테이너의 폭을 채우고 높이는 기본 680px 또는 페이지 레이아웃에 맞는 명시적 값으로 설정한다.
- 로딩, API 오류, 데이터 없음 상태를 추가한다.
- 기존 헤더·사이드바·테마를 깨뜨리지 않는다.
- 지도 타일 도메인과 API가 CSP/CORS에서 허용되는지 확인한다.

## 완료 전 검증

1. 프로덕션 빌드와 TypeScript 검사를 통과시킨다.
2. 구·군 feature가 정확히 9개인지 확인한다.
3. 대구 내부만 연두색이고 외부에는 overlay가 없는지 확인한다.
4. 축소 상태에서 cluster보다 9개 구·군 라벨이 위에 보이는지 확인한다.
5. 라벨과 cluster가 겹친 위치에서도 cluster 클릭이 가능한지 확인한다.
6. 확대 시 cluster가 marker로 분리되고 모든 500m Circle이 계속 보이는지 확인한다.
7. 다시 축소했을 때 marker만 cluster로 합쳐지고 Circle과 라벨은 유지되는지 확인한다.

완료 후 수정한 파일, 데이터 adapter 위치, 사용한 API, 빌드 결과, 위 7개 검증 결과를 보고해라.

---
