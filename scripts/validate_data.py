"""Human-readable validation report for raw and processed layers."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Settings  # noqa: E402
from src.pipeline import run_analysis  # noqa: E402


def main() -> int:
    artifacts = run_analysis(Settings.from_env())
    areas = artifacts.areas
    shelters = artifacts.shelters
    candidates = artifacts.candidates
    area_union = areas.to_crs("EPSG:5179").geometry.union_all()
    shelter_metric = shelters.to_crs("EPSG:5179")
    checks = [
        ("행정동 코드 중복", not areas["adm_cd"].duplicated().any(), int(areas["adm_cd"].duplicated().sum())),
        ("인구 음수", bool((areas["population"] >= 0).all()), int((areas["population"] < 0).sum())),
        (
            "고령인구가 총인구 이하",
            bool((areas["elderly_population"] <= areas["population"]).all()),
            int((areas["elderly_population"] > areas["population"]).sum()),
        ),
        (
            "쉼터 위경도 범위",
            bool(shelters["latitude"].between(35.5, 36.1).all() and shelters["longitude"].between(128.3, 129.0).all()),
            "대구 광역 sanity range",
        ),
        (
            "분석경계 밖 쉼터",
            bool(shelter_metric.geometry.map(area_union.covers).all()),
            int((~shelter_metric.geometry.map(area_union.covers)).sum()),
        ),
        ("행정동 geometry 존재", bool(areas.geometry.notna().all()), int(areas.geometry.isna().sum())),
        ("쉼터 geometry 존재", bool(shelters.geometry.notna().all()), int(shelters.geometry.isna().sum())),
        (
            "중복 쉼터",
            not shelters.duplicated(subset=["name", "latitude", "longitude"]).any(),
            int(shelters.duplicated(subset=["name", "latitude", "longitude"]).sum()),
        ),
        (
            "후보 비용 양수",
            bool((pd.to_numeric(candidates["cost"], errors="coerce") > 0).all()),
            int((pd.to_numeric(candidates["cost"], errors="coerce") <= 0).sum()),
        ),
    ]
    print("AI 폭염 도시처방 데이터 검증")
    print(f"데이터 모드: {artifacts.metadata['data_mode']}")
    print("-" * 72)
    for name, passed, detail in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    failed = [name for name, passed, _ in checks if not passed]
    if failed:
        print(f"\n검증 실패 {len(failed)}건: {', '.join(failed)}")
        return 1
    print(f"\n전체 {len(checks)}개 검증 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


