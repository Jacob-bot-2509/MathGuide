#!/usr/bin/env python3
"""Read-only, bounded public HF audit; no imports to MathGuide. Python3 + requests.
Raw pages cache locally; report contains only ids/hashes/metrics, no source text.
"""
import argparse, concurrent.futures, hashlib, json, random, re
from pathlib import Path
import requests
PATTERNS = {
 'orthogonal-transform':r'orthogonal (?:transformation|matrix|matrices)|orthonormal transformation',
 'vector-space':r'vector space|subspace|linear independence|linearly independent|basis for',
 'inner-product':r'inner product|gram.schmidt|orthonormal basis',
 'fourier-series':r'fourier series|fourier coefficient',
 'fourier-transform':r'fourier transform', 'laplace-transform':r'laplace transform',
 'taylor':r'taylor (?:series|polynomial|expansion)|maclaurin',
 'power-series':r'power series|radius of convergence',
 'cauchy-riemann':r'cauchy.riemann', 'green-theorem':r"green.?s? theorem",
 'divergence-theorem':r'divergence theorem|gauss.?s? theorem', 'stokes-theorem':r'stokes.?s? theorem',
 'line-surface-integral':r'line integral|surface integral', 'jacobian':r'jacobian',
 'implicit-function':r'implicit function theorem', 'quadric-surface':r'quadric surface|ellipsoid|hyperboloid|paraboloid',
 'norm':r'\bnorm\b|\bnorms\b', 'convolution':r'convolution|convolve',
 'generating-function':r'generating function', 'markov-chain':r'markov chain|transition matrix',
 'matrix-exponential':r'matrix exponential|exponential of (?:a |the )?matrix',
 'ode-system':r'system of differential equations|system of (?:linear )?ODEs',
 'prime-number-theorem':r'prime number theorem', 'riemann-zeta':r'riemann zeta|zeta function|\\zeta',
 'analytic-number-theory':r'analytic number theory|dirichlet (?:series|L.function)|prime number theorem|riemann zeta',
 'variational':r'calculus of variations|euler.lagrange|variational',
 'green-function':r"green.?s? function", 'parseval':r'parseval'
}
BAN=re.compile(r'考研|全国大学生数学竞赛|丘(?:成桐)?赛|阿里(?:巴巴)?(?:赛|数学)|alibaba|yau.*competition|chinese.*(?:graduate|postgraduate).*exam|chinese.*college.*math.*competition',re.I)
MARKS=re.compile(r'=|\\le|\\Rightarrow|→|\\therefore|所以|因此|thus',re.I)
def metrics(row):
 p=row.get('problem','');s=row.get('solution','');a=str(row.get('answer','')).strip()
 strict=bool(a and a.lower() not in {'proof','notfound','none','null','no_answer','nan'})
 answer=strict or bool(re.search(r'\\boxed\s*\{|(?:Answer|答案)\s*[:：]',s,re.I))
 process=len(s)>=200 or len(s)>=80 and len(MARKS.findall(s))>=2
 statement=len(p.strip())>=20
 zh=len(re.findall(r'[\u4e00-\u9fff]',p+s));en=len(re.findall(r'[A-Za-z]+',p+s))
 return dict(statement=statement,answer_strict=strict,answer=answer,process=process,triple_strict=statement and strict and process,triple=statement and answer and process,chinese=zh/max(1,zh+en)>=.2,figure_marker=bool(re.search(r'<(?:img|svg)|!\[|\\includegraphics|\[asy\]',p+s,re.I)))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cache',default='/tmp/mathguide-topic-audit');ap.add_argument('--out',required=True);ap.add_argument('--seed',type=int,default=20261107);a=ap.parse_args();cache=Path(a.cache);cache.mkdir(parents=True,exist_ok=True)
 tasks=[]
 sizes=requests.get('https://datasets-server.huggingface.co/size',params={'dataset':'EleutherAI/hendrycks_math'},timeout=90);sizes.raise_for_status()
 for split in sizes.json()['size']['splits']:
  if split['split']=='test':
   for off in range(0,split['num_rows'],100):tasks.append(('MATH','EleutherAI/hendrycks_math',split['config'],'test',off))
 # Fixed windows spread over the full published 896k-row corpus; bounded, NOT a census.
 for off in range(0,900000,10000):tasks.append(('NuminaMath','project-numina/NuminaMath-1.5','default','train',off))
 def get(t):
  label,ds,cfg,sp,off=t;key=f'{label}-{cfg}-{sp}-{off}';p=cache/(key+'.json')
  try:
   if p.exists():data=json.loads(p.read_text())
   else:
    r=requests.get('https://datasets-server.huggingface.co/rows',params=dict(dataset=ds,config=cfg,split=sp,offset=off,length=100),timeout=90);r.raise_for_status();data=r.json();p.write_text(json.dumps(data))
   return t,data,None
  except Exception as e:return t,None,str(e)
 pools={s:{t:[] for t in PATTERNS} for s in ['MATH','NuminaMath']};seen={s:0 for s in pools};errors=[];excluded={s:0 for s in pools};sources={}
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
  for task,d,err in ex.map(get,tasks):
   label,ds,cfg,sp,off=task
   if err:errors.append(dict(task=task,error=err));continue
   for item in d['rows']:
    row=item['row'];seen[label]+=1;src=row.get('source','');sources[src]=sources.get(src,0)+1
    if BAN.search(row.get('problem','')+' '+str(src)):excluded[label]+=1;continue
    # cn_contest broad exclusion avoids importing banned event originals without provenance.
    if src=='cn_contest':excluded[label]+=1;continue
    for topic,pat in PATTERNS.items():
     if re.search(pat,row.get('problem',''),re.I):
      m=metrics(row);m.update(id=f'{cfg}/{sp}/{item["row_idx"]}',sha256=hashlib.sha256(row.get('problem','').encode()).hexdigest(),source=src)
      pools[label][topic].append(m)
 result=dict(seed=a.seed,rows_scanned=seen,excluded=excluded,source_counts=sources,errors=errors,topics={})
 for t in PATTERNS:
  result['topics'][t]={}
  for label in pools:
   pool=sorted(pools[label][t],key=lambda m:m['id']);sample=random.Random(str(a.seed)+t+label).sample(pool,min(50,len(pool)))
   counts={k:sum(m[k] for m in sample) for k in ['statement','answer_strict','answer','process','triple_strict','triple','chinese','figure_marker']}
   result['topics'][t][label]=dict(pool_matches=len(pool),n=len(sample),counts=counts,items=sample)
 Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:result[k] for k in ['rows_scanned','excluded','source_counts','errors']},ensure_ascii=False));print('topic MATH(pool/n/triple) Numina(pool/n/triple)')
 for t,v in result['topics'].items():print(t,*[(s,v[s]['pool_matches'],v[s]['n'],v[s]['counts']['triple']) for s in v])
if __name__=='__main__':main()
