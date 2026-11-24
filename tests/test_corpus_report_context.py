"""Report date and well resolution from verified forms and the PDF text layer."""
from pathlib import Path
import unittest
from unittest.mock import patch

from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from graph_builder.corpus.report_context import document_contexts, document_well, page_context, report_contexts

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


DEMO_CONFIG = ROOT / "configs/corpus/candidates/k1_demo_v1.json"


class DocumentWellTests(unittest.TestCase):
    """The optional document_context: one well per end-of-well report, read from its cover page."""
    SETTINGS = load_k1_config(DEMO_CONFIG)["document_context"]
    COVERS = {"AK-3": "Phone: 760-341-0186\r\nAkutan Geothermal Project\r\nAK-3\r\nEnd of Well Report\r\nOctober 14, 2016",
              "68-32": "Palm Desert, CA 92211\r\nEnd of Well Report\r\nSeismic Monitoring Wells\r\n68-32\r\nPrepared by:",
              "56-32": "Final Issued 22 July 21\r\nEnd of Well Report\r\nForge Seismic Monitoring Well 56-32 \r\nMilford, Utah"}

    def test_the_three_cover_layouts_give_their_well(self):
        for well, cover in self.COVERS.items():
            self.assertEqual(document_well({1: cover}, self.SETTINGS), (well, [well]), well)

    def test_other_wells_on_later_pages_are_not_read(self):
        texts = {1: self.COVERS["AK-3"], 3: "TG-2\nTG-4\n"}
        self.assertEqual(document_well(texts, self.SETTINGS)[0], "AK-3")

    def test_two_wells_on_the_cover_give_no_well(self):
        self.assertEqual(document_well({1: "AK-3\nTG-2\nEnd of Well Report"}, self.SETTINGS), ("", ["AK-3", "TG-2"]))
        self.assertEqual(document_well({1: "End of Well Report"}, self.SETTINGS), ("", []))

    def test_document_contexts_cover_every_page_or_none(self):
        with with_text({1: self.COVERS["56-32"]}):
            self.assertEqual(document_contexts(Path("x.pdf"), [1, 2], "eowr", self.SETTINGS),
                             ({1: {"well": "56-32"}, 2: {"well": "56-32"}}, [], {"well": "56-32", "candidates": ["56-32"]}))
        with with_text({1: "no well here"}):
            self.assertEqual(document_contexts(Path("x.pdf"), [1, 2], "eowr", self.SETTINGS)[:2], ({}, [1, 2]))
        self.assertEqual(document_contexts(Path("x.pdf"), [1], "daily_report", self.SETTINGS), ({}, [], None))
        self.assertEqual(document_contexts(Path("x.pdf"), [1], "eowr", None), ({}, [], None))

    def test_configuration_is_checked(self):
        base = load_k1_config()
        self.assertNotIn("document_context", base)
        for broken in (dict(self.SETTINGS, pages=0), dict(self.SETTINGS, document_types=[]), dict(self.SETTINGS, extra=1),
                       dict(self.SETTINGS, well_patterns=["AK-3"]), dict(self.SETTINGS, document_types=["daily_report"])):
            with self.assertRaises(ValueError, msg=broken):
                validate_k1_config(dict(base, document_context=broken))


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


class ReportBoundaryTests(unittest.TestCase):
    settings = dict(well_label="Well ID:", report_label="Report No:", date_label="Date:")

    def layer(self):
        words = []
        for index, (y, well, date) in enumerate(((20, "Alpha", "01-Jan-20"), (120, "Beta", "02-Jan-20"))):
            for row, text in ((index * 2, "Well ID: " + well),
                              (index * 2 + 1, f"Report No: {index + 1} Date: {date}")):
                top = y + (row % 2) * 10
                x = 12
                for token in text.split():
                    words.append(dict(text=token, row=row, bbox=[x, top, x + len(token) * 3, top + 6]))
                    x += len(token) * 3 + 3
        return dict(page=1, rotation=0, words=words, rulings=[[10, 18, 250, 38], [10, 118, 250, 138], [10, 138, 250, 220]])

    def fixture(self, ys=(50, 150, 60)):
        from types import SimpleNamespace as NS
        from docling_core.types.doc import BoundingBox, CoordOrigin
        texts, spans = [], []
        text = ""
        for i, y in enumerate(ys):
            value = f"value{i} "
            ref = f"#/texts/{i}"
            texts.append(NS(self_ref=ref, text=value, prov=[NS(page_no=1, charspan=(0,len(value)),
                bbox=BoundingBox(l=20,t=y,r=80,b=y+5,coord_origin=CoordOrigin.TOPLEFT))]))
            spans.append(dict(source_ref=ref,page=1,start=len(text),end=len(text)+len(value),source_start=0,source_end=len(value)))
            text += value
        chunk = dict(chunk_id="original",text=text,pages=[1],page=1,type="text",regions=[],source_spans=spans)
        return chunk, NS(texts=texts,tables=[],pages={1:NS(size=NS(height=240))})

    def partition(self, chunk, document, layer=None, changes=None, forms=None):
        from graph_builder.corpus.k1_build import partition_reports
        return partition_reports([chunk], forms or [], document, {1:layer or self.layer()}, self.settings, changes or [])

    def test_interleaved_order_splits_without_losing_or_reordering_content(self):
        chunk, document = self.fixture()
        children, _, evidence = self.partition(chunk, document)
        self.assertEqual([c["_report_context"]["well"] for c in children], ["Alpha", "Beta", "Alpha"])
        self.assertEqual("".join(c["text"] for c in children),chunk["text"])
        self.assertEqual([s["report_index"] for s in evidence["slices"]],[0,1,0])
        for child in children:
            self.assertEqual(child["source_spans"][0]["start"],0)
            self.assertEqual(child["source_spans"][-1]["end"],len(child["text"]))

    def test_same_report_keeps_multiple_chunks_and_distinct_report_separates(self):
        from graph_builder.corpus.k1_build import partition_reports
        chunk, doc = self.fixture((50,60))
        children, _, _ = partition_reports([chunk,chunk], [], doc, {1:self.layer()},self.settings,[])
        self.assertEqual(len(children),2)
        self.assertTrue(all(c["_report_context"]["well"] == "Alpha" for c in children))
        chunk, doc = self.fixture((50,150))
        self.assertEqual(len(self.partition(chunk,doc)[0]),2)

    def test_preamble_is_preserved_without_report_context(self):
        chunk, doc = self.fixture((2,50))
        children, _, _ = self.partition(chunk,doc)
        self.assertEqual(children[0]["_report_context"],{})
        self.assertEqual("".join(c["text"] for c in children),chunk["text"])

    def test_ambiguous_headers_and_provenance_fail_closed(self):
        from graph_builder.corpus.k1_build import ReportBoundaryError, report_bands
        layer = self.layer()
        layer["rulings"] = []
        with self.assertRaisesRegex(ReportBoundaryError,"missing_ruled_header"):
            report_bands(layer,self.settings)
        chunk, doc = self.fixture((116,))
        with self.assertRaisesRegex(ReportBoundaryError,"unassigned_box"):
            self.partition(chunk,doc)
        chunk, doc = self.fixture()
        chunk["source_spans"][0]["start"] = 1
        with self.assertRaisesRegex(ReportBoundaryError,"uncovered_text"):
            self.partition(chunk,doc)

    def test_rewrite_provenance_is_used_and_wrong_text_is_rejected(self):
        from graph_builder.corpus.k1_build import ReportBoundaryError
        chunk, doc = self.fixture((50,))
        change = dict(ref="#/texts/0",page=1,text=chunk["text"],box=[20,150,80,155])
        self.assertEqual(self.partition(chunk,doc,changes=[change])[0][0]["_report_context"]["well"],"Beta")
        change["text"] = "unrelated"
        with self.assertRaisesRegex(ReportBoundaryError,"source_slice_mismatch"):
            self.partition(chunk,doc,changes=[change])

    def test_cross_report_tables_and_forms_are_blocked(self):
        from graph_builder.corpus.k1_build import ReportBoundaryError
        chunk, doc = self.fixture((50,150))
        chunk["type"] = "table"
        with self.assertRaisesRegex(ReportBoundaryError,"nontext_crosses_reports"):
            self.partition(chunk,doc)
        chunk["type"] = "text"
        form = dict(page=1,fields=[dict(key="a",key_bbox=[20,50,30,55],value_bbox=[40,150,50,155])])
        with self.assertRaises(ReportBoundaryError):
            self.partition(chunk,doc,forms=[form])

    def test_option_is_fingerprinted_and_validation_is_strict(self):
        from graph_builder.corpus.k1_export import package_identity
        off = load_k1_config()
        on = dict(off,report_boundaries=self.settings)
        validate_k1_config(on)
        self.assertNotEqual(package_identity("test",off),package_identity("test",on))
        with self.assertRaises(ValueError):
            validate_k1_config(dict(off,report_boundaries={}))

    def test_distinct_report_numbers_with_same_k1_context_are_ambiguous(self):
        from graph_builder.corpus.k1_build import ReportBoundaryError, report_bands
        layer = self.layer()
        for word in layer["words"]:
            word["text"] = {"Beta":"Alpha", "02-Jan-20":"01-Jan-20"}.get(word["text"],word["text"])
        with self.assertRaisesRegex(ReportBoundaryError,"duplicate_identity"):
            report_bands(layer,self.settings)

    def test_partial_headers_rotation_and_unchunked_tables_fail_closed(self):
        from graph_builder.corpus.k1_build import ReportBoundaryError, report_bands, partition_reports
        layer = self.layer()
        layer["words"] = [w for w in layer["words"] if not (w["row"] == 3 and w["text"] == "Date:")]
        with self.assertRaisesRegex(ReportBoundaryError,"incomplete_identity_headers"):
            report_bands(layer,self.settings)
        layer = self.layer()
        layer["rotation"] = 90
        with self.assertRaisesRegex(ReportBoundaryError,"rotated_frame"):
            report_bands(layer,self.settings)
        _, doc = self.fixture()
        table = dict(source_ref="#/tables/0",regions=[dict(page=1,bbox=[20,50,80,160])])
        with self.assertRaisesRegex(ReportBoundaryError,"unassigned_box"):
            partition_reports([],[],doc,{1:self.layer()},self.settings,[],[table])

    def test_export_withholds_every_representation_and_records_source(self):
        import json
        import tempfile
        import test_corpus_k1 as helpers
        from graph_builder.corpus.catalog import Corpus
        from graph_builder.corpus.config import load_config, fingerprint
        from graph_builder.corpus.k1_export import K1CompletenessError, export_k1
        scratch = ROOT / "data/interim/cx-p2/dr29-tests"
        scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            root = Path(temporary)
            corpus = Corpus.create(root/"corpus",load_config(ROOT/"configs/corpus/default.json"))
            helpers.add_sample(corpus,root,"sample-report",fingerprint(corpus.config,{}))
            layer = self.layer()
            layer["rulings"] = []
            with patch("graph_builder.corpus.ocr_engines.engine_fingerprint",return_value=helpers.OCR), \
                 patch("graph_builder.corpus.text_layer.source_page",return_value=layer):
                with self.assertRaises(K1CompletenessError) as caught:
                    export_k1(corpus,"guarded",Path("models"),dict(load_k1_config(),report_boundaries=self.settings))
            report = json.loads(caught.exception.report_path.read_text(encoding="utf-8"))
            self.assertFalse((corpus.exports/"guarded/CURRENT.json").exists())
            self.assertFalse((corpus.exports/"guarded/releases").exists())
            held = report["blocked_documents"][0]
            self.assertEqual(held["detail"]["reason"],"report_boundary_missing_ruled_header")
            self.assertTrue(held["sha256"])
            self.assertTrue(held["source_references"][0]["source_spans"])
            self.assertEqual(held["pages_held"],2)


if __name__ == "__main__":
    unittest.main()
