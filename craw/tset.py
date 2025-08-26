import json, sys
p=r'D:\port\craw\out_clean.jsonl'
tot=sec=lst=0;s=[]
for L in open(p,encoding='utf-8'):
  if not L.strip(): continue
  r=json.loads(L); secobj=(r.get('sections') or {}).get('등장인물') or {}
  li=secobj.get('list') or []
  if '등장인물' in (r.get('sections') or {}): sec+=1
  if li:
    lst+=1
    if len(s)<5: s.append((r.get('seed'), len(li), [c.get('name') for c in li[:3]]))
  tot+=1
print('total:',tot,'with_char_section:',sec,'with_list:',lst,f'({(lst/max(1,tot))*100:.2f}%)')
print('samples:',s)