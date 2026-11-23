"""Sensor platform for the Retele Electrice Romania integration."""

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import ReteleElectriceCoordinator
from .helpers import (
    build_pod_address,
    decode_html_entities,
    format_date_ro_ddmmyyyy,
    normalize_title,
    safe_float,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class PodContext:
    """Shared context for a single POD across sensor entities."""

    pod_name: str
    pod_data: dict
    account_name: str
    address: str
    is_prosumer: bool
    is_smart: bool


def _get_readings_from_coordinator(data: dict, pod_name: str) -> list:
    """Return XML_Readings list for a POD from coordinator data."""
    if not data:
        return []
    archive = data.get("reading_archive", {}).get(pod_name)
    if not archive or not isinstance(archive, dict):
        return []
    return archive.get("XML_Readings", [])


def _extract_years_from_readings(readings: list[dict]) -> list[int]:
    """Return up to the two most recent reading years in descending order."""
    years: set[int] = set()
    for r in readings:
        date_str = r.get("measureDate", "")
        try:
            parsed = datetime.strptime(date_str.split(" ")[0], "%d.%m.%Y")
            years.add(parsed.year)
        except (ValueError, TypeError):
            pass
    return sorted(years, reverse=True)[:2]


def _filter_readings_by_year(readings: list[dict], year: int) -> list[dict]:
    """Filter readings matching a specific calendar year."""
    result: list[dict] = []
    for r in readings:
        date_str = r.get("measureDate", "")
        try:
            parsed = datetime.strptime(date_str.split(" ")[0], "%d.%m.%Y")
            if parsed.year == year:
                result.append(r)
        except (ValueError, TypeError):
            pass
    return result


def _get_energy_value(meters: list[dict], energy_type: str) -> float | None:
    """Extract numeric meter reading value for a given energy type (e.g. EA, EAP)."""
    for m in meters:
        if m.get("typeofenergy_measured") == energy_type:
            return safe_float(m.get("Value"), None)
    return None


def _format_reading_date(date_str: str) -> str:
    """Format a reading date string for display."""
    return format_date_ro_ddmmyyyy(date_str)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for all discovered PODs."""
    coordinator: ReteleElectriceCoordinator = config_entry.runtime_data

    if not coordinator.data:
        return

    pods = coordinator.data.get("pods", [])
    if not isinstance(pods, list):
        return

    account_info = coordinator.data.get("account_info") or {}
    raw_name = (
        account_info.get("Name", "Necunoscut")
        if isinstance(account_info, dict)
        else "Necunoscut"
    )
    account_name = normalize_title(raw_name)

    entities: list[SensorEntity] = []

    for pod in pods:
        pod_name = pod.get("Name") or pod.get("POD__c", "")
        if not pod_name:
            continue

        address = build_pod_address(pod)
        is_prosumer = pod.get("isProductor__c", False) or (
            (pod.get("Contract_Type__c", "") or "").upper() == "PROSUMER"
        )
        is_smart = pod.get("Smart_meter__c", False) or pod.get(
            "IsSmartMeter__c", False
        )

        ctx = PodContext(
            pod_name=pod_name,
            pod_data=pod,
            account_name=account_name,
            address=address,
            is_prosumer=is_prosumer,
            is_smart=is_smart,
        )

        entities.append(InformatiiPodSensor(coordinator, config_entry, ctx))
        entities.append(InformatiiContSensor(coordinator, config_entry, ctx))
        entities.append(IntreruperiCurentSensor(coordinator, config_entry, ctx))

        entities.append(IndexCitireConsumSensor(coordinator, config_entry, ctx))
        if is_prosumer:
            entities.append(IndexCitireProductieSensor(coordinator, config_entry, ctx))

        # Create up to two recent annual archive sensors per energy direction
        readings = _get_readings_from_coordinator(coordinator.data, pod_name)
        years = _extract_years_from_readings(readings)
        for year in years:
            entities.append(
                ArhivaEnergieConsumataSensor(coordinator, config_entry, ctx, year)
            )
            if is_prosumer:
                entities.append(
                    ArhivaEnergieProdusSensor(coordinator, config_entry, ctx, year)
                )

        entities.append(DateFurnizorSensor(coordinator, config_entry, ctx))

        if is_smart:
            entities.append(SmartMeterConsumSensor(coordinator, config_entry, ctx))
            if is_prosumer:
                entities.append(SmartMeterProductieSensor(coordinator, config_entry, ctx))

            entities.append(ValoareInstantaneeConsumSensor(coordinator, config_entry, ctx))
            if is_prosumer:
                entities.append(ValoareInstantaneeProductieSensor(coordinator, config_entry, ctx))

    async_add_entities(entities)


class ReteleElectriceSensorBase(
    CoordinatorEntity[ReteleElectriceCoordinator], SensorEntity
):
    """Base class for all Retele Electrice sensor entities."""

    _attr_has_entity_name = False
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: ReteleElectriceCoordinator,
        config_entry: ConfigEntry,
        ctx: PodContext,
        sensor_key: str,
        sensor_name: str,
        icon: str = "mdi:flash",
    ) -> None:
        """Initialize base sensor metadata and entity ID."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._ctx = ctx
        self._sensor_key = sensor_key
        self._attr_name = sensor_name
        self._attr_icon = icon
        pod_slug = ctx.pod_name.lower()
        self._attr_unique_id = f"{DOMAIN}_{pod_slug}_{sensor_key}"
        self._custom_entity_id = f"sensor.{DOMAIN}_{pod_slug}_{sensor_key}"

    @property
    def entity_id(self) -> str | None:
        """Return the custom entity ID."""
        return self._custom_entity_id

    @entity_id.setter
    def entity_id(self, value: str) -> None:
        """Set the custom entity ID."""
        self._custom_entity_id = value

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info grouped by POD."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._ctx.pod_name)},
            name=f"Retele Electrice {self._ctx.pod_name}",
            manufacturer="Retele Electrice Romania",
            model="Retele Electrice Romania",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Return True when the coordinator has valid data."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
        )


class InformatiiPodSensor(ReteleElectriceSensorBase):
    """Sensor exposing POD contract and technical attributes."""

    def __init__(self, coordinator, config_entry, ctx: PodContext) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="informatii_pod",
            sensor_name="POD",
            icon="mdi:file-document-outline",
        )

    @property
    def native_value(self) -> str | None:
        pod = self._ctx.pod_data
        return normalize_title(pod.get("Contract_Type__c", "Necunoscut"))

    @property
    def extra_state_attributes(self) -> dict:
        pod = self._ctx.pod_data
        return {
            "POD": self._ctx.pod_name,
            "Adresa": self._ctx.address,
            "Tip contract": normalize_title(pod.get("Contract_Type__c", "")),
            "Stare contract": normalize_title(pod.get("Contract_State__c", "")),
            "Tip consumator": normalize_title(pod.get("Consumer_Type_Account__c", "")),
            "Piata": normalize_title(pod.get("Market_Type__c", "")),
            "Putere absorbita (kW)": pod.get("Absorbed_Power_KW__c", ""),
            "Putere absorbita (kVA)": pod.get("Absorbed_Power_KVA__c", ""),
            "Putere cedata (kW)": pod.get("Released_Power_KW__c", ""),
            "Putere cedata (kVA)": pod.get("Released_Power_KVA__c", ""),
            "Nivel tensiune": pod.get("Voltage_Level__c", ""),
            "Tensiune nominala (kV)": pod.get("Nominal_Voltage_kV__c", ""),
            "Serie contor": pod.get("EA_METER_SERIE__c", ""),
            "Tip contor": pod.get("EA_METER_TYPE__c", ""),
            "Smart meter": self._ctx.is_smart,
            "Prosumer": self._ctx.is_prosumer,
            "Tarif": pod.get("TARIFF__c", ""),
            "Profil consum": pod.get("ConsumptionProfile__c", ""),
            "Constanta contor": pod.get("EA_CONSTANT__c", ""),
            "Precizie": pod.get("EA_PRECISION__c", ""),
            "Unitate operativa": pod.get("Operative_Unit__c", ""),
            "Zona": pod.get("Zone_Cod__c", ""),
            "Cod CFT": pod.get("CFT_Code__c", ""),
            "ATR": pod.get("ATR__c", ""),
            "Perioada masurare": pod.get("MeasurementPeriod__c", ""),
            "Data start contract": pod.get("ContractStartDate__c", ""),
            "Distribuitor": normalize_title(
                (pod.get("DistributionCompany__r") or {}).get("Name", "")
            ),
            "attribution": ATTRIBUTION,
        }


class InformatiiContSensor(ReteleElectriceSensorBase):
    """Sensor exposing account and contact details."""

    def __init__(self, coordinator, config_entry, ctx: PodContext) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="informatii_cont",
            sensor_name="Date utilizator",
            icon="mdi:account-circle",
        )

    @property
    def native_value(self) -> str | None:
        return self._ctx.account_name

    @property
    def extra_state_attributes(self) -> dict:
        account = self.coordinator.data.get("account_info") or {}
        contact = self.coordinator.data.get("contact_info") or {}

        if not isinstance(account, dict):
            account = {}
        if not isinstance(contact, dict):
            contact = {}

        return {
            "Nume": normalize_title(account.get("Name", "")),
            "Email": account.get("Email__c", "") or contact.get("Email", ""),
            "Telefon": account.get("Mobile_Phone__c", "") or contact.get("MobilePhone", ""),
            "CNP": account.get("CNP__c", ""),
            "Cod fiscal": account.get("Fiscal_Code__c", ""),
            "Adresa": normalize_title(account.get("Address__c", "")),
            "Oras": normalize_title(account.get("City__c", "")),
            "Judet": normalize_title(account.get("County__c", "")),
            "Cod postal": account.get("ZIP_COD__c", ""),
            "Tip cont": normalize_title((account.get("RecordType") or {}).get("Name", "")),
            "attribution": ATTRIBUTION,
        }


class IndexCitireConsumSensor(ReteleElectriceSensorBase):
    """Sensor for the latest active energy consumption meter reading."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, coordinator, config_entry, ctx: PodContext) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="index_citire_consum",
            sensor_name="Index citire consum",
            icon="mdi:counter",
        )

    @property
    def native_value(self) -> float | None:
        readings = _get_readings_from_coordinator(self.coordinator.data, self._ctx.pod_name)
        if not readings:
            return None
        return _get_energy_value(readings[0].get("meter", []), "EA")

    @property
    def extra_state_attributes(self) -> dict:
        readings = _get_readings_from_coordinator(self.coordinator.data, self._ctx.pod_name)
        if not readings:
            return {"attribution": ATTRIBUTION}

        latest = readings[0]
        ea_val = _get_energy_value(latest.get("meter", []), "EA")

        attrs: dict = {
            "Data citire": _format_reading_date(latest.get("measureDate", "")),
            "Tip citire": normalize_title(latest.get("typeOfReading", "")),
            "Serie contor": latest.get("SerialNumber", ""),
            "Constanta": latest.get("constanta", ""),
            "Index energie consumata (kWh)": ea_val,
        }

        if len(readings) >= 2:
            prev = readings[1]
            prev_ea = _get_energy_value(prev.get("meter", []), "EA")
            if ea_val is not None and prev_ea is not None:
                attrs["Consum lunar (kWh)"] = round(ea_val - prev_ea, 3)
                attrs["Citire anterioara"] = _format_reading_date(prev.get("measureDate", ""))

        attrs["attribution"] = ATTRIBUTION
        return attrs


class IndexCitireProductieSensor(ReteleElectriceSensorBase):
    """Sensor for the latest active energy production meter reading."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, coordinator, config_entry, ctx: PodContext) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="index_citire_productie",
            sensor_name="Index citire productie",
            icon="mdi:solar-power",
        )

    @property
    def native_value(self) -> float | None:
        readings = _get_readings_from_coordinator(self.coordinator.data, self._ctx.pod_name)
        if not readings:
            return None
        return _get_energy_value(readings[0].get("meter", []), "EAP")

    @property
    def extra_state_attributes(self) -> dict:
        readings = _get_readings_from_coordinator(self.coordinator.data, self._ctx.pod_name)
        if not readings:
            return {"attribution": ATTRIBUTION}

        latest = readings[0]
        eap_val = _get_energy_value(latest.get("meter", []), "EAP")

        attrs: dict = {
            "Data citire": _format_reading_date(latest.get("measureDate", "")),
            "Tip citire": normalize_title(latest.get("typeOfReading", "")),
            "Serie contor": latest.get("SerialNumber", ""),
            "Constanta": latest.get("constanta", ""),
            "Index energie produsa (kWh)": eap_val,
        }

        if len(readings) >= 2:
            prev = readings[1]
            prev_eap = _get_energy_value(prev.get("meter", []), "EAP")
            if eap_val is not None and prev_eap is not None:
                attrs["Productie lunara (kWh)"] = round(eap_val - prev_eap, 3)
                attrs["Citire anterioara"] = _format_reading_date(prev.get("measureDate", ""))

        attrs["attribution"] = ATTRIBUTION
        return attrs


class ArhivaEnergieConsumataSensor(ReteleElectriceSensorBase):
    """Sensor summarizing annual consumed energy and individual readings."""

    def __init__(self, coordinator, config_entry, ctx: PodContext, year: int) -> None:
        self._year = year
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key=f"arhiva_energie_consumata_{year}",
            sensor_name=f"{year} -> Energie consumata",
            icon="mdi:history",
        )

    @property
    def native_value(self) -> str | None:
        year_readings = self._get_year_readings()
        if not year_readings:
            return "Fara date"

        first_ea = _get_energy_value(year_readings[-1].get("meter", []), "EA")
        last_ea = _get_energy_value(year_readings[0].get("meter", []), "EA")

        if first_ea is not None and last_ea is not None and len(year_readings) > 1:
            return f"{round(last_ea - first_ea, 3)} kWh"

        ea = _get_energy_value(year_readings[0].get("meter", []), "EA")
        return f"{ea} kWh" if ea is not None else "Fara date"

    @property
    def extra_state_attributes(self) -> dict:
        year_readings = self._get_year_readings()
        if not year_readings:
            return {"attribution": ATTRIBUTION}

        attrs: dict = {}
        for reading in year_readings:
            date_label = _format_reading_date(reading.get("measureDate", ""))
            ea_val = _get_energy_value(reading.get("meter", []), "EA")
            attrs[date_label] = f"{ea_val} kWh" if ea_val is not None else "fara date"

        attrs["Total citiri"] = len(year_readings)
        attrs["Serie contor"] = year_readings[0].get("SerialNumber", "")
        attrs["attribution"] = ATTRIBUTION
        return attrs

    def _get_year_readings(self) -> list[dict]:
        readings = _get_readings_from_coordinator(self.coordinator.data, self._ctx.pod_name)
        return _filter_readings_by_year(readings, self._year)


class ArhivaEnergieProdusSensor(ReteleElectriceSensorBase):
    """Sensor summarizing annual produced energy and individual readings."""

    def __init__(self, coordinator, config_entry, ctx: PodContext, year: int) -> None:
        self._year = year
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key=f"arhiva_energie_produsa_{year}",
            sensor_name=f"{year} -> Energie produsa",
            icon="mdi:solar-power",
        )

    @property
    def native_value(self) -> str | None:
        year_readings = self._get_year_readings()
        if not year_readings:
            return "Fara date"

        first_eap = _get_energy_value(year_readings[-1].get("meter", []), "EAP")
        last_eap = _get_energy_value(year_readings[0].get("meter", []), "EAP")

        if first_eap is not None and last_eap is not None and len(year_readings) > 1:
            return f"{round(last_eap - first_eap, 3)} kWh"

        eap = _get_energy_value(year_readings[0].get("meter", []), "EAP")
        return f"{eap} kWh" if eap is not None else "Fara date"

    @property
    def extra_state_attributes(self) -> dict:
        year_readings = self._get_year_readings()
        if not year_readings:
            return {"attribution": ATTRIBUTION}

        attrs: dict = {}
        for reading in year_readings:
            date_label = _format_reading_date(reading.get("measureDate", ""))
            eap_val = _get_energy_value(reading.get("meter", []), "EAP")
            attrs[date_label] = f"{eap_val} kWh" if eap_val is not None else "fara date"

        attrs["Total citiri"] = len(year_readings)
        attrs["Serie contor"] = year_readings[0].get("SerialNumber", "")
        attrs["attribution"] = ATTRIBUTION
        return attrs

    def _get_year_readings(self) -> list[dict]:
        readings = _get_readings_from_coordinator(self.coordinator.data, self._ctx.pod_name)
        return _filter_readings_by_year(readings, self._year)


class IntreruperiCurentSensor(ReteleElectriceSensorBase):
    """Sensor reporting power outage status for a POD."""

    def __init__(self, coordinator, config_entry, ctx: PodContext) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="intreruperi_curent",
            sensor_name="Intreruperi curent",
            icon="mdi:flash-alert",
        )

    @property
    def native_value(self) -> str | None:
        outage_data = self._get_outage_data()
        if not outage_data:
            return "Fara date"

        data_obj = outage_data.get("data")
        if isinstance(data_obj, dict):
            check = data_obj.get("checkInterruzione", "")
            if check == "true":
                return "Fara intreruperi"
            if check == "false":
                return "Intrerupere activa"

        return outage_data.get("esito", "") or "Necunoscut"

    @property
    def extra_state_attributes(self) -> dict:
        outage_data = self._get_outage_data()
        if not outage_data:
            return {"attribution": ATTRIBUTION}

        attrs: dict = {"POD": self._ctx.pod_name}
        data_obj = outage_data.get("data")
        if isinstance(data_obj, dict):
            messaggio = data_obj.get("messaggio", "")
            if messaggio:
                attrs["Mesaj"] = decode_html_entities(messaggio)
            attrs["Verificare intreruperi"] = data_obj.get("checkInterruzione", "")
            attrs["Rezultat"] = data_obj.get("esito", "")

        attrs["attribution"] = ATTRIBUTION
        return attrs

    def _get_outage_data(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("power_outages", {}).get(self._ctx.pod_name)


class SmartMeterConsumSensor(ReteleElectriceSensorBase):
    """Sensor for historical smart meter consumption summary."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, coordinator, config_entry, ctx: PodContext) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="smart_meter_consum",
            sensor_name="Smart Meter Consum",
            icon="mdi:chart-line",
        )

    @property
    def native_value(self) -> float | None:
        sm_data = self._get_smart_meter_data()
        if not sm_data or sm_data.get("Result", "") != "OK":
            return None
        rows = sm_data.get("row", [])
        return safe_float(rows[0].get("SUM_EA", "0"), None) if rows else None

    @property
    def extra_state_attributes(self) -> dict:
        sm_data = self._get_smart_meter_data()
        if not sm_data:
            return {"attribution": ATTRIBUTION}

        rows = sm_data.get("row", [])
        if not rows:
            return {"Rezultat": sm_data.get("Result", ""), "attribution": ATTRIBUTION}

        row = rows[0]
        attrs: dict = {
            "POD": row.get("POD", self._ctx.pod_name),
            "Contor": row.get("METER", ""),
            "Perioada start": row.get("START_DATE", ""),
            "Perioada sfarsit": row.get("END_DATE", ""),
            "Total energie consumata (kWh)": safe_float(row.get("SUM_EA", "0")),
            "Varf consum (kWh)": safe_float(row.get("MAX_EA", "0")),
        }

        if row.get("SUM_ER"):
            attrs["Total energie reactiva (kVArh)"] = safe_float(row["SUM_ER"])
        if row.get("MAX_ER"):
            attrs["Varf energie reactiva (kVArh)"] = safe_float(row["MAX_ER"])

        cosfi = row.get("COSFI", "-9999")
        if cosfi and cosfi != "-9999":
            attrs["Factor de putere (cos phi)"] = safe_float(cosfi)

        attrs["Rezultat"] = sm_data.get("Result", "")
        attrs["attribution"] = ATTRIBUTION
        return attrs

    def _get_smart_meter_data(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("smart_meter", {}).get(self._ctx.pod_name)


class SmartMeterProductieSensor(ReteleElectriceSensorBase):
    """Sensor for historical smart meter production summary."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, coordinator, config_entry, ctx: PodContext) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="smart_meter_productie",
            sensor_name="Smart Meter Productie",
            icon="mdi:solar-power",
        )

    @property
    def native_value(self) -> float | None:
        sm_data = self._get_smart_meter_data()
        if not sm_data or sm_data.get("Result", "") != "OK":
            return None
        rows = sm_data.get("row", [])
        return safe_float(rows[0].get("SUM_EAP", "0"), None) if rows else None

    @property
    def extra_state_attributes(self) -> dict:
        sm_data = self._get_smart_meter_data()
        if not sm_data:
            return {"attribution": ATTRIBUTION}

        rows = sm_data.get("row", [])
        if not rows:
            return {"Rezultat": sm_data.get("Result", ""), "attribution": ATTRIBUTION}

        row = rows[0]
        attrs: dict = {
            "POD": row.get("POD", self._ctx.pod_name),
            "Contor": row.get("METER", ""),
            "Perioada start": row.get("START_DATE", ""),
            "Perioada sfarsit": row.get("END_DATE", ""),
            "Total energie produsa (kWh)": safe_float(row.get("SUM_EAP", "0")),
            "Varf productie (kWh)": safe_float(row.get("MAX_EAP", "0")),
        }

        if row.get("SUM_ERC"):
            attrs["Total energie reactiva capacitiva (kVArh)"] = safe_float(row["SUM_ERC"])
        if row.get("MAX_ERC"):
            attrs["Varf energie reactiva capacitiva (kVArh)"] = safe_float(row["MAX_ERC"])

        cosfic = row.get("COSFIC", "-9999")
        if cosfic and cosfic != "-9999":
            attrs["Factor de putere capacitiv"] = safe_float(cosfic)

        attrs["Rezultat"] = sm_data.get("Result", "")
        attrs["attribution"] = ATTRIBUTION
        return attrs

    def _get_smart_meter_data(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("smart_meter", {}).get(self._ctx.pod_name)


def _parse_comma_float(value: str | None) -> float | None:
    """Parse a decimal string with comma or dot separator; ignore sentinel -9999."""
    if not value or value == "-9999":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _get_instant_data(coordinator, pod_name: str) -> dict | None:
    """Return instantaneous smart meter payload for a POD."""
    if not coordinator.data:
        return None
    return coordinator.data.get("instant_values", {}).get(pod_name)


def _get_instant_energy(instant_data: dict, code: str) -> float | None:
    """Extract an instantaneous energy register value (EA, EAP, ER, ERC)."""
    if not instant_data:
        return None
    value_list = instant_data.get("dataIstantValueList")
    if not value_list or not isinstance(value_list, list):
        return None
    readings = value_list[0].get("energyReadingList")
    if not readings or not isinstance(readings, list):
        return None
    for r in readings:
        if r.get("ENERGY_TYPE") == code:
            return _parse_comma_float(r.get("VALUE"))
    return None


class ValoareInstantaneeConsumSensor(ReteleElectriceSensorBase):
    """Sensor for instantaneous active consumption and electrical phase attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "valoare_instantanee_consum"
    _attr_icon = "mdi:flash"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self,
        coordinator: ReteleElectriceCoordinator,
        config_entry: ConfigEntry,
        ctx: PodContext,
    ) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="valoare_instantanee_consum",
            sensor_name="Valoare instantanee consum",
            icon="mdi:flash",
        )

    @property
    def native_value(self) -> float | None:
        instant = _get_instant_data(self.coordinator, self._ctx.pod_name)
        return _get_instant_energy(instant, "EA")

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {}
        instant = _get_instant_data(self.coordinator, self._ctx.pod_name)
        if not instant:
            attrs["attribution"] = ATTRIBUTION
            return attrs

        value_list = instant.get("dataIstantValueList")
        if not value_list or not isinstance(value_list, list):
            attrs["attribution"] = ATTRIBUTION
            return attrs

        first = value_list[0]

        for phase, key in [("R", "UR_VALUE"), ("S", "US_VALUE"), ("T", "UT_VALUE")]:
            val = _parse_comma_float(first.get(key))
            if val is not None:
                attrs[f"Tensiune faza {phase} (V)"] = val

        for phase, key in [("R", "IR_VALUE"), ("S", "IS_VALUE"), ("T", "IT_VALUE")]:
            val = _parse_comma_float(first.get(key))
            if val is not None:
                attrs[f"Curent faza {phase} (A)"] = val

        p_val = _parse_comma_float(first.get("P_VALUE"))
        if p_val is not None:
            attrs["Putere activa instantanee (kW)"] = p_val

        er_val = _get_instant_energy(instant, "ER")
        if er_val is not None:
            attrs["Energie reactiva (kVArh)"] = er_val

        if first.get("READING_DATE"):
            attrs["Data citire"] = first["READING_DATE"]
        if first.get("LAST_UPDATED"):
            attrs["Ultima actualizare"] = first["LAST_UPDATED"]
        if first.get("METER"):
            attrs["Contor"] = first["METER"]
        if instant.get("Result"):
            attrs["Rezultat"] = instant["Result"]

        attrs["attribution"] = ATTRIBUTION
        return attrs


class ValoareInstantaneeProductieSensor(ReteleElectriceSensorBase):
    """Sensor for instantaneous active production on prosumer smart meters."""

    _attr_has_entity_name = True
    _attr_translation_key = "valoare_instantanee_productie"
    _attr_icon = "mdi:solar-power"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self,
        coordinator: ReteleElectriceCoordinator,
        config_entry: ConfigEntry,
        ctx: PodContext,
    ) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="valoare_instantanee_productie",
            sensor_name="Valoare instantanee productie",
            icon="mdi:solar-power",
        )

    @property
    def native_value(self) -> float | None:
        instant = _get_instant_data(self.coordinator, self._ctx.pod_name)
        return _get_instant_energy(instant, "EAP")

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {}
        instant = _get_instant_data(self.coordinator, self._ctx.pod_name)
        if not instant:
            attrs["attribution"] = ATTRIBUTION
            return attrs

        eap_val = _get_instant_energy(instant, "EAP")
        if eap_val is not None:
            attrs["Energie activa produsa (kWh)"] = eap_val

        erc_val = _get_instant_energy(instant, "ERC")
        if erc_val is not None:
            attrs["Energie reactiva capacitiva (kVArh)"] = erc_val

        value_list = instant.get("dataIstantValueList")
        if value_list and isinstance(value_list, list):
            first = value_list[0]
            if first.get("READING_DATE"):
                attrs["Data citire"] = first["READING_DATE"]
            if first.get("LAST_UPDATED"):
                attrs["Ultima actualizare"] = first["LAST_UPDATED"]
            if first.get("METER"):
                attrs["Contor"] = first["METER"]

        if instant.get("Result"):
            attrs["Rezultat"] = instant["Result"]

        attrs["attribution"] = ATTRIBUTION
        return attrs


_LUNI_RO = {
    1: "ianuarie", 2: "februarie", 3: "martie", 4: "aprilie",
    5: "mai", 6: "iunie", 7: "iulie", 8: "august",
    9: "septembrie", 10: "octombrie", 11: "noiembrie", 12: "decembrie",
}


def _format_date_friendly(date_str: str | None) -> str | None:
    """Format ISO (YYYY-MM-DD) or dot-separated (DD.MM.YYYY) dates."""
    if not date_str:
        return None
    date_str = date_str.strip()
    if len(date_str) >= 10 and date_str[4] == "-":
        try:
            parts = date_str[:10].split("-")
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{d} {_LUNI_RO.get(m, str(m))} {y}"
        except (ValueError, IndexError):
            pass
    if len(date_str) >= 10 and date_str[2] == ".":
        try:
            parts = date_str[:10].split(".")
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{d} {_LUNI_RO.get(m, str(m))} {y}"
        except (ValueError, IndexError):
            pass
    return date_str


class DateFurnizorSensor(ReteleElectriceSensorBase):
    """Sensor exposing supplier and technical POD metadata from queryPOD."""

    _attr_has_entity_name = True
    _attr_translation_key = "date_furnizor"
    _attr_icon = "mdi:office-building"

    def __init__(
        self,
        coordinator: ReteleElectriceCoordinator,
        config_entry: ConfigEntry,
        ctx: PodContext,
    ) -> None:
        super().__init__(
            coordinator,
            config_entry,
            ctx,
            sensor_key="date_furnizor",
            sensor_name="Date furnizor",
            icon="mdi:office-building",
        )

    @property
    def native_value(self) -> str | None:
        supplier = self._get_supplier_data()
        return supplier.get("cui") if supplier else None

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {}
        supplier = self._get_supplier_data()
        if not supplier:
            attrs["attribution"] = ATTRIBUTION
            return attrs

        mapping = [
            ("furnizor", "Furnizor"),
            ("furnizor_pre", "PRE (Operator distributie)"),
            ("cui", "CUI furnizor"),
            ("nume_client", "Nume client"),
            ("adresa_client", "Adresa client"),
            ("adresa_locons", "Adresa loc de consum"),
            ("kw_aprobata", "Putere aprobata (kW)"),
            ("kw_evacuata", "Putere evacuata (kW)"),
            ("delimitare", "Punct delimitare"),
            ("u_delimitare", "Tensiune punct delimitare"),
            ("cft_description", "Zona distributie"),
            ("cft_ou_description", "Unitate operationala"),
            ("cft_district_uo", "Judet distributie"),
            ("aggregation_formula", "Formula agregare"),
            ("compensation_mode", "Mod compensare"),
        ]
        for key, label in mapping:
            if supplier.get(key):
                attrs[label] = supplier[key]

        racordare = supplier.get("racordare")
        if racordare and racordare.strip() not in ("", "-"):
            attrs["Punct de racordare"] = racordare

        if supplier.get("activ"):
            attrs["Stare"] = "Activ" if supplier["activ"] == "D" else "Inactiv"
        if supplier.get("deconectat"):
            attrs["Deconectat"] = "Da" if supplier["deconectat"] == "D" else "Nu"
        if supplier.get("activ_furnizor_la"):
            attrs["Activ furnizor de la"] = _format_date_friendly(supplier["activ_furnizor_la"])
        if supplier.get("activ_consumator_la"):
            attrs["Activ consumator de la"] = _format_date_friendly(supplier["activ_consumator_la"])

        if supplier.get("atr_number"):
            atr_str = supplier["atr_number"]
            if supplier.get("atr_date"):
                atr_str += f" / {_format_date_friendly(supplier['atr_date'])}"
            attrs["Nr. si data ATR/CER"] = atr_str

        if supplier.get("cer_version"):
            cer_str = f"v{supplier['cer_version']}"
            if supplier.get("cer_date"):
                cer_str += f" / {_format_date_friendly(supplier['cer_date'])}"
            attrs["Versiune CER"] = cer_str

        if supplier.get("telecitit"):
            attrs["Telecitire"] = "Da" if supplier["telecitit"] == "D" else "Nu"

        contoare = supplier.get("Contor")
        if contoare and isinstance(contoare, list) and len(contoare) > 0:
            c = contoare[0]
            if c.get("seria"):
                attrs["Seria contorului"] = c["seria"]
            if c.get("marca"):
                attrs["Marca contor"] = c["marca"]
            if c.get("det_tip"):
                attrs["Tip contor"] = c["det_tip"]
            if c.get("data_montare"):
                attrs["Data montare"] = _format_date_friendly(c["data_montare"])
            if c.get("precizie"):
                attrs["Precizie"] = c["precizie"]
            if c.get("constanta"):
                attrs["Constanta"] = c["constanta"]

        corectii = supplier.get("corectii")
        if corectii and corectii.strip() not in ("", "-"):
            attrs["Corectii"] = corectii

        attrs["attribution"] = ATTRIBUTION
        return attrs

    def _get_supplier_data(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("supplier_data", {}).get(self._ctx.pod_name)
