import unittest

from graph_builder.corpus.column_alignment import independently_readable, proves_mapping
from graph_builder.corpus.scan_table_ink import replaces_suffix


class SourceAlignmentTests(unittest.TestCase):
    def test_only_a_complete_unambiguous_column_permutation_can_be_realigned(self):
        native = [["Hole", "", "Shoe"], ["17 in", "100 m", "First"], ["10 in", "220 m", "Second"]]
        printed = [["", "Hole", "Shoe"], ["First", "17 in", "100 m"], ["Second", "10 in", "220 m"]]
        self.assertTrue(proves_mapping(native, printed))
        swapped = [*printed[:2], ["Second", "220 m", "10 in"]]
        self.assertFalse(proves_mapping(native, swapped))
        wrong_unit = [*printed[:2], ["Second", "10 in", "220 ft"]]
        self.assertFalse(proves_mapping(native, wrong_unit))

    def test_second_pdf_reader_must_verify_blank_columns_and_units(self):
        table = {"grid": [["", "30 m"]], "cell_boxes": [[[0, 0, 20, 12], [20, 0, 40, 12]]]}
        words = [("30", [22, 1, 30, 8]), ("m", [31, 1, 37, 8])]
        self.assertTrue(independently_readable(table, words))
        self.assertFalse(independently_readable(table, [("A", [5, 1, 12, 8]), *words]))

    def test_headers_can_be_intact_repeated_or_partly_blank_when_the_body_proves_the_order(self):
        for header in (["Size", "Shoe", "Grade", "Weight"], ["Depth", "Depth", "Grade", "Weight"], ["", "", "Grade", "Weight"]):
            with self.subTest(header=header):
                before = [header, ["10", "20", "red", "48"], ["30", "40", "blue", "38"]]
                after = [header, ["20", "10", "red", "48"], ["40", "30", "blue", "38"]]
                self.assertTrue(proves_mapping(before, after))
        duplicate_columns = [["Depth", "Depth", "Grade"], ["10", "20", "20"], ["30", "40", "40"]]
        ambiguous = [duplicate_columns[0], ["20", "10", "20"], ["40", "30", "40"]]
        self.assertFalse(proves_mapping(duplicate_columns, ambiguous))

    def test_scan_printed_line_only_accepts_a_prefix_of_the_native_cell(self):
        self.assertTrue(replaces_suffix("Pressure measured strays", "Pressure measured"))
        self.assertFalse(replaces_suffix("Pressure measured strays", "Pressure verified"))
        self.assertFalse(replaces_suffix("18 22 35", "18 22"))
