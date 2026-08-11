from __future__ import annotations

from src.data.kma_history import parse_daily_max_temperatures


def test_parse_daily_max_temperatures_from_calendar_table():
    page = """
    <table class="table-col table-cal"><tbody>
      <tr><td><span>1일</span></td><td><span>2일</span></td></tr>
      <tr>
        <td><span>평균기온:30.0℃</span><span>최고기온:34.0℃</span></td>
        <td><span>평균기온:31.0℃</span><span>최고기온:37.2℃</span></td>
      </tr>
    </tbody></table>
    """

    records = parse_daily_max_temperatures(page, 2026, 7)

    assert records == [
        {"date": "2026-07-01", "maximum_temperature_c": 34.0},
        {"date": "2026-07-02", "maximum_temperature_c": 37.2},
    ]
