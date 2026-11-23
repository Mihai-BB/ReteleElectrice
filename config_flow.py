"""
ConfigFlow și OptionsFlow pentru integrarea Rețele Electrice România.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import ReteleElectriceAPI
from .const import (
    DEFAULT_UPDATE,
    DOMAIN,
    MAX_UPDATE,
    MIN_UPDATE,
)
from .helpers import build_pod_address

_LOGGER = logging.getLogger(__name__)

_INTERVAL = vol.All(vol.Coerce(int), vol.Range(min=MIN_UPDATE, max=MAX_UPDATE))


def _build_pod_options(pods: list[dict]) -> list[SelectOptionDict]:
    """Construiește lista de opțiuni pentru selectorul de POD-uri."""
    options: list[SelectOptionDict] = []

    for pod in pods:
        pod_name = pod.get("Name", "") or pod.get("POD__c", "")
        if not pod_name:
            continue

        address = build_pod_address(pod)
        contract_type = pod.get("Contract_Type__c", "")
        smart_meter = pod.get("Smart_meter__c", False) or pod.get("IsSmartMeter__c", False)

        label = f"{address} ➜ POD: {pod_name}"
        if contract_type:
            label += f" ({contract_type})"
        if smart_meter:
            label += " [Smart Meter]"

        options.append(SelectOptionDict(value=pod_name, label=label))

    return options


def _extract_all_pod_names(pods: list[dict]) -> list[str]:
    """Extrage toate numele POD-urilor unice."""
    names: list[str] = []
    for pod in pods:
        name = pod.get("Name", "") or pod.get("POD__c", "")
        if name and name not in names:
            names.append(name)
    return names


def _resolve_selected_pods(
    select_all: bool,
    selected: list[str],
    pods: list[dict],
) -> list[str]:
    """Returnează lista finală de POD-uri."""
    if select_all:
        return _extract_all_pod_names(pods)
    return selected


class ReteleElectriceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """ConfigFlow — autentificare + selecție POD-uri."""

    VERSION = 3

    def __init__(self) -> None:
        self._username: str = ""
        self._password: str = ""
        self._update_interval: int = DEFAULT_UPDATE
        self._pods: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input["username"]
            self._password = user_input["password"]
            self._update_interval = user_input.get(
                "update_interval", DEFAULT_UPDATE
            )

            await self.async_set_unique_id(self._username.lower())
            self._abort_if_unique_id_configured()

            api = ReteleElectriceAPI(
                self.hass,
                username=self._username,
                password=self._password,
            )

            if await api.async_login():
                pods_raw = await api.async_get_pods()
                await api.async_close()

                if pods_raw and isinstance(pods_raw, list) and len(pods_raw) > 0:
                    self._pods = pods_raw
                    return await self.async_step_select_pod()

                errors["base"] = "no_data"
            else:
                await api.async_close()
                errors["base"] = "auth_failed"

        schema = vol.Schema(
            {
                vol.Required("username"): str,
                vol.Required("password"): str,
                vol.Optional(
                    "update_interval", default=DEFAULT_UPDATE
                ): _INTERVAL,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_select_pod(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            select_all = user_input.get("select_all", False)
            selected = user_input.get("selected_pods", [])

            if not select_all and not selected:
                errors["base"] = "no_pod_selected"
            else:
                final_selection = _resolve_selected_pods(
                    select_all, selected, self._pods
                )

                return self.async_create_entry(
                    title=f"Rețele Electrice ({self._username})",
                    data={
                        "username": self._username,
                        "password": self._password,
                        "update_interval": self._update_interval,
                        "select_all": select_all,
                        "selected_pods": final_selection,
                    },
                )

        pod_options = _build_pod_options(self._pods)

        schema = vol.Schema(
            {
                vol.Optional("select_all", default=False): bool,
                vol.Required("selected_pods", default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=pod_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="select_pod",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ReteleElectriceOptionsFlow:
        return ReteleElectriceOptionsFlow()


class ReteleElectriceOptionsFlow(config_entries.OptionsFlow):
    """OptionsFlow — modificare credențiale, interval și selecție POD-uri."""

    def __init__(self) -> None:
        self._username: str = ""
        self._password: str = ""
        self._update_interval: int = DEFAULT_UPDATE
        self._pods: list[dict] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Modificare credențiale și interval de actualizare."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input["username"]
            password = user_input["password"]
            update_interval = user_input.get(
                "update_interval", DEFAULT_UPDATE
            )

            api = ReteleElectriceAPI(
                self.hass, username=username, password=password
            )

            conflict = any(
                e.entry_id != self.config_entry.entry_id
                and e.unique_id == username.lower()
                for e in self.hass.config_entries.async_entries(DOMAIN)
            )
            if conflict:
                await api.async_close()
                errors["base"] = "already_configured"
            elif await api.async_login():
                pods_raw = await api.async_get_pods()
                await api.async_close()

                if pods_raw and isinstance(pods_raw, list) and len(pods_raw) > 0:
                    self._pods = pods_raw
                    self._username = username
                    self._password = password
                    self._update_interval = update_interval
                    return await self.async_step_select_pod()

                errors["base"] = "no_data"
            else:
                await api.async_close()
                errors["base"] = "auth_failed"

        current = self.config_entry.data

        schema = vol.Schema(
            {
                vol.Required(
                    "username", default=current.get("username", "")
                ): str,
                vol.Required(
                    "password", default=current.get("password", "")
                ): str,
                vol.Required(
                    "update_interval",
                    default=current.get(
                        "update_interval", DEFAULT_UPDATE
                    ),
                ): _INTERVAL,
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )

    async def async_step_select_pod(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Modificare selecție POD-uri."""
        errors: dict[str, str] = {}

        if user_input is not None:
            select_all = user_input.get("select_all", False)
            selected = user_input.get("selected_pods", [])

            if not select_all and not selected:
                errors["base"] = "no_pod_selected"
            else:
                final_selection = _resolve_selected_pods(
                    select_all, selected, self._pods
                )

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        "username": self._username,
                        "password": self._password,
                        "update_interval": self._update_interval,
                        "select_all": select_all,
                        "selected_pods": final_selection,
                    },
                    title=f"Rețele Electrice ({self._username})",
                    unique_id=self._username.lower(),
                )

                await self.hass.config_entries.async_reload(
                    self.config_entry.entry_id
                )

                return self.async_create_entry(data=dict(self.config_entry.options))

        current = self.config_entry.data

        schema = vol.Schema(
            {
                vol.Optional(
                    "select_all",
                    default=current.get("select_all", False),
                ): bool,
                vol.Required(
                    "selected_pods",
                    default=current.get("selected_pods", []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_build_pod_options(self._pods),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="select_pod",
            data_schema=schema,
            errors=errors,
        )