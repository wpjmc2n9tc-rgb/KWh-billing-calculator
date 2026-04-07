from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .config import AppConfig
from .database import TransactionRepository
from .models import ExportResult, PipelineResult, ValidationIssue
from .parsers import DocumentParser, discover_source_documents, group_documents_by_file
from .pdf import write_text_pdf


class BillingPipeline:
    def __init__(self, config: AppConfig, io_dir: Path, db_path: Path) -> None:
        self.config = config
        self.io_dir = io_dir
        self.db_path = db_path
        self.parser = DocumentParser(config)

    def run(self) -> PipelineResult:
        self.io_dir.mkdir(parents=True, exist_ok=True)
        result = PipelineResult()
        documents = discover_source_documents(self.io_dir)
        result.scanned_files = len({str(document.source_path) for document in documents})

        with TransactionRepository(self.db_path) as repository:
            self._import_documents(repository, documents, result)
            self._export_completed_months(repository, result)
        return result

    def _import_documents(
        self,
        repository: TransactionRepository,
        documents,
        result: PipelineResult,
    ) -> None:
        for content_hash, file_documents in group_documents_by_file(documents).items():
            if repository.has_processed_hash(content_hash):
                continue

            parsed_transactions = []
            parsed_any_document = False
            source_path = file_documents[0].source_path
            for document in file_documents:
                try:
                    transactions, issues = self.parser.parse_document(document)
                except ValueError as error:
                    result.issues.append(
                        ValidationIssue(
                            source_file=document.display_name,
                            message=str(error),
                        )
                    )
                    continue
                parsed_any_document = True
                parsed_transactions.extend(transactions)
                result.issues.extend(issues)

            if not parsed_any_document:
                continue

            inserted, duplicates, issues = repository.insert_transactions(parsed_transactions)
            result.imported_transactions += inserted
            result.skipped_duplicates += duplicates
            result.issues.extend(issues)
            repository.record_processed_file(str(source_path), content_hash)

    def _export_completed_months(
        self,
        repository: TransactionRepository,
        result: PipelineResult,
    ) -> None:
        for vehicle_id, month in repository.completed_months():
            rows = repository.fetch_month_transactions(vehicle_id, month)
            if not rows:
                continue

            export_result = self._write_monthly_pdf(vehicle_id, month, rows)
            result.exported_files.append(export_result)

            transaction_ids = [int(row["id"]) for row in rows]
            source_files = sorted({str(row["source_file"]) for row in rows})
            repository.delete_transactions(transaction_ids)

            for source_file in source_files:
                if repository.count_transactions_for_source(source_file) > 0:
                    continue
                source_path = Path(source_file)
                if source_path.exists():
                    source_path.unlink()
                    result.deleted_source_files.append(source_path)

    def _write_monthly_pdf(self, vehicle_id: str, month: str, rows) -> ExportResult:
        vehicle = self.config.vehicles[vehicle_id]
        lines = [
            f"Vehicle: {vehicle.label} ({vehicle.vehicle_id})",
            f"Month: {month}",
            f"Price per kWh: EUR {self._format_money(self.config.price_per_kwh_eur)}",
            "",
            "Timestamp | kWh | EUR",
        ]

        total_kwh = Decimal("0")
        total_eur = Decimal("0")
        for row in rows:
            kwh = Decimal(str(row["kwh"]))
            eur = (kwh * self.config.price_per_kwh_eur).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            total_kwh += kwh
            total_eur += eur
            lines.append(
                f"{row['timestamp']} | {self._format_kwh(kwh)} | EUR {self._format_money(eur)}"
            )

        lines.extend(
            [
                "",
                f"Transactions: {len(rows)}",
                f"Total kWh: {self._format_kwh(total_kwh)}",
                f"Total EUR: {self._format_money(total_eur)}",
            ]
        )

        pdf_name = f"{month}_{vehicle.vehicle_id}_{self._slug(vehicle.label)}.pdf"
        pdf_path = self.io_dir / pdf_name
        title = f"{vehicle.label} charging summary {month}"
        write_text_pdf(pdf_path, title, lines)

        return ExportResult(
            vehicle_id=vehicle_id,
            month=month,
            pdf_path=pdf_path,
            transaction_count=len(rows),
            total_kwh=total_kwh,
            total_eur=total_eur,
        )

    def _format_kwh(self, value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.001'))} kWh"

    def _format_money(self, value: Decimal) -> str:
        return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"

    def _slug(self, value: str) -> str:
        return value.lower().replace(" ", "-")
