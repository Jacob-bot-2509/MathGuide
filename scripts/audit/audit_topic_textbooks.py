#!/usr/bin/env python3
"""Count PreTeXt exercise blocks, not subparts or worked examples.
Topic map is a disclosed SECTION proxy, not a semantic classifier. Actual solution
blocks and answers measured separately; an answer is never silently a solution.
"""
import argparse, concurrent.futures, hashlib, json, random,re
from pathlib import Path
import requests
from bs4 import BeautifulSoup
A='https://opentext.uleth.ca/apex-calculus/'
D='https://www.jirka.org/diffyqs/html/'
SECTIONS={
 'taylor':[A+'sec_taylor_poly.html',A+'sec_taylor_series.html'],
 'power-series':[A+'sec_power_series.html'],
 'green-theorem':[A+'sec_greensthm.html'],
 'divergence-theorem':[A+'sec_stokes_divergence.html'],
 'stokes-theorem':[A+'sec_stokes_divergence.html'],
 'line-surface-integral':[A+'sec_line_int_intro.html',A+'sec_surface_integral.html'],
 'quadric-surface':[A+'sec_space_coord.html'],
 'implicit-function':[A+'sec_multi_chain.html'],
 'vector-space':[D+'subspaces_section.html'],
 'inner-product':[D+'innerproduct_section.html'],
 'norm':[D+'innerproduct_section.html'],
 'fourier-series':[D+'ts_section.html',D+'moreonfourier_section.html'],
 'laplace-transform':[D+'laplace_section.html',D+'transformsofders_section.html'],
 'convolution':[D+'convolution_section.html'],
 'matrix-exponential':[D+'sec_matexp.html'],
 'ode-system':[D+'sec_introtosys.html',D+'linsystems_section.html'],
}
def clean(e):
 c=BeautifulSoup(str(e),'html.parser')
 for x in c.select('.autopermalink,summary,.heading'):x.decompose()
 return c.get_text(' ',strip=True)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cache',default='/tmp/mathguide-textbooks');ap.add_argument('--out',required=True);a=ap.parse_args();cache=Path(a.cache);cache.mkdir(parents=True,exist_ok=True)
 def get(u):
  p=cache/(hashlib.sha256(u.encode()).hexdigest()+'.html')
  try:
   if p.exists():text=p.read_text()
   else:
    r=requests.get(u,timeout=60);r.raise_for_status();r.encoding='utf-8';text=r.text;p.write_text(text)
   soup=BeautifulSoup(text,'html.parser');items=[]
   for ex in soup.select('article.exercise'):
    ans=ex.select_one('details.answer');sol=ex.select_one('details.solution')
    # Some editions put solution/answer bodies in non-details wrappers.
    if not sol:sol=ex.select_one('.solution.knowl__content')
    if not ans:ans=ex.select_one('.answer.knowl__content')
    st=BeautifulSoup(str(ex),'html.parser')
    for x in st.select('.solutions,.autopermalink,.heading'):x.decompose()
    statement=clean(st);s=clean(sol) if sol else '';at=clean(ans) if ans else ''
    # Phase0 heuristic; answers may contain derivations, so consider both blocks.
    work=s or at
    proc=bool(work) and (len(work)>=200 or len(work)>=80 and len(re.findall(r'=|\\le|\\Rightarrow|→|thus',work))>=2)
    has_ans=bool(at) or bool(re.search(r'\\boxed\s*\{|Answer\s*:',s,re.I))
    items.append(dict(id=ex.get('id'),url=u+'#'+ex.get('id',''),number=ex.select_one('.codenumber').get_text(strip=True) if ex.select_one('.codenumber') else '',statement=len(statement)>=20,answer=has_ans,solution_block=bool(s),process=proc,triple=len(statement)>=20 and has_ans and proc,figure=bool(ex.select('img,svg,figure,iframe,object')),sha256=hashlib.sha256(statement.encode()).hexdigest(),answer_chars=len(at),solution_chars=len(s)))
   return u,items,None
  except Exception as e:return u,[],str(e)
 # APEX publishes answers in a separate public appendix: pair by exact backlink.
 appendix_url=A+'selected-answers.html'
 appendix_path=cache/'apex-selected-answers.html'
 if appendix_path.exists(): appendix=appendix_path.read_text()
 else:
  r=requests.get(appendix_url,timeout=60);r.raise_for_status();r.encoding='utf-8';appendix=r.text;appendix_path.write_text(appendix)
 answer_map={}
 for block in BeautifulSoup(appendix,'html.parser').select('article.exercise-like'):
  link=block.select_one('.heading a[href]')
  if link: answer_map[link['href']]=block
 pages={};errors=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
  for u,items,err in ex.map(get,sorted(set(sum(SECTIONS.values(),[])))):
   if u.startswith(A):
    for item in items:
     key=u[len(A):]+'#'+item['id'];block=answer_map.get(key)
     if block:
      ans=block.select_one('details.answer');sol=block.select_one('details.solution')
      item['answer']=bool(ans and clean(ans));item['answer_chars']=len(clean(ans)) if ans else 0
      item['solution_block']=bool(sol);item['solution_chars']=len(clean(sol)) if sol else 0
      work=clean(sol) if sol else (clean(ans) if ans else '')
      item['process']=len(work)>=200 or len(work)>=80 and len(re.findall(r'=|\\le|\\Rightarrow|→|thus',work))>=2
      item['triple']=item['statement'] and item['answer'] and item['process']
      item['answer_url']=appendix_url
      item['figure']=item['figure'] or bool(block.select('img,svg,figure,iframe,object'))
   pages[u]=items
   if err:errors.append(dict(url=u,error=err))
 result=dict(note='SECTION-PROXY pools; combined sections overinclude. No semantic coverage claim.',errors=errors,pages=pages,topics={})
 for t,urls in SECTIONS.items():
  pool=sum([pages[u] for u in urls],[]);sample=random.Random('20261107'+t).sample(pool,min(50,len(pool)))
  result['topics'][t]=dict(urls=urls,pool_exercise_blocks=len(pool),n=len(sample),counts={k:sum(x[k] for x in sample) for k in ['statement','answer','solution_block','process','triple','figure']},items=sample)
 Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2));print('ERRORS',errors)
 for t,x in result['topics'].items():print(t,x['pool_exercise_blocks'],x['n'],x['counts'])
if __name__=='__main__':main()
