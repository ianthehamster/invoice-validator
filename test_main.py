import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path
from unittest import mock

import main


def make_invoice(**overrides):
    invoice = {
        "invoice_number": "INV-001",
        "supplier_id": "SUP-001",
        "subtotal": 1000,
        "tax": 200,
        "total": 1200,
    }
    invoice.update(overrides)
    return invoice


def error_codes(errors):
    return [(error["code"], error["field"]) for error in errors]


class ValidateInvoiceTests(unittest.TestCase):
    def test_valid_invoice_has_no_errors(self):
        self.assertEqual(main.validate_invoice(make_invoice()), [])

    def test_non_dict_records_are_rejected(self):
        for record in ([], "INV-001", 42, None):
            with self.subTest(record=record):
                self.assertEqual(
                    error_codes(main.validate_invoice(record)),
                    [("not_an_object", None)],
                )

    def test_missing_field(self):
        invoice = make_invoice()
        del invoice["tax"]
        self.assertEqual(
            error_codes(main.validate_invoice(invoice)),
            [("missing_field", "tax")],
        )

    def test_ids_must_be_nonempty_strings(self):
        cases = [
            ("", "empty_field"),
            ("   ", "empty_field"),
            (1, "invalid_type"),
            (None, "invalid_type"),
        ]
        for value, code in cases:
            with self.subTest(value=value):
                invoice = make_invoice(supplier_id=value)
                self.assertEqual(
                    error_codes(main.validate_invoice(invoice)),
                    [(code, "supplier_id")],
                )

    def test_bad_amounts_are_rejected_without_checking_total(self):
        bad_values = [
            True,
            "1000",
            None,
            float("nan"),
            float("inf"),
            Decimal("NaN"),
            Decimal("Infinity"),
        ]
        for value in bad_values:
            with self.subTest(value=value):
                invoice = make_invoice(subtotal=value)
                # Only the amount error: no total_mismatch and no crash.
                self.assertEqual(
                    error_codes(main.validate_invoice(invoice)),
                    [("invalid_amount", "subtotal")],
                )

    def test_total_mismatch(self):
        errors = main.validate_invoice(make_invoice(total=1300))
        self.assertEqual(error_codes(errors), [("total_mismatch", "total")])
        self.assertEqual(errors[0]["message"], "Expected total 1200, got 1300")

    def test_decimal_amounts_compare_exactly(self):
        # 0.1 + 0.2 != 0.3 with floats, but must be valid for money.
        self.assertEqual(
            main.validate_invoice(make_invoice(subtotal=0.1, tax=0.2, total=0.3)), []
        )
        self.assertEqual(
            main.validate_invoice(make_invoice(
                subtotal=Decimal("0.10"), tax=Decimal("0.20"), total=Decimal("0.3")
            )),
            [],
        )

    def test_all_errors_are_collected(self):
        invoice = {"invoice_number": "", "subtotal": "x", "tax": 1}
        self.assertEqual(
            error_codes(main.validate_invoice(invoice)),
            [
                ("empty_field", "invoice_number"),
                ("missing_field", "supplier_id"),
                ("invalid_amount", "subtotal"),
                ("missing_field", "total"),
            ],
        )


class DuplicateRuleTests(unittest.TestCase):
    def statuses(self, invoices):
        return [result["status"] for result in main.process_invoices(invoices)]

    def test_second_valid_copy_is_duplicate(self):
        results = main.process_invoices([make_invoice(), make_invoice()])
        self.assertEqual([r["status"] for r in results], ["accepted", "duplicate"])
        self.assertEqual(error_codes(results[1]["errors"]), [("duplicate", None)])

    def test_invalid_first_occurrence_does_not_block_valid_copy(self):
        invalid_first = make_invoice(total=9999)
        self.assertEqual(
            self.statuses([invalid_first, make_invoice()]),
            ["invalid", "accepted"],
        )

    def test_invalid_copy_after_accepted_is_invalid_not_duplicate(self):
        self.assertEqual(
            self.statuses([make_invoice(), make_invoice(tax=0), make_invoice()]),
            ["accepted", "invalid", "duplicate"],
        )

    def test_same_number_different_supplier_is_not_duplicate(self):
        self.assertEqual(
            self.statuses([make_invoice(), make_invoice(supplier_id="SUP-002")]),
            ["accepted", "accepted"],
        )

    def test_non_dict_record_gets_null_ids(self):
        result = main.process_invoices(["oops"])[0]
        self.assertEqual(result["status"], "invalid")
        self.assertIsNone(result["invoice_number"])
        self.assertIsNone(result["supplier_id"])


class ReportTests(unittest.TestCase):
    def test_summary_counts_and_plain_json_types(self):
        invoices = [make_invoice(), make_invoice(total=1), make_invoice()]
        report = main.build_report(main.process_invoices(invoices))
        self.assertEqual(
            report["summary"],
            {"total": 3, "accepted": 1, "invalid": 1, "duplicate": 1},
        )
        # Must serialise without any default= converter.
        json.dumps(report)


class LoadAndMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_load_parses_decimals(self):
        path = self.write("in.json", '[{"subtotal": 0.1}]')
        self.assertEqual(main.load_invoices(path), [{"subtotal": Decimal("0.1")}])

    def test_load_rejects_non_list(self):
        path = self.write("in.json", '{"invoice_number": "INV-001"}')
        with self.assertRaises(ValueError):
            main.load_invoices(path)

    def run_main(self, input_path, report_path):
        stderr = io.StringIO()
        with mock.patch.object(main, "INPUT_PATH", input_path), \
                mock.patch.object(main, "REPORT_PATH", report_path), \
                redirect_stderr(stderr), redirect_stdout(io.StringIO()):
            code = main.main()
        return code, stderr.getvalue()

    def test_main_missing_input_returns_1(self):
        code, stderr = self.run_main(self.dir / "missing.json", self.dir / "out.json")
        self.assertEqual(code, 1)
        self.assertIn("Could not find", stderr)

    def test_main_invalid_json_returns_1(self):
        path = self.write("in.json", "[{")
        code, stderr = self.run_main(path, self.dir / "out.json")
        self.assertEqual(code, 1)
        self.assertIn("invalid JSON", stderr)

    def test_main_report_write_failure_returns_1(self):
        path = self.write("in.json", "[]")
        # A directory cannot be opened as a file for writing.
        code, stderr = self.run_main(path, self.dir)
        self.assertEqual(code, 1)
        self.assertIn("Could not write", stderr)

    def test_main_writes_report(self):
        path = self.write("in.json", json.dumps([make_invoice()]))
        out = self.dir / "out.json"
        code, _ = self.run_main(path, out)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out))
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
