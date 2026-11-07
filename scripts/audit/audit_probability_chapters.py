#!/usr/bin/env python3
"""Public GFDL book exercise labels; no presumed access to solutions manuals."""
import argparse,hashlib,json,random,re
from pathlib import Path
import requests
ap=argparse.ArgumentParser();ap.add_argument('--cache',required=True);ap.add_argument('--out',required=True);args=ap.parse_args();cache=Path(args.cache);cache.mkdir(parents=True,exist_ok=True);out={}
for topic,c in [('generating-function',10),('markov-chain',11)]:
 url=f'https://math.dartmouth.edu/~prob/prob/ch{c}.tex';p=cache/f'prob-ch{c}.tex'
 if not p.exists():
  r=requests.get(url,timeout=45);r.raise_for_status();p.write_text(r.text)
 raw=p.read_text();items=[]
 for m in re.finditer(r'\\i(?:star)?\s*\\label\{exer\s+('+str(c)+r'\.\d+\.\d+)\}',raw):
  next_label=re.search(r'\\i(?:star)?\s*\\label',raw[m.end():]);end=m.end()+next_label.start() if next_label else len(raw)
  end_env=raw.find('\\end{LJSItem}',m.end())
  if end_env>=0:end=min(end,end_env)
  chunk=raw[m.end():end];items.append(dict(id=m.group(1),url=url,offset=m.start(),sha256=hashlib.sha256(chunk.encode()).hexdigest(),statement=True,answer=False,process=False,triple=False,figure_reference=bool(re.search(r'\\(?:epsfig|includegraphics)|Figure|figure|\\ref\{fig',chunk))))
 # Book/source has no matched answer manual; zero here means NONE PAIRED, not no manual exists.
 sample=random.Random('20261107'+topic).sample(items,min(50,len(items)))
 out[topic]=dict(pool=len(items),n=len(sample),counts=dict(statement=len(sample),answer=0,process=0,triple=0,figure_reference=sum(x['figure_reference'] for x in sample)),items=sample)
Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2))
for k,v in out.items():print(k,v['pool'],v['n'],v['counts'])
