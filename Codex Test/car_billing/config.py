from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import SourceFormat, VehicleConfig


@dataclass(frozen=True)
class AppConfig:
    price_per_kwh_eur: Decimal
    timezone: ZoneInfo
    max_session_factor: Decimal
    vehicles: dict[str, VehicleConfig]
    source_formats: tuple[SourceFormat, ...]


class EuropeBerlinFallback(tzinfo):
    """DST-aware fallback for Europe/Berlin when IANA tzdata is unavailable."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=1) + self.dst(dt)

    def dst(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(0)
        naive = dt.replace(tzinfo=None)
        start = _last_sunday(naive.year, 3).replace(hour=2)
        end = _last_sunday(naive.year, 10).replace(hour=3)
        if start <= naive < end:
            return timedelta(hours=1)
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "Europe/Berlin"


def _last_sunday(year: int, month: int) -> datetime:
    day = datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year, 12, 31)
    while day.weekday() != 6:
        day -= timedelta(days=1)
    return day


def _build_timezone() -> tzinfo:
    try:
        return ZoneInfo("Europe/Berlin")
    except ZoneInfoNotFoundError:
        return EuropeBerlinFallback()


def build_config() -> AppConfig:
    """Return the fixed project configuration.

    Update the aliases here if the real app exports use different headers.
    """

    vehicles = {
        "default": VehicleConfig(
            vehicle_id="default",
            label="Skoda Enyaq",
            battery_capacity_kwh=Decimal("60"),
        ),
        "1": VehicleConfig(
            vehicle_id="1",
            label="Volkswagen Arteon",
            battery_capacity_kwh=Decimal("13"),
            vin_prefixes=("WVW",),
        ),
        "2": VehicleConfig(
            vehicle_id="2",
            label="Audi S7",
            battery_capacity_kwh=Decimal("17"),
            vin_prefixes=("WAU",),
        ),
    }

    app12_aliases = {
        "timestamp": (
            "timestamp",
            "date",
            "datetime",
            "transaction time",
            "start time",
            "zeitpunkt",
            "ladebeginn",
            "fahrtende",
        ),
        "date": ("date", "datum"),
        "time": ("time", "uhrzeit"),
        "kwh": (
            "kwh",
            "energy",
            "charged energy",
            "charged energy (kwh)",
            "consumption (kwh)",
            "geladene energie",
            "geladene energie (kwh)",
            "verbrauch (kwh)",
            "gesamtverbrauch in kwh",
        ),
        "vehicle_ref": (
            "vin",
            "vehicle",
            "vehicle id",
            "fahrzeug",
            "fin",
            "vehicle number",
        ),
    }

    app3_aliases = {
        "timestamp": ("timestamp", "datetime", "zeitpunkt"),
        "date": ("date", "datum", "booking date"),
        "time": ("time", "uhrzeit", "booking time"),
        "kwh": (
            "kwh",
            "energy",
            "energy (kwh)",
            "verbraucht (kwh)",
            "verbrauch (kwh)",
            "charged energy (kwh)",
        ),
        "vehicle_ref": ("vin", "vehicle", "fahrzeug"),
    }

    source_formats = (
        SourceFormat(
            key="app12",
            label="App 1/2",
            supported_extensions=("csv", "xlsx"),
            required_fields=("kwh",),
            column_aliases=app12_aliases,
            datetime_formats=(
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
            ),
        ),
        SourceFormat(
            key="app3",
            label="App 3",
            supported_extensions=("csv", "xlsx"),
            required_fields=("kwh",),
            column_aliases=app3_aliases,
            datetime_formats=(
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
            ),
            default_vehicle_id="default",
        ),
    )

    return AppConfig(
        price_per_kwh_eur=Decimal("0.379"),
        timezone=_build_timezone(),
        max_session_factor=Decimal("3.0"),
        vehicles=vehicles,
        source_formats=source_formats,
    )
