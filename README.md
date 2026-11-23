# Rețele Electrice România — Integrare Home Assistant

Integrare personalizată (*custom component*) pentru **Home Assistant** care preia automat datele punctelor de consum (**POD**) din portalul [contulmeu.reteleelectrice.ro](https://contulmeu.reteleelectrice.ro).

## Funcționalități principale

* **Descoperire automată a POD-urilor:** După autentificare, îți poți alege toate punctele de consum sau doar pe cele dorite.
* **Suport complet Consumator & Prosumator:** Senzori dedicați atât pentru energia activă consumată (`EA`), cât și pentru energia produsă/injectată în rețea (`EAP`).
* **Compatibilitate Energy Dashboard:** Senzorii de index și valori instantanee folosesc `device_class: energy` și `state_class: total_increasing`, fiind gata de adăugat în panoul *Energy* din Home Assistant.
* **Suport Smart Meter:** Preluare date detaliate de la contoarele inteligente (consum/producție cumulată, tensiune și curent pe fiecare fază R, S, T, putere activă instantanee, factor de putere cosφ).
* **Actualizare la cerere:** Buton dedicat per POD (pentru contoarele smart) pentru interogarea instantanee a contorului.
* **Istoric & Date administrative:** Arhivă anuală a citirilor, status întreruperi de curent, date furnizor (CUI, PRE, putere aprobată/evacuată, serie contor, ATR/CER) și date profil client.

## Entități create per POD

Pentru fiecare punct de consum (POD) selectat, integrarea creează un dispozitiv (*Service*) cu următoarele entități:

### Senzori generali

| Entitate | Descriere |
| :--- | :--- |
| **POD** | Tipul contractului, stare, putere absorbită/cedată, serie contor, adresă și date tehnice. |
| **Date utilizator** | Nume titular, CNP/CUI, email, telefon și adresă de corespondență. |
| **Index citire consum** | Ultimul index înregistrat pentru energia consumată (`kWh`). |
| **Index citire producție** | Ultimul index înregistrat pentru energia produsă (`kWh`, doar pentru prosumatori). |
| **Energie consumată ({An})** | Totalul și istoricul citirilor de consum pe ultimii 2 ani. |
| **Energie produsă ({An})** | Totalul și istoricul citirilor de producție pe ultimii 2 ani (doar pentru prosumatori). |
| **Întreruperi curent** | Starea alimentării și eventualele mesaje privind întreruperile programate/neprogramate. |
| **Date furnizor** | CUI furnizor, nume furnizor, PRE, putere aprobată/evacuată, punct de delimitare și detalii contor. |

### Senzori & Butoane Smart Meter *(doar pentru POD-uri cu contor inteligent)*

| Entitate | Tip | Descriere |
| :--- | :--- | :--- |
| **Smart Meter Consum** | Senzor | Total energie consumată și vârf de consum din istoricul smart meter (`kWh`). |
| **Smart Meter Producție** | Senzor | Total energie produsă și vârf de producție (`kWh`, doar prosumatori). |
| **Valoare instantanee consum** | Senzor | Index instantaneu consum (`kWh`), cu atribute pentru tensiune (UR, US, UT), curent (IR, IS, IT) și putere activă. |
| **Valoare instantanee producție** | Senzor | Index instantaneu producție (`kWh`, doar prosumatori). |
| **Actualizare valori instantanee** | Buton | Forțează citirea valorilor instantanee din portalul Rețele Electrice. |

## Instalare

### Opțiunea 1: Prin HACS (Recomandat)

1. Deschide **HACS** în Home Assistant.
2. Mergi la **Integrations** → meniul din dreapta sus (**⋮**) → **Custom repositories**.
3. Adaugă URL-ul acestui repository GitHub și selectează categoria **Integration**.
4. Caută **Rețele Electrice România** în HACS și apasă **Download**.
5. Repornește Home Assistant.

### Opțiunea 2: Instalare manuală

1. Descarcă acest repository.
2. Copiază folderul `custom_components/reteleelectrice` în directorul `config/custom_components/` al instanței tale Home Assistant.
3. Asigură-te că structura arată astfel:

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
