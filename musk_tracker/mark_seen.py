"""Record video ids as reported: python3 mark_seen.py ID [ID ...]  (state/seen.json keeps the last 2000)."""
import json, os, sys
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "seen.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
seen = []
if os.path.exists(path):
    seen = json.load(open(path))
for vid in sys.argv[1:]:
    if vid not in seen:
        seen.append(vid)
json.dump(seen[-2000:], open(path, "w"))
print(len(seen), "ids in", path)
