"""Admin CLI: convert a CMS "tall" MRF CSV (one payer/plan per row, named
charge columns) into the simplified tall CSV scripts/ingest_mrf.py consumes.

The two CMS layouts are "tall" (one row per charge, this module) and "wide"
(hundreds of standard_charge|<payer>|<plan>|negotiated_dollar columns, see
convert_wide_cms_csv.py). This project's own ingest_mrf.py.iter_csv_rows
reads a third, simplified shape (BillBuster's own intermediate format, used
for the checked-in public_prices.csv) -- it is not a real CMS layout, so a
raw hospital "tall" file still needs this converter first.

Filters to an allowlist up front so a large hospital file never fully
expands in memory or on disk.

Usage:
    uv run python scripts/convert_tall_cms_csv.py --file /tmp/carilion.csv \
        --allowlist /tmp/allowlist.json --output /tmp/carilion_tall.csv \
        --source-url https://example.org/standardcharges.csv --file-date 2026-04-01
"""

import argparse
import csv
import json
from pathlib import Path

TALL_FIELDS = [
    "description",
    "code",
    "code_type",
    "setting",
    "charge_scope",
    "charge_type",
    "payer_name",
    "plan_name",
    "amount",
    "allowed_count",
    "source_url",
    "file_date",
    "source_record_locator",
]


def load_allowlist(path: Path) -> set[tuple[str, str]]:
    entries = json.loads(path.read_text())
    return {(e["code_type"], e["code"]) for e in entries}


def _locator(physical_row: int, matched_n: str, code_type: str, code: str, other_codes: str, column: str) -> str:
    suffix = f"; {other_codes}" if other_codes else ""
    return f"CSV physical row {physical_row}; code|{matched_n}={code_type}:{code}{suffix}; column={column}"


def convert(file_path: Path, allowlist: set[tuple[str, str]], source_url: str, file_date: str) -> list[dict]:
    out: list[dict] = []
    # gross/discounted_cash/min/max don't vary by payer, but a real CMS tall
    # file repeats them on every payer row for the same code -- without this,
    # a code with 70 payer rows produces 70 duplicate "gross" rows all
    # carrying the identical amount. Emit each once per (code, charge_type).
    seen_non_payer: set[tuple[str, str]] = set()

    with file_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        next(reader)  # hospital metadata header
        next(reader)  # hospital metadata values
        header = next(reader)  # item-level header
        physical_row = 3  # 1-indexed; three header rows consumed above

        for row in csv.DictReader(fh, fieldnames=header):
            physical_row += 1
            matched = None
            matched_n = None
            for n in ("1", "2", "3"):
                code, code_type = (row.get(f"code|{n}") or "").strip(), (row.get(f"code|{n}|type") or "").strip()
                if (code_type, code) in allowlist:
                    matched, matched_n = (code, code_type), n
                    break
            if not matched:
                continue
            code, code_type = matched
            other_codes = ";".join(
                f"code|{n}={row.get(f'code|{n}|type')}:{row.get(f'code|{n}')}"
                for n in ("1", "2", "3")
                if n != matched_n and row.get(f"code|{n}")
            )
            base = {
                "description": row.get("description"),
                "code": code,
                "code_type": code_type,
                "setting": row.get("setting") or "unknown",
                "charge_scope": "unknown",
                "source_url": source_url,
                "file_date": file_date,
            }

            dedup_key_base = (code, code_type)
            for column, charge_type in (
                ("standard_charge|gross", "gross"),
                ("standard_charge|discounted_cash", "discounted_cash"),
                ("standard_charge|min", "deidentified_min"),
                ("standard_charge|max", "deidentified_max"),
            ):
                value = row.get(column)
                dedup_key = (*dedup_key_base, charge_type)
                if value and dedup_key not in seen_non_payer:
                    seen_non_payer.add(dedup_key)
                    loc = _locator(physical_row, matched_n, code_type, code, other_codes, column)
                    out.append({**base, "charge_type": charge_type, "amount": value, "source_record_locator": loc})
            negotiated = row.get("standard_charge|negotiated_dollar")
            if negotiated:
                out.append(
                    {
                        **base,
                        "charge_type": "payer_negotiated",
                        "amount": negotiated,
                        "payer_name": row.get("payer_name"),
                        "plan_name": row.get("plan_name"),
                        "source_record_locator": _locator(
                            physical_row, matched_n, code_type, code, other_codes, "standard_charge|negotiated_dollar"
                        ),
                    }
                )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--allowlist", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--file-date", required=True)
    args = parser.parse_args()

    rows = convert(args.file, load_allowlist(args.allowlist), args.source_url, args.file_date)
    with args.output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TALL_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in TALL_FIELDS})
    print(f"Wrote {len(rows)} tall rows to {args.output}")


if __name__ == "__main__":
    main()
