"""Build processed GeoJSON layers from the best available data sources."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import PROCESSED_DIR, Settings  # noqa: E402
from src.pipeline import run_analysis  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    artifacts = run_analysis(settings)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    artifacts.areas.to_file(PROCESSED_DIR / "areas.geojson", driver="GeoJSON")
    artifacts.shelters.to_file(PROCESSED_DIR / "shelters.geojson", driver="GeoJSON")
    artifacts.candidates.to_file(PROCESSED_DIR / "candidates.geojson", driver="GeoJSON")
    artifacts.blindspots.to_file(PROCESSED_DIR / "blindspots.geojson", driver="GeoJSON")
    (PROCESSED_DIR / "metadata.json").write_text(
        json.dumps(artifacts.metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        f"완료: 행정동 {len(artifacts.areas)}개, 쉼터 {len(artifacts.shelters)}개, "
        f"후보 {len(artifacts.candidates)}개, 사각지대 {len(artifacts.blindspots)}개"
    )
    print(f"데이터 모드: {artifacts.metadata['data_mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


