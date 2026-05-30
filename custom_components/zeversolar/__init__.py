"""The Zeversolar (Eversolar protocol) integration.

Configured through the UI (config flow). ``async_setup_entry`` builds the TCP
client + coordinator and forwards to the sensor platform; the coordinator is
stored on ``entry.runtime_data`` for the platform to pick up.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .client import ZeversolarClient
from .const import (
    CONF_INVERTER_ADDRESS,
    CONF_LOG_RAW_FRAMES,
    CONF_PASSIVE,
    DEFAULT_INVERTER_ADDRESS,
    DEFAULT_LOG_RAW_FRAMES,
    DEFAULT_PASSIVE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,  # noqa: F401  (re-exported for convenience)
)
from .coordinator import ZeversolarCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """No YAML component setup; everything is driven by config entries."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Zeversolar from a config entry."""
    data = {**entry.data, **entry.options}
    client = ZeversolarClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        inverter_address=data.get(CONF_INVERTER_ADDRESS, DEFAULT_INVERTER_ADDRESS),
        log_raw_frames=data.get(CONF_LOG_RAW_FRAMES, DEFAULT_LOG_RAW_FRAMES),
        passive=data.get(CONF_PASSIVE, DEFAULT_PASSIVE),
    )
    coordinator = ZeversolarCoordinator(
        hass, client, int(data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    )

    # Don't raise if the inverter is dark (e.g. at night): let the entities come
    # up "unavailable" and recover on their own on a later poll.
    await coordinator.async_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_shutdown)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and its platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry)
