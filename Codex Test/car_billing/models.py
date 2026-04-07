from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class VehicleConfig:
    vehicle_id: str
    label: str
    battery_capacity_kwh: Decimal
    vin_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceFormat:
    key: str
    label: str
    supported_extensions: tuple[str, ...]
    required_fields: tuple[str, ...]
    column_aliases: dict[str, tuple[str, ...]]
    datetime_formats: tuple[str, ...]
    default_vehicle_id: str | None = None
    preferred_sheet_name: str | None = None


@dataclass(frozen=True)
class SourceDocument:
    source_path: Path
    extension: str
    content: bytes
    member_name: str | None = None
    content_hash: str | None = None

    @property
    def display_name(self) -> str:
        if self.member_name:
            return f"{self.source_path.name}::{self.member_name}"
        return self.source_path.name


@dataclass(frozen=True)
class ParsedTransaction:
    vehicle_id: str
    timestamp: datetime
    kwh: Decimal
    source_file: str
    source_row: int


@dataclass(frozen=True)
class ValidationIssue:
    source_file: str
    message: str
    row_number: int | None = None
    level: str = "error"


@dataclass(frozen=True)
class ExportResult:
    vehicle_id: str
    month: str
    pdf_path: Path
    transaction_count: int
    total_kwh: Decimal
    total_eur: Decimal


@dataclass
class PipelineResult:
    scanned_files: int = 0
    imported_transactions: int = 0
    skipped_duplicates: int = 0
    exported_files: list[ExportResult] = field(default_factory=list)
    deleted_source_files: list[Path] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
