"""Config flow for the Zeversolar (Eversolar protocol) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .client import ZeversolarClient
from .const import (
    CONF_INVERTER_ADDRESS,
    CONF_LOG_RAW_FRAMES,
    CONF_PASSIVE,
    DEFAULT_INVERTER_ADDRESS,
    DEFAULT_LOG_RAW_FRAMES,
    DEFAULT_NAME,
    DEFAULT_PASSIVE,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_PASSIVE, default=DEFAULT_PASSIVE): cv.boolean,
        vol.Optional(
            CONF_INVERTER_ADDRESS, default=DEFAULT_INVERTER_ADDRESS
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=254)),
    }
)


class ZeversolarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI configuration flow for Zeversolar."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            client = ZeversolarClient(
                host=host,
                port=port,
                inverter_address=user_input[CONF_INVERTER_ADDRESS],
                passive=user_input[CONF_PASSIVE],
            )
            try:
                await client.async_test_connection()
            except Exception:  # noqa: BLE001 - any failure means "can't connect"
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return ZeversolarOptionsFlow(config_entry)


class ZeversolarOptionsFlow(OptionsFlow):
    """Handle runtime options (poll interval, debug logging)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Stash the entry without shadowing the built-in ``config_entry``."""
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=600)),
                vol.Optional(
                    CONF_LOG_RAW_FRAMES,
                    default=options.get(CONF_LOG_RAW_FRAMES, DEFAULT_LOG_RAW_FRAMES),
                ): cv.boolean,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
