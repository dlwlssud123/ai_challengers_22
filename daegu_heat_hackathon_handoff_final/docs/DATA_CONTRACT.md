# 배치 분석 데이터 계약서

`src/analysis/dbscan_shap_batch.py`는 원본 4개 자료를 결합해 CSV·PNG·정책 리포트를 생성하는 오프라인 파이프라인이다. 파일을 `data/raw/`에 배치하고 다음처럼 실행한다.

```bash
python src/analysis/dbscan_shap_batch.py \
  --input-dir data/raw --output-dir data/outputs
```

## 파일명 패턴

| 필수 | 파일명 패턴 | 읽는 시트/헤더 |
|---|---|---|
| 필수 | `daegu_heat_vulnerability_v2*.csv` | UTF-8-SIG CSV |
| 필수 | `daegu_future_heat_illness_risk_index_by_admin_dong_2030*.xlsx` | `행정동별 결과`, header=3 |
| 필수 | `daegu_facility_resilience_by_admin_dong_*.xlsx` | `행정동별 결과`, header=3 |
| 선택 | `daegu_response_facility_shortage_by_admin_dong_*.csv` | UTF-8-SIG CSV |

패턴에 맞는 파일은 각각 정확히 하나여야 한다. 필수 입력 3개가 없으면 실행하지 않는다. 선택 파일이 없으면 코드에 명시된 산식으로 `대응시설부족도`를 재계산한다.

## 결합 키와 검증

- 미래위험·시설·부족도는 `행정동코드`로 일대일 결합한다. 숫자 코드의 `.0`은 제거하고 10자리로 맞춘다.
- 지역취약도는 `district_name + dong_name` 정규화키로 결합한다. 공백·마침표·가운뎃점만 정규화한다.
- 중복 키는 임의로 합치지 않고 즉시 실패한다. `duplicate_key_errors.csv`를 확인한다.
- 미결합 행은 삭제하지 않는다. `merge_missing_dongs.csv`에 기록하고 Feature 결측만 중앙값 대체한다.

## 산출물

| 파일 | 소비자 | 용도 |
|---|---|---|
| `daegu_dbscan_cluster_assignments.csv` | 지도/표 화면 | 행정동 군집·표준화 Feature·우선순위 |
| `daegu_facility_recommendations_by_dong.csv` | 추천 카드 | 원인·추천시설·주의사항 |
| `cluster_profiles.csv` | 군집 화면 | 원값·z값 평균과 군집 요약 |
| `daegu_cluster_shap_summary.csv` | SHAP 차트 | 전체/군집별 중요도 |
| `analysis_run_summary.json` | Backend | KPI, 군집별 원인과 추천 |
| `tree_surrogate_validation.json` | QA/프론트 | CV 품질, SHAP 방식 |
| `dbscan_pca_scatter.png`, `cluster_profile_heatmap.png` | 보고서 | 검증용 시각화 |
| `daegu_heat_policy_report.md` | 발표/정책 | ALAN 또는 규칙 기반 리포트 |

경계 GeoJSON은 이 파이프라인의 입력이 아니다. 지도는 별도 공식 행정동 경계를 수급하고 `행정동코드`로 join해야 한다.

## ALAN API

배치 스크립트는 `ALAN_API_KEY`와 `ALAN_API_URL`이 모두 있을 때만 군집 대표값을 보내 정책 리포트를 1회 생성한다. API URL·인증 규격은 실제 ALAN 문서에 맞춰 배포 전에 검증한다. 키가 없거나 호출이 실패하면 로컬 규칙 기반 리포트를 만든다.
