"""Pre-registered verifier parsing, including misleading first-letter prefixes."""
from __future__ import annotations

import unittest

from helpers import PROJECT_ROOT
from kgbuilder.core.choice import classify, normalize_choice, parse_choices


class ChoiceTest(unittest.TestCase):
    def test_template_choices_and_classification(self):
        template = (PROJECT_ROOT / "third_party/edc/prompt_templates/sc_template.txt").read_text(encoding="utf-8")
        choices = "\n".join(f"{letter}. '{relation}': Synthetic relation." for letter, relation in zip("ABCDE", ("one", "two", "three", "four", "five")))
        prompt = template.format(input_text="Invented text.", query_triplet=["x", "one", "y"], query_relation="one", query_relation_definition="Synthetic.", choices=choices + "\nF. None of the above.\n")
        letters, none = parse_choices(prompt)
        self.assertEqual(letters, dict(zip("ABCDE", ("one", "two", "three", "four", "five"))))
        self.assertEqual(none, "F")
        for answer, expected in (("B", "choice"), (" B", "unparsed"), ("F", "none_of_above"), ("None of the above", "none_of_above"), ("", "unparsed"), ("Answer: C", "choice")):
            self.assertEqual(classify(answer, letters, none), expected)
        self.assertEqual(parse_choices("no choices"), ({}, None))

    def test_normalization(self):
        examples = {" B": "B", "'C'": "C'", "Answer: D": "D", "**A**": "A**", "B": "B", "None": "None", "": "",
                    "Correct answer: B": "B", "The answer is C": "C", " [ 'B": "'B", "Answer:": "Answer:", "first": "first"}
        for value, expected in examples.items():
            with self.subTest(value=value): self.assertEqual(normalize_choice(value), expected)
