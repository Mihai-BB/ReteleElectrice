"""
Inițializarea integrării Rețele Electrice România.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ReteleElectriceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

type ReteleElectriceConfigEntry = ConfigEntry[ReteleElectriceCoordinator]

_STARI_ACTIVE = (
    ConfigEntryState.LOADED,
    ConfigEntryState.SETUP_IN_PROGRESS,
    ConfigEntryState.SETUP_RETRY,
    ConfigEntryState.UNLOAD_IN_PROGRESS,
)


def _cleanup_domain(hass: HomeAssistant) -> None:
    """Eliberează datele domeniului."""
    hass.data.pop(DOMAIN, None)


async def async_setup_entry(hass: HomeAssistant, entry: ReteleElectriceConfigEntry) -> bool:
    """Configurare intrare: creează coordinator, face primul refresh, setează platformele."""
    _LOGGER.debug("[ReteleElectrice] Setup entry_id=%s", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})

    coordinator = ReteleElectriceCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.api.async_close()
        raise

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.debug("[ReteleElectrice] Setup complet pentru entry_id=%s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ReteleElectriceConfigEntry) -> bool:
    """Descarcă platformele la eliminarea intrării."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator and hasattr(coordinator, "api"):
            await coordinator.api.async_close()

        entry_ids_ramase = {
            e.entry_id
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state in _STARI_ACTIVE
        }

        if not entry_ids_ramase:
            _cleanup_domain(hass)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Curăță datele domeniului când ultima intrare este ștearsă."""
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]
    if not remaining:
        _cleanup_domain(hass)