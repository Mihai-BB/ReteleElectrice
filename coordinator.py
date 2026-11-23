"""Coordinator for the Retele Electrice Romania integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import ReteleElectriceAPI
from .const import DEFAULT_UPDATE, DOMAIN

_LOGGER = logging.getLogger(__name__)

_VF_ERROR_STATUSES = {
    "error",
    "vf_page_error",
    "vf_get_failed",
    "vf_no_viewstate",
    "vf_post_error",
    "vf_post_failed",
    "a4j_no_data_in_response",
}


def _vf_failed(result: Any) -> bool:
    """Return True if a Visualforce proxy result is missing or errored."""
    if result is None:
        return True
    return isinstance(result, dict) and result.get("status") in _VF_ERROR_STATUSES


type ReteleElectriceConfigEntry = ConfigEntry["ReteleElectriceCoordinator"]


class ReteleElectriceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Central data coordinator for Retele Electrice Romania."""

    config_entry: ReteleElectriceConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator and API client."""
        update_seconds = config_entry.data.get("update_interval", DEFAULT_UPDATE)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_seconds),
            config_entry=config_entry,
        )

        self.api = ReteleElectriceAPI(
            hass,
            username=config_entry.data["username"],
            password=config_entry.data["password"],
        )

        self._selected_pods: list[str] | None = config_entry.data.get(
            "selected_pods"
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch periodic data for all selected PODs."""
        _LOGGER.debug("[ReteleElectrice] Starting data update")

        try:
            if not self.api._logged_in:
                if not await self.api.async_login():
                    raise UpdateFailed("Failed to authenticate with Retele Electrice")

            user_name = await self.api.async_get_user_name()
            account_info = await self.api.async_get_account_info()
            contact_info = await self.api.async_get_contact_info()

            # Retry login once if session cookies expired and profile calls returned None
            if user_name is None or account_info is None or contact_info is None:
                _LOGGER.debug("[ReteleElectrice] Profile data missing; retrying login...")
                if await self.api.async_login():
                    user_name = await self.api.async_get_user_name()
                    account_info = await self.api.async_get_account_info()
                    contact_info = await self.api.async_get_contact_info()

            pods_raw = await self.api.async_get_pods()
            if not pods_raw or not isinstance(pods_raw, list):
                _LOGGER.warning("[ReteleElectrice] Empty POD list; retrying login...")
                if await self.api.async_login():
                    pods_raw = await self.api.async_get_pods()

                if not pods_raw or not isinstance(pods_raw, list):
                    raise UpdateFailed("Failed to retrieve PODs")

            if self._selected_pods:
                filtered_pods = [
                    pod
                    for pod in pods_raw
                    if (pod.get("Name") or pod.get("POD__c", "")) in self._selected_pods
                ]
            else:
                filtered_pods = pods_raw

            cnp = ""
            if account_info and isinstance(account_info, dict):
                cnp = account_info.get("CNP__c", "") or account_info.get("Fiscal_Code__c", "")

            pod_details: dict[str, Any] = {}
            pod_reading_details: dict[str, Any] = {}
            reading_archive: dict[str, Any] = {}
            power_outages: dict[str, Any] = {}
            smart_meter: dict[str, Any] = {}
            instant_values: dict[str, Any] = {}
            supplier_data: dict[str, Any] = {}

            prev = self.data or {}

            def _or_previous(bucket: str, pod_name: str, value: Any) -> Any:
                """Keep previous valid data if a transient VF error occurs."""
                if _vf_failed(value):
                    old = (prev.get(bucket) or {}).get(pod_name)
                    if old is not None and not _vf_failed(old):
                        _LOGGER.debug(
                            "[ReteleElectrice] %s/%s unavailable; keeping previous data",
                            bucket,
                            pod_name,
                        )
                        return old
                return value

            for pod in filtered_pods:
                pod_name = pod.get("Name") or pod.get("POD__c", "")
                if not pod_name:
                    continue

                pod_details[pod_name] = _or_previous(
                    "pod_details", pod_name, await self.api.async_get_pod_details(pod_name)
                )

                pod_reading_details[pod_name] = _or_previous(
                    "pod_reading_details",
                    pod_name,
                    await self.api.async_get_reading_archive_pod_details(pod_name),
                )

                reading_archive[pod_name] = _or_previous(
                    "reading_archive",
                    pod_name,
                    await self.api.async_get_reading_archive(pod_name, cnp=cnp),
                )

                power_outages[pod_name] = _or_previous(
                    "power_outages",
                    pod_name,
                    await self.api.async_get_power_outages(pod_name),
                )

                is_smart = pod.get("Smart_meter__c", False) or pod.get("IsSmartMeter__c", False)
                if is_smart:
                    smart_meter[pod_name] = _or_previous(
                        "smart_meter",
                        pod_name,
                        await self.api.async_get_smart_meter_data(pod_name, cnp=cnp),
                    )

                    instant_values[pod_name] = _or_previous(
                        "instant_values",
                        pod_name,
                        await self.api.async_get_instant_values(pod_name, cnp=cnp),
                    )

                supplier_data[pod_name] = _or_previous(
                    "supplier_data",
                    pod_name,
                    await self.api.async_get_supplier_data(pod_name),
                )

        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("[ReteleElectrice] Data update error: %s", err)
            raise UpdateFailed(f"Failed to update data: {err}") from err

        return {
            "user_name": user_name,
            "account_info": account_info,
            "contact_info": contact_info,
            "pods": filtered_pods,
            "pod_details": pod_details,
            "pod_reading_details": pod_reading_details,
            "reading_archive": reading_archive,
            "power_outages": power_outages,
            "smart_meter": smart_meter,
            "instant_values": instant_values,
            "supplier_data": supplier_data,
            "selected_pods": self._selected_pods,
        }
