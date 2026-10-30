"""Render publication tables directly from the immutable expected-results ledger."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tables():
    records = json.loads((ROOT / 'results/expected_results.json').read_bytes())['sources']
    index = {}
    for source in records:
        for metric in source['metrics']:
            key = source['release_source'], metric['metric']
            if key in index and index[key] != metric['value']:
                raise ValueError(f'Conflicting expected metric: {key}')
            index[key] = metric['value']

    def value(source, metric):
        v = index[source, metric]
        return 'undefined' if v is None else str(v)

    def table(headers, rows):
        return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                          '| ' + ' | '.join('---' for _ in headers) + ' |',
                          *['| ' + ' | '.join(map(str, row)) + ' |' for row in rows]])

    bsee = 'results/bsee_text/'
    l2 = '/exports/full/ai_gold/L2/f1'
    iaa = '/exports/full/ai_gold/iaa_reference/L2/f1'
    summary_rows = [
        ['WebNLG-10', 'EDC with window grounding, A4', 'Strict F1', value('results/ablation_window_grounding/webnlg10/A4/eval/scores.json', '/strict/F1'), 'not applicable'],
        ['MINE-3', 'Recorded extraction and judge', 'Accuracy (29/45, source precision)', value('results/upstream/kggen/mine_3/summary.json', '/overall_accuracy'), 'not applicable'],
        ['2Wiki-10', 'Text retrieval', 'Answer F1', value('results/ablation_window_grounding/qa/qa.json', '/rows/0/f1'), 'not applicable'],
    ]
    for label, name in [('v1 base', 'test_subset_v1_base'), ('v1 guided', 'test_subset_v1_guided'),
                        ('v2 guided', 'test_v2_guided'), ('v2 guided + recall', 'test_v2_guided_recall')]:
        source = bsee + name + '/evaluation/A4/scores.json'
        summary_rows.append(['BSEE text ' + label, 'A4 full', 'L2 F1', value(source, l2), value(source, iaa)])
    summary = table(['Dataset', 'Configuration', 'Metric', 'Value', 'L2 IAA'], summary_rows)
    sections = ['# Results', '', 'All table cells are read from `results/expected_results.json`. Values retain their captured precision. Undefined scores remain undefined. Timing and external baselines are recorded observations, not reproducible performance promises.', '', summary,
                '', 'The BSEE labels form an LLM-annotated benchmark: two independent LLM annotators from different model families and an LLM adjudicator, with no human expert validation. IAA measures agreement, not correctness. The adjudicator shares annotator A\'s family; on v2 partial disagreements the family participation counts were 91 for A, 27 for B and 9 edited decisions. Decisions accepting both contribute to both counts. `time` is unscored. **v1 and v2 scores are not comparable** because corpus and converter differ.', '', '## WebNLG-10 ablation', '', 'A0-A5 are pipeline levels, defined in [evaluation](evaluation.md). EDC strict F1 is an upstream evaluator measure; it is not full-triple exact match. The sentence and window configurations also differ in resolution guards, validation and judge settings.']
    for grounding in ('sentence', 'window'):
        rows = []
        for method, suffix in [('EDC', ''), ('KGGen', '_kggen'), ('Router', '_auto')]:
            cells = []
            for level in range(6):
                key = (f'results/ablation_{grounding}_grounding/webnlg10{suffix}/A{level}/eval/scores.json', '/strict/F1')
                cells.append(value(*key) if key in index else 'not run')
            rows.append([method, *cells])
        sections.extend(['', '### ' + grounding.title() + ' grounding', '', table(['Extractor', 'A0', 'A1', 'A2', 'A3', 'A4', 'A5'], rows)])
    sections.extend(['', '## MINE-3', '', table(['Essay', 'Correct', 'Queries'], [[value('results/upstream/kggen/mine_3/summary.json', f'/essays/{i}/id'), value('results/upstream/kggen/mine_3/summary.json', f'/essays/{i}/correct'), value('results/upstream/kggen/mine_3/summary.json', f'/essays/{i}/queries')] for i in range(3)]), '', 'The recorded judge uses the captured retrieval contexts. This is model-judged accuracy and is not directly comparable to a published score using a different model.'])
    sections.extend(['', '## 2Wiki-10 QA', '', 'EM and token F1 use the pinned upstream QA metric. Only ten questions were evaluated.'])
    for grounding in ('sentence', 'window'):
        source = f'results/ablation_{grounding}_grounding/qa/qa.json'
        raw = json.loads((ROOT / source).read_bytes())
        rows = [[row['mode'], row.get('graph', '-'), value(source, f'/rows/{i}/em'), value(source, f'/rows/{i}/f1')] for i, row in enumerate(raw['rows'])]
        sections.extend(['', '### ' + grounding.title() + ' configuration', '', table(['Retrieval', 'Graph level', 'EM', 'F1'], rows)])
    sections.extend(['', '## BSEE table graphs', '', 'These aggregate counts are recorded. Rebuilding requires public raw downloads and is optional; it performs no LLM inference.', '', table(['Bundle', 'Nodes', 'Edges', 'Sources', 'Unresolved'], [[bundle, *[value(f'results/bsee_tables/{bundle}/domain_stats.json', '/counts/' + field) for field in ('nodes', 'edges', 'sources', 'unresolved')]] for bundle in ('core', 'extended')])])
    sections.extend(['', '## BSEE text', '', 'v1 test results cover 50 selected documents, 49 readable. The full v1 test split has 75 documents; the other 25 were reserved and not built or scored by the extraction pipeline. v2 test covers 155 documents, 150 readable. Development results are in-sample. Every F1 below carries its scope-matched IAA.'])
    names = [('v1 test base','test_subset_v1_base'),('v1 test guided','test_subset_v1_guided'),('v2 dev guided','dev_v2_guided'),('v2 dev windows','dev_v2_guided_windows'),('v2 dev groups','dev_v2_guided_groups'),('v2 dev recall','dev_v2_guided_recall'),('v2 test guided','test_v2_guided'),('v2 test recall','test_v2_guided_recall')]
    for export in ('full', 'strict'):
        rows=[]
        for label, name in names:
            source=bsee+name+'/evaluation/A4/scores.json'
            rows.append([label, *[value(source,f'/exports/{export}/ai_gold/{level}/f1')+' ('+value(source,f'/exports/{export}/ai_gold/iaa_reference/{level}/f1')+')' for level in ('L1','L2','L3')]])
        sections.extend(['', '### A4 ' + export, '', table(['Configuration', 'L1 F1 (IAA)', 'L2 F1 (IAA)', 'L3 F1 (IAA)'], rows)])
    rows=[]
    for label, name in [('v1 guided minus base','test_subset_v1_guided'),('v2 recall minus guided','test_v2_guided_recall')]:
        source=bsee+name+'/evaluation/A4/scores.json'
        prefix='/exports/full/ai_gold/paired/L2/'
        rows.append([label,value(source,prefix+'difference'), '['+value(source,prefix+'ci95/0')+', '+value(source,prefix+'ci95/1')+']',value(source,prefix+'n'),value(source,prefix+'sign_test'),'not confirmed'])
    sections.extend(['', '### Primary paired comparisons', '', table(['Comparison', 'L2 F1 difference', '95% paired bootstrap CI', 'Readable documents', 'Sign-test p', 'Conclusion'],rows), '', 'Confirmation requires the pre-registered primary full-export confidence interval lower bound to be strictly positive. Neither comparison meets that rule. The sign-test result does not replace the primary rule; the positive strict-export interval for v2 is secondary.', '', '## Interpretation', '', 'The samples are small and domain-specific. Development selection, correlated LLM annotation errors, conversion rules and evidence filtering all affect the scores. The v1 annotation correction involved one annotator seeing parser code; independence was procedural. Earlier aggregate test results helped inform the development menu. No human accuracy ceiling can be inferred from IAA. See [evaluation](evaluation.md), [annotation methodology](annotation-guideline.md) and [development history](project-history.md).', ''])
    return summary, '\n'.join(sections)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    summary, results=tables()
    readme=ROOT/'README.md'
    before=readme.read_text(encoding='utf-8')
    start,end='<!-- results:start -->','<!-- results:end -->'
    left,rest=before.split(start)
    _,right=rest.split(end)
    expected=left+start+'\n\n'+summary+'\n\n'+end+right
    if args.check:
        if before!=expected or (ROOT/'docs/results.md').read_text(encoding='utf-8')!=results:
            raise SystemExit('Publication tables differ from expected results')
        print('README and results tables match expected_results.json')
    else:
        readme.write_text(expected,encoding='utf-8')
        (ROOT/'docs/results.md').write_text(results,encoding='utf-8')


if __name__=='__main__':main()
