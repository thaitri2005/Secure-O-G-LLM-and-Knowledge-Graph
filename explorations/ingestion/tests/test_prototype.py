"""Regression checks for conversion normalization, geometry and K1 lineage."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ingest_prototype import runtime
from ingest_prototype.chunking import map_children, page_texts, separate_contexts
from ingest_prototype.evaluate import normalize_quotes, pair_score, transcription
from ingest_prototype.rotation import improves, restore_box


class ConversionTests(unittest.TestCase):
    def test_cold_and_cached_use_validated_json(self):
        from ingest_prototype.convert import segment, _CONVERTERS
        from docling_core.types.doc import DoclingDocument
        document = DoclingDocument(name='example')
        result = Mock(document=document, status=Mock(value='success'))
        converter = Mock()
        converter.convert.return_value = result
        _CONVERTERS.clear()
        with tempfile.TemporaryDirectory(dir=runtime.BASE / 'runs') as directory:
            cache = Path(directory) / 'native.json.gz'
            with patch('graph_builder.corpus.convert.build_converter', return_value=converter):
                cold, first = segment(Path('example.pdf'), 'text', None, cache, {})
                cached, second = segment(Path('example.pdf'), 'text', None, cache, {})
            self.assertEqual(cold.model_dump_json(), cached.model_dump_json())
            self.assertIsNot(cold, document)
            self.assertFalse(first['cached'])
            self.assertTrue(second['cached'])
            self.assertEqual(converter.convert.call_count, 1)

    def test_rotation_requires_both_improvements(self):
        before = {'cells': 10, 'word_recall': .5}
        self.assertFalse(improves(before, {'cells': 11, 'word_recall': .5}))
        self.assertFalse(improves(before, {'cells': 10, 'word_recall': .6}))
        self.assertTrue(improves(before, {'cells': 11, 'word_recall': .6}))

    def test_inverse_rotation_boxes(self):
        from docling_core.types.doc import BoundingBox
        box = BoundingBox(l=20, t=10, r=40, b=30, coord_origin='TOPLEFT')
        restored = restore_box(box, 100, 200, 100, 90)
        self.assertEqual([restored.l, restored.t, restored.r, restored.b], [10, 160, 30, 180])
        restored = restore_box(box, 100, 200, 100, 270)
        self.assertEqual([restored.l, restored.t, restored.r, restored.b], [70, 20, 90, 40])


class RecordTests(unittest.TestCase):
    def test_header_only_continuation_extension(self):
        from ingest_prototype.tables import continued_tables
        import copy
        def raw(row, col, text):
            return dict(start_row_offset_idx=row, start_col_offset_idx=col, row_span=1, col_span=1,
                        text=text, column_header=row == 0,
                        bbox=dict(l=10 + col * 90, t=20, r=90 + col * 90, b=30, coord_origin='TOPLEFT'))
        left_cells = [raw(0, 0, 'Item'), raw(0, 1, 'Actual')]
        right_cells = [raw(0, 0, 'Depth'), raw(0, 1, '100')]
        tables = [dict(id='left', page=1, bbox=[10, 200, 190, 220], height=300, num_cols=2,
                       grid=[['Item', 'Actual']], header_rows=1, cells=[dict(r=0, c=0, text='Item', row_span=1, col_span=1)], native_index=0),
                  dict(id='right', page=2, bbox=[10, 20, 190, 100], height=300, num_cols=2,
                       grid=[['Depth', '100']], header_rows=0, cells=[dict(r=0, c=0, text='Depth', row_span=1, col_span=1)], native_index=1)]
        data = dict(tables=[dict(data=dict(table_cells=left_cells)), dict(data=dict(table_cells=right_cells))],
                    pages={str(n): dict(size=dict(width=200, height=300)) for n in (1, 2)}, texts=[])
        document = Mock()
        document.export_to_dict.return_value = data
        with patch('ingest_prototype.tables.native', return_value=copy.deepcopy(tables)), \
             patch('ingest_prototype.text_layer.source_page', return_value=dict(height=300, words=[])):
            logical, pairs, audit = continued_tables(document, Path('report.pdf'), [])
        self.assertEqual(len(logical), 1)
        self.assertEqual(logical[0]['pages'], [1, 2])
        self.assertEqual(pairs[0]['reasons'], ['header_only_extension_informed_by_review'])

    def test_form_parent_context_and_verbatim_text(self):
        chunk = dict(chunk_id='old', doc_id='sample', type='text', text='Original prose.', section_path=[],
                     page=1, pages=[1], source_spans=[], table_id=None, quality='ok')
        fields = [dict(key='Report For', value='31-Aug-16', key_bbox=[1, 1, 2, 2], value_bbox=[3, 1, 5, 2]),
                  dict(key='Well ID:', value='AK-3', key_bbox=[1, 3, 2, 4], value_bbox=[3, 3, 5, 4])]
        forms = [dict(page=1, fields=fields, verified=True)]
        children, parents = map_children('f' + '0' * 16, 'sample', 'daily_report', [chunk], [], forms)
        self.assertEqual(children[0]['text'], 'Original prose.')
        self.assertEqual(children[0]['context'], {'report_date': '31-Aug-16', 'well': 'AK-3'})
        self.assertEqual(children[1]['text'], 'Report For: 31-Aug-16\nWell ID: AK-3')
        self.assertEqual(children[1]['parent_id'], forms[0]['form_id'])
        self.assertEqual(parents[-1]['type'], 'form')

    def test_page_rebuild_uses_span_order(self):
        chunks = [dict(text='left RIGHT', page=1, source_spans=[dict(page=1, start=0, end=4), dict(page=2, start=5, end=10)]),
                  dict(text='again', page=2, source_spans=[])]
        self.assertEqual(page_texts(chunks), {1: 'left', 2: 'RIGHT\nagain'})

    def test_cross_page_passage_splits_when_report_context_changes(self):
        chunks = [dict(text='first second', page=1, pages=[1, 2], regions=[],
                       source_spans=[dict(page=1, start=0, end=5), dict(page=2, start=6, end=12)])]
        contexts = {1: {'report_date': 'today', 'well': 'A'}, 2: {'report_date': 'tomorrow', 'well': 'A'}}
        split = separate_contexts(chunks, contexts)
        self.assertEqual([row['text'] for row in split], ['first', 'second'])
        self.assertEqual(page_texts(chunks), page_texts(split))

    def test_serialization_rounds_geometry_only(self):
        value = {'bbox': [1.00001, 2.99999, 3.0, 4.0], 'threshold': .12345, 'text': '1.00001'}
        self.assertEqual(runtime.canonical(value), {'bbox': [1.0, 3.0, 3.0, 4.0], 'threshold': .12345, 'text': '1.00001'})

    def test_quote_normalization_and_raw_evidence(self):
        raw = transcription('2600’ East', "2600' East", ['2600’'])
        normalized = transcription('2600’ East', "2600' East", ['2600’'], True)
        self.assertEqual(raw['critical_matches'], 0)
        self.assertEqual(normalized['critical_matches'], 1)
        self.assertEqual(normalized['CER'], 0)
        self.assertEqual(normalize_quotes('‘’′“”″'), "'''\"\"\"")

    def test_pair_accuracy_penalizes_extra_predictions(self):
        actual = [dict(key='A', value='one', key_bbox=[1]*4, value_bbox=[2]*4),
                  dict(key='B', value='invented', key_bbox=None, value_bbox=None)]
        result = pair_score([('A', 'one')], actual, 'A one')
        self.assertEqual(result['pair_accuracy'], .5)
        self.assertEqual(result['literal_source_absent_count'], 1)
        self.assertEqual(result['bbox_share'], .5)


if __name__ == '__main__':
    unittest.main()
