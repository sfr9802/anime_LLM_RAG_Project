import re
import json

input_path = "text.txt"
output_path = "parsed_law_chunks_flexible.json"
parsed_data = []

with open(input_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    line = line.strip()
    if not line:
        continue

    # "문장", (태그) or "문장" (태그) 모두 지원
    match = re.match(r'^"?(.+?)"?[\s,]*\(?([가-힣]+)\)?$', line)
    if match:
        text = match.group(1).strip(' "')
        tag = match.group(2).strip(' ()')
        parsed_data.append({"text": text, "tag": tag})
    else:
        print(f"[!] Unmatched Line {i+1}: {line}")

# 저장
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(parsed_data, f, ensure_ascii=False, indent=2)

print(f"{len(parsed_data)}개 항목이 {output_path}에 저장되었습니다.")
