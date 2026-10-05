"""Tests for reading the season spreadsheet in both generator scripts.

``fixtures/season_export.csv`` is a small made-up copy of the Google Sheets
export format: a "Fall 2026" title row above the header, cp1252 encoding
(smart quote), past customers with no bags, a zero-bag row, routes that are
not adjacent, a mail-in order with a special-action comment, the benefactor
order with "TBD" instructions, an order with no map link, a blank row and
the Totals/Pallets summary rows at the bottom.  The ``.xlsx`` tests build
a workbook from the same rows (see ``build_season_workbook``).

Run from the project root:

    python3 -m unittest discover tests
"""

import contextlib
import csv
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

import addresses  # noqa: E402
import check_workbook  # noqa: E402
import generate_maps_pdf as maps  # noqa: E402
import generate_order_forms as forms  # noqa: E402

SEASON_CSV = os.path.join(HERE, "fixtures", "season_export.csv")

import sheet_reader  # noqa: E402

# Column indexes in the season sheet.
BAGS, SUPPORT, COMMENT, ZIP = 16, 18, 21, 9


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
        self.records = maps.read_records(SEASON_CSV)

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

    def test_street_addresses(self):
        self.assertEqual(
            [r[4] for r in self.records],
            ["100 Maple Drive", "200 Oak Court", "500 Maple Drive", "600 Ox Road"],
        )

    def test_max_records(self):
        self.assertEqual(len(maps.read_records(SEASON_CSV, max_records=2)), 2)

    def test_positional_format_without_header(self):
        path = write_temp_csv("https://maps.example/1,Fairfax 15A,20\nhttps://maps.example/2,Burke 01\n")
        self.addCleanup(os.remove, path)
        self.assertEqual(
            maps.read_records(path),
            [
                ("https://maps.example/1", "Fairfax 15A", "20", None, None),
                ("https://maps.example/2", "Burke 01", None, None, None),
            ],
        )


class GroupByLabelTests(unittest.TestCase):
    def test_non_adjacent_rows_for_a_route_are_grouped_together(self):
        groups = maps.group_by_label(maps.read_records(SEASON_CSV))
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


def build_season_workbook(path: str) -> None:
    """Write the fixture rows as an .xlsx like the real season workbook.

    Numbers are stored as numbers (money with a "$" format), the first sheet
    is ``Customers`` with another sheet after it, and the comments carry
    colours: Bob's "Need one pallet" is red, Erin's comment is "Order 14813"
    followed by a red "call before delivery", and the church has a comment
    in the default colour.
    """
    import openpyxl
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont
    from openpyxl.styles import Font

    with open(SEASON_CSV, newline="", encoding="cp1252") as f:
        rows = list(csv.reader(f))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Customers"
    for r, values in enumerate(rows, start=1):
        for c, value in enumerate(values, start=1):
            if value == "":
                continue
            cell = ws.cell(r, c)
            text = value.strip()
            if r > 2 and c - 1 in (BAGS, ZIP) and text.isdigit():
                cell.value = int(text)
            elif r > 2 and c - 1 == SUPPORT and text.startswith("$"):
                cell.value = float(text.strip("$").replace(",", ""))
                cell.number_format = '_("$"* #,##0.00_)'
            else:
                cell.value = value
    for r in range(3, ws.max_row + 1):
        last = ws.cell(r, 4).value
        comment = ws.cell(r, COMMENT + 1)
        if last == "Mailer":
            comment.font = Font(color="FFFF0000")
        elif last == "Testerson" and ws.cell(r, 5).value == "Erin":
            comment.value = CellRichText(
                "Order 14813 ", TextBlock(InlineFont(color="FFFF0000"), "call before delivery")
            )
        elif last == "Church":
            comment.value = "Benefactor"
    wb.create_sheet("Totals")["A1"] = "not the customer list"
    stats = wb.create_sheet("BasicOrderStats")
    stats.append(["Basic Order Stats"])
    stats.append(["Total Bags", 81])
    stats.append(["Orders", 5])
    stats.append(["Average Order", 16.2])
    wb.save(path)


class XlsxInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.xlsx = os.path.join(cls.tmp.name, "Mulch Sales - Fall 2026.xlsx")
        build_season_workbook(cls.xlsx)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_order_forms_match_csv(self):
        from_csv, _ = quiet(forms.parse_order_records, SEASON_CSV)
        from_xlsx, output = quiet(forms.parse_order_records, self.xlsx)
        # Same orders and fields; numbers render as in the CSV export.
        for rec in from_csv:
            rec.pop("order_no")  # Erin's comment differs in the workbook
        for rec in from_xlsx:
            rec.pop("order_no")
        self.assertEqual(from_xlsx, from_csv)
        self.assertEqual(from_xlsx[0]["amount_support"], "$53.00")
        self.assertEqual(from_xlsx[0]["bags"], "20")
        self.assertEqual(output.count("WARNING"), 2)

    def test_map_notes_are_only_the_red_text(self):
        records = maps.read_records(self.xlsx)
        self.assertEqual([r[2] for r in records], ["20", "5", "10", "40"])
        self.assertEqual(
            [r[3] for r in records],
            [None, "Need one pallet", "call before delivery", None],
        )

    def test_named_sheet(self):
        self.assertEqual(len(maps.read_records(self.xlsx, sheet="Customers")), 4)
        with self.assertRaises(KeyError):
            maps.read_records(self.xlsx, sheet="No Such Sheet")


class FormatValueTests(unittest.TestCase):
    def test_numbers(self):
        money = '_("$"* #,##0.00_);_("$"* \\(#,##0.00\\);_("$"* "-"??_);_(@_)'
        self.assertEqual(sheet_reader._format_value(13.25, money), "$13.25")
        self.assertEqual(sheet_reader._format_value(10260, money), "$10,260.00")
        self.assertEqual(sheet_reader._format_value(20, "General"), "20")
        self.assertEqual(sheet_reader._format_value(20.0, "General"), "20")
        self.assertEqual(sheet_reader._format_value(38.4, "General"), "38.4")
        self.assertEqual(sheet_reader._format_value(None, "General"), "")


class OrderFormPagesTests(unittest.TestCase):
    """Every page of a route's PDF is the form for that page's order.

    Merging single-page PDFs with PyPDF2 used to repeat some orders and
    drop others once a route had several orders.
    """

    def test_many_orders_in_one_route(self):
        from PIL import ImageChops
        from PyPDF2 import PdfReader

        # 30 orders: enough that the old merging reliably got pages wrong.
        records = [
            {"order_no": str(14800 + i), "amount_support": f"${2.65 * (i + 4):.2f}",
             "customer": f"Customer{i}, Test", "city": "Fairfax", "address": f"{100 + i} Elm Street",
             "email": f"c{i}@example.com", "bags": str(i + 4), "route": "Fairfax 01A",
             "id": i + 1, "instructions": f"Instructions for order {i}"}
            for i in range(30)
        ]
        fonts = forms.load_fonts()
        with tempfile.TemporaryDirectory() as out_dir:
            quiet(forms.save_order_forms, records, out_dir)
            pages = PdfReader(os.path.join(out_dir, "Fairfax_01A.pdf")).pages
            self.assertEqual(len(pages), 30)
            images = [check_workbook._page_image(p) for p in pages]
        for i, (rec, image) in enumerate(zip(records, images)):
            expected = forms.draw_order_form(rec, fonts).convert("L")
            diff = ImageChops.difference(expected, image.resize(expected.size))
            changed = sum(diff.point(lambda v: 255 if v > 100 else 0).histogram()[255:])
            with self.subTest(page=i + 1):
                self.assertLessEqual(changed, 50)


class SameStreetAddressTests(unittest.TestCase):
    def test_abbreviations_and_town(self):
        self.assertTrue(addresses.same_street_address("100 Maple Ct, Fairfax, VA 22030", "100 Maple Court"))
        self.assertTrue(addresses.same_street_address("200 Oak Hill Dr", "200 Oak Hill Drive"))
        self.assertTrue(addresses.same_street_address("300 O’Hara Rd", "300 O'Hara Road"))
        self.assertTrue(addresses.same_street_address("400 Elm Blvd", "400 Elm Boulevard"))

    def test_different_addresses(self):
        self.assertFalse(addresses.same_street_address("900 Birch Terrace, Fairfax", "300 O'Hara Rd"))
        self.assertFalse(addresses.same_street_address("100 Maple Ct", "105 Maple Court"))
        self.assertFalse(addresses.same_street_address("", ""))


class CheckWorkbookTests(unittest.TestCase):
    """The checks run before and after generating (see check_workbook.py)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.xlsx = os.path.join(cls.tmp.name, "season.xlsx")
        build_season_workbook(cls.xlsx)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check_before(self, path):
        problems, _ = quiet(check_workbook.check_before, path)
        return problems

    def edited_workbook(self, edit):
        import openpyxl

        path = os.path.join(self.tmp.name, "edited.xlsx")
        wb = openpyxl.load_workbook(self.xlsx)
        edit(wb)
        wb.save(path)
        return path

    def test_totals_and_stats_match(self):
        # The only problem in the fixture is the order with no Map Link.
        self.assertEqual(self.check_before(self.xlsx), ["700 Birch Way (Fairfax 01A): no Map Link."])
        self.assertEqual(self.check_before(SEASON_CSV), ["700 Birch Way (Fairfax 01A): no Map Link."])

    def test_totals_row_mismatch(self):
        def edit(wb):
            for row in wb["Customers"].iter_rows():
                if row[14].value == "Totals":
                    row[16].value = 80
        problems = self.check_before(self.edited_workbook(edit))
        self.assertIn("Totals row says 80 bags, but the orders add up to 81.", problems)

    def test_stats_mismatch(self):
        def edit(wb):
            wb["BasicOrderStats"]["B2"] = 90
            wb["BasicOrderStats"]["B3"] = 6
        problems = self.check_before(self.edited_workbook(edit))
        self.assertIn("BasicOrderStats 'Total Bags' is 90, but the orders add up to 81.", problems)
        self.assertIn("BasicOrderStats 'Orders' is 6, but there are 5 orders.", problems)

    def test_map_link_for_another_address(self):
        def edit(wb):
            ws = wb["Customers"]
            for r in range(3, ws.max_row + 1):
                if ws.cell(r, 4).value == "Mailer":
                    ws.cell(r, 11).value = "https://www.google.com/maps/place/900+Birch+Terrace,+Fairfax,+VA+22030/@38.8,-77.3,17z"
        problems = self.check_before(self.edited_workbook(edit))
        self.assertIn(
            "200 Oak Court (Fairfax 01A): Map Link is for '900 Birch Terrace, Fairfax, VA 22030'.",
            problems,
        )

    def test_after_generating(self):
        records, _ = quiet(forms.parse_order_records, self.xlsx)
        with tempfile.TemporaryDirectory() as out_dir:
            quiet(forms.save_order_forms, records, out_dir)
            problems, _ = quiet(check_workbook.check_after, self.xlsx, None, None, out_dir)
            self.assertEqual(problems, [])
            os.remove(os.path.join(out_dir, "Fairfax_07.pdf"))
            problems, _ = quiet(check_workbook.check_after, self.xlsx, None, None, out_dir)
        self.assertIn("order forms: 3 pages, but there are 5 orders.", problems)
        self.assertIn("order forms: Fairfax_07.pdf has 0 page(s), expected 2.", problems)

    def test_after_generating_catches_pages_for_the_wrong_order(self):
        records, _ = quiet(forms.parse_order_records, self.xlsx)
        fonts = forms.load_fonts()
        with tempfile.TemporaryDirectory() as out_dir:
            quiet(forms.save_order_forms, records, out_dir)
            # Rewrite Fairfax 07 with Alice's form twice instead of Alice, Erin.
            alice = forms.draw_order_form(records[0], fonts)
            alice.save(os.path.join(out_dir, "Fairfax_07.pdf"), save_all=True, append_images=[alice])
            problems, _ = quiet(check_workbook.check_after, self.xlsx, None, None, out_dir)
        self.assertEqual(
            problems,
            ["order forms: Fairfax_07.pdf page 2 should be Testerson, Erin, 500 Maple Drive (10 bags) but isn't."],
        )


if __name__ == "__main__":
    unittest.main()
