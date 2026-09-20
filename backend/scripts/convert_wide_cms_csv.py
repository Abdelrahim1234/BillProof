"""Admin CLI: convert a CMS "wide" MRF CSV (one column per payer|plan) into the
tall CSV shape scripts/ingest_mrf.py already consumes.

CMS price-transparency files come in two standard layouts: "tall" (one row per
charge) and "wide" (one row per service, hundreds of standard_charge|<payer>|
<plan>|negotiated_dollar columns). ingest_mrf.py only understands tall CSVs and
the V3 JSON shape; this fills the wide-CSV gap without touching that script.

Filters to an allowlist up front so a 300+MB hospital file never fully expands
in memory or on disk -- same intent as ingest_mrf.py's own allowlist filter,
just applied one stage earlier.

Usage:
    uv run python scripts/convert_wide_cms_csv.py --file /tmp/wide.csv \
        --allowlist /tmp/inova_allowlist.json --output /tmp/inova_tall.csv \
        --source-url https://example.org/standardcharges.csv --file-date 2026-04-01
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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


def convert(file_path: Path, allowlist: set[tuple[str, str]], source_url: str, file_date: str) -> list[dict]:
    out: list[dict] = []
    with file_path.open(newline="", encoding="cp1252") as fh:
        reader = csv.reader(fh)
        next(reader)  # hospital metadata header
        next(reader)  # hospital metadata values
        header = next(reader)  # item-level header
        payer_cols = [h for h in header if h.endswith("|negotiated_dollar") and h.count("|") == 3]

        for row in csv.DictReader(fh, fieldnames=header):
            matched = None
            for n in ("1", "2", "3"):
                code, code_type = (row.get(f"code|{n}") or "").strip(), (row.get(f"code|{n}|type") or "").strip()
                if (code_type, code) in allowlist:
                    matched = (code, code_type)
                    break
            if not matched:
                continue
            code, code_type = matched
            base = {
                "description": row.get("description"),
                "code": code,
                "code_type": code_type,
                "setting": row.get("setting") or "unknown",
                "charge_scope": "unknown",
                "source_url": source_url,
                "file_date": file_date,
            }
            gross = row.get("standard_charge|gross")
            if gross:
                out.append({**base, "charge_type": "gross", "amount": gross, "source_record_locator": "standard_charge|gross"})
            cash = row.get("standard_charge|discounted_cash")
            if cash:
                out.append(
                    {
                        **base,
                        "charge_type": "discounted_cash",
                        "amount": cash,
                        "source_record_locator": "standard_charge|discounted_cash",
                    }
                )
            dmin = row.get("standard_charge|min")
            if dmin:
                out.append(
                    {**base, "charge_type": "deidentified_min", "amount": dmin, "source_record_locator": "standard_charge|min"}
                )
            dmax = row.get("standard_charge|max")
            if dmax:
                out.append(
                    {**base, "charge_type": "deidentified_max", "amount": dmax, "source_record_locator": "standard_charge|max"}
                )
            for col in payer_cols:
                value = row.get(col)
                if not value:
                    continue
                _, payer, plan, _ = col.split("|")
                out.append(
                    {
                        **base,
                        "charge_type": "payer_negotiated",
                        "amount": value,
                        "payer_name": payer.title(),
                        "plan_name": plan.title(),
                        "source_record_locator": col,
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
