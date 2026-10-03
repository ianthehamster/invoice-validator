# Invoice Validator

A small Python application that validates supplier invoices from a JSON file,
detects duplicates, and writes a structured JSON report.

Standard library only: no frameworks, no database, no external dependencies.

## What it does

1. **Loads** invoices from `invoices.json`.
2. **Validates** each invoice:
   - the record must be a JSON object;
   - `invoice_number` and `supplier_id` must be non-empty strings;
   - `subtotal`, `tax` and `total` must be finite numbers (booleans, strings,
     `null`, NaN and infinity are rejected);
   - `subtotal + tax` must equal `total`, calculated with `Decimal` so money
     arithmetic is exact.
3. **Detects duplicates** by `(supplier_id, invoice_number)`. Only valid
   invoices are recorded as seen, so an invalid first occurrence does not
   block a later valid copy.
4. **Writes** `report.json` with summary counts and one result per invoice.

## Running it

Requires Python 3.9+.

```bash
python main.py
```

On Windows, use `py` if `python` is not on your PATH.

Output:

```
3 invoices: 1 accepted, 1 invalid, 1 duplicate -> report.json
```

The exit code is `0` when the report is written, and `1` if the input cannot
be read or the report cannot be written. Invalid invoices are reported in the
results; they do not change the exit code.

## Running the tests

```bash
python -m unittest -v test_main
```

The tests cover field validation, amount handling, exact decimal totals,
duplicate rules (including an invalid first occurrence followed by a valid
copy), report shape, and file error handling in `main()`.

## Example report

From the included `invoices.json`:

```json
{
  "summary": { "total": 3, "accepted": 1, "invalid": 1, "duplicate": 1 },
  "results": [
    {
      "index": 0, "invoice_number": "INV-001", "supplier_id": "SUP-001",
      "status": "accepted", "errors": []
    },
    {
      "index": 1, "invoice_number": "INV-002", "supplier_id": "SUP-002",
      "status": "invalid",
      "errors": [
        { "code": "total_mismatch", "field": "total",
          "message": "Expected total 600, got 700" }
      ]
    },
    {
      "index": 2, "invoice_number": "INV-001", "supplier_id": "SUP-001",
      "status": "duplicate",
      "errors": [
        { "code": "duplicate", "field": null,
          "message": "Duplicate of accepted invoice at index 0" }
      ]
    }
  ]
}
```

## Design

Each function has a single job, and only `main()` does printing or exit codes:

| Function | Responsibility |
|---|---|
| `load_invoices(path)` | Read and parse the JSON file (floats parsed as `Decimal`) |
| `validate_invoice(invoice)` | Return a list of structured errors; empty means valid |
| `process_invoices(invoices)` | Validate each invoice and apply the duplicate rule |
| `build_report(results)` | Add summary counts |
| `save_report(report, path)` | Write the report as JSON |
| `main()` | Wire the steps together and handle file errors |

Key decisions:

- **Errors are data, not exceptions or prints.** Each error is
  `{"code", "field", "message"}`, so callers and tests can inspect them, and
  one bad invoice never stops the batch.
- **All errors are collected**, not just the first.
- **Amounts are type-checked before arithmetic**, so bad input becomes an
  `invalid_amount` error instead of a crash.
- **The report contains only plain JSON types.** No `default=` converter is
  used, so an unexpected type fails loudly instead of being silently
  stringified.

## Possible next steps

- Normalise IDs (trim whitespace, case) before duplicate comparison.
- Reject negative amounts or amounts with more than two decimal places.
- Accept input and report paths as command-line arguments.
