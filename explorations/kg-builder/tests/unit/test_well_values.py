"""Guideline quantity formats, explicit references, dates and tolerance boundaries."""
from __future__ import annotations

import unittest

from kgbuilder.core.well_values import compare, hash_is_pressure, in_name, parse_quantity, parse_us_date


class WellValuesTest(unittest.TestCase):
    def test_guideline_conformance(self):
        # Each quantity tuple is value, lower, upper, unit, reference, datum.
        rows = [
            ("3/14/2011", "date", ("2011-03-14", "day"), "day"),
            ("3-14-2011", "date", ("2011-03-14", "day"), "day"),
            ("3-14-11", "date", ("2011-03-14", "day"), "day"),
            ("3-14-49", "date", ("2049-03-14", "day"), "day"),
            ("3-14-50", "date", ("1950-03-14", "day"), "day"),
            ("9/29/08", "date", ("2008-09-29", "day"), "day"),
            ("June 19, 2011", "date", ("2011-06-19", "day"), "day"),
            ("12/10/2011", "date", ("2011-12-10", "day"), "day"),
            ("08/11/2010", "date", ("2010-08-11", "day"), "day"),
            ("June 2011", "date", ("2011-06", "month"), "month"),
            ("early 2012", "date", ("2012", "year"), "year"),
            ("2008", "date", ("2008", "year"), "year"),
        ]
        rows += [(text, "date", (None, "partial"), "partial") for text in
                 ("3/14", "3-14", "11/5", "3/14-11", "3-14/11", "2-30-20", "9-5/8", "13202'-24'",
                  "3-14-111", "3/14/111", "unrecognized synthetic date")]
        for text, value in [('9-5/8"', "9.625"), ('13 3/8"', "13.375"), ('2-9/16"', "2.5625"),
                            ('5.5"', "5.5"), ('30"', "30"), ('7"', "7"), ('1.56"', "1.56")]:
            rows.append((text, "size", (value, None, None, "in", "unknown", "unknown"), "ok"))
        rows += [('16.5 x 19"', "size", (None, None, None, "unknown", "unknown", "unknown"), "unparsed"),
                 ('16.5X19"', "size", (None, None, None, "unknown", "unknown", "unknown"), "unparsed")]
        for text, kind, value in [("tested to 1000#", None, "1000"), ("bleed to 0#", None, "0"),
                                  ("7,500 psi", "pressure", "7500"), ("100 psig", "pressure", "100")]:
            rows.append((text, kind, (value, None, None, "psi", "unknown", "unknown"), "ok"))
        rows.append(("23#", None, (None, None, None, "unknown", "unknown", "unknown"), "unparsed"))
        for text, value in [("17.7 ppg", "17.7"), ("16.2 ppg", "16.2"), ("17.0 ppg", "17"),
                            ("10 lb/gal", "10"), ("17.7 ppg EMW", "17.7")]:
            rows.append((text, "density", (value, None, None, "ppg", "unknown", "unknown"), "ok"))
        for text, value, unit in [("24 bbls", "24", "bbl"), ("42 sx", "42", "sx"), ("387 cu ft", "387", "cuft"), ("3 gal", "3", "gal")]:
            rows.append((text, "volume", (value, None, None, unit, "unknown", "unknown"), "ok"))
        for text, value, unit, reference, datum in [
            ("11,640", "11640", "unknown", "unknown", "unknown"),
            ("1,484' MD", "1484", "ft", "MD", "unknown"), ("7983'", "7983", "ft", "unknown", "unknown"),
            ("18'BML", "18", "ft", "BML", "ML"), ("10'AML", "10", "ft", "AML", "ML"),
            ("12440' tvd", "12440", "ft", "TVD", "unknown"), ("12440' TVD", "12440", "ft", "TVD", "unknown"),
            ("100' md", "100", "ft", "MD", "unknown"), ("2987' CTM", "2987", "ft", "MD", "CTM"),
            ("100' DPM", "100", "ft", "MD", "DPM"), ("100' dpm", "100", "ft", "MD", "DPM"),
            ("8000' KBM", "8000", "ft", "unknown", "KB"), ("100' RKB", "100", "ft", "unknown", "KB"),
            ("100' KB", "100", "ft", "unknown", "KB"), ("100' SLM", "100", "ft", "MD", "SLM"),
            ("100' WLM", "100", "ft", "MD", "WLM"), ("100 feet", "100", "ft", "unknown", "unknown"),
            ("100 m", "100", "m", "unknown", "unknown"), ("13007\u00bf", "13007", "unknown", "unknown", "unknown"),
        ]:
            rows.append((text, "depth", (value, None, None, unit, reference, datum), "ambiguous" if unit == "unknown" else "ok"))
        for text, unit, reference in [("13243' MD/12625' TVD", "ft", "MD"), ("BN 7300' Sand", "ft", "unknown"),
                                      ("B-1 Sand-200", "unknown", "unknown"), ("MP 107 D2", "unknown", "unknown")]:
            rows.append((text, "depth", (None, None, None, unit, reference, "unknown"), "unparsed"))
        for text, lo, hi, ref in [("13202'-24'", "13202", "13224", "unknown"), ("11884'-950'", "11884", "11950", "unknown"),
                                  ("5840'-6240'", "5840", "6240", "unknown"), ("10,830' MD to 11,430' MD", "10830", "11430", "MD"),
                                  ("11,626' to 11,630' MD", "11626", "11630", "MD")]:
            rows.append((text, "interval", (None, lo, hi, "ft", ref, "unknown"), "ok"))
        for surface, unit, reference in [("600ft", "ft", "unknown"), ("600ft MD", "ft", "MD"),
                                          ("600feet", "ft", "unknown"), ("600m", "m", "unknown"),
                                          ("600meters", "m", "unknown"), ("600 m", "m", "unknown")]:
            rows.append((surface, "depth", ("600", None, None, unit, reference, "unknown"), "ok"))
        rows.append(("600 mud", "depth", (None, None, None, "unknown", "unknown", "unknown"), "unparsed"))
        rows.append(("600ft-700ft", "interval", (None, "600", "700", "ft", "unknown", "unknown"), "ok"))
        for surface, kind, expected, status in rows:
            with self.subTest(surface=surface, kind=kind):
                if kind == "date":
                    result = parse_us_date(surface)
                    self.assertEqual(result, expected)
                    self.assertEqual(result[1], status)
                else:
                    result = parse_quantity(surface, kind)
                    self.assertEqual(tuple(getattr(result, k) for k in ("value", "lower", "upper", "unit", "reference", "datum")), expected)
                    self.assertEqual(result.status, status)

    def test_names_and_symmetric_quantities(self):
        self.assertTrue(in_name("Amber 6100 ft Sand", 6, 13))
        self.assertFalse(in_name("6100 ft MD.", 0, 7))
        self.assertTrue(in_name("7300' Sand", 0, 5))
        for kind, unit in (("pressure", "psi"), ("volume", "bbl")):
            for number, expected in (("990", True), ("989", False), ("0", False)):
                a, b = parse_quantity("1000 " + unit, kind), parse_quantity(number + " " + unit, kind)
                self.assertEqual(compare(a, b, {}, symmetric=True), expected)
                self.assertEqual(compare(b, a, {}, symmetric=True), expected)

    def test_hash_context_and_date_fallback(self):
        for text in ("no hash", "tested to 1000#", "bleed to 0#", "bled down to 0#", "pressure 23#", "23# psig"):
            self.assertTrue(hash_is_pressure(text), text)
        self.assertFalse(hash_is_pressure("23# tubular"))
        for surface, expected in [("2011-03-14", ("2011-03-14", "day")), ("mid 2011", ("2011", "year")),
                                  ("late 2011", ("2011", "year")), ("Feb 29, 2000", ("2000-02-29", "day")),
                                  ("13-14", (None, "partial")), ("unknown", (None, "partial"))]:
            self.assertEqual(parse_us_date(surface), expected)

    def test_examples(self):
        for text, kind, value, unit, reference, datum in [
            ("7,500 psi", "pressure", "7500", "psi", "unknown", "unknown"),
            ("1000#", "pressure", "1000", "psi", "unknown", "unknown"),
            ('9-5/8"', "size", "9.625", "in", "unknown", "unknown"),
            ('13 3/8"', "size", "13.375", "in", "unknown", "unknown"),
            ('2-9/16"', "size", "2.5625", "in", "unknown", "unknown"),
            ("12440' tvd", "depth", "12440", "ft", "TVD", "unknown"),
            ("2987' CTM", "depth", "2987", "ft", "MD", "CTM"),
            ("8000' KBM", "depth", "8000", "ft", "unknown", "KB"),
            ("18'BML", "depth", "18", "ft", "BML", "ML"),
            ("13007\u00bf", "depth", "13007", "unknown", "unknown", "unknown"),
            ("1955", "depth", "1955", "unknown", "unknown", "unknown"),
            ("24 bbls", "volume", "24", "bbl", "unknown", "unknown"),
            ("387 cu ft", "volume", "387", "cuft", "unknown", "unknown"),
            ("17.7 ppg EMW", "density", "17.7", "ppg", "unknown", "unknown"),
        ]:
            with self.subTest(text=text):
                q = parse_quantity(text, kind)
                self.assertEqual((q.value, q.unit, q.reference, q.datum), (value, unit, reference, datum))
                self.assertEqual(q.status, "ambiguous" if unit == "unknown" else "ok")
                self.assertEqual(q.raw, text)
        for text, ends in [("11,626' to 11,630' MD", ("11626", "11630")),
                           ("13202'-24'", ("13202", "13224")), ("11884'-950'", ("11884", "11950"))]:
            q = parse_quantity(text, "interval")
            self.assertEqual((q.lower, q.upper), ends)
            self.assertEqual(q.status, "ok")

    def test_comparison(self):
        self.assertNotEqual(parse_quantity("1000#").unit, "psi")
        self.assertEqual(parse_quantity("tested to 1000#").unit, "psi")
        def eq(a, b, kind): return compare(parse_quantity(a, kind), parse_quantity(b, kind), {})
        for a, b, kind in [("100 ft MD", "101 ft MD", "depth"), ("0 psi", "0 psi", "pressure"),
                           ("1000 psi", "1010 psi", "pressure"), ("10 ppg", "10.05 ppg", "density"),
                           ("100", "100 ft", "depth"), ("100'-200'", "101'-201'", "interval")]:
            self.assertTrue(eq(a, b, kind), (a, b))
        for a, b, kind in [("100 ft MD", "100 ft TVD", "depth"), ("0 psi", "0.01 psi", "pressure"),
                           ("1000 psi", "1010.01 psi", "pressure"), ("10 ppg", "10.051 ppg", "density"),
                           ("100", "101 ft", "depth"), ("100 ft", "100 m", "depth"),
                           ('5.5"', '5.51"', "size"), ("100 bbl", "100 sx", "volume")]:
            self.assertFalse(eq(a, b, kind), (a, b))
        self.assertFalse(compare(parse_quantity("100 ft"), parse_quantity("100'-100'"), {}))

    def test_dates(self):
        for text, expected in [("11/16/08", ("2008-11-16", "day")), ("10/28", (None, "partial")),
                               ("June 19, 2011", ("2011-06-19", "day")), ("1/1/49", ("2049-01-01", "day")),
                               ("1/1/50", ("1950-01-01", "day")), ("early 2012", ("2012", "year")),
                               ("June 2011", ("2011-06", "month")), ("2/30/20", (None, "partial"))]:
            self.assertEqual(parse_us_date(text), expected)
