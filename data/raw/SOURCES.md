# 제공 원본 데이터

아래 CSV는 사용자가 제공한 공공데이터 원문의 내용과 인코딩을 변경하지 않고 복사했습니다.
`areas.geojson`은 공식 API 응답을 분석 스키마로 결합한 재현 가능한 산출물입니다.

| 표준 파일명 | 원본 | 용도 |
|---|---|---|
| `shelters.csv` | 대구광역시 수성구_수성구 홈페이지 무더위 쉼터_20250902.csv | 실제 기존 쉼터 131개 |
| `elderly_facilities.csv` | 대구광역시 수성구_노인복지시설_20250915.csv | 후보시설 주소 원천 |
| `administrative_facilities.csv` | 대구광역시_수성구_행정기관_20251114.csv | 후보시설 주소·행정동명 원천 |
| `weather_extremum.csv` | extremum_20260811102646.csv | 대구 ASOS 2016–2025년 7–8월 월별 기온 참고자료 |
| `areas.geojson` | SGIS 경계·인구 + KMA 초단기실황 | 실제 23개 행정동, SGIS 2024 + KMA 2026-08-11 09:00 T1H/REH |
| `daegu_dong_population_202607.csv` | 2026년 7월 행정안전부 주민등록 거주자 연령별 인구 구·군별 CSV 9개 | 대구 150개 행정동 총인구와 60세 이상 고령인구; 논공읍·다사읍 출장소는 본청에 합산 |
| `daegu_dong_green_ratio.csv` | 사용자 제공 행정동별 녹지율 | 대구 150개 행정동 녹지율(%) |

CSV 원문은 CP949 인코딩이며 `areas.geojson`은 UTF-8입니다. 앱은 현재 실제 공공데이터 모드로
실행되고, `areas.geojson`이 없을 때만 경계·인구·동별기상을 명시적인 `DEMO SAMPLE`로 전환합니다.
