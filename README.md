# Rețele Electrice România — Home Assistant Custom Integration

A free, local-processing custom integration for **Home Assistant** that fetches consumption point (**POD**) data from the [contulmeu.reteleelectrice.ro](https://contulmeu.reteleelectrice.ro) portal without license servers or external validation checks.

## Key Features

* **Automatic POD Discovery:** After signing in, choose to monitor all consumption points (**POD**) or only the ones you select.
* **Consumer & Prosumer Support:** Dedicated sensors for both consumed active energy (`EA`) and produced/fed-in energy (`EAP`).
* **Energy Dashboard Ready:** Meter reading and instant value sensors use `device_class: energy` and `state_class: total_increasing` for direct use in Home Assistant's Energy dashboard.
* **Smart Meter Support:** Retrieves cumulative consumption/production, per-phase voltages (`UR`, `US`, `UT`) and currents (`IR`, `IS`, `IT`), instantaneous active power, and power factor (`cosφ`).
* **On-Demand Refresh:** Includes a per-POD button (for smart meters) to force an immediate reading update.
* **Archive & Account Details:** Annual reading archives, power outage status, supplier/technical POD data (`CUI`, `PRE`, approved/exported power, meter serial, `ATR`/`CER`), and account profile details.

## Entities Created per POD

For each selected **POD**, the integration creates a service device with the following entities:

### General Sensors

| Entity | Description |
| :--- | :--- |
| **POD** | Contract type, status, absorbed/exported power, meter serial, address, and technical details. |
| **Date utilizator** | Account holder name, CNP/CUI, email, phone, and address. |
| **Index citire consum** | Latest recorded consumption meter index (`kWh`). |
| **Index citire producție** | Latest recorded production meter index (`kWh`, prosumers only). |
| **Energie consumată ({Year})** | Annual consumption total and reading history for up to the last 2 years. |
| **Energie produsă ({Year})** | Annual production total and reading history for up to the last 2 years (prosumers only). |
| **Întreruperi curent** | Power outage status and messages from the portal. |
| **Date furnizor** | Supplier `CUI`, supplier name, `PRE`, approved/exported power, demarcation point, and meter details. |

### Smart Meter Sensors & Buttons *(smart meter PODs only)*

| Entity | Type | Description |
| :--- | :--- | :--- |
| **Smart Meter Consum** | Sensor | Total consumed energy and peak consumption from smart meter history (`kWh`). |
| **Smart Meter Producție** | Sensor | Total produced energy and peak production (`kWh`, prosumers only). |
| **Valoare instantanee consum** | Sensor | Instantaneous consumption index (`kWh`), with attributes for phase voltages (`UR`, `US`, `UT`), currents (`IR`, `IS`, `IT`), and active power. |
| **Valoare instantanee producție** | Sensor | Instantaneous production index (`kWh`, prosumers only). |
| **Actualizare valori instantanee** | Button | Forces an immediate refresh of instantaneous meter values. |

## Installation

### Option 1: HACS (Recommended)

1. Open **HACS** in Home Assistant.
2. Go to **Integrations** → top-right menu (**⋮**) → **Custom repositories**.
3. Add this GitHub repository URL and select **Integration** as the category.
4. Search for **Rețele Electrice România** in HACS and click **Download**.
5. Restart Home Assistant.

### Option 2: Manual Installation

1. Download or clone this repository.
2. Copy the `custom_components/reteleelectrice` folder into your Home Assistant `config/custom_components/` directory.
3. Verify the directory layout matches:

```text
config/
└── custom_components/
    └── reteleelectrice/
        ├── __init__.py
        ├── api.py
        ├── button.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── helpers.py
        ├── manifest.json
        ├── sensor.py
        ├── strings.json
        └── translations/
            └── ro.json
