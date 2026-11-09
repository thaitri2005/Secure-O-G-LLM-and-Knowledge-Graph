"""Validation of the ``table_rules.operations_summary`` settings of configs/corpus/k1.json (N27)."""
from __future__ import annotations

import copy
import unittest

from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config


def with_rule(change) -> dict:
    """The shipped configuration with ``change(rule)`` applied to a private copy of the Operations Summary rule."""
    config = copy.deepcopy(load_k1_config())
    change(config["table_rules"]["operations_summary"])
    return config


class OperationsRuleConfigTests(unittest.TestCase):
    def rejects(self, change):
        with self.assertRaises(ValueError):
            validate_k1_config(with_rule(change))

    def test_the_shipped_rule_is_valid_and_complete(self):
        rule = load_k1_config()["table_rules"]["operations_summary"]
        self.assertEqual(set(rule), {"document_types", "schema", "recognition", "tolerances"})
        self.assertEqual([column["kind"] for column in rule["schema"]["columns"]],
                         ["time", "time", "hours", "depth", "code", "text", "mark"])

    def test_every_block_needs_exactly_its_keys(self):
        def drop(*path):
            def change(rule):
                target = rule
                for key in path[:-1]:
                    target = target[key]
                del target[path[-1]]
            return change

        def add(*path):
            def change(rule):
                target = rule
                for key in path:
                    target = target[key]
                target["unexpected"] = 1
            return change

        for path in (("schema",), ("recognition",), ("tolerances",), ("schema", "title_words"), ("schema", "columns"),
                     ("schema", "patterns"), ("schema", "mark"), ("schema", "annotation_kinds"),
                     ("schema", "patterns", "time"), ("schema", "mark", "glyph"), ("recognition", "phrase_gap_em_title"),
                     ("recognition", "annotation_max_tokens"), ("tolerances", "line_gap_em_header"),
                     ("tolerances", "section_title"), ("tolerances", "section_title", "max_words")):
            with self.subTest(missing=path):
                self.rejects(drop(*path))
        for path in ((), ("schema",), ("schema", "patterns"), ("schema", "mark"), ("recognition",), ("tolerances",),
                     ("tolerances", "section_title")):
            with self.subTest(extra=path):
                self.rejects(add(*path))
        self.rejects(lambda rule: rule["schema"]["columns"][0].update(extra=1))
        self.rejects(lambda rule: rule["schema"]["annotation_kinds"][0].update(extra=1))
        self.rejects(lambda rule: rule["schema"]["annotation_kinds"][0].pop("sample"))

    def test_the_row_grammar_and_labels_are_fixed(self):
        self.rejects(lambda rule: rule["schema"]["columns"].reverse())
        self.rejects(lambda rule: rule["schema"]["columns"].pop())
        self.rejects(lambda rule: rule["schema"]["columns"][1].update(label="From"))
        self.rejects(lambda rule: rule["schema"]["columns"][1].update(label="  ---  "))
        self.rejects(lambda rule: rule["schema"]["columns"][1].update(label=""))

    def test_title_words_and_mark_glyph(self):
        for words in (["Operations"], ["Operations", "Summary", "Extra"], ["Operations", ""], ["Operations", "Sum mary"],
                      ["Operations", 5], "Operations Summary"):
            self.rejects(lambda rule, words=words: rule["schema"].update(title_words=words))
        self.rejects(lambda rule: rule["schema"]["mark"].update(glyph="XX"))
        self.rejects(lambda rule: rule["schema"]["mark"].update(glyph=""))

    def test_title_words_may_hold_regex_characters(self):
        validate_k1_config(with_rule(lambda rule: rule["schema"].update(title_words=["Ops.", "Sum+"])))

    def test_patterns_are_checked(self):
        self.rejects(lambda rule: rule["schema"]["patterns"].update(time="("))
        self.rejects(lambda rule: rule["schema"]["patterns"].update(time="^abc$"))  # must match 9:05
        self.rejects(lambda rule: rule["schema"]["patterns"].update(time=".*"))  # must not match abc
        self.rejects(lambda rule: rule["schema"]["patterns"].update(hours=""))
        self.rejects(lambda rule: rule["schema"]["patterns"].update(code=5))

    def test_annotation_kinds_are_checked_against_their_sample(self):
        kinds = lambda rule: rule["schema"]["annotation_kinds"]  # noqa: E731
        self.rejects(lambda rule: kinds(rule)[0].update(pattern="^records not printed$"))  # no capture group
        self.rejects(lambda rule: kinds(rule)[0].update(pattern="^(\\d+) (records?) not printed$"))  # two groups
        self.rejects(lambda rule: kinds(rule)[0].update(sample="nothing like it"))  # pattern does not match the sample
        self.rejects(lambda rule: kinds(rule)[0].update(sample=""))
        self.rejects(lambda rule: kinds(rule)[0].update(pattern="^(\\w+) records$", sample="abc records"))  # group 1 not digits
        self.rejects(lambda rule: kinds(rule).append(dict(kinds(rule)[0])))  # the same kind twice
        self.rejects(lambda rule: rule["schema"].update(annotation_kinds="records_not_printed"))
        validate_k1_config(with_rule(lambda rule: rule["schema"].update(annotation_kinds=[])))  # an empty list is fine
        validate_k1_config(with_rule(lambda rule: kinds(rule).append(
            {"kind": "pages_missing", "pattern": "^(\\d+) pages? missing$", "sample": "3 pages missing"})))

    def test_numbers_must_be_in_range(self):
        for key, value in (("phrase_gap_em_title", 0), ("phrase_gap_em_title", -1), ("annotation_min_gap_em_title", 11),
                           ("annotation_max_tokens", 0), ("annotation_max_tokens", 51), ("annotation_max_tokens", 2.5),
                           ("title_header_gap_em_header", "1.0"), ("title_header_gap_em_header", True)):
            with self.subTest(key=key, value=value):
                self.rejects(lambda rule, key=key, value=value: rule["recognition"].update({key: value}))
        for key, value in (("line_gap_em_header", 0), ("continuation_indent_em_header", 10.5), ("band_margin_em_header", -2),
                           ("code_zone_extension", 2.5), ("code_zone_extension", -0.1), ("elapsed_tolerance_minutes", 0),
                           ("docling_overlap", 0), ("docling_overlap", 1.5)):
            with self.subTest(key=key, value=value):
                self.rejects(lambda rule, key=key, value=value: rule["tolerances"].update({key: value}))
        for key, value in (("centre_tolerance_page_width", 0), ("centre_tolerance_page_width", 0.5), ("max_words", 0),
                           ("max_words", 11), ("word_pattern", "(")):
            with self.subTest(key=key, value=value):
                self.rejects(lambda rule, key=key, value=value: rule["tolerances"]["section_title"].update({key: value}))
        validate_k1_config(with_rule(lambda rule: rule["tolerances"].update(code_zone_extension=0)))

    def test_the_phrase_gap_must_stay_below_the_annotation_gap(self):
        self.rejects(lambda rule: rule["recognition"].update(phrase_gap_em_title=3.0))
        self.rejects(lambda rule: rule["recognition"].update(phrase_gap_em_title=4.0))

    def test_a_rule_that_is_switched_on_needs_its_settings(self):
        config = copy.deepcopy(load_k1_config())
        config["table_rules"]["operations_summary"] = {"document_types": ["daily_report"]}
        with self.assertRaises(ValueError):
            validate_k1_config(config)

    def test_no_table_rules_means_no_rule(self):
        config = {key: value for key, value in load_k1_config().items() if key != "table_rules"}
        self.assertEqual(validate_k1_config(config), config)


if __name__ == "__main__":
    unittest.main()
