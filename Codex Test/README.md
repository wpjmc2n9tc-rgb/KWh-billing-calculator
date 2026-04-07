# Car Energy Billing Processor

## Status
- Completed: Replaced the unrelated starter script with a configurable car-energy billing pipeline.
- Completed: Added ingestion, validation, SQLite persistence, monthly PDF export, and cleanup logic.
- Completed: Added automated tests for ZIP/CSV ingestion, SQLite duplicate handling, XLSX parsing, export gating, and cleanup.
- Completed: Verified the test suite in this environment with Python 3.12.
- Completed: Adjusted kWh validation/storage so `0 kWh` rows are imported instead of rejected.

## What It Does
- Reads charging transactions from a shared `input_output` folder outside the script folder.
- Supports direct `csv` / `xlsx` files and `zip` archives that contain those files.
- Detects the source format, identifies the vehicle, validates rows, and stores normalized transactions in SQLite.
- Exports one PDF per vehicle and complete month once a later month exists for the same vehicle.
- Deletes fully processed source files and removes exported rows from SQLite.

## Supported Real Export Shapes
- `chargingHistory_<VIN>_...csv`: headerless Skoda charging history. The parser uses column 1 as timestamp and column 3 as kWh.
- `ExportTrips-...zip` with `Kurzzeitdaten.csv`: Volkswagen trip export. The parser reads `Fahrtende` as timestamp and `Gesamtverbrauch in kWh` as kWh.
- `ExportTrips-...zip` with `Kurzzeitspeicher.csv`: Audi trip export. The parser reads `Fahrtende` as timestamp and `Gesamtverbrauch in kWh` as kWh.
- Inside ZIP exports, only the short-term trip CSVs are considered relevant: `Kurzzeitdaten.csv` and `Kurzzeitspeicher.csv`.
- Every other CSV inside the ZIP is skipped on purpose so aggregate/history data cannot be imported accidentally.

## Fixed Configuration
- Electricity price: `0.379 EUR / kWh`
- Vehicle `default`: `Skoda Enyaq`, `60 kWh`
- Vehicle `1`: `Volkswagen Arteon`, `13 kWh`
- Vehicle `2`: `Audi S7`, `17 kWh`

The fixed mappings live in [car_billing/config.py](/C:/Users/joela/OneDrive/Dokumente/Coden/Codex%20Test/car_billing/config.py). If the real app exports use different header names than the defaults included there, update only that file.

## Running
Use a Python 3.12 interpreter and run:

```powershell
python .\Aufgabe.py
```

Optional arguments:

```powershell
python .\Aufgabe.py --io-dir ..\input_output --db-path .\data\transactions.sqlite
```

If you use an embedded Windows Python that does not add the project folder to `sys.path`, the entrypoint now injects its own script directory automatically before importing `car_billing`.

## Testing
Run:

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
```

## Notes
- `xlsx` is supported without third-party libraries.
- Legacy binary Excel files (`.xls`) are rejected explicitly because the standard library cannot parse them safely.
- A `Europe/Berlin` fallback timezone implementation is included so the pipeline still works when the Python runtime has no bundled `tzdata`.
- Real sample-file parsing was checked against the user-provided exports in `C:\Users\joela\Downloads`.
- Transactions with `0 kWh` are allowed and billed as `0.00 EUR`; only negative values are rejected.
- The CLI prints only the first 25 issues by default so duplicate-heavy runs stay readable.
