"""Config flow for Haiphong Tide integration."""

import logging
from typing import Any, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import DOMAIN, NAME

_LOGGER = logging.getLogger(__name__)


class HaiphongTideConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Haiphong Tide."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=NAME, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={"location": "Đồ Sơn (Hòn Dấu)"},
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> dict[str, Any]:
        """Handle import from configuration.yaml."""
        return await self.async_step_user(import_data)
