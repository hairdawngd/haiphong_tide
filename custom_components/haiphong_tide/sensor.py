"""Sensor entities for Haiphong Tide integration."""

import logging
from typing import Any, Optional
from datetime import datetime   

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HaiphongTideCoordinator
from .const import DOMAIN, LOCATION_NAME

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Haiphong Tide sensors."""
    
    coordinator: HaiphongTideCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    sensors = [
        HaiphongTideCurrentSensor(coordinator),
        HaiphongTideNextSensor(coordinator),
        HaiphongTideTodayLowSensor(coordinator),
        HaiphongTideTodayHighSensor(coordinator),
        HaiphongTideScheduleSensor(coordinator),
        HaiphongTideCurrentLevelSensor(coordinator),
    ]

    async_add_entities(sensors)


class HaiphongTideCurrentSensor(CoordinatorEntity, SensorEntity):
    """Sensor for current/next tide."""

    def __init__(self, coordinator: HaiphongTideCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Current Tide"
        self._attr_unique_id = f"{DOMAIN}_current_tide"
        self._attr_icon = "mdi:water"

    @property
    def native_value(self) -> Optional[str]:
        """Return the state of the sensor."""
        tide = self.coordinator.get_current_tide()
        if not tide:
            return "Unknown"
        return f"{tide.get('tide_type', '').capitalize()} - {tide.get('time', '')}h"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        tide = self.coordinator.get_current_tide()
        if not tide:
            return {}

        return {
            "date": tide.get("date"),
            "time": tide.get("time"),
            "height": f"{tide.get('height')} m",
            "tide_type": tide.get("tide_type"),
            "description": tide.get("description"),
            "location": LOCATION_NAME,
        }


class HaiphongTideNextSensor(CoordinatorEntity, SensorEntity):
    """Sensor for next tide."""

    def __init__(self, coordinator: HaiphongTideCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Next Tide"
        self._attr_unique_id = f"{DOMAIN}_next_tide"
        self._attr_icon = "mdi:water-percent"

    @property
    def native_value(self) -> Optional[str]:
        """Return the state of the sensor."""
        tide = self.coordinator.get_next_tide()
        if not tide:
            return "Unknown"
        return f"{tide.get('tide_type', '').capitalize()} - {tide.get('time', '')}h"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        tide = self.coordinator.get_next_tide()
        if not tide:
            return {}

        return {
            "date": tide.get("date"),
            "time": tide.get("time"),
            "height": f"{tide.get('height')} m",
            "tide_type": tide.get("tide_type"),
            "description": tide.get("description"),
            "location": LOCATION_NAME,
        }


class HaiphongTideTodayLowSensor(CoordinatorEntity, SensorEntity):
    """Sensor for today's low tide."""

    def __init__(self, coordinator: HaiphongTideCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Today Low Tide"
        self._attr_unique_id = f"{DOMAIN}_today_low"
        self._attr_icon = "mdi:water-off"
        self._attr_native_unit_of_measurement = "m"

    @property
    def native_value(self) -> Optional[float]:
        """Return the state of the sensor."""
        tides = self.coordinator.get_today_tides()
        if not tides:
            return None

        for tide in tides:
            if tide.get("tide_type") == "low":
                return tide.get("height")

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        tides = self.coordinator.get_today_tides()
        if not tides:
            return {}

        for tide in tides:
            if tide.get("tide_type") == "low":
                return {
                    "date": tide.get("date"),
                    "time": tide.get("time"),
                    "description": tide.get("description"),
                    "location": LOCATION_NAME,
                }

        return {}


class HaiphongTideTodayHighSensor(CoordinatorEntity, SensorEntity):
    """Sensor for today's high tide."""

    def __init__(self, coordinator: HaiphongTideCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Today High Tide"
        self._attr_unique_id = f"{DOMAIN}_today_high"
        self._attr_icon = "mdi:water"
        self._attr_native_unit_of_measurement = "m"

    @property
    def native_value(self) -> Optional[float]:
        """Return the state of the sensor."""
        tides = self.coordinator.get_today_tides()
        if not tides:
            return None

        for tide in tides:
            if tide.get("tide_type") == "high":
                return tide.get("height")

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        tides = self.coordinator.get_today_tides()
        if not tides:
            return {}

        for tide in tides:
            if tide.get("tide_type") == "high":
                return {
                    "date": tide.get("date"),
                    "time": tide.get("time"),
                    "description": tide.get("description"),
                    "location": LOCATION_NAME,
                }

        return {}


class HaiphongTideCurrentLevelSensor(CoordinatorEntity, SensorEntity):
    """Sensor for interpolated current tide level."""

    def __init__(self, coordinator: HaiphongTideCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Current Tide Level"
        self._attr_unique_id = f"{DOMAIN}_current_level"
        self._attr_icon = "mdi:waves"
        self._attr_native_unit_of_measurement = "m"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.get_current_tide_level()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "updated_at": datetime.now().isoformat(),
        }

class HaiphongTideScheduleSensor(CoordinatorEntity, SensorEntity):
    """Sensor for interpolated tide curve over full data range from website."""

    def __init__(self, coordinator: HaiphongTideCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Tide Schedule"
        self._attr_unique_id = f"{DOMAIN}_schedule"
        self._attr_icon = "mdi:calendar-month"

    @property
    def native_value(self) -> Optional[str]:
        """Return the date range of available data."""
        tides = self.coordinator.data.get("tides", [])
        if not tides:
            return None
        start = tides[0].get("date")
        end = tides[-1].get("date")
        return f"{start} → {end}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "tide_points": self.coordinator.data.get("tide_points", []),
            "curve_points": self.coordinator.data.get("curve_points", []),
            "location": LOCATION_NAME,
        }
