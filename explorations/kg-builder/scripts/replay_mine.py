"""Replay pinned MINE extraction and all 45 judges on shipped retrieval inputs."""
import argparse
import importlib.util
import json
from pathlib import Path
import dspy
from kg_gen import KGGen
from kg_gen.steps._3_deduplicate import DeduplicateMethod
from kgbuilder.core.project import PROJECT_ROOT as R
from kgbuilder.runtime.gateway import Gateway
from kgbuilder.runtime.onprem import load_env, guard_network, blocked_count

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
out=args.out.resolve()
if not out.is_relative_to(R/'runs'):raise ValueError('Output must stay under runs')
out.mkdir(parents=True,exist_ok=True)
load_env()
net=guard_network(out/'net.jsonl')
spec=importlib.util.spec_from_file_location('mine_replay', R/'third_party/kg-gen/experiments/MINE/_1_evaluation.py')
mine=importlib.util.module_from_spec(spec);spec.loader.exec_module(mine)
g=Gateway('http://127.0.0.1:9/v1',out/'llm_calls.jsonl',None,'readonly',[R/'data/fixtures/llm/mine3_kggen.jsonl'])
results=[]
try:
    url=g.start()
    model='lm_studio/qwen3.6-35b-a3b'
    judge=dspy.LM(model=model,api_base=url,api_key='lm-studio',temperature=0.0,max_tokens=2048,cache=False)
    dspy.configure(lm=judge)
    kggen=KGGen(model=model,api_base=url,api_key='lm-studio',temperature=0.0,max_tokens=2048,
                retrieval_model='sentence-transformers/all-MiniLM-L6-v2',disable_cache=True)
    essays=[json.loads(x) for x in (R/'data/benchmarks/mine/mine_5.jsonl').read_text(encoding='utf-8').splitlines()]
    reference=R/'results/upstream/kggen/mine_3'
    for essay in essays[:3]:
        identity=essay['id']
        graph=kggen.generate(essay['essay_content'],deduplication_method=DeduplicateMethod.SEMHASH)
        old=json.loads((reference/f'kg_{identity}.json').read_bytes())
        assert set(graph.entities)==set(old['entities']),('entities',identity)
        assert set(graph.relations)=={tuple(x) for x in old['relations']},('relations',identity)
        rows=json.loads((reference/f'results_{identity}.json').read_bytes())
        decisions=[]
        for row in rows[:-1]:
            actual=mine.gpt_evaluate_response(row['correct_answer'],row['retrieved_context'])
            assert actual==row['evaluation'],(identity,len(decisions),actual,row['evaluation'])
            decisions.append(actual)
        assert f'{sum(decisions)/len(decisions)*100:.2f}%'==rows[-1]['accuracy']
        results.append({'id':identity,'entities':len(graph.entities),'relations':len(graph.relations),
                        'correct':sum(decisions),'queries':len(decisions),'accuracy':rows[-1]['accuracy']})
        print(results[-1],flush=True)
    assert g.stats['cache_misses']==0 and g.fatal is None,g.stats
    assert blocked_count(net)==0
    report={'essays':results,'gateway':g.stats,'blocked_network':blocked_count(net),
            'retrieval':'Recorded retrieved_context values are unchanged inputs to the pinned upstream judge.'}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
finally:g.stop()
