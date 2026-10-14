"""Reproducible CPU text-extraction benchmark; no production integration."""
import argparse,json,os,sys,time,resource,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from shopping_bot.store import parse_items
from shopping_bot.categories import infer_category
p=argparse.ArgumentParser();p.add_argument('engine',choices=['rules','gliner','gliner2']);a=p.parse_args()
cases=json.loads(Path(__file__).with_name('cases.json').read_text())
start=time.perf_counter()
if a.engine!='rules':
 import torch
 torch.set_num_threads(2)
 if a.engine=='gliner':
  from gliner import GLiNER
  model=GLiNER.from_pretrained('urchade/gliner_multi-v2.1').to('cpu').eval()
 else:
  from gliner2 import AutoExtractor
  model=AutoExtractor.from_pretrained('fastino/gliner2-multi-v1').to('cpu').eval()
load=time.perf_counter()-start

def extract(text):
 if a.engine=='rules':return [x[0] for x in parse_items(text)]
 if a.engine=='gliner':return [x['text'] for x in model.predict_entities(text,['shopping product'],threshold=0.5)]
 result=model.extract_entities(text,['shopping product'],threshold=0.5)
 return result['entities'].get('shopping product',[])

def tokens(s):return set(re.findall(r'\w+',s.casefold()))
rows=[]
for c in cases:
 t=time.perf_counter();out=extract(c['text']);elapsed=time.perf_counter()-t
 out=[x if isinstance(x,str) else x['text'] for x in out]
 expected=c['items'];pairs=[]
 for i,x in enumerate(out):
  for j,(y,cat) in enumerate(expected):
   tx,ty=tokens(x),tokens(y);score=len(tx&ty)/max(1,len(tx|ty))
   if score>=.5:pairs.append((score,i,j))
 used_i=set();used_j=set();matches=[]
 for score,i,j in sorted(pairs,reverse=True):
  if i not in used_i and j not in used_j:
   used_i.add(i);used_j.add(j);matches.append((i,j))
 rows.append(dict(**c,predicted=out,categories=[infer_category(x) for x in out],seconds=elapsed,tp=len(matches),fp=len(out)-len(matches),fn=len(expected)-len(matches),category_correct=sum(infer_category(out[i])==expected[j][1] for i,j in matches),strict_correct=sorted(x.casefold().strip(' .!') for x in out)==sorted(x[0].casefold().strip(' .!') for x in expected)))
r=dict(engine=a.engine,load_seconds=load,peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024**2,rows=rows)
path=Path(__file__).with_name(a.engine+'.json');path.write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in r.items() if k!='rows'}),flush=True)
