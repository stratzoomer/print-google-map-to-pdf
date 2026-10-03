"""Tests for reading the season CSV export in both generator scripts.

``fixtures/season_export.csv`` is a small made-up copy of the Google Sheets
export format: a "Fall 2026" title row above the header, cp1252 encoding
(smart quote), past customers with no bags, a zero-bag row, routes that are
not adjacent, a mail-in order with a special-action comment, the benefactor
order with "TBD" instructions, an order with no map link, a blank row and
the Totals/Pallets summary rows at the bottom.

Run from the project root:

    python3 -m unittest discover tests
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

import generate_maps_pdf as maps  # noqa: E402
import generate_order_forms as forms  # noqa: E402

SEASON_CSV = os.path.join(HERE, "fixtures", "season_export.csv")


def quiet(fn, *args, **kwargs):
    """Call ``fn`` and return ``(result, captured stdout)``."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


def write_temp_csv(text: str) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    with f:
        f.write(text)
    return f.name


class OrderFormParsingTests(unittest.TestCase):
    def setUp(self):
        self.records, self.output = quiet(forms.parse_order_records, SEASON_CSV)

    def test_only_rows_with_bags_are_orders(self):
        # Skips the title row, past customers with no bags, the zero-bag
        # row, the blank row and the Totals/Pallets summary rows.
        self.assertEqual(
            [r["customer"] for r in self.records],
            [
                "Testerson, Alice",
                "Mailer, Bob",
                "Testerson, Erin",
                "Church, Benefactor",
                "Nolink, Frank",
            ],
        )

    def test_fields_come_from_header_below_title_row(self):
        alice = self.records[0]
        self.assertEqual(alice["order_no"], "14812")
        self.assertEqual(alice["amount_support"], "$53.00")
        self.assertEqual(alice["city"], "Fairfax")
        self.assertEqual(alice["address"], "100 Maple Drive")
        self.assertEqual(alice["email"], "alice@example.com")
        self.assertEqual(alice["bags"], "20")
        self.assertEqual(alice["route"], "Fairfax 07")

    def test_cp1252_smart_quote_is_decoded(self):
        self.assertEqual(self.records[0]["instructions"], "End of driveway, don’t block gate")

    def test_ids_are_sequential_among_orders(self):
        self.assertEqual([r["id"] for r in self.records], [1, 2, 3, 4, 5])

    def test_mail_in_order_has_no_order_number(self):
        self.assertEqual(self.records[1]["order_no"], "")

    def test_benefactor_has_no_support_amount(self):
        self.assertEqual(self.records[3]["amount_support"], "")

    def test_warns_about_tbd_instructions_and_missing_map_link(self):
        self.assertIn("Church, Benefactor (Fairfax 12A): Delivery Instructions are still 'TBD'", self.output)
        self.assertIn("Nolink, Frank (Fairfax 01A): no Map Link", self.output)
        self.assertEqual(self.output.count("WARNING"), 2)

    def test_header_on_first_row_still_works(self):
        # Older exports (e.g. Spring 2026) had no title row.
        path = write_temp_csv(
            "LastName,FirstName,Street Address,Town,Map Link,Delivery Route,"
            "EmailAddress,Number of Bags,Support Troop Amount,Comment,Delivery Instructions\n"
            "Smith,Jo,1 Main St,Fairfax,https://maps.example/1,Fairfax 15A,"
            "jo@example.com,20, $53.00 ,Order 123,By the garage\n"
        )
        self.addCleanup(os.remove, path)
        records, _ = quiet(forms.parse_order_records, path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["customer"], "Smith, Jo")
        self.assertEqual(records[0]["order_no"], "123")


class IsOrderRowTests(unittest.TestCase):
    def test_positive_bags_with_name(self):
        self.assertTrue(forms.is_order_row({"Number of Bags": " 5 ", "LastName": "Smith"}))

    def test_positive_bags_with_address_only(self):
        self.assertTrue(forms.is_order_row({"Number of Bags": "5", "Street Address": "1 Main St"}))

    def test_rejects_blank_zero_and_non_integer_bags(self):
        for bags in ("", "0", "38.4", "abc"):
            with self.subTest(bags=bags):
                self.assertFalse(forms.is_order_row({"Number of Bags": bags, "LastName": "Smith"}))

    def test_rejects_summary_row_without_name_or_address(self):
        self.assertFalse(forms.is_order_row({"Number of Bags": "1730", "EmailAddress": "Totals"}))


class OrderFormOutputTests(unittest.TestCase):
    def test_one_pdf_per_route_with_one_page_per_order(self):
        from PyPDF2 import PdfReader

        records, _ = quiet(forms.parse_order_records, SEASON_CSV)
        with tempfile.TemporaryDirectory() as out_dir:
            quiet(forms.save_order_forms, records, out_dir)
            pages = {
                name: len(PdfReader(os.path.join(out_dir, name)).pages)
                for name in os.listdir(out_dir)
            }
        self.assertEqual(
            pages,
            {"Fairfax_07.pdf": 2, "Fairfax_01A.pdf": 2, "Fairfax_12A.pdf": 1},
        )


class MapRecordTests(unittest.TestCase):
    def setUp(self):
        self.records = maps.read_records_from_csv(SEASON_CSV)

    def test_only_orders_with_map_links(self):
        # Same orders as the forms, minus the one with no Map Link.
        self.assertEqual([r[2] for r in self.records], ["20", "5", "10", "40"])
        self.assertTrue(all(r[0].startswith("https://www.google.com/maps/place/") for r in self.records))

    def test_route_labels(self):
        self.assertEqual(
            [r[1] for r in self.records],
            ["Fairfax 07", "Fairfax 01A", "Fairfax 07", "Fairfax 12A"],
        )

    def test_only_special_comments_become_notes(self):
        self.assertEqual([r[3] for r in self.records], [None, "Need one pallet", None, None])

    def test_max_records(self):
        self.assertEqual(len(maps.read_records_from_csv(SEASON_CSV, max_records=2)), 2)

    def test_positional_format_without_header(self):
        path = write_temp_csv("https://maps.example/1,Fairfax 15A,20\nhttps://maps.example/2,Burke 01\n")
        self.addCleanup(os.remove, path)
        self.assertEqual(
            maps.read_records_from_csv(path),
            [
                ("https://maps.example/1", "Fairfax 15A", "20", None),
                ("https://maps.example/2", "Burke 01", None, None),
            ],
        )


class GroupByLabelTests(unittest.TestCase):
    def test_non_adjacent_rows_for_a_route_are_grouped_together(self):
        groups = maps.group_by_label(maps.read_records_from_csv(SEASON_CSV))
        self.assertEqual(list(groups), ["Fairfax 07", "Fairfax 01A", "Fairfax 12A"])
        self.assertEqual([r[2] for r in groups["Fairfax 07"]], ["20", "10"])


class SpecialNoteTests(unittest.TestCase):
    def test_order_numbers_and_blanks_are_not_notes(self):
        for comment in ("", "   ", "Order 14812", " Order  14812 "):
            with self.subTest(comment=comment):
                self.assertIsNone(maps.special_note(comment))

    def test_other_comments_are_notes(self):
        self.assertEqual(maps.special_note(" Need one pallet "), "Need one pallet")
        self.assertEqual(maps.special_note("Order 14812 - call first"), "Order 14812 - call first")


if __name__ == "__main__":
    unittest.main()
