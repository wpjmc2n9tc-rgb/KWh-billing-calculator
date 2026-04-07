from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from .models import ParsedTransaction, ValidationIssue


class TransactionRepository(AbstractContextManager["TransactionRepository"]):
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "TransactionRepository":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if self.connection is not None:
            self.connection.close()

    def _initialize(self) -> None:
        connection = self._require_connection()
        self._ensure_transactions_schema(connection)
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_vehicle_timestamp
            ON transactions(vehicle_id, timestamp);

            CREATE TABLE IF NOT EXISTS processed_files (
                content_hash TEXT PRIMARY KEY,
                source_file TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );
            """
        )
        connection.commit()

    def _ensure_transactions_schema(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'transactions'
            """
        ).fetchone()
        if row is None:
            connection.execute(self._transactions_table_sql())
            return

        schema_sql = row["sql"] or ""
        if "CHECK (kwh > 0)" not in schema_sql:
            return

        connection.executescript(
            f"""
            ALTER TABLE transactions RENAME TO transactions_legacy;
            {self._transactions_table_sql()}
            INSERT INTO transactions (
                id, vehicle_id, timestamp, kwh, source_file, source_row, imported_at
            )
            SELECT
                id, vehicle_id, timestamp, kwh, source_file, source_row, imported_at
            FROM transactions_legacy;
            DROP TABLE transactions_legacy;
            """
        )

    def _transactions_table_sql(self) -> str:
        return """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            kwh REAL NOT NULL CHECK (kwh >= 0),
            source_file TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            imported_at TEXT NOT NULL,
            UNIQUE(vehicle_id, timestamp)
        );
        """

    def has_processed_hash(self, content_hash: str) -> bool:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT 1 FROM processed_files WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return row is not None

    def record_processed_file(self, source_file: str, content_hash: str) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            INSERT INTO processed_files(content_hash, source_file, processed_at)
            VALUES(?, ?, ?)
            """,
            (content_hash, source_file, datetime.now(UTC).isoformat(timespec="seconds")),
        )
        connection.commit()

    def insert_transactions(
        self,
        transactions: list[ParsedTransaction],
    ) -> tuple[int, int, list[ValidationIssue]]:
        connection = self._require_connection()
        inserted = 0
        duplicates = 0
        issues: list[ValidationIssue] = []
        imported_at = datetime.now(UTC).isoformat(timespec="seconds")
        for transaction in transactions:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO transactions(
                    vehicle_id, timestamp, kwh, source_file, source_row, imported_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction.vehicle_id,
                    transaction.timestamp.isoformat(),
                    float(transaction.kwh),
                    transaction.source_file,
                    transaction.source_row,
                    imported_at,
                ),
            )
            if cursor.rowcount:
                inserted += 1
                continue
            duplicates += 1
            issues.append(
                ValidationIssue(
                    source_file=transaction.source_file,
                    row_number=transaction.source_row,
                    message=(
                        "Skipped duplicate transaction because the same vehicle and "
                        "timestamp already exist in SQLite."
                    ),
                    level="warning",
                )
            )
        connection.commit()
        return inserted, duplicates, issues

    def completed_months(self) -> list[tuple[str, str]]:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT vehicle_id, timestamp FROM transactions ORDER BY vehicle_id, timestamp"
        ).fetchall()

        vehicle_months: dict[str, list[str]] = {}
        for row in rows:
            timestamp = datetime.fromisoformat(row["timestamp"])
            month_key = timestamp.strftime("%Y-%m")
            vehicle_months.setdefault(row["vehicle_id"], [])
            if month_key not in vehicle_months[row["vehicle_id"]]:
                vehicle_months[row["vehicle_id"]].append(month_key)

        completed: list[tuple[str, str]] = []
        for vehicle_id, months in vehicle_months.items():
            for month in months[:-1]:
                completed.append((vehicle_id, month))
        return completed

    def fetch_month_transactions(self, vehicle_id: str, month: str) -> list[sqlite3.Row]:
        connection = self._require_connection()
        return connection.execute(
            """
            SELECT id, vehicle_id, timestamp, kwh, source_file, source_row
            FROM transactions
            WHERE vehicle_id = ? AND timestamp LIKE ?
            ORDER BY timestamp
            """,
            (vehicle_id, f"{month}-%"),
        ).fetchall()

    def delete_transactions(self, transaction_ids: list[int]) -> None:
        if not transaction_ids:
            return
        connection = self._require_connection()
        placeholders = ",".join("?" for _ in transaction_ids)
        connection.execute(
            f"DELETE FROM transactions WHERE id IN ({placeholders})",
            transaction_ids,
        )
        connection.commit()

    def count_transactions_for_source(self, source_file: str) -> int:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT COUNT(*) AS row_count FROM transactions WHERE source_file = ?",
            (source_file,),
        ).fetchone()
        return int(row["row_count"])

    def transaction_count(self) -> int:
        connection = self._require_connection()
        row = connection.execute("SELECT COUNT(*) AS row_count FROM transactions").fetchone()
        return int(row["row_count"])

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("The repository connection is not open.")
        return self.connection
