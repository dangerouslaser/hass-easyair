"""Bosch EasyAir heat pump energy integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import EasyAirApi
from .const import CONF_TOKENS, DOMAIN
from .coordinator import STORAGE_VERSION, EasyAirCoordinator

PLATFORMS = [Platform.SENSOR]

type EasyAirConfigEntry = ConfigEntry[EasyAirCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EasyAirConfigEntry) -> bool:
    """Set up EasyAir from a config entry."""

    def _save_tokens(tokens: dict) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKENS: tokens}
        )

    api = EasyAirApi(
        async_get_clientsession(hass), dict(entry.data[CONF_TOKENS]), _save_tokens
    )
    coordinator = EasyAirCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EasyAirConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: EasyAirConfigEntry) -> None:
    """Remove stored lifetime counters."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
