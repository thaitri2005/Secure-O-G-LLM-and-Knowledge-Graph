"""Report date and well resolution from verified forms and the PDF text layer."""
from pathlib import Path
import unittest
from unittest.mock import patch

from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from graph_builder.corpus.report_context import page_context, report_contexts

ROOT = Path(__file__).resolve().parents[1]
DDR_NAMES = ["gdr882_ak3_appx_27_6_dailyreportdetailrpt_nocost_160920154309",
             "gdr882_ak3_appx_28_6_dailyreportdetailrpt_160920153612",
             "gdr882_ak3_appx_29_6_dailyreportgraphicalrpt_160920155318",
             "gdr882_ak3_appx_30_6_dailyreportsummaryrpt_160920155352"]
DDR_PDFS = [ROOT / "data/raw" / f"{name}.pdf" for name in DDR_NAMES]
CONFIG = load_k1_config()["report_context"]


def form(date="18-Aug-16", well="AK-3", verified=True, well_key="Well ID:"):
    return {"verified": verified, "fields": [{"key": "Report For", "value": date}, {"key": well_key, "value": well},
                                             {"key": "Other:", "value": "x"}]}


def with_text(texts):
    return patch("graph_builder.corpus.report_context.pdf_page_texts", return_value=texts)


class PageContextTests(unittest.TestCase):
    def test_verified_form_wins_over_text(self):
        text = "Report For 01-Jan-00\nWell ID: ZZ-9"
        self.assertEqual(page_context(form(), text, CONFIG), {"report_date": "18-Aug-16", "well": "AK-3"})

    def test_well_name_is_used_when_well_id_is_missing(self):
        self.assertEqual(page_context(form(well_key="Well Name:"), "", CONFIG), {"report_date": "18-Aug-16", "well": "AK-3"})

    def test_text_patterns_fill_a_continuation_page(self):
        text = "Report For 19-Aug-16\r\nDaily Drilling Report\r\nWell ID:\r\nGeothermal Resource Group\r\nAK-3 Well Name: AK-3"
        self.assertEqual(page_context(None, text, CONFIG), {"report_date": "19-Aug-16", "well": "AK-3"})

    def test_unverified_form_is_ignored(self):
        self.assertEqual(page_context(form(verified=False), "", CONFIG), {})

    def test_graphical_summary_header(self):
        text = "Graphical Summary 7-Sep-16\nWell ID: AK-3"
        self.assertEqual(page_context(None, text, CONFIG), {"report_date": "7-Sep-16", "well": "AK-3"})

    def test_both_values_are_required(self):
        self.assertEqual(page_context(None, "Report For 19-Aug-16", CONFIG), {})
        self.assertEqual(page_context(None, "Well ID: AK-3", CONFIG), {})

    def test_form_fills_one_field_and_text_the_other(self):
        partial = {"verified": True, "fields": [{"key": "Report For", "value": "18-Aug-16"}]}
        self.assertEqual(page_context(partial, "Well ID: AK-3", CONFIG), {"report_date": "18-Aug-16", "well": "AK-3"})


class ReportContextsTests(unittest.TestCase):
    def test_non_daily_documents_get_nothing(self):
        with with_text({1: "Report For 18-Aug-16\nWell ID: AK-3"}):
            self.assertEqual(report_contexts(Path("x.pdf"), [1], {}, "eowr", CONFIG), ({}, [], []))

    def test_pages_are_split_into_contexts_and_missing(self):
        texts = {1: "Report For 18-Aug-16\nWell ID: AK-3", 2: "nothing useful"}
        with with_text(texts):
            contexts, conflicts, missing = report_contexts(Path("x.pdf"), [1, 2], {}, "daily_report", CONFIG)
        self.assertEqual(contexts, {1: {"report_date": "18-Aug-16", "well": "AK-3"}})
        self.assertEqual((conflicts, missing), ([], [2]))

    def test_disagreement_between_form_and_text_is_reported_and_the_form_wins(self):
        texts = {3: "Report For 19-Aug-16\nWell ID: AK-3"}
        with with_text(texts):
            contexts, conflicts, missing = report_contexts(Path("x.pdf"), [3], {3: form()}, "daily_report", CONFIG)
        self.assertEqual(contexts[3]["report_date"], "18-Aug-16")
        self.assertEqual(conflicts, [{"page": 3, "field": "report_date", "form": "18-Aug-16", "text": "19-Aug-16"}])
        self.assertEqual(missing, [])

    def test_agreeing_form_and_text_report_no_conflict(self):
        texts = {1: "Report For 18-Aug-16\nWell ID: AK-3"}
        with with_text(texts):
            self.assertEqual(report_contexts(Path("x.pdf"), [1], {1: form()}, "daily_report", CONFIG)[1], [])


class ConfigTests(unittest.TestCase):
    def test_shipped_configuration_is_valid(self):
        config = load_k1_config()
        self.assertEqual(config["report_context"]["document_types"], ["daily_report"])
        self.assertIs(config["forms"]["generic"], False)

    def test_unknown_keys_and_invalid_regexes_are_rejected(self):
        def changed(section, key, value):
            config = load_k1_config()
            config[section][key] = value
            return config

        with self.assertRaises(ValueError):
            validate_k1_config({**load_k1_config(), "extra": {}})
        with self.assertRaises(ValueError):
            validate_k1_config(changed("forms", "unknown", 1))
        with self.assertRaises(ValueError):
            validate_k1_config(changed("report_context", "date_patterns", ["(unclosed"]))
        with self.assertRaises(ValueError):
            validate_k1_config(changed("report_context", "well_patterns", ["no group"]))
        with self.assertRaises(ValueError):
            validate_k1_config(changed("forms", "generic", "false"))

    def test_document_type_rules(self):
        from graph_builder.corpus.k1_config import document_type
        config = load_k1_config()
        self.assertEqual(document_type("gdr882_ak3_eowr", config), "eowr")
        self.assertEqual(document_type("gdr882-ak3-appx-30-6-dailyreportsummaryrpt-1a2b3c4d", config), "daily_report")
        self.assertEqual(document_type("unknown-file", config), "other")


@unittest.skipUnless(all(path.exists() for path in DDR_PDFS), "daily report PDFs are not in data/raw")
class RealDailyReportTests(unittest.TestCase):
    def test_every_page_of_the_four_daily_reports_has_date_and_well(self):
        import pypdfium2 as pdfium
        from graph_builder.corpus.forms import extract_auto, load_template
        template = load_template()
        total = 0
        for path in DDR_PDFS:
            with pdfium.PdfDocument(path) as pdf:
                count = len(pdf)
            pages = range(1, count + 1)
            forms = {number: form for number in pages if (form := extract_auto(path, number, template, 0.4))}
            contexts, conflicts, missing = report_contexts(path, pages, forms, "daily_report", CONFIG)
            self.assertEqual((len(contexts), missing, conflicts), (count, [], []), path.name)
            self.assertEqual({context["well"] for context in contexts.values()}, {"AK-3"}, path.name)
            total += len(contexts)
        self.assertEqual(total, 145)


if __name__ == "__main__":
    unittest.main()
