import json
p = r'.\namu_anime_v3.with_subpages.jsonl'
tot = chars = hubs = 0
with open(p, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line: 
            continue
        tot += 1
        rec = json.loads(line)
        sp = rec.get('subpages') or {}
        bucket = sp.get('등장인물') or []
        for it in bucket:
            if it.get('is_character'): 
                chars += 1
            if (it.get('title') or '').strip() == '등장인물(허브)':
                hubs += 1
print('records:', tot, '  char_items:', chars, '  hubs:', hubs)
