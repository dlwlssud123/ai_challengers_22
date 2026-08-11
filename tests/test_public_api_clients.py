from __future__ import annotations

from src.data.kma_surface import absolute_heat_hazard_score, parse_surface_text
from src.data.safety_shelters import normalize_safety_shelters


def test_safety_shelters_keep_only_valid_daegu_rows():
    payload = {
        "body": [
            {
                "RSTR_FCLTY_NO": 1,
                "RSTR_NM": "대구 쉼터",
                "RN_DTL_ADRES": "대구광역시 수성구 달구벌대로 1",
                "USE_PSBL_NMPR": 20,
                "FCLTY_TY": "001",
                "LO": 128.62,
                "LA": 35.85,
                "CHCK_MATTER_WKEND_HDAY_OPN_AT": "Y",
                "CHCK_MATTER_NIGHT_OPN_AT": "N",
            },
            {
                "RSTR_FCLTY_NO": 2,
                "RSTR_NM": "인접지역 쉼터",
                "RN_DTL_ADRES": "경상북도 경산시 중앙로 1",
                "USE_PSBL_NMPR": 10,
                "LO": 128.74,
                "LA": 35.82,
            },
        ]
    }

    shelters = normalize_safety_shelters(payload)

    assert len(shelters) == 1
    assert shelters.iloc[0]["name"] == "대구 쉼터"
    assert bool(shelters.iloc[0]["weekend_open"]) is True
    assert shelters.crs.to_epsg() == 4326


def test_kma_surface_parser_uses_help_header_names():
    text = """
# TM STN WD WS PA PS TA TD HM RN
202608111500 143 18 2.1 995.0 1004.0 34.2 25.0 61.0 0.0
"""

    result = parse_surface_text(text)

    assert result == {
        "station_id": 143,
        "observed_at_kst": "202608111500",
        "temperature_c": 34.2,
        "humidity_percent": 61.0,
    }


def test_kma_surface_parser_uses_numbered_help_descriptors():
    text = """
#  1. TM     : 관측시각 (KST)
#  2. STN    : 국내 지점번호
#  3. TA     : 기온 (C)
#  4. HM     : 상대습도 (%)
202608111600 143 28.0 47.0
"""

    assert parse_surface_text(text)["temperature_c"] == 28.0
    assert parse_surface_text(text)["humidity_percent"] == 47.0


def test_absolute_heat_hazard_score_is_bounded_and_increases_with_heat():
    assert absolute_heat_hazard_score(20, 30) == 0
    assert absolute_heat_hazard_score(40, 100) == 100
    assert absolute_heat_hazard_score(34, 60) > absolute_heat_hazard_score(30, 60)
