"""DataUpdateCoordinator wrapping the HA-free Eversolar TCP client."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import ZeversolarClient
from .const import DOMAIN

# Re-exported so callers can import both names from this module.
__all__ = ["ZeversolarClient", "ZeversolarCoordinator"]

_LOGGER = logging.getLogger(__name__)


class ZeversolarCoordinator(DataUpdateCoordinator):
    """Polls the inverter on a fixed interval via the client."""

    def __init__(
        self, hass: HomeAssistant, client: ZeversolarClient, scan_interval: int
    ) -> None:
        """Set up the coordinator with the given poll interval (seconds)."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, float | str | None]:
        try:
            return await self.client.async_update()
        except Exception as err:  # surfaced as "unavailable" entities
            raise UpdateFailed(f"Error communicating with inverter: {err}") from err

    async def async_shutdown(self) -> None:
        """Close the socket when Home Assistant unloads the platform."""
        await super().async_shutdown()
        await self.client.close()
