from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO, StringIO
import csv
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile

from .config import AppConfig
from .excel import read_xlsx_rows
from .models import ParsedTransaction, SourceDocument, SourceFormat, ValidationIssue


INPUT_EXTENSIONS = {".csv", ".xlsx", ".zip", ".xls"}
TRIP_EXPORT_FILES = {
    "kurzzeitdaten.csv",
    "kurzzeitspeicher.csv",
}


class DocumentParser:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def parse_document(
        self,
        document: SourceDocument,
    ) -> tuple[list[ParsedTransaction], list[ValidationIssue]]:
        rows = self._read_rows(document)
        if not rows:
            return [], [ValidationIssue(document.display_name, "The file does not contain any data rows.")]

        source_format = self._detect_source_format(rows)
        column_map = self._resolve_columns(rows[0], source_format)
        return self._parse_rows(document, rows, source_format, column_map)

    def _read_rows(self, document: SourceDocument) -> list[dict[str, Any]]:
        document_name = _document_name(document)
        if document.extension == "csv":
            if document_name.startswith("charginghistory_"):
                return read_charging_history_rows(document)
            if document_name in TRIP_EXPORT_FILES:
                return read_trip_export_rows(document.content)
            return read_csv_rows(document.content)
        if document.extension == "xlsx":
            return read_xlsx_rows(document.content)
        if document.extension == "xls":
            raise ValueError(
                f"{document.display_name} uses the legacy .xls format, which is not supported "
                "without an additional dependency."
            )
        raise ValueError(f"{document.display_name} has an unsupported file type.")

    def _detect_source_format(self, rows: list[dict[str, Any]]) -> SourceFormat:
        headers = set(rows[0].keys())
        best_format: SourceFormat | None = None
        best_score = -1
        for source_format in self.config.source_formats:
            column_map = self._resolve_columns(rows[0], source_format)
            required_present = all(field in column_map for field in source_format.required_fields)
            has_datetime = "timestamp" in column_map or (
                "date" in column_map and "time" in column_map
            )
            if not required_present or not has_datetime:
                continue

            score = len(column_map)
            if source_format.default_vehicle_id and "vehicle_ref" not in column_map:
                score += 2
            if not source_format.default_vehicle_id and "vehicle_ref" in column_map:
                score += 2
            if len(headers) <= 4 and source_format.default_vehicle_id:
                score += 1
            if score > best_score:
                best_score = score
                best_format = source_format

        if best_format is None:
            raise ValueError("The file headers do not match any configured app format.")
        return best_format

    def _resolve_columns(
        self,
        row: dict[str, Any],
        source_format: SourceFormat,
    ) -> dict[str, str]:
        normalized_headers = {_normalize_header(header): header for header in row}
        mapping: dict[str, str] = {}
        for field_name, aliases in source_format.column_aliases.items():
            for alias in aliases:
                normalized_alias = _normalize_header(alias)
                if normalized_alias in normalized_headers:
                    mapping[field_name] = normalized_headers[normalized_alias]
                    break
        return mapping

    def _parse_rows(
        self,
        document: SourceDocument,
        rows: list[dict[str, Any]],
        source_format: SourceFormat,
        column_map: dict[str, str],
    ) -> tuple[list[ParsedTransaction], list[ValidationIssue]]:
        issues: list[ValidationIssue] = []
        transactions: list[ParsedTransaction] = []
        seen_keys: set[tuple[str, str]] = set()

        for row_number, row in enumerate(rows, start=2):
            try:
                timestamp = self._parse_timestamp(row, column_map, source_format)
                vehicle_id = self._resolve_vehicle_id(row, column_map, source_format)
                kwh = _parse_decimal(row.get(column_map["kwh"]))
                self._validate_kwh(kwh, vehicle_id)
            except ValueError as error:
                issues.append(
                    ValidationIssue(
                        source_file=document.display_name,
                        row_number=row_number,
                        message=str(error),
                    )
                )
                continue

            key = (vehicle_id, timestamp.isoformat())
            if key in seen_keys:
                issues.append(
                    ValidationIssue(
                        source_file=document.display_name,
                        row_number=row_number,
                        message="Skipped duplicate row inside the same file.",
                        level="warning",
                    )
                )
                continue

            seen_keys.add(key)
            transactions.append(
                ParsedTransaction(
                    vehicle_id=vehicle_id,
                    timestamp=timestamp,
                    kwh=kwh,
                    source_file=str(document.source_path),
                    source_row=row_number,
                )
            )
        return transactions, issues

    def _parse_timestamp(
        self,
        row: dict[str, Any],
        column_map: dict[str, str],
        source_format: SourceFormat,
    ) -> datetime:
        if "timestamp" in column_map:
            value = row.get(column_map["timestamp"])
            return _parse_datetime_value(value, source_format.datetime_formats, self.config.timezone)

        date_value = row.get(column_map["date"])
        time_value = row.get(column_map["time"])
        combined = f"{date_value} {time_value}"
        return _parse_datetime_value(combined, source_format.datetime_formats, self.config.timezone)

    def _resolve_vehicle_id(
        self,
        row: dict[str, Any],
        column_map: dict[str, str],
        source_format: SourceFormat,
    ) -> str:
        if "vehicle_ref" in column_map:
            vehicle_ref = str(row.get(column_map["vehicle_ref"], "")).strip().upper()
            for vehicle_id, vehicle in self.config.vehicles.items():
                if any(vehicle_ref.startswith(prefix) for prefix in vehicle.vin_prefixes):
                    return vehicle_id
        if source_format.default_vehicle_id:
            return source_format.default_vehicle_id
        raise ValueError("Could not determine the vehicle ID from the row.")

    def _validate_kwh(self, kwh: Decimal, vehicle_id: str) -> None:
        if kwh < 0:
            raise ValueError("kWh must be zero or greater.")
        vehicle = self.config.vehicles[vehicle_id]
        max_allowed = vehicle.battery_capacity_kwh * self.config.max_session_factor
        if kwh > max_allowed:
            raise ValueError(
                f"kWh value {kwh} exceeds the configured plausibility threshold of {max_allowed}."
            )


def discover_source_documents(input_dir: Path) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in INPUT_EXTENSIONS:
            continue
        content = path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        if path.suffix.lower() == ".zip":
            documents.extend(_documents_from_zip(path, content, content_hash))
            continue
        documents.append(
            SourceDocument(
                source_path=path,
                extension=path.suffix.lower().lstrip("."),
                content=content,
                content_hash=content_hash,
            )
        )
    return documents


def group_documents_by_file(documents: list[SourceDocument]) -> dict[str, list[SourceDocument]]:
    grouped: dict[str, list[SourceDocument]] = {}
    for document in documents:
        grouped.setdefault(document.content_hash or "", []).append(document)
    return grouped


def read_csv_rows(content: bytes) -> list[dict[str, str]]:
    return _read_csv_rows(content)


def read_charging_history_rows(document: SourceDocument) -> list[dict[str, str]]:
    text = _decode_bytes(document.content)
    reader = csv.reader(StringIO(text), delimiter=",", quotechar='"')
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        if not raw_row or all(not value.strip() for value in raw_row):
            continue
        padded = list(raw_row)
        timestamp = padded[0] if padded else ""
        charging_type = padded[1] if len(padded) > 1 else ""
        kwh = padded[2] if len(padded) > 2 else ""
        duration = padded[3] if len(padded) > 3 else ""

        # Some exports split date/time into two columns instead of a single timestamp field.
        if len(padded) >= 5:
            timestamp = f"{padded[0]} {padded[1]}".strip()
            charging_type = padded[2]
            kwh = padded[3]
            duration = padded[4]

        rows.append(
            {
                "timestamp": timestamp,
                "charging_type": charging_type,
                "kwh": kwh,
                "duration": duration,
            }
        )
    return rows


def read_trip_export_rows(content: bytes) -> list[dict[str, str]]:
    rows = _read_csv_lines(content)
    if len(rows) < 4:
        return []

    vin = rows[0][0].strip() if rows[0] else ""
    headers = rows[2]
    data_rows = rows[3:]
    parsed_rows: list[dict[str, str]] = []
    for raw_row in data_rows:
        if not raw_row or all(not value.strip() for value in raw_row):
            continue
        row: dict[str, str] = {"VIN": vin}
        for index, header in enumerate(headers):
            if not header:
                continue
            row[header.strip()] = raw_row[index] if index < len(raw_row) else ""

        # Real VW/Audi exports are stable by position:
        # first column = trip timestamp, last column = total kWh used.
        row["timestamp"] = raw_row[0].strip() if raw_row else ""
        row["kwh"] = raw_row[-1].strip() if raw_row else ""
        parsed_rows.append(row)
    return parsed_rows


def _read_csv_rows(content: bytes) -> list[dict[str, str]]:
    text = _decode_bytes(content)
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    reader = csv.DictReader(StringIO(text), dialect=dialect)
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned_row = {key.strip(): value for key, value in row.items() if key is not None}
        if cleaned_row:
            rows.append(cleaned_row)
    return rows


def _read_csv_lines(content: bytes) -> list[list[str]]:
    text = _decode_bytes(content)
    reader = csv.reader(StringIO(text), delimiter=";", quotechar='"')
    return [row for row in reader]


def _documents_from_zip(path: Path, content: bytes, content_hash: str) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    with ZipFile(BytesIO(content)) as archive:
        for member_name in archive.namelist():
            member_basename = Path(member_name).name.casefold()
            suffix = Path(member_name).suffix.lower()
            if member_name.endswith("/") or suffix not in {".csv", ".xlsx", ".xls"}:
                continue
            if suffix == ".csv" and member_basename not in TRIP_EXPORT_FILES:
                continue
            documents.append(
                SourceDocument(
                    source_path=path,
                    extension=suffix.lstrip("."),
                    content=archive.read(member_name),
                    member_name=member_name,
                    content_hash=content_hash,
                )
            )
    return documents


def _decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("The file encoding is not supported.")


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _document_name(document: SourceDocument) -> str:
    if document.member_name:
        return Path(document.member_name).name.casefold()
    return document.source_path.name.casefold()


def _parse_decimal(value: Any) -> Decimal:
    if value is None:
        raise ValueError("kWh is missing.")
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError("kWh is missing.")
    cleaned = cleaned.replace("kWh", "").replace("KWH", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(f"Could not parse kWh value '{value}'.") from error


def _parse_datetime_value(value: Any, formats: tuple[str, ...], timezone) -> datetime:
    if value is None or value == "":
        raise ValueError("Timestamp is missing.")

    if isinstance(value, (int, float)):
        timestamp = datetime(1899, 12, 30) + timedelta(days=float(value))
        return timestamp.replace(tzinfo=timezone)

    text = str(value).strip()
    normalized_text = text.replace(", ", " ")
    try:
        parsed = datetime.fromisoformat(normalized_text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone)
    except ValueError:
        pass

    for fmt in formats:
        try:
            return datetime.strptime(normalized_text, fmt).replace(tzinfo=timezone)
        except ValueError:
            continue
    raise ValueError(f"Could not parse timestamp '{value}'.")
