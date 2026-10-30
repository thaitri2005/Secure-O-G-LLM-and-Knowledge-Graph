# Results

All table cells are read from `results/expected_results.json`. Values retain their captured precision. Undefined scores remain undefined. Timing and external baselines are recorded observations, not reproducible performance promises.

| Dataset | Configuration | Metric | Value | L2 IAA |
| --- | --- | --- | --- | --- |
| WebNLG-10 | EDC with window grounding, A4 | Strict F1 | 0.8428571428571429 | not applicable |
| MINE-3 | Recorded extraction and judge | Accuracy (29/45, source precision) | 0.6444 | not applicable |
| 2Wiki-10 | Text retrieval | Answer F1 | 0.7357142857142857 | not applicable |
| BSEE text v1 base | A4 full | L2 F1 | 0.2085889570552147 | 0.8790697674418605 |
| BSEE text v1 guided | A4 full | L2 F1 | 0.3450479233226837 | 0.8790697674418605 |
| BSEE text v2 guided | A4 full | L2 F1 | 0.4533715925394548 | 0.8538622129436325 |
| BSEE text v2 guided + recall | A4 full | L2 F1 | 0.5005714285714286 | 0.8538622129436325 |

The BSEE labels form an LLM-annotated benchmark: two independent LLM annotators from different model families and an LLM adjudicator, with no human expert validation. IAA measures agreement, not correctness. The adjudicator shares annotator A's family; on v2 partial disagreements the family participation counts were 91 for A, 27 for B and 9 edited decisions. Decisions accepting both contribute to both counts. `time` is unscored. **v1 and v2 scores are not comparable** because corpus and converter differ.

## WebNLG-10 ablation

A0-A5 are pipeline levels, defined in [evaluation](evaluation.md). EDC strict F1 is an upstream evaluator measure; it is not full-triple exact match. The sentence and window configurations also differ in resolution guards, validation and judge settings.

### Sentence grounding

| Extractor | A0 | A1 | A2 | A3 | A4 | A5 |
| --- | --- | --- | --- | --- | --- | --- |
| EDC | 0.7357142857142857 | 0.7357142857142857 | 0.8428571428571429 | 0.8428571428571429 | 0.8238095238095238 | 0.7761904761904762 |
| KGGen | 0.4366151866151866 | 0.4366151866151866 | 0.6009009009009009 | 0.6009009009009009 | 0.5898148148148148 | not run |
| Router | 0.6309523809523809 | 0.6309523809523809 | 0.7761904761904762 | 0.7761904761904762 | 0.7571428571428571 | not run |

### Window grounding

| Extractor | A0 | A1 | A2 | A3 | A4 | A5 |
| --- | --- | --- | --- | --- | --- | --- |
| EDC | 0.7357142857142857 | 0.7357142857142857 | 0.8428571428571429 | 0.8428571428571429 | 0.8428571428571429 | 0.8428571428571429 |
| KGGen | 0.4366151866151866 | 0.4366151866151866 | 0.6009009009009009 | 0.6009009009009009 | 0.6009009009009009 | not run |
| Router | 0.6309523809523809 | 0.6309523809523809 | 0.7761904761904762 | 0.7761904761904762 | 0.7761904761904762 | not run |

## MINE-3

| Essay | Correct | Queries |
| --- | --- | --- |
| 4 | 3 | 15 |
| 15 | 13 | 15 |
| 37 | 13 | 15 |

The recorded judge uses the captured retrieval contexts. This is model-judged accuracy and is not directly comparable to a published score using a different model.

## 2Wiki-10 QA

EM and token F1 use the pinned upstream QA metric. Only ten questions were evaluated.

### Sentence configuration

| Retrieval | Graph level | EM | F1 |
| --- | --- | --- | --- |
| text | None | 0.6 | 0.7357142857142857 |
| graph | A0 | 0.5 | 0.6357142857142857 |
| graph | A1 | 0.5 | 0.6357142857142857 |
| graph | A4 | 0.3 | 0.4757142857142857 |
| graph | A5 | 0.3 | 0.39 |
| hybrid | A0 | 0.6 | 0.7357142857142857 |
| hybrid | A1 | 0.6 | 0.7357142857142857 |
| hybrid | A4 | 0.4 | 0.5757142857142857 |
| hybrid | A5 | 0.4 | 0.5757142857142857 |

### Window configuration

| Retrieval | Graph level | EM | F1 |
| --- | --- | --- | --- |
| text | None | 0.6 | 0.7357142857142857 |
| graph | A0 | 0.4 | 0.5757142857142857 |
| graph | A4 | 0.5 | 0.6757142857142857 |
| graph | A5 | 0.5 | 0.6757142857142857 |
| hybrid | A0 | 0.5 | 0.6757142857142857 |
| hybrid | A4 | 0.5 | 0.6757142857142857 |
| hybrid | A5 | 0.5 | 0.6757142857142857 |

## BSEE table graphs

These aggregate counts are recorded. Rebuilding requires public raw downloads and is optional; it performs no LLM inference.

| Bundle | Nodes | Edges | Sources | Unresolved |
| --- | --- | --- | --- | --- |
| core | 136057 | 351047 | 361517 | 122158 |
| extended | 336264 | 551254 | 582165 | 122498 |

## BSEE text

v1 test results cover 50 selected documents, 49 readable. The full v1 test split has 75 documents; the other 25 were reserved and not built or scored by the extraction pipeline. v2 test covers 155 documents, 150 readable. Development results are in-sample. Every F1 below carries its scope-matched IAA.

### A4 full

| Configuration | L1 F1 (IAA) | L2 F1 (IAA) | L3 F1 (IAA) |
| --- | --- | --- | --- |
| v1 test base | 0.22291021671826625 (0.8790697674418605) | 0.2085889570552147 (0.8790697674418605) | 0.08588957055214724 (0.772093023255814) |
| v1 test guided | 0.3974358974358974 (0.8790697674418605) | 0.3450479233226837 (0.8790697674418605) | 0.1853035143769968 (0.772093023255814) |
| v2 dev guided | 0.48295454545454547 (0.84) | 0.4225352112676056 (0.8290909090909091) | 0.2535211267605634 (0.8109090909090909) |
| v2 dev windows | 0.5179063360881543 (0.84) | 0.4385026737967914 (0.8290909090909091) | 0.33689839572192515 (0.8109090909090909) |
| v2 dev groups | 0.5326876513317191 (0.84) | 0.4630071599045346 (0.8290909090909091) | 0.3476190476190476 (0.8109090909090909) |
| v2 dev recall | 0.6022471910112359 (0.84) | 0.5401785714285714 (0.8290909090909091) | 0.36160714285714285 (0.8109090909090909) |
| v2 test guided | 0.5304347826086957 (0.8663883089770354) | 0.4533715925394548 (0.8538622129436325) | 0.2253922967189729 (0.8058455114822547) |
| v2 test recall | 0.5671296296296297 (0.8663883089770354) | 0.5005714285714286 (0.8538622129436325) | 0.26621160409556316 (0.8058455114822547) |

### A4 strict

| Configuration | L1 F1 (IAA) | L2 F1 (IAA) | L3 F1 (IAA) |
| --- | --- | --- | --- |
| v1 test base | 0.21587301587301588 (0.8790697674418605) | 0.20125786163522014 (0.8790697674418605) | 0.0880503144654088 (0.772093023255814) |
| v1 test guided | 0.3818770226537217 (0.8790697674418605) | 0.32903225806451614 (0.8790697674418605) | 0.1870967741935484 (0.772093023255814) |
| v2 dev guided | 0.4668587896253602 (0.84) | 0.4057142857142857 (0.8290909090909091) | 0.2571428571428571 (0.8109090909090909) |
| v2 dev windows | 0.5138121546961326 (0.84) | 0.44086021505376344 (0.8290909090909091) | 0.3387096774193548 (0.8109090909090909) |
| v2 dev groups | 0.5294117647058824 (0.84) | 0.45893719806763283 (0.8290909090909091) | 0.35180722891566263 (0.8109090909090909) |
| v2 dev recall | 0.5981735159817352 (0.84) | 0.5351473922902494 (0.8290909090909091) | 0.36281179138321995 (0.8109090909090909) |
| v2 test guided | 0.5073746312684366 (0.8663883089770354) | 0.4298245614035088 (0.8538622129436325) | 0.22965116279069767 (0.8058455114822547) |
| v2 test recall | 0.5731132075471698 (0.8663883089770354) | 0.5058275058275058 (0.8538622129436325) | 0.2691415313225058 (0.8058455114822547) |

### Primary paired comparisons

| Comparison | L2 F1 difference | 95% paired bootstrap CI | Readable documents | Sign-test p | Conclusion |
| --- | --- | --- | --- | --- | --- |
| v1 guided minus base | 0.13645896626746898 | [-0.00023166023166026894, 0.24162708561685542] | 49 | 0.022655844688415527 | not confirmed |
| v2 recall minus guided | 0.04719983603197375 | [-0.004062877409445664, 0.10439655429371963] | 150 | 0.620144765081303 | not confirmed |

Confirmation requires the pre-registered primary full-export confidence interval lower bound to be strictly positive. Neither comparison meets that rule. The sign-test result does not replace the primary rule; the positive strict-export interval for v2 is secondary.

## Interpretation

The samples are small and domain-specific. Development selection, correlated LLM annotation errors, conversion rules and evidence filtering all affect the scores. The v1 annotation correction involved one annotator seeing parser code; independence was procedural. Earlier aggregate test results helped inform the development menu. No human accuracy ceiling can be inferred from IAA. See [evaluation](evaluation.md), [annotation methodology](annotation-guideline.md) and [development history](project-history.md).
