import React from 'react';
import {
  DaeguShelterMap,
  type CityBoundaryCollection,
  type DistrictBoundaryCollection,
  type Shelter,
} from './DaeguShelterMap';

type OverviewResponse = {
  district_boundaries: DistrictBoundaryCollection;
  city_boundary: CityBoundaryCollection;
  shelters: Shelter[];
};

export default function DaeguShelterMapExample() {
  const [data, setData] = React.useState<OverviewResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [selectedDistrict, setSelectedDistrict] = React.useState<string>();

  React.useEffect(() => {
    const controller = new AbortController();
    fetch('/api/overview?metric=vulnerability', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`지도 API 오류: ${response.status}`);
        return response.json() as Promise<OverviewResponse>;
      })
      .then(setData)
      .catch((reason) => {
        if (reason?.name !== 'AbortError') setError(String(reason));
      });
    return () => controller.abort();
  }, []);

  if (error) return <p role="alert">{error}</p>;
  if (!data) return <p>지도를 불러오는 중입니다…</p>;

  return (
    <DaeguShelterMap
      districtBoundaries={data.district_boundaries}
      cityBoundary={data.city_boundary}
      shelters={data.shelters}
      selectedDistrict={selectedDistrict}
      onDistrictClick={setSelectedDistrict}
      onShelterClick={(shelter) => console.info('선택한 쉼터', shelter)}
      height="720px"
    />
  );
}
