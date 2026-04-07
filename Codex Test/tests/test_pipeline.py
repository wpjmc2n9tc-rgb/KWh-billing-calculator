from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from car_billing.config import build_config
from car_billing.database import TransactionRepository
from car_billing.parsers import DocumentParser, discover_source_documents
from car_billing.pipeline import BillingPipeline


class BillingPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.io_dir = self.workspace / "input_output"
        self.io_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.workspace / "data" / "transactions.sqlite"
        self.config = build_config()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pipeline_exports_completed_month_and_deletes_fully_processed_file(self) -> None:
        self._write_trip_export_zip(
            self.io_dir / "march_vw.zip",
            "ExportTrips-2026-03-31 14-18-43/Kurzzeitdaten.csv",
            "WVWZZZ3HZNE500823",
            [
                ["31/03/2026, 08:30", "4,5"],
            ],
        )
        self._write_trip_export_zip(
            self.io_dir / "april_vw.zip",
            "ExportTrips-2026-04-30 14-18-43/Kurzzeitdaten.csv",
            "WVWZZZ3HZNE500823",
            [
                ["01/04/2026, 09:00", "2,0"],
            ],
        )

        result = BillingPipeline(self.config, self.io_dir, self.db_path).run()

        self.assertEqual(result.imported_transactions, 2)
        self.assertEqual(len(result.exported_files), 1)
        self.assertFalse((self.io_dir / "march_vw.zip").exists())
        self.assertTrue((self.io_dir / "april_vw.zip").exists())
        exported_pdf = self.io_dir / "2026-03_1_volkswagen-arteon.pdf"
        self.assertTrue(exported_pdf.exists())
        self.assertTrue(exported_pdf.read_bytes().startswith(b"%PDF-1.4"))

        with TransactionRepository(self.db_path) as repository:
            self.assertEqual(repository.transaction_count(), 1)

    def test_duplicate_transaction_is_skipped_against_sqlite(self) -> None:
        self._write_trip_export_zip(
            self.io_dir / "april_vw.zip",
            "ExportTrips-2026-04-30 14-18-43/Kurzzeitdaten.csv",
            "WVWZZZ3HZNE500823",
            [
                ["01/04/2026, 09:00", "2,0"],
            ],
        )
        self._write_trip_export_zip(
            self.io_dir / "april_vw_duplicate.zip",
            "ExportTrips-2026-04-30 14-15-40/Kurzzeitdaten.csv",
            "WVWZZZ3HZNE500823",
            [
                ["01/04/2026, 09:00", "2,0"],
            ],
        )

        result = BillingPipeline(self.config, self.io_dir, self.db_path).run()

        self.assertEqual(result.imported_transactions, 1)
        self.assertEqual(result.skipped_duplicates, 1)
        self.assertTrue(
            any("Skipped duplicate transaction" in issue.message for issue in result.issues)
        )

    def test_zero_kwh_transaction_is_imported(self) -> None:
        self._write_trip_export_zip(
            self.io_dir / "vw_zero.zip",
            "ExportTrips-2026-04-30 14-18-43/Kurzzeitdaten.csv",
            "WVWZZZ3HZNE500823",
            [
                ["01/04/2026, 09:00", "0"],
            ],
        )

        result = BillingPipeline(self.config, self.io_dir, self.db_path).run()

        self.assertEqual(result.imported_transactions, 1)
        self.assertFalse(any("zero or greater" in issue.message for issue in result.issues))

        with TransactionRepository(self.db_path) as repository:
            rows = repository.fetch_month_transactions("1", "2026-04")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kwh"], 0.0)

    def test_xlsx_default_vehicle_is_detected_for_app3_format(self) -> None:
        xlsx_path = self.io_dir / "skoda_april.xlsx"
        self._write_minimal_xlsx(
            xlsx_path,
            [
                ["Datum", "Uhrzeit", "Verbrauch (kWh)"],
                ["01.04.2026", "10:30", "8,2"],
            ],
        )

        documents = discover_source_documents(self.io_dir)
        parser = DocumentParser(self.config)
        transactions, issues = parser.parse_document(documents[0])

        self.assertEqual(len(issues), 0)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].vehicle_id, "default")

    def test_headerless_charging_history_csv_is_detected(self) -> None:
        csv_path = self.io_dir / "chargingHistory_TMBJB9NYXRF036225_31032026_141618.csv"
        csv_path.write_text(
            '"30.03.2026 20:11","AC","23","14:22"\n'
            '"25.03.2026 08:56","AC","3","08:45"\n',
            encoding="utf-8",
        )

        documents = discover_source_documents(self.io_dir)
        charging_document = next(doc for doc in documents if doc.source_path == csv_path)
        parser = DocumentParser(self.config)
        transactions, issues = parser.parse_document(charging_document)

        self.assertEqual(len(issues), 0)
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0].vehicle_id, "default")
        self.assertEqual(str(transactions[0].kwh), "23")

    def test_skoda_charging_history_with_split_date_and_time_is_detected(self) -> None:
        csv_path = self.io_dir / "chargingHistory_TMBJB9NYXRF036225_split.csv"
        csv_path.write_text(
            '"30.03.2026","20:11","AC","23","14:22"\n',
            encoding="utf-8",
        )

        documents = discover_source_documents(self.io_dir)
        charging_document = next(doc for doc in documents if doc.source_path == csv_path)
        parser = DocumentParser(self.config)
        transactions, issues = parser.parse_document(charging_document)

        self.assertEqual(len(issues), 0)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].vehicle_id, "default")
        self.assertEqual(str(transactions[0].kwh), "23")

    def test_audi_trip_export_is_detected_from_kurzzeitspeicher(self) -> None:
        zip_path = self.io_dir / "audi_export.zip"
        self._write_audi_trip_export_zip(
            zip_path,
            "ExportTrips-2026-03-31 14-15-40/Kurzzeitspeicher.csv",
            "WAUZZZF21RN043169",
            [["31/03/2026, 09:17", "2,48"]],
        )

        documents = discover_source_documents(self.io_dir)
        audi_document = next(doc for doc in documents if doc.source_path == zip_path)
        parser = DocumentParser(self.config)
        transactions, issues = parser.parse_document(audi_document)

        self.assertEqual(len(issues), 0)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].vehicle_id, "2")
        self.assertEqual(str(transactions[0].kwh), "2.48")

    def test_zip_discovery_ignores_non_relevant_csv_members(self) -> None:
        zip_path = self.io_dir / "mixed_export.zip"
        with ZipFile(zip_path, "w") as archive:
            archive.writestr(
                "ExportTrips-2026-03-31 14-15-40/Kurzzeitspeicher.csv",
                "\n".join(
                    [
                        'WAUZZZF21RN043169;;;Strecke:;27.421 km;Exportiert am:;"31/03/2026, 14:15"',
                        ";;;;;;;Hybridantrieb",
                        "Fahrtende;Zurückgelegte Strecke in km;Gefahrene Zeit in Stunden;Durchschnittsgeschwindigkeit in km/h;Durchschnittlicher Kraftstoffverbrauch in l/100km;Durchschnittlicher Energieverbrauch in kWh/100km;Gesamtverbrauch in l;Gesamtverbrauch in kWh",
                        '"31/03/2026, 09:17";8;00:11;47;"3,3";31;"0,26";"2,48"',
                    ]
                ),
            )
            archive.writestr("ExportTrips-2026-03-31 14-15-40/Langzeitspeicher.csv", "ignored")
            archive.writestr("ExportTrips-2026-03-31 14-15-40/Ab Laden oder Tanken.csv", "ignored")

        documents = discover_source_documents(self.io_dir)

        self.assertEqual(len(documents), 1)
        self.assertEqual(Path(documents[0].member_name).name, "Kurzzeitspeicher.csv")

    def _write_zip_csv(self, zip_path: Path, inner_name: str, rows: list[list[str]]) -> None:
        lines = [";".join(row) for row in rows]
        with ZipFile(zip_path, "w") as archive:
            archive.writestr(inner_name, "\n".join(lines))

    def _write_trip_export_zip(
        self,
        zip_path: Path,
        inner_name: str,
        vin: str,
        rows: list[list[str]],
    ) -> None:
        header = (
            "Fahrtende;Fahrstrecke in km;Fahrzeit in Std.;Durchschnittsgeschwindigkeit in km/h;"
            "Durchschnittsverbrauch Kraftstoff in l/100 km;"
            "Durchschnittsverbrauch Strom in kWh/100 km;"
            "Gesamtverbrauch in l;Gesamtverbrauch in kWh"
        )
        lines = [
            f'{vin};;;Kilometerstand:;52.490 km;Export erstellt am:;"31/03/2026, 14:18"',
            ";;;;;;;Hybridantrieb",
            header,
        ]
        for timestamp, total_kwh in rows:
            lines.append(f'"{timestamp}";9;00:12;43;"6,5";"12,8";"0,6";"{total_kwh}"')
        with ZipFile(zip_path, "w") as archive:
            archive.writestr(inner_name, "\n".join(lines))

    def _write_audi_trip_export_zip(
        self,
        zip_path: Path,
        inner_name: str,
        vin: str,
        rows: list[list[str]],
    ) -> None:
        header = (
            "Fahrtende;Zurückgelegte Strecke in km;Gefahrene Zeit in Stunden;"
            "Durchschnittsgeschwindigkeit in km/h;"
            "Durchschnittlicher Kraftstoffverbrauch in l/100km;"
            "Durchschnittlicher Energieverbrauch in kWh/100km;"
            "Gesamtverbrauch in l;Gesamtverbrauch in kWh"
        )
        lines = [
            f'{vin};;;Strecke:;27.421 km;Exportiert am:;"31/03/2026, 14:15"',
            ";;;;;;;Hybridantrieb",
            header,
        ]
        for timestamp, total_kwh in rows:
            lines.append(f'"{timestamp}";8;00:11;47;"3,3";31;"0,26";"{total_kwh}"')
        with ZipFile(zip_path, "w") as archive:
            archive.writestr(inner_name, "\n".join(lines))

    def _write_minimal_xlsx(self, path: Path, rows: list[list[str]]) -> None:
        with ZipFile(path, "w") as workbook:
            workbook.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
                    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
                    <Default Extension="xml" ContentType="application/xml"/>
                    <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
                    <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
                </Types>
                """,
            )
            workbook.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
                </Relationships>
                """,
            )
            workbook.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                    <sheets>
                        <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
                    </sheets>
                </workbook>
                """,
            )
            workbook.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
                </Relationships>
                """,
            )
            workbook.writestr("xl/worksheets/sheet1.xml", self._sheet_xml(rows))

    def _sheet_xml(self, rows: list[list[str]]) -> str:
        xml_rows = []
        for row_index, row in enumerate(rows, start=1):
            cells = []
            for column_index, value in enumerate(row, start=1):
                cell_reference = f"{self._column_name(column_index)}{row_index}"
                if self._is_number(value):
                    cells.append(f'<c r="{cell_reference}"><v>{value.replace(",", ".")}</v></c>')
                else:
                    cells.append(
                        f'<c r="{cell_reference}" t="inlineStr"><is><t>{value}</t></is></c>'
                    )
            xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        return (
            """<?xml version="1.0" encoding="UTF-8"?>
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                <sheetData>"""
            + "".join(xml_rows)
            + """</sheetData>
            </worksheet>"""
        )

    def _column_name(self, index: int) -> str:
        letters = []
        while index:
            index, remainder = divmod(index - 1, 26)
            letters.append(chr(65 + remainder))
        return "".join(reversed(letters))

    def _is_number(self, value: str) -> bool:
        try:
            float(value.replace(",", "."))
            return True
        except ValueError:
            return False


if __name__ == "__main__":
    unittest.main()
