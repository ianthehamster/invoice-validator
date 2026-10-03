import json
import math
import sys
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "invoices.json"
REPORT_PATH = BASE_DIR / "report.json"

ID_FIELDS = ("invoice_number", "supplier_id")
AMOUNT_FIELDS = ("subtotal", "tax", "total")

STATUS_ACCEPTED = "accepted"
STATUS_INVALID = "invalid"
STATUS_DUPLICATE = "duplicate"
STATUSES = (STATUS_ACCEPTED, STATUS_INVALID, STATUS_DUPLICATE)


def load_invoices(path):
    """Read invoices from a JSON file. Decimal numbers are parsed as Decimal."""
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file, parse_float=Decimal)

    if not isinstance(data, list):
        raise ValueError("Expected a JSON list of invoices")

    return data


def make_error(code, message, field=None):
    return {"code": code, "field": field, "message": message}


def to_decimal(value):
    """Return value as a finite Decimal, or None if it is not a usable amount."""
    # bool is a subclass of int, so it must be rejected first.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # str() avoids binary artefacts: Decimal(0.1) != Decimal("0.1").
        return Decimal(str(value)) if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    return None


def validate_invoice(invoice):
    """Return a list of error dicts. An empty list means the invoice is valid."""
    if not isinstance(invoice, dict):
        return [make_error(
            "not_an_object",
            f"Invoice must be a JSON object, got {type(invoice).__name__}",
        )]

    errors = []

    for field in ID_FIELDS:
        if field not in invoice:
            errors.append(make_error("missing_field", f"Missing field: {field}", field))
        elif not isinstance(invoice[field], str):
            errors.append(make_error("invalid_type", f"Field '{field}' must be a string", field))
        elif not invoice[field].strip():
            errors.append(make_error("empty_field", f"Field '{field}' must not be empty", field))

    amounts = {}
    for field in AMOUNT_FIELDS:
        if field not in invoice:
            errors.append(make_error("missing_field", f"Missing field: {field}", field))
            continue

        amount = to_decimal(invoice[field])
        if amount is None:
            errors.append(make_error(
                "invalid_amount", f"Field '{field}' must be a finite number", field
            ))
        else:
            amounts[field] = amount

    # Only check the total once every amount is known to be a valid number.
    if len(amounts) == len(AMOUNT_FIELDS):
        expected_total = amounts["subtotal"] + amounts["tax"]
        if expected_total != amounts["total"]:
            errors.append(make_error(
                "total_mismatch",
                f"Expected total {expected_total}, got {amounts['total']}",
                "total",
            ))

    return errors


def _string_field(invoice, field):
    """Return the field if it is a string, so results only contain JSON-safe types."""
    if isinstance(invoice, dict) and isinstance(invoice.get(field), str):
        return invoice[field]
    return None


def process_invoices(invoices):
    """Validate each invoice and flag duplicates. Returns one result dict per invoice.

    Only valid invoices are recorded as seen, so an invalid first occurrence
    does not block a later valid copy.
    """
    results = []
    seen = {}  # (supplier_id, invoice_number) -> index of the accepted invoice

    for index, invoice in enumerate(invoices):
        errors = validate_invoice(invoice)

        if errors:
            status = STATUS_INVALID
        else:
            key = (invoice["supplier_id"], invoice["invoice_number"])
            if key in seen:
                status = STATUS_DUPLICATE
                errors = [make_error(
                    "duplicate",
                    f"Duplicate of accepted invoice at index {seen[key]}",
                )]
            else:
                seen[key] = index
                status = STATUS_ACCEPTED

        results.append({
            "index": index,
            "invoice_number": _string_field(invoice, "invoice_number"),
            "supplier_id": _string_field(invoice, "supplier_id"),
            "status": status,
            "errors": errors,
        })

    return results


def build_report(results):
    summary = {"total": len(results)}
    for status in STATUSES:
        summary[status] = sum(1 for result in results if result["status"] == status)

    return {"summary": summary, "results": results}


def save_report(report, path):
    # No default= converter: the report must contain only JSON types, and a
    # stray Decimal or other object should fail loudly rather than be stringified.
    with open(path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
        file.write("\n")


def main():
    try:
        invoices = load_invoices(INPUT_PATH)
    except FileNotFoundError:
        print(f"Could not find {INPUT_PATH.name}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as error:
        print(f"{INPUT_PATH.name} contains invalid JSON: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"Could not read {INPUT_PATH.name}: {error}", file=sys.stderr)
        return 1

    report = build_report(process_invoices(invoices))

    try:
        save_report(report, REPORT_PATH)
    except OSError as error:
        print(f"Could not write {REPORT_PATH.name}: {error}", file=sys.stderr)
        return 1

    summary = report["summary"]
    print(
        f"{summary['total']} invoices: "
        f"{summary[STATUS_ACCEPTED]} accepted, "
        f"{summary[STATUS_INVALID]} invalid, "
        f"{summary[STATUS_DUPLICATE]} duplicate "
        f"-> {REPORT_PATH.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
