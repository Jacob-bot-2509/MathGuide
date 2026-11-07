#!/usr/bin/env python3
"""Curated, disclosed problem-number sampling from public OER chapters.
Needs requests, bs4 and pdftotext (poppler-utils). No solutions inferred from examples.
"""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
import requests
from bs4 import BeautifulSoup
BASE='https://people.uncw.edu/hermanr/pde2/PDE2notes/'
SOURCES={
 'fourier-transform':dict(url=BASE+'Transforms.pdf',ids=[6,7,8,9,10,30,31,34],expected_pool=34),
 'green-function':dict(url=BASE+'Greens.pdf',ids=[1,2,3,4,5,9,10,13,14,15,16,24],expected_pool=26),
 'cauchy-riemann':dict(url=BASE+'Complex.pdf',ids=[11,14,27],expected_pool=30),
 'parseval':dict(url='https://people.uncw.edu/hermanr/pde1/PDE1notes/Fourier.pdf',ids=[3,4,5],expected_pool=None),
}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cache',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();cache=Path(a.cache);cache.mkdir(parents=True,exist_ok=True);result={}
 for topic,v in SOURCES.items():
  p=cache/(hashlib.sha256(v['url'].encode()).hexdigest()+'.pdf');txt=p.with_suffix('.txt')
  if not p.exists():
   r=requests.get(v['url'],timeout=60);r.raise_for_status();p.write_bytes(r.content)
  assert p.read_bytes().startswith(b'%PDF'),v['url']
  subprocess.run(['pdftotext','-layout',str(p),str(txt)],check=True)
  raw=txt.read_text();start=raw.rfind('Problems');assert start>=0;body=raw[start:]
  markers=list(re.finditer(r'^\s*(\d+)\.\s+(?=[A-Z])',body,re.M));blocks={int(m.group(1)):body[m.end():markers[i+1].start() if i+1<len(markers) else len(body)] for i,m in enumerate(markers)}
  if v['expected_pool']:assert len(blocks)==v['expected_pool'],(topic,len(blocks))
  items=[]
  for num in v['ids']:
   st=blocks[num];items.append(dict(id=num,url=v['url'],statement=True,answer=False,process=False,triple=False,figure_reference=bool(re.search(r'Figure|[Ss]ketch|[Pp]lot',st)),sha256=hashlib.sha256(st.encode()).hexdigest()))
  result[topic]=dict(source=v['url'],chapter_problem_blocks=len(blocks),curated_pool=len(items),n=len(items),counts=dict(statement=len(items),answer=0,process=0,triple=0,figure_reference=sum(x['figure_reference'] for x in items)),items=items)
 # Cline: chapter page uses numbered paragraphs, NOT <section class=box-exercise>.
 url='https://phys.libretexts.org/Bookshelves/Classical_Mechanics/Variational_Principles_in_Classical_Mechanics_(Cline)/05%3A_Calculus_of_Variations/5.E%3A_Calculus_of_Variations_(Exercises)'
 p=cache/'cline-exercises.html'
 if not p.exists():
  r=requests.get(url,timeout=45);r.raise_for_status();r.encoding='utf-8';p.write_text(r.text)
 s=BeautifulSoup(p.read_text(),'html.parser');content=s.select_one('.mt-content-container');assert content
 # Each leading numbered paragraph is a top-level exercise, nested lists are subparts.
 starts=[x for x in content.select('p') if re.match(r'^\d+\.\s',x.get_text(' ',strip=True))]
 nums=[int(re.match(r'^(\d+)\.',x.get_text(' ',strip=True)).group(1)) for x in starts];assert nums==list(range(1,12)),nums
 result['variational']=dict(source=url,curated_pool=11,n=11,counts=dict(statement=11,answer=0,process=0,triple=0),figure_note='Problem 8 has an actual figure; other drawing requirements not image-counted',items=[dict(id=n,url=url,sha256=hashlib.sha256(x.get_text(' ',strip=True).encode()).hexdigest()) for n,x in zip(nums,starts)])
 Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2))
 for k,v in result.items():print(k,v.get('chapter_problem_blocks'),v['curated_pool'],v['n'],v['counts'])
if __name__=='__main__':main()
