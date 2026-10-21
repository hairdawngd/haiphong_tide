from datetime import datetime
from zoneinfo import ZoneInfo

from haiphong_tide.service import build_sensor_states, parse_tides


def test_parse_tides_extracts_hourly_values_and_turning_points() -> None:
    heights = [str(min(hour, 24 - hour) / 10) for hour in range(24)]
    html = (
        "<p>Dương lịch 21/10/2026 Thời gian (h là giờ) "
        + " ".join(f"{hour}h {height}m" for hour, height in enumerate(heights))
        + " Mực nước"
    ).encode()

    tides = parse_tides(html)

    assert len(tides) == 24
    assert tides[0]["date"] == "2026-10-21"
    assert tides[0]["height"] == 0
    assert tides[12]["tide_type"] == "high"
    assert tides[0]["tide_type"] == "low"


def test_build_sensor_states_publishes_hourly_and_daily_sensors() -> None:
    date = "2026-10-21"
    tides = [
        {
            "date": date,
            "time": f"{hour:02d}:00",
            "height": height,
            "tide_type": tide_type,
            "description": f"Hòn Dấu {hour:02d}:00",
        }
        for hour, height, tide_type in (
            (10, 1.0, "low"),
            (11, 2.0, "high"),
            (12, 1.0, "low"),
        )
    ]
    now = datetime(2026, 10, 21, 10, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    states = build_sensor_states(tides, now)

    assert states["sensor.haiphong_tide_current"]["state"] == "Low - 10:00h"
    assert states["sensor.haiphong_tide_next"]["state"] == "High - 11:00h"
    assert states["sensor.haiphong_tide_today_low"]["state"] == "1.0"
    assert states["sensor.haiphong_tide_today_high"]["state"] == "2.0"
    assert states["sensor.haiphong_tide_current_level_hourly"]["state"] == "1.5"
    assert len(
        states["sensor.haiphong_tide_schedule"]["attributes"]["curve_points"]
    ) == 5
