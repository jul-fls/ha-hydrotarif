"""SISPEA water prices for a French commune."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SispeaClient, SispeaError
from .const import CONF_INSEE, DOMAIN

PLATFORMS = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


@dataclass
class HydroTarifRuntimeData:
    """Data shared with the sensor platform."""

    coordinator: DataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a commune and its daily refresh."""
    client = SispeaClient(async_get_clientsession(hass))

    async def update():
        try:
            return await client.fetch(entry.data[CONF_INSEE])
        except SispeaError as err:
            raise UpdateFailed(str(err)) from err

    coordinator = DataUpdateCoordinator(
        hass,
        logger=_LOGGER,
        name=DOMAIN,
        update_method=update,
        update_interval=timedelta(hours=24),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = HydroTarifRuntimeData(coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload sensors."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unloaded
