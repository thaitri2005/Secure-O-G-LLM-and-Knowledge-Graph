"""Neutral synthetic mappings preserve bytes, facts, counts and seal validation."""
import hashlib
import json
import unittest

from helpers import assert_expected_artifact, clean_dir, PROJECT_ROOT
from kgbuilder.core.config import ConfigError
from kgbuilder.core.text import cj, iter_jsonl, write_jsonl
from kgbuilder.evaluation import well_gold
from unit.test_well_gold import gold_fixture


def mapped_bytes(raw, mapping):
    rows = [json.loads(line) for line in raw.splitlines()]
    for row in rows:
        row['annotator'] = mapping.get(row['annotator'], row['annotator'])
    return ''.join(cj(row) + '\n' for row in rows).encode()


class PublicationMappingTest(unittest.TestCase):
    def test_mapping_changes_only_role_and_keeps_exact_bytes_and_hashes(self):
        old = b'{"annotator":"role_x","count":2,"note":"role_x is preserved as text"}\n'
        expected = b'{"annotator":"annotator_a","count":2,"note":"role_x is preserved as text"}\n'
        actual = mapped_bytes(old, {'role_x': 'annotator_a'})
        self.assertEqual(actual, expected)
        self.assertEqual(hashlib.sha256(actual).digest(), hashlib.sha256(expected).digest())
        self.assertEqual(json.loads(actual)['count'], json.loads(old)['count'])
        self.assertEqual(json.loads(actual)['note'], json.loads(old)['note'])
        self.assertEqual(mapped_bytes(actual, {'role_x': 'annotator_a'}), expected)
        self.assertNotEqual(hashlib.sha256(old).digest(), hashlib.sha256(expected).digest())

    def test_mapped_annotations_preserve_fact_counts_and_seals(self):
        cfg = gold_fixture(complete=True)
        root = cfg['root']
        before = list(iter_jsonl(root / 'adjudicated.jsonl'))
        expected_facts = sum(row['record'] == 'fact' for row in before)
        self.assertGreater(expected_facts, 0)
        for path in sorted((root / 'annotations/annotator_a').glob('*.jsonl')):
            current = path.read_bytes()
            legacy = mapped_bytes(current, {'annotator_a': 'role_x'})
            restored = mapped_bytes(legacy, {'role_x': 'annotator_a'})
            self.assertEqual(restored, current)
            self.assertEqual(hashlib.sha256(restored).digest(), hashlib.sha256(current).digest())
            self.assertEqual(len(legacy.splitlines()), len(restored.splitlines()))
            path.write_bytes(restored)
        self.assertTrue(all(value == 'OK' for value in well_gold.verify(cfg).values()))
        after = list(iter_jsonl(root / 'adjudicated.jsonl'))
        self.assertEqual(after, before)
        self.assertEqual(sum(row['record'] == 'fact' for row in after), expected_facts)
        path = next((root / 'annotations/annotator_a').glob('*.jsonl'))
        records = list(iter_jsonl(path))
        records[0]['note'] = 'Synthetic tamper'
        write_jsonl(path, records)
        with self.assertRaises(ConfigError):
            well_gold.verify(cfg)

    def test_complete_byte_regression_rejects_content_and_digest_tampering(self):
        root = clean_dir(PROJECT_ROOT / 'runs/_test/publication_mapping')
        path = root / 'expected.json'
        expected = '{"annotator":"annotator_a","count":2}\n'
        entry = {'text': expected, 'sha256': hashlib.sha256(expected.encode()).hexdigest()}
        path.write_bytes(expected.encode())
        assert_expected_artifact(self, path, entry)
        path.write_bytes(expected.replace('2', '3').encode())
        with self.assertRaises(AssertionError):
            assert_expected_artifact(self, path, entry)
        path.write_bytes(expected.encode())
        with self.assertRaises(AssertionError):
            assert_expected_artifact(self, path, {**entry, 'sha256': '0' * 64})
