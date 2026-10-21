"""Publish Haiphong tide data as Home Assistant sensor states."""

import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

DOMAIN = "haiphong_tide"
LOCATION_NAME = "Hải Phòng"
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
TIDE_URL = "https://thegioimoicau.com/dia-danh/hon-dau/trang-1"
API_URL = os.environ.get("SUPERVISOR_ENDPOINT", "http://supervisor") + "/core/api"
LOG = logging.getLogger(DOMAIN)


def parse_tides(html: bytes) -> list[dict[str, Any]]:
    """Extract hourly Hòn Dấu tide heights from the source page."""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    pattern = re.compile(
        r"Dương lịch\s+(\d{1,2}/\d{1,2}/\d{4}).*?"
        r"Thời gian \(h là giờ\)(.*?)(?=Mực nước|TheGioiMoiCau\.Com)",
        re.DOTALL,
    )
    tides = []
    for date_text, values in pattern.findall(text):
        day_date = datetime.strptime(date_text, "%d/%m/%Y").date()
        pairs = re.findall(r"(\d{1,2})h\s+([0-9]+(?:[.,][0-9]+)?)m", values)
        if len(pairs) != 24:
            LOG.warning("Expected 24 hourly values for %s, got %s", date_text, len(pairs))
        day = [
            {
                "date": day_date.isoformat(),
                "time": f"{int(hour):02d}:00",
                "hour": int(hour),
                "height": float(height.replace(",", ".")),
                "tide_type": "hourly",
                "description": f"Hòn Dấu {date_text} {int(hour):02d}:00",
            }
            for hour, height in pairs
        ]
        for index, tide in enumerate(day):
            before = day[index - 1]["height"] if index else tide["height"]
            after = day[index + 1]["height"] if index + 1 < len(day) else tide["height"]
            if tide["height"] >= before and tide["height"] >= after:
                tide["tide_type"] = "high"
            elif tide["height"] <= before and tide["height"] <= after:
                tide["tide_type"] = "low"
        tides.extend(day)
    if not tides:
        raise ValueError("No tide data found on the source page")
    return tides


def _tide_datetime(tide: dict[str, Any]) -> datetime:
    """Return a timezone-aware datetime for a tide entry."""
    return datetime.strptime(
        f"{tide['date']} {tide['time']}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=TIMEZONE)


def _tide_attributes(tide: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": tide["date"],
        "time": tide["time"],
        "height": f"{tide['height']} m",
        "tide_type": tide["tide_type"],
        "description": tide["description"],
        "location": LOCATION_NAME,
    }


def build_sensor_states(
    tides: list[dict[str, Any]], now: datetime
) -> dict[str, dict[str, Any]]:
    """Build the Home Assistant state payload for each tide sensor."""
    points = sorted(
        ((_tide_datetime(tide), tide) for tide in tides),
        key=lambda point: point[0],
    )
    today_tides = [tide for tide in tides if tide["date"] == now.date().isoformat()]
    current_index = max(
        (index for index, (point_time, _) in enumerate(points) if point_time <= now),
        default=0,
    )
    current_time, current_tide = points[current_index]
    next_tide = points[current_index + 1][1] if current_index + 1 < len(points) else None

    current_level = None
    if current_index + 1 < len(points):
        next_time, next_point = points[current_index + 1]
        duration = (next_time - current_time).total_seconds()
        if duration > 0 and current_time <= now <= next_time:
            fraction = (now - current_time).total_seconds() / duration
            current_level = round(
                current_tide["height"]
                + (next_point["height"] - current_tide["height"])
                / 2
                * (1 - math.cos(math.pi * fraction)),
                2,
            )

    def extremum(tide_type: str) -> dict[str, Any] | None:
        return next(
            (tide for tide in today_tides if tide["tide_type"] == tide_type),
            None,
        )

    schedule_points = [
        {
            "datetime": point_time.isoformat(),
            "value": tide["height"],
            "type": tide["tide_type"],
        }
        for point_time, tide in points
    ]
    curve_points = []
    if len(points) >= 2:
        point_index = 0
        point_time = points[0][0]
        end_time = points[-1][0]
        while point_time <= end_time:
            while point_index < len(points) - 2 and point_time > points[point_index + 1][0]:
                point_index += 1
            start, first = points[point_index]
            end, second = points[point_index + 1]
            duration = (end - start).total_seconds()
            fraction = (point_time - start).total_seconds() / duration
            height = first["height"] + (second["height"] - first["height"]) / 2 * (
                1 - math.cos(math.pi * fraction)
            )
            curve_points.append(
                {"datetime": point_time.isoformat(), "value": round(height, 3)}
            )
            point_time += timedelta(minutes=30)

    def state(
        value: Any,
        attributes: dict[str, Any],
        *,
        name: str,
        unit: str | None = None,
        icon: str,
    ) -> dict[str, Any]:
        payload = {"state": "unknown" if value is None else str(value), "attributes": attributes}
        payload["attributes"].update(
            {"friendly_name": name, "icon": icon, "location": LOCATION_NAME}
        )
        if unit:
            payload["attributes"]["unit_of_measurement"] = unit
        return payload

    current_label = f"{current_tide['tide_type'].capitalize()} - {current_tide['time']}h"
    next_label = (
        f"{next_tide['tide_type'].capitalize()} - {next_tide['time']}h"
        if next_tide
        else None
    )
    low_tide = extremum("low")
    high_tide = extremum("high")
    date_range = f"{tides[0]['date']} → {tides[-1]['date']}"
    return {
        f"sensor.{DOMAIN}_current": state(
            current_label, _tide_attributes(current_tide), name="Current Tide", icon="mdi:water"
        ),
        f"sensor.{DOMAIN}_next": state(
            next_label,
            _tide_attributes(next_tide) if next_tide else {},
            name="Next Tide",
            icon="mdi:water-percent",
        ),
        f"sensor.{DOMAIN}_today_low": state(
            low_tide["height"] if low_tide else None,
            {
                "date": low_tide["date"],
                "time": low_tide["time"],
                "description": low_tide["description"],
            }
            if low_tide
            else {},
            name="Today Low Tide",
            unit="m",
            icon="mdi:water-off",
        ),
        f"sensor.{DOMAIN}_today_high": state(
            high_tide["height"] if high_tide else None,
            {
                "date": high_tide["date"],
                "time": high_tide["time"],
                "description": high_tide["description"],
            }
            if high_tide
            else {},
            name="Today High Tide",
            unit="m",
            icon="mdi:water",
        ),
        f"sensor.{DOMAIN}_current_level_hourly": state(
            current_level,
            {"updated_at": now.isoformat()},
            name="Current Tide Level (Hourly)",
            unit="m",
            icon="mdi:waves",
        ),
        f"sensor.{DOMAIN}_schedule": state(
            date_range,
            {"tide_points": schedule_points, "curve_points": curve_points},
            name="Tide Schedule",
            icon="mdi:calendar-month",
        ),
    }


def publish_states(states: dict[str, dict[str, Any]], session: requests.Session) -> None:
    """Create or update sensor states through the Home Assistant REST API."""
    for entity_id, payload in states.items():
        response = session.post(f"{API_URL}/states/{entity_id}", json=payload, timeout=15)
        response.raise_for_status()


def _poll_interval() -> int:
    try:
        with open("/data/options.json", encoding="utf-8") as options_file:
            options = json.load(options_file)
        minutes = int(options.get("poll_minutes", 60))
    except FileNotFoundError:
        minutes = 60
    if not 5 <= minutes <= 240:
        raise ValueError("poll_minutes must be between 5 and 240")
    return minutes * 60


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN is missing; enable homeassistant_api in config.yaml")

    interval = _poll_interval()
    session = requests.Session()
    session.headers.update(
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    while True:
        try:
            response = session.get(
                TIDE_URL,
                headers={"User-Agent": "Home Assistant Haiphong Tide add-on"},
                timeout=30,
            )
            response.raise_for_status()
            tides = parse_tides(response.content)
            states = build_sensor_states(tides, datetime.now(TIMEZONE))
            publish_states(states, session)
            LOG.info("Updated %d Haiphong Tide sensors", len(states))
        except (requests.RequestException, ValueError):
            LOG.exception("Unable to update Haiphong Tide sensors")
        time.sleep(interval)


if __name__ == "__main__":
    main()
