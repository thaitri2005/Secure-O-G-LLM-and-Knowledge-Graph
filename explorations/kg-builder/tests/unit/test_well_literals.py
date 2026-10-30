"""Synthetic typed spans, exclusions, date parity and frozen status case rules."""
from __future__ import annotations

import re
import unittest

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.config import ConfigError
from kgbuilder.core.well_literals import DATE_PATTERNS, load_lexicon, status_code, typed_spans, typed_surface
from kgbuilder.core.well_values import parse_us_date
from kgbuilder.evaluation.well_eval import mention_spans


class WellLiteralsTest(unittest.TestCase):
    def test_typed_surfaces(self):
        cases = [("CIBP at 9,500'", ("depth",), "9,500'"), ("CIBP at 9,500' and 9,800'", ("depth",), None),
                 ("perfs 9500-9520' MD", ("interval", "depth"), "9500-9520' MD"), ("Amber 6100' Sand", ("depth",), None),
                 ('16.5 x 19" hole', ("size",), None), ('9-5/8" casing', ("size",), '9-5/8"'),
                 ("Tested to 500#", ("pressure",), "500#"), ("23# casing", ("pressure",), None),
                 ("mud 12.4 ppg", ("density",), "12.4 ppg"), ("pumped 42 sx", ("volume",), "42 sx"),
                 ("on 3/14/2011", ("date",), "3/14/2011"), ("on 3/14", ("date",), None),
                 ("at 100ft MD and 100ft MD", ("depth",), "100ft MD")]
        for surface, kinds, expected in cases:
            with self.subTest(surface=surface): self.assertEqual(typed_surface(surface, kinds), expected)
        self.assertEqual(typed_spans("at 100 ft", ("depth",)), [(3, 9, "100 ft")])

    def test_status_and_lexicon(self):
        lex = load_lexicon(PROJECT_ROOT / "configs/domains/bsee/bsee_literals.yaml")
        for text, expected in (("TA'd", "TA"), ("St. Mary well", None), ("well is ta", None), ("Temporarily Abandoned", "TA"),
                               ("TA'd then P&A", None), ("well ST", "ST"), ("Si", None), ("well shut-in", "SI")):
            self.assertEqual(status_code(text, lex["status"]), expected)
        path = clean_dir(PROJECT_ROOT / "runs/_test/guided_lexicon") / "bad.yaml"
        path.write_text("version: 1\n", encoding="utf-8")
        with self.assertRaises(ConfigError): load_lexicon(path)

    def test_date_pattern_parity(self):
        for surface in ("3/14/2011", "3-14-11", "June 2010", "June 20, 2009", "2010-02-03", "2012", "3/14"):
            text = "Invented on " + surface + "."
            iso, precision = parse_us_date(surface)
            obj = {"kind": "date", "text": surface, "iso": iso, "precision": precision}
            spans = sorted({h.span() for p in DATE_PATTERNS for h in re.finditer(p, text)
                            if parse_us_date(h[0]) == (iso, precision) and (precision != "partial" or h[0] == surface)})
            self.assertEqual(spans, mention_spans(text, obj, {}))
