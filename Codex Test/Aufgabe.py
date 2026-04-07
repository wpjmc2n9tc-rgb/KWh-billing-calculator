from __future__ import annotations

import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from car_billing.config import build_config
from car_billing.pipeline import BillingPipeline


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    default_io_dir = script_dir.parent / "input_output"
    default_db_path = script_dir / "data" / "transactions.sqlite"

    parser = argparse.ArgumentParser(
        description="Process car charging data, export complete months, and clean up source files."
    )
    parser.add_argument(
        "--io-dir",
        type=Path,
        default=default_io_dir,
        help="Shared input/output directory that contains the incoming files.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db_path,
        help="SQLite database path for normalized transactions.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pipeline = BillingPipeline(build_config(), args.io_dir, args.db_path)
    result = pipeline.run()

    print(f"Scanned files: {result.scanned_files}")
    print(f"Imported transactions: {result.imported_transactions}")
    print(f"Skipped duplicates: {result.skipped_duplicates}")
    print(f"Exported PDFs: {len(result.exported_files)}")
    print(f"Deleted source files: {len(result.deleted_source_files)}")

    if result.exported_files:
        for export in result.exported_files:
            print(
                f"- {export.vehicle_id} {export.month}: {export.transaction_count} "
                f"transactions -> {export.pdf_path}"
            )

    if result.issues:
        max_issue_lines = 25
        print(f"Issues: {len(result.issues)} total")
        for issue in result.issues[:max_issue_lines]:
            location = (
                f"{issue.source_file}:{issue.row_number}"
                if issue.row_number is not None
                else issue.source_file
            )
            print(f"- [{issue.level}] {location} - {issue.message}")
        remaining = len(result.issues) - max_issue_lines
        if remaining > 0:
            print(f"- ... {remaining} more issue(s) not shown")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
