"""Data coordinator for Haiphong Tide integration."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, HAIPHONG_TIDE_URL, LOCATION_NAME, SCAN_INTERVAL, TIDE_HIGH, TIDE_LOW, TIDE_TIMEZONE

_LOGGER = logging.getLogger(__name__)


class HaiphongTideCoordinator(DataUpdateCoordinator):
    """Coordinator for Haiphong Tide data.
    
    DataUpdateCoordinator tự cache in-memory: self.data được set mỗi chu kỳ update
    và sensor đọc từ đó giữa các chu kỳ, không cần cache file phức tạp.
    """

    def __init__(self, hass):
        """Initialize the coordinator."""
        try:
            super().__init__(
                hass,
                _LOGGER,
                name=DOMAIN,
                update_interval=timedelta(seconds=SCAN_INTERVAL),
            )
        except Exception:
            self.hass = hass

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from tide-forecast.com."""
        try:
            response = await self.hass.async_add_executor_job(
                requests.get,
                HAIPHONG_TIDE_URL,
                {"timeout": 15, "headers": {"User-Agent": "Home Assistant haiphong_tide"}},
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            tides = self._parse_tide_table(soup)
            _LOGGER.warning("HaiphongTide: Parsed tides: %s", tides)
            if not tides:
                raise UpdateFailed("No tide data found")
        except requests.exceptions.RequestException as err:
            _LOGGER.error(f"HaiphongTide: Request ERROR: %s", err)
            raise UpdateFailed(f"Error fetching tide data: {err}") from err
        except Exception as err:
            _LOGGER.error(f"HaiphongTide: Parse ERROR: %s", err)
            raise UpdateFailed(f"Error parsing tide data: {err}") from err

        # Build output
        points = self._parse_points(tides)
        tide_points = self._build_tide_points(tides)
        now = datetime.now(ZoneInfo(TIDE_TIMEZONE)).replace(second=0, microsecond=0)
        start_full = points[0]["dt"] if points else now
        end_full = points[-1]["dt"] if points else now

        return {
            "tides": tides,
            "last_update": datetime.now(),
            "location": LOCATION_NAME,
            "tide_points": tide_points,
            "curve_points": self._build_curve_points(points, start_full, end_full, 30) if len(points) >= 2 else [],
        }

    def _parse_tide_table(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Parse hourly Hòn Dấu data from thegioimoicau.com."""
        import re

        text = soup.get_text(" ", strip=True)
        pattern = re.compile(
            r"Dương lịch\s+(\d{1,2}/\d{1,2}/\d{4}).*?"
            r"Thời gian \(h là giờ\)(.*?)(?=Mực nước|TheGioiMoiCau\.Com)",
            re.DOTALL,
        )
        tides = []
        for date_text, values in pattern.findall(text):
            date_obj = datetime.strptime(date_text, "%d/%m/%Y")
            pairs = re.findall(r"(\d{1,2})h\s+([0-9]+(?:[.,][0-9]+)?)m", values)
            if len(pairs) != 24:
                _LOGGER.warning("Expected 24 hourly values for %s, got %s", date_text, len(pairs))
            day = [{
                "date": date_obj.strftime("%Y-%m-%d"),
                "time": f"{int(hour):02d}:00",
                "hour": int(hour),
                "height": float(height.replace(",", ".")),
                "tide_type": "hourly",
                "description": f"Hòn Dấu {date_text} {int(hour):02d}:00",
            } for hour, height in pairs]
            for i, tide in enumerate(day):
                before = day[i - 1]["height"] if i else tide["height"]
                after = day[i + 1]["height"] if i + 1 < len(day) else tide["height"]
                tide["tide_type"] = TIDE_HIGH if tide["height"] >= before and tide["height"] >= after else TIDE_LOW if tide["height"] <= before and tide["height"] <= after else "hourly"
            tides.extend(day)
        return tides

    def get_current_tide(self) -> Optional[Dict[str, Any]]:
        """Get the most recent tide before or at current time."""
        if not self.data or "tides" not in self.data:
            return None

        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        points = self._parse_points(self.data["tides"])
        
        for i in range(len(points) - 1):
            if points[i]["dt"] <= now <= points[i + 1]["dt"]:
                tide = self._find_tide_by_dt(self.data["tides"], points[i]["dt"])
                return tide
        return self.data["tides"][0] if self.data["tides"] else None

    def get_next_tide(self) -> Optional[Dict[str, Any]]:
        """Get the next upcoming tide after current time."""
        if not self.data or "tides" not in self.data:
            return None

        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        points = self._parse_points(self.data["tides"])
        
        for i in range(len(points) - 1):
            if points[i]["dt"] <= now <= points[i + 1]["dt"]:
                tide = self._find_tide_by_dt(self.data["tides"], points[i + 1]["dt"])
                return tide
        return self.data["tides"][1] if len(self.data["tides"]) > 1 else None

    def _find_tide_by_dt(self, tides: list, target_dt: datetime) -> Optional[Dict[str, Any]]:
        """Find tide entry matching a specific datetime."""
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
        for tide in tides:
            d = tide.get("date")
            t = tide.get("time", "").strip()
            if d and t:
                try:
                    if "AM" in t or "PM" in t:
                        dt_obj = datetime.strptime(f"{d} {t}", "%Y-%m-%d %I:%M%p").replace(tzinfo=tz)
                    else:
                        dt_obj = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                    if dt_obj == target_dt:
                        return tide
                except Exception:
                    pass
        return None

    def get_today_tides(self) -> List[Dict[str, Any]]:
        """Get all tides for today."""
        if not self.data or "tides" not in self.data:
            return []

        today = datetime.now().strftime("%Y-%m-%d")
        tides = self.data["tides"]

        return [tide for tide in tides if tide.get("date") == today]

    def get_current_tide_level(self) -> Optional[float]:
        """Cosine interpolate tide height for current time."""
        if not self.data or "tides" not in self.data:
            return None
        points = self._parse_points(self.data["tides"])
        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        for i in range(len(points) - 1):
            a = points[i]
            b = points[i + 1]
            if a["dt"] <= now <= b["dt"]:
                total = (b["dt"] - a["dt"]).total_seconds()
                elapsed = (now - a["dt"]).total_seconds()
                if total <= 0:
                    return a["height"]
                f = elapsed / total
                import math
                return round(
                    a["height"] + (b["height"] - a["height"]) / 2 * (1 - math.cos(math.pi * f)),
                    2,
                )
        return None

    def _build_curve_points(self, points: list, start_dt: datetime, end_dt: datetime, step_minutes: int) -> list:
        """Sinh chuỗi điểm nội suy."""
        import math
        if len(points) < 2:
            return []

        out = []
        t = start_dt
        segment = 0
        points_len = len(points)

        while t <= end_dt:
            # Advance segment if needed
            while segment < points_len - 2 and t > points[segment + 1]["dt"]:
                segment += 1

            a = points[segment]
            b = points[segment + 1]

            if a["dt"] <= t <= b["dt"]:
                total = (b["dt"] - a["dt"]).total_seconds()
                elapsed = (t - a["dt"]).total_seconds()
                if total <= 0:
                    y = a["height"]
                else:
                    f = elapsed / total
                    y = a["height"] + (b["height"] - a["height"]) / 2 * (1 - math.cos(math.pi * f))
                
                out.append({
                    "datetime": t.isoformat(),
                    "value": round(y, 3)
                })
            
            t += timedelta(minutes=step_minutes)

        return out

    def _parse_points(self, tides: list) -> list:
        """Helper: parse tides into sorted points with dt/height timezone-aware."""
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
        def parse_dt(tide):
            d = tide.get("date")
            t = tide.get("time").strip()
            try:
                if "AM" in t or "PM" in t:
                    dt_obj = datetime.strptime(f"{d} {t}", "%Y-%m-%d %I:%M%p")
                else:
                    dt_obj = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
                return dt_obj.replace(tzinfo=tz)
            except Exception:
                return None
        
        points = [{"dt": parse_dt(tide), "height": tide.get("height", 0.0)} for tide in tides]
        return sorted([p for p in points if p["dt"]], key=lambda x: x["dt"])

    def _build_tide_points(self, tides: list) -> list:
        """Return list of tide points with timezone-aware ISO datetime for plotting."""
        out = []
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
        for tide in tides:
            d = tide.get("date")
            t = tide.get("time", "").strip()
            if d and t:
                try:
                    if "AM" in t or "PM" in t:
                        dt_obj = datetime.strptime(f"{d} {t}", "%Y-%m-%d %I:%M%p").replace(tzinfo=tz)
                    else:
                        dt_obj = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                    out.append({
                        "datetime": dt_obj.isoformat(),
                        "value": tide.get("height"),
                        "type": tide.get("tide_type"),
                    })
                except Exception:
                    pass
        return out
