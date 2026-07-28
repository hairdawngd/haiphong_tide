"""Data coordinator for Haiphong Tide integration."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, HAIPHONG_TIDE_URL, LOCATION_NAME, SCAN_INTERVAL, TIDE_HIGH, TIDE_LOW

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
                requests.get, HAIPHONG_TIDE_URL, {"timeout": 15}
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            # DEBUG: Save/print raw HTML content for troubleshooting
            _LOGGER.warning("HaiphongTide: Response HTML trunc: %s", response.content[:500])
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
        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).replace(second=0, microsecond=0)
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
        """Parse tide data from tide-forecast.com HTML."""
        tides = []

        container = soup.find("div", class_="tide-table")
        if not container:
            _LOGGER.error("tide-table container not found")
            return tides

        table = container.find("table", class_="tide-table__table")
        if not table:
            _LOGGER.error("tide-table__table not found")
            return tides

        # In newer HTML, rows might be directly under table or inside tbody
        tbody = table.find("tbody")
        rows = tbody.find_all("tr", recursive=False) if tbody else table.find_all("tr", recursive=False)

        # Row 0: day headers with date
        day_headers = rows[0].find_all("th", class_="tide-table__day") if len(rows) > 0 else []
        dates = [th.get("data-date", "") for th in day_headers]

        high_row = None
        low_row = None
        for row in rows:
            if row.find("td", class_=lambda c: c and "tide-table__part--high" in c and "tide-table__part--last" in c):
                high_row = row
            if row.find("td", class_=lambda c: c and "tide-table__part--low" in c and "tide-table__part--last" in c):
                low_row = row

        if not high_row and not low_row:
            return tides

        high_cells = high_row.find_all("td", class_="tide-table__part--last") if high_row else []
        low_cells = low_row.find_all("td", class_="tide-table__part--last") if low_row else []

        for i, date_str in enumerate(dates):
            if not date_str:
                continue

            # Parse high tides for this day
            if i < len(high_cells):
                for entry in self._parse_tide_entries(high_cells[i], TIDE_HIGH, date_str):
                    tides.append(entry)

            # Parse low tides for this day
            if i < len(low_cells):
                for entry in self._parse_tide_entries(low_cells[i], TIDE_LOW, date_str):
                    tides.append(entry)

        return tides

    def _parse_tide_entries(self, cell, tide_type: str, date_str: str) -> List[Dict[str, Any]]:
        """Parse one or more tide entries from a table cell."""
        entries = []
        tide_divs = cell.find_all("div", class_="tide-time")
        for div in tide_divs:
            time_span = div.find("span", class_=lambda c: c and "tide-time__time" in c)
            height_span = div.find("span", class_="tide-time__height")
            if not time_span or not height_span:
                continue
            time_text = time_span.get_text(strip=True)
            height_text = height_span.get_text(strip=True)
            try:
                height = float(height_text)
            except ValueError:
                height = 0.0
            entries.append({
                "date": date_str,
                "time": time_text,
                "height": height,
                "tide_type": tide_type,
                "description": f"{tide_type.capitalize()} tide at {time_text} - {height}m",
            })
        return entries

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
