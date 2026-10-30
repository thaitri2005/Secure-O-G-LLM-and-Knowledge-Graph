"""Recompute published scores and optionally replay builds without LLM inference."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import yaml
from prepare_reference import prepare

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_bytes())


def rows(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def pointer(value, path):
    for part in path.lstrip('/').split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, (list, tuple)) else value[part]
    return value


def equal(actual, wanted):
    if type(wanted) is float:
        return type(actual) in (int, float) and abs(actual - wanted) <= 1e-9
    return type(actual) is type(wanted) and actual == wanted


class Reproduction:
    def __init__(self, full, workers):
        self.start = time.monotonic()
        self.soft_budget = 1800 if full else 300
        self.hard_limit = 5400
        self.budget_warning_printed = False
        self.workers = workers
        self.out = ROOT / 'runs/reproduction' / (time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
        self.out.mkdir(parents=True)
        self.expected = read(ROOT / 'results/expected_results.json')
        self.spec = read(ROOT / 'data/evaluation/reproduction.json')
        self.references = {x['source']: x['destination'] for x in read(ROOT / 'data/evaluation/reference_files.json')}
        self.sources = defaultdict(list)
        for source, aliases in zip(self.expected['sources'], self.spec['metric_source_pointers']):
            self.sources[source['release_source']].append((source, aliases))
        self.report = {'mode': 'full' if full else 'quick', 'workers': workers,
                       'soft_budget_seconds': self.soft_budget, 'hard_limit_seconds': self.hard_limit,
                       'integrity_assertions': 0,
                       'recomputed_assertions': 0, 'recomputed_sources': [], 'builds': [], 'differences': []}
        self.results = {}

    def warn_if_over_budget(self, elapsed):
        if elapsed > self.soft_budget and not self.budget_warning_printed:
            self.budget_warning_printed = True
            print(f'WARNING: Reproduction exceeded the {self.soft_budget}-second planning budget; '
                  f'correctness checks continue within the {self.hard_limit}-second safety limit.',flush=True)

    def remaining(self):
        elapsed = time.monotonic() - self.start
        self.warn_if_over_budget(elapsed)
        seconds = self.hard_limit - elapsed
        if seconds <= 0:
            raise TimeoutError('Reproduction hard safety limit exceeded')
        return seconds

    def compare(self, source, actual, recomputed=True, prefix=None):
        count = 0
        for record, aliases in self.sources[source]:
            for metric in record['metrics']:
                if recomputed and metric['verification'] != 'recompute':
                    continue
                if prefix and not metric['metric'].startswith(prefix):
                    continue
                path = metric['metric'] if recomputed else aliases.get(metric['metric'], metric['metric'])
                try:
                    value = pointer(actual, path)
                except (KeyError, IndexError):
                    if not recomputed or metric['metric'] not in aliases:
                        raise
                    value = pointer(actual, aliases[metric['metric']])
                if not equal(value, metric['value']):
                    raise AssertionError(f'{source} {metric["metric"]}: {value!r} != {metric["value"]!r}')
                count += 1
        self.report['recomputed_assertions' if recomputed else 'integrity_assertions'] += count
        if recomputed:
            self.report['recomputed_sources'].append({'source': source, 'assertions': count, 'prefix': prefix})
            self.results[source] = actual
        return count

    def reference(self, source):
        return ROOT / self.references[source]

    def integrity(self):
        for source in self.sources:
            self.compare(source, read(ROOT / source), False)
        print(f'Captured-value integrity: {self.report["integrity_assertions"]} assertions', flush=True)

    def quick(self):
        from kgbuilder.core import config, text
        from kgbuilder.core.well_facts import WellFact, partition
        from kgbuilder.core.well_literals import load_lexicon
        from kgbuilder.evaluation import evaluate, well_eval, well_gold, well_attribution, analysis, ablation
        from kgbuilder.serve import qa
        self.remaining()
        policy = config.load_well_eval(ROOT / 'configs/experiments/bsee_eval.yaml')
        policy_hash = text.sha256_file(ROOT / 'configs/experiments/bsee_eval.yaml')
        lexicon = load_lexicon(ROOT / 'configs/domains/bsee/bsee_literals.yaml')
        build_index = {b['graph']: b for b in self.spec['builds']}

        # Identical prediction/reference bytes share one evaluator invocation.
        score_groups = defaultdict(list)
        for source in self.sources:
            if source.endswith('/eval/scores.json') or source.endswith('/eval/strict/scores.json'):
                ref = self.reference(source).parent
                key = hashlib.sha256((ref / 'pred.txt').read_bytes() + b'\0' + (ref / 'ref.txt').read_bytes()).hexdigest()
                score_groups[key].append((source, ref))
        def webnlg(item):
            key, group = item
            ref = group[0][1]
            work = self.out / 'webnlg' / key[:16]
            work.mkdir(parents=True)
            result = evaluate.run_webnlg_evaluator(ref / 'pred.txt', ref / 'ref.txt', work,
                                                  ROOT / '.venvs/edc/Scripts/python.exe', int(self.remaining()))
            return group, result
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for group, result in pool.map(webnlg, score_groups.items()):
                for source, _ in group:
                    self.compare(source, result)
        print(f'WebNLG: {sum(map(len, score_groups.values()))} score tables from {len(score_groups)} distinct inputs', flush=True)
        for source in self.sources:
            if not source.endswith('/eval/showcase_checks.json'):
                continue
            graph = source.removesuffix('/eval/showcase_checks.json') + '/graph.json'
            build = build_index[graph]
            work = self.out / 'showcase' / str(len(self.results))
            work.mkdir(parents=True)
            ref = self.reference(source).parent.parent
            for name in ('graph.json', 'entities.jsonl'):
                shutil.copyfile(ref / name, work / name)
            evaluate.eval_showcase(work, config.from_resolved(build['config']))
            self.compare(source, read(work / 'eval/showcase_checks.json'))

        pending = {s for s in self.sources if '/evaluation/' in s and s.endswith('/scores.json')}
        completed = {}
        while pending:
            progress = False
            for source in sorted(pending):
                parts = source.split('/')
                name, level = parts[2], parts[4]
                version = 'v2' if '_v2_' in name else 'v1'
                old = read(ROOT / source)
                baseline_name = None
                if 'paired' in old['exports']['full']['ai_gold']:
                    if version == 'v2':
                        base = ('dev' if name.startswith('dev') else 'test') + '_v2_guided'
                        baseline_name = f'results/bsee_text/{base}/evaluation/A4/scores.json'
                    elif name.endswith('_guided'):
                        baseline_name = source.replace('_guided/', '_base/')
                    else:
                        baseline_name = source.replace('/A4/', '/A0/')
                if baseline_name and baseline_name not in completed:
                    continue
                graph = f'results/bsee_text/{name}/{level}/graph.json'
                work = self.out / 'wells' / name / level
                actual = well_eval.evaluate_wells(self.reference(graph).parent,
                    ROOT / 'data/benchmarks/bsee_text' / version, policy, work,
                    ROOT / 'data/evaluation/bsee_text' / version / 'silver',
                    ROOT / 'data/evaluation/bsee_text' / version / 'rules',
                    ROOT / 'data/benchmarks/bsee_gold' / version,
                    completed.get(baseline_name), policy_file_sha256=policy_hash,
                    split='dev' if name.startswith('dev') else 'test')
                self.compare(source, actual)
                completed[source] = work
                pending.remove(source)
                progress = True
                self.remaining()
            if not progress:
                raise ValueError('Unresolved well-evaluation baseline dependencies: ' + str(pending))
        print(f'BSEE score tables: {len(completed)}', flush=True)
        for source in self.sources:
            if not source.endswith('/attribution.json'):
                continue
            parts = source.split('/')
            name, level = parts[2], parts[4]
            version = 'v2' if '_v2_' in name else 'v1'
            actual = well_attribution.attribute(
                self.reference(f'results/bsee_text/{name}/{level.removesuffix("_strict")}/graph.json').parent,
                ROOT / 'data/benchmarks/bsee_text' / version, ROOT / 'data/benchmarks/bsee_gold' / version,
                policy.model_dump(), lexicon, 'dev' if name.startswith('dev') else 'test',
                'strict' if level.endswith('_strict') else 'full', self.out / 'attribution' / name / level)
            self.compare(source, actual)
        for version, filename in [('v1', 'bsee_gold.yaml'), ('v2', 'bsee_gold_v2.yaml')]:
            cfg = well_gold.load_config(ROOT / 'configs/experiments' / filename)
            if not all(v == 'OK' for v in well_gold.verify(cfg).values()):
                raise AssertionError('Gold verification failed')
            result = well_gold.agreement(cfg, self.out / 'agreement' / version,
                                         ROOT / 'data/evaluation/bsee_text' / version / 'rules')
            self.compare(f'results/bsee_gold/{version}/agreement/agreement.json', result)
            facts = [WellFact.model_validate(x) for x in rows(cfg['root'] / 'adjudicated.jsonl') if x['record'] == 'fact']
            counts = dict(Counter(partition(x) for x in facts)); counts['Total'] = len(facts)
            self.compare(f'results/bsee_gold/{version}/annotation_counts.json', {'partitions': counts}, prefix='/partitions/')
            if version == 'v2':
                annotation_rows = rows(cfg['root']/'adjudicated.jsonl')
                split = read(cfg['root']/'split.json')
                dev = [x for x in facts if x.chunk_id.rsplit('#',1)[0] in split['dev'] and partition(x)=='G+']
                packet_items = {x['item_id']:x for path in (cfg['root']/'adjudication').glob('packet_*.jsonl') for x in rows(path) if 'item_id' in x}
                role_key = read(cfg['root']/'adjudication/key.json')
                choices, decisions = defaultdict(Counter), defaultdict(Counter)
                for path in (cfg['root']/'adjudication').glob('decisions_*.jsonl'):
                    for decision in rows(path):
                        item=packet_items[decision['item_id']];kind=item['kind'];choice=decision['decision']
                        decisions[kind][choice]+=1
                        sides=['A','B'] if choice in ('keep','accept_both') else [choice[-1]] if choice in ('accept_A','accept_B') else []
                        for side in sides:choices[kind][role_key[item['chunk_id']][side]]+=1
                        if not sides:choices[kind][choice]+=1
                actual={'chunk_records':sum(x['record']=='chunk' for x in annotation_rows), 'merged_fact_records':len(facts),
                        'dev':{'documents':len(split['dev']),'readable_chunks':result['scopes']['dev']['n']-result['scopes']['dev']['n_unreadable'],
                               'G+':len(dev),'by_relation':dict(Counter(x.relation for x in dev)), 'by_kind':dict(Counter(x.object['kind'] for x in dev))},
                        'agreement':{'n_unreadable':result['n_unreadable'],'keep_time_differs':result['keep_time_differs'],
                                     'IAA':{scope:{level:values['iaa'][level]['f1'] for level in ('L1','L2','L3')} for scope,values in result['scopes'].items()}},
                        'adjudication_decision_counts_by_kind':dict(decisions),'adjudication_choices_by_family':dict(choices),'partitions':counts,
                        'split_repeat_byte_equal':read(ROOT/'data/benchmarks/bsee_text/v2/selection.json')['dev']==split['dev']}
                self.compare('results/bsee_gold/v2/annotation_counts.json',actual)

        norm = qa.normalizer()
        for source in self.sources:
            if not source.endswith('/qa.json'):
                continue
            old = read(ROOT / source)
            answers = rows(self.reference(source).with_name('answers.jsonl'))
            question_path = ROOT / 'data/benchmarks/2wiki/questions_10.json'
            if not question_path.exists():
                question_path = ROOT / old['config']['questions']
            questions = {x['_id']: x for x in qa.load_questions(question_path, old['config']['limit'])}
            actual = copy.deepcopy(old)
            byrow = {}
            for i, row in enumerate(old['rows']):
                scores = []
                for answer in answers:
                    if answer['row'] != row['row']: continue
                    question = questions[answer['qid']]
                    assert answer['gold'] == question['answer']
                    scores.append({**answer, 'em': qa.exact_match(question['answer'], answer['prediction'], norm),
                        'f1': qa.token_f1(question['answer'], answer['prediction'], norm),
                        **{f'recall@{k}': qa.recall_at({f[0] for f in question['supporting_facts']}, answer['retrieved'], k) for k in old['recall_k']}})
                assert len(scores) == old['n_questions']
                byrow[row['row']] = scores
                result = actual['rows'][i]
                for key in ['em', 'f1', *[f'recall@{k}' for k in old['recall_k']]]:
                    result[key] = sum(s[key] for s in scores) / len(scores)
                result.update(no_context=sum(s['skipped'] for s in scores),
                              seeded=sum(bool(s['seeds']) for s in scores) if row['mode'] != 'text' else None,
                              mean_passages=sum(len(s['retrieved']) for s in scores)/len(scores),
                              mean_facts=sum(len(s['facts']) for s in scores)/len(scores))
                result['by_type'] = {t: {'n':len(group), **{k:sum(s[k] for s in group)/len(group) for k in ('em','f1',f'recall@{old["config"]["k"]}')}}
                                     for t in row['by_type'] for group in [[s for s in scores if s['type']==t]]}
            for pair in actual['pairwise']:
                diffs=[a['f1']-b['f1'] for a,b in zip(byrow[pair['row']],byrow[pair['vs']])]
                pair.update(wins=sum(d>0 for d in diffs),ties=sum(d==0 for d in diffs),losses=sum(d<0 for d in diffs))
            self.compare(source,actual,prefix='/rows/')
            self.compare(source,actual,prefix='/pairwise/')
        for source in self.sources:
            if source.endswith('/analysis.json'):
                ground = 'window' if '/window_' in source else 'sentence'
                actual = analysis.analyze(ROOT / f'runs/reference/ablation_{ground}_grounding',
                    [ROOT/'runs/reference/twowiki10_qa_intermediate_graphs'] if ground=='sentence' else [])
                self.compare(source,actual)
        mine = 'results/upstream/kggen/mine_3/summary.json'
        result = copy.deepcopy(read(ROOT/mine))
        for essay in result['essays']:
            identity = essay['id']
            graph = read(ROOT/f'results/upstream/kggen/mine_3/kg_{identity}.json')
            decisions = read(ROOT/f'results/upstream/kggen/mine_3/results_{identity}.json')[:-1]
            essay.update(entities=len(graph['entities']),relations=len(graph['relations']),correct=sum(x['evaluation'] for x in decisions),queries=len(decisions))
        result['correct']=sum(x['correct'] for x in result['essays']);result['queries']=sum(x['queries'] for x in result['essays'])
        result['overall_accuracy']=round(result['correct']/result['queries'],4)
        self.compare(mine,result,prefix='/essays/')
        for prefix in ('/correct','/queries','/overall_accuracy'):self.compare(mine,result,prefix=prefix)
        sys.path.insert(0,str(ROOT/'scripts/upstream'))
        from run_kggen_showcase import score as showcase_score
        upstream='results/upstream/kggen/showcase/summary.json'
        result=copy.deepcopy(read(ROOT/upstream))
        show=ROOT/'data/benchmarks/showcase'
        aliases={a.lower():e['canonical'].lower() for e in rows(show/'gold_entities.jsonl') for a in [e['canonical'],*e['aliases']]}
        merged=read(ROOT/'results/upstream/kggen/showcase/kg_merged.json')
        result['score']=showcase_score(sorted(merged['relations']),rows(show/'gold_triples.jsonl'),aliases)
        for name,doc in result['docs'].items():
            graph=read(ROOT/f'results/upstream/kggen/showcase/kg_{name}.json')
            doc.update(entities=len(graph['entities']),relations=len(graph['relations']))
        self.compare(upstream,result,prefix='/score/')
        self.compare(upstream,result,prefix='/docs/')
        upstream=ROOT/'results/upstream/edc/webnlg_10'
        work=self.out/'upstream_webnlg';work.mkdir()
        actual=evaluate.run_webnlg_evaluator(upstream/'iter0/canon_kg.txt',upstream/'reference.txt',work,
                                           ROOT/'.venvs/edc/Scripts/python.exe',int(self.remaining()))
        recorded=evaluate.parse_eval_txt((upstream/'eval.txt').read_text(encoding='utf-8'))
        assert actual==recorded
        self.report['upstream_webnlg_score']='PASS'
        for grounding in ('sentence','window'):
            source=f'results/ablation_{grounding}_grounding/ablation.json'
            old=read(ROOT/source);actual=copy.deepcopy(old)
            root=ROOT/f'runs/reference/ablation_{grounding}_grounding'
            seen={}
            for i,row in enumerate(old['rows']):
                new=ablation.level_row(row['run'],row['level'],root/row['run']/row['level'],row['exit_code'],seen.setdefault(row['run'],set()),{})
                actual['rows'][i]={**row,**{k:v for k,v in new.items() if k in row and k!='modules'}}
            self.compare(source,actual,prefix='/rows/')
        selection='results/bsee_text/dev_v2_selection.json'
        actual=copy.deepcopy(read(ROOT/selection))
        for index,name in enumerate(('guided','guided_windows','guided_groups','guided_recall')):
            scored=self.results[f'results/bsee_text/dev_v2_{name}/evaluation/A4/scores.json']
            row=actual['rows'][index]
            row['L']={level:scored['exports']['full']['ai_gold'][level] for level in ('L1','L2','L3')}
            row['strict']={level:scored['exports']['strict']['ai_gold'][level] for level in ('L1','L2','L3')}
            row['IAA']={level:scored['exports']['full']['ai_gold']['iaa_reference'][level]['f1'] for level in ('L1','L2','L3')}
        actual['best_L2_f1']=max(row['L']['L2']['f1'] for row in actual['rows'])
        for prefix in ('/best_L2_f1',*[f'/rows/{i}/{key}/' for i in range(4) for key in ('L','strict','IAA')]):
            self.compare(selection,actual,prefix=prefix)
        for bundle in ('core','extended'):
            result=read(ROOT/f'results/bsee_tables/{bundle}/domain_stats.json')
            assert sum(result['nodes_by_type'].values())==result['counts']['nodes']
            assert sum(result['edges_by_type'].values())==result['counts']['edges']
            assert result['llm_calls']==0
        self.report['table_graph_aggregate_conservation']='PASS'
        self.remaining()

    def command(self, args, output):
        with output.open('w',encoding='utf-8') as log:
            subprocess.run([sys.executable,'-B',*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                           timeout=self.remaining(),check=True)

    def full(self):
        from helpers import assert_graph_equivalent
        import unittest
        groups=defaultdict(list)
        for build in self.spec['builds']:
            cfg=copy.deepcopy(build['config'])
            cfg['llm']['cache_path']=(self.out/'no_cache.jsonl').relative_to(ROOT).as_posix()
            groups[json.dumps(cfg,sort_keys=True)].append(build)
        def build_group(item):
            index,(raw,group)=item
            folder=self.out/'builds'/str(index);folder.mkdir(parents=True)
            path=folder/'config.yaml';path.write_text(yaml.safe_dump(json.loads(raw),sort_keys=False),encoding='utf-8')
            self.command(['-m','kgbuilder','build','--config',str(path),'--out',str(folder/'output'),'--mock'],folder/'build.log')
            out=folder/'output';stats=read(out/'metrics.json')
            assert stats['llm']['cache_misses']==0
            assert not any(x.get('miss') for x in rows(out/'llm_calls.jsonl'))
            test=unittest.TestCase()
            for entry in group:
                assert_graph_equivalent(test,out/'graph.json',ROOT/entry['graph'])
                if entry['strict_graph']:assert_graph_equivalent(test,out/'graph_strict.json',ROOT/entry['strict_graph'])
                else:assert not (out/'graph_strict.json').exists()
            return [{'configuration':entry['name'],'cache_misses':0,'output':out.relative_to(ROOT).as_posix()} for entry in group]
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for result in pool.map(build_group,enumerate(groups.items())):
                self.report['builds'].extend(result)
                print(f'Replay {len(self.report["builds"])}/{len(self.spec["builds"])} configurations; zero misses',flush=True)
        assert not (self.out/'no_cache.jsonl').exists()
        # Additional groups exercise recorded upstream and schema/QA requests.
        groups=['integration.test_upstream_shims','integration.test_extract_replay','integration.test_edc_worker',
                'e2e.test_extract_backend','e2e.test_qa_replay','e2e.test_schema_induction_ablation_replay','e2e.test_window_grounding_replay']
        def extra(group):
            log=self.out/(group+'.log')
            self.command(['-m','unittest',group,'-v'],log)
            output=log.read_text(encoding='utf-8')
            if 'skipped=' in output or '\nOK\n' not in output:
                raise AssertionError(f'Additional replay group did not pass without skips: {group}')
            return group
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(extra,groups))
        self.command(['scripts/replay_mine.py','--out',str(self.out/'mine')],self.out/'mine.log')
        assert read(self.out/'mine/report.json')['gateway']['cache_misses']==0
        groups.append('mine extraction and 45 recorded judges')
        self.report['additional_groups']=groups


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--quick',action='store_true');modes.add_argument('--full',action='store_true')
    parser.add_argument('--workers',type=int,choices=range(1,5),default=2)
    args=parser.parse_args()
    os.chdir(ROOT)
    task=Reproduction(args.full,args.workers)
    if os.name=='nt':ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        prepare(ROOT)
        task.integrity()
        if args.full:task.full()
        task.quick()
        task.report['status']='PASS'
    except BaseException as exc:
        task.report.update(status='FAIL',error=str(exc))
        raise
    finally:
        elapsed=time.monotonic()-task.start
        task.warn_if_over_budget(elapsed)
        task.report['seconds']=elapsed
        task.report['soft_budget_exceeded']=elapsed > task.soft_budget
        (task.out/'report.json').write_text(json.dumps(task.report,indent=2)+'\n',encoding='utf-8')
        print(f'Wall time: {elapsed:.3f} s; planning budget: {task.soft_budget} s; '
              f'hard safety limit: {task.hard_limit} s',flush=True)
        print(f'Report: {task.out.relative_to(ROOT) / "report.json"}',flush=True)
        if os.name=='nt':ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__=='__main__':main()
