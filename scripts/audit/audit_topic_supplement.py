#!/usr/bin/env python3
"""Supplement OER page samples. Results are structural/heuristic, NOT correctness review."""
import argparse,concurrent.futures,hashlib,json,random,re
from pathlib import Path
import requests
from bs4 import BeautifulSoup
N='https://math.gordon.edu/ntic/ntic/'
C='https://activecalculus.org/single/'
K='https://math.libretexts.org/Bookshelves/Linear_Algebra/A_First_Course_in_Linear_Algebra_(Kuttler)/'
GROUPS={
 'lebl-implicit':dict(topic='implicit-function',urls=['https://www.jirka.org/ra/html/sec_svinvfuncthm.html']),
 'lebl-norm':dict(topic='norm',urls=['https://www.jirka.org/ra/html/sec_normsmatsdets.html']),

 'active-taylor':dict(topic='taylor',urls=[C+'sec-8-2-taylor-poly.html',C+'sec-8-4-taylor-series.html',C+'sec-8-5-finding-using-taylor-series.html']),
 'ntic-pnt':dict(topic='prime-number-theorem',urls=[N+'exercises-prime-pi.html']),
 'ntic-zeta':dict(topic='riemann-zeta',urls=[N+'exercises-infinite-sums.html',N+'exercises-riemann-hypothesis.html']),
 'ntic-analytic':dict(topic='analytic-number-theory',urls=[N+'exercises-prime-pi.html',N+'exercises-infinite-sums.html',N+'exercises-riemann-hypothesis.html']),
 'kuttler-vector':dict(topic='vector-space',urls=[K+'09%3A_Vector_Spaces/9.E%3A_Exercises']),
 'kuttler-spectral':dict(topic='orthogonal-transform',required=r'orthogonal matrix',urls=[K+'07%3A_Spectral_Theory/7.E%3A_Exercises']),
 'active-jacobian':dict(topic='jacobian',urls=['https://activecalculus.org/multi/S-11-9-Change-of-Variable.html']),
 'active-green':dict(topic='green-theorem',urls=['https://activecalculus.org/multi/S_Vector_GreensTheorem.html']),
 'active-divergence':dict(topic='divergence-theorem',urls=['https://activecalculus.org/multi/S_Vector_DivThm.html']),
 'active-stokes':dict(topic='stokes-theorem',urls=['https://activecalculus.org/multi/S_Vector_StokesThm.html']),
 'active-line-surface':dict(topic='line-surface-integral',urls=['https://activecalculus.org/multi/S_Vector_ParamLineIntegrals.html','https://activecalculus.org/multi/S_Vector_ScalarSurfaceIntegral.html']),
 'active-quadric':dict(topic='quadric-surface',urls=['https://activecalculus.org/multi/S-Precalc-CommonGraphs.html']),

}
def text(x):
 if not x:return ''
 s=BeautifulSoup(str(x),'html.parser')
 for y in s.select('.autopermalink,.heading,summary,.box-legend'):y.decompose()
 return s.get_text(' ',strip=True)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cache',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();cache=Path(a.cache);cache.mkdir(parents=True,exist_ok=True)
 def get(url):
  p=cache/(hashlib.sha256(url.encode()).hexdigest()+'.html')
  if p.exists():raw=p.read_text()
  else:
   r=requests.get(url,timeout=60);r.raise_for_status();r.encoding='utf-8';raw=r.text;p.write_text(raw)
  s=BeautifulSoup(raw,'html.parser');rows=[]
  for i,x in enumerate(s.select('article.exercise,section.box-exercise')):
   ans=x.select_one('details.answer,.answer.knowl__content');sol=x.select_one('details.solution,.solution.knowl__content');dl=x.select_one('dl')
   if not ans and dl and dl.select_one('dt') and dl.select_one('dt').get_text(strip=True).lower() in ['answer','solution']:ans=dl.select_one('dd')
   an=text(ans);so=text(sol);work=so or an
   proc=len(work)>=200 or len(work)>=80 and len(re.findall(r'=|\\le|\\Rightarrow|→|thus',work))>=2
   st=BeautifulSoup(str(x),'html.parser')
   for y in st.select('dl,.solutions,details'):y.decompose()
   statement=text(st);anchor=x.get('id') or (x.select_one('span[id]')['id'] if x.select_one('span[id]') else str(i+1))
   rows.append(dict(id=anchor,url=url+'#'+anchor,statement=len(statement)>=20,answer=bool(an) or bool(re.search(r'\\boxed\s*\{|Answer\s*:',so)),process_candidate=proc,triple_candidate=len(statement)>=20 and (bool(an) or bool(re.search(r'\\boxed\s*\{|Answer\s*:',so))) and proc,figure=bool(x.select('img,svg,figure,iframe,object')),answer_chars=len(an),solution_chars=len(so),orthogonal_matrix=bool(re.search(r'orthogonal matrix',statement,re.I)),sha256=hashlib.sha256(statement.encode()).hexdigest()))
  return url,rows
 pages={};errors=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
  futures={ex.submit(get,u):u for u in set(sum([v['urls'] for v in GROUPS.values()],[]))}
  for f in concurrent.futures.as_completed(futures):
   try:u,rows=f.result();pages[u]=rows
   except Exception as e:errors.append(dict(url=futures[f],error=str(e)))
 result=dict(groups={},pages=pages,errors=errors)
 for key,v in GROUPS.items():
  pool=sum([pages.get(u,[]) for u in v['urls']],[])
  if v.get('required'):pool=[x for x in pool if x['orthogonal_matrix']]
  sample=random.Random('20261107'+key).sample(pool,min(50,len(pool)));result['groups'][key]=dict(**v,pool=len(pool),n=len(sample),counts={k:sum(x[k] for x in sample) for k in ['statement','answer','process_candidate','triple_candidate','figure']},items=sample)
 Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2));print('errors',errors)
 for k,v in result['groups'].items():print(k,v['pool'],v['n'],v['counts'])
if __name__=='__main__':main()
