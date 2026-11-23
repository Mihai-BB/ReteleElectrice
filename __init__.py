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

# Config entry states that still count as active during setup, reload, or unload.
_ACTIVE_STATES = (
    ConfigEntryState.LOADED,
    ConfigEntryState.SETUP_IN_PROGRESS,
    ConfigEntryState.SETUP_RETRY,
    ConfigEntryState.UNLOAD_IN_PROGRESS,
)


def _cleanup_domain(hass: HomeAssistant) -> None:
    """Remove domain-level data from Home Assistant state."""
    hass.data.pop(DOMAIN, None)


async def async_setup_entry(hass: HomeAssistant, entry: ReteleElectriceConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    _LOGGER.debug("[ReteleElectrice] Setup entry_id=%s", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})

    coordinator = ReteleElectriceCoordinator(hass, entry)
    try:
        # Run initial refresh before forwarding platforms.
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # Close the dedicated HTTP session so retries do not leak open sockets.
        await coordinator.api.async_close()
        raise

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.debug("[ReteleElectrice] Setup complete for entry_id=%s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ReteleElectriceConfigEntry) -> bool:
    """Unload platforms and clean up resources for a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator and hasattr(coordinator, "api"):
            await coordinator.api.async_close()

        # Check if any other active entries still use this domain.
        remaining_entries = {
            e.entry_id
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state in _ACTIVE_STATES
        }

        if not remaining_entries:
            _cleanup_domain(hass)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up domain data when the last config entry is removed."""
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]
    if not remaining:
        _cleanup_domain(hass)
