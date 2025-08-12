import json
import re

# Load the titles-only JSON file
with open("anime_titles_only.json", "r", encoding="utf-8") as f:
    titles_data = json.load(f)

# Define regex pattern to remove special symbols and age ratings
pattern = re.compile(r"[←→↔◇◆◐▩◈♧☆▣⑫⑮⑲]")

# Clean titles
cleaned_titles = {}
for quarter, titles in titles_data.items():
    cleaned_titles[quarter] = []
    for title in titles:
        # Remove all specified symbols and trim whitespace
        cleaned = pattern.sub("", title).strip()
        # Remove any leftover empty parentheses
        cleaned = re.sub(r"\(\s*\)", "", cleaned).strip()
        cleaned_titles[quarter].append(cleaned)

# Save cleaned titles to new JSON
output_file = "anime_titles_clean.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(cleaned_titles, f, ensure_ascii=False, indent=2)

# Preview the first few cleaned titles per quarter
for quarter in list(cleaned_titles)[:3]:
    print(f"{quarter} -> {cleaned_titles[quarter][:5]}{'...' if len(cleaned_titles[quarter]) > 5 else ''}")

print(f"\n✅ Cleaned titles saved to {output_file}")
