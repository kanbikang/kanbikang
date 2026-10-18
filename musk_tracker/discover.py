"""Find YouTube videos featuring Elon Musk uploaded in the last N hours.

Usage: python3 discover.py --hours 26 --out out/2026-10-19
Writes candidates.json / candidates.md. Classification here is heuristic;
the final triage (does Musk actually speak?) is done by the model that reads
candidates.md.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from innertube import InnerTube

QUERIES = [
    "Elon Musk", "Elon Musk interview", "Elon Musk podcast", "Elon Musk speaks",
    "Elon Musk full", "Musk Tesla", "Musk SpaceX", "Musk xAI Grok", "Musk live",
]
# Channels whose uploads are checked directly (title may not contain "Musk").
OFFICIAL_HANDLES = ["@tesla", "@SpaceX", "@xai", "@neuralink", "@boringcompany"]
# Channels where Musk regularly appears speaking at length.
INTERVIEW_HANDLES = ["@TeslaOwnersSiliconValley", "@lexfridman", "@joerogan", "@allin",
                     "@DwarkeshPatel", "@TBPN", "@CNBCtelevision", "@BloombergTelevision",
                     "@FoxNews", "@FoxBusiness"]

SPEAKING_RE = re.compile(r"\b(full interview|interview|speaks|keynote|q ?& ?a|fireside|town hall|"
                         r"conversation with|talks? (to|with)|joins|sits down|unveil|event|earnings call|"
                         r"all[- ]hands|testimony|remarks|address|press conference|livestream|live stream|"
                         r"announces|presentation|panel)\b", re.I)
COMMENTARY_RE = re.compile(r"\b(reacts?|reaction|explained|breakdown|analysis|destroys|humiliates|"
                           r"shocked|exposed|the truth|secret(ly)?|ai voice|compilation|documentary|"
                           r"rant|career|meltdown|slams|responds|just|finally|insane|crazy)\b", re.I)


def latin_ratio(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    latin = sum(1 for c in letters if ord(c) < 0x250)
    return latin / len(letters)


def classify(v, official_ids, interview_ids):
    title = v.get("title", "")
    if v.get("channel_id") in official_ids:
        return "official"
    if v.get("channel_id") in interview_ids:
        return "interview_channel"
    if SPEAKING_RE.search(title) and not COMMENTARY_RE.search(title):
        return "likely_speaking"
    if COMMENTARY_RE.search(title):
        return "commentary"
    return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=26)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--min-seconds", type=int, default=60)
    ap.add_argument("--state", default="state/seen.json", help="json list of video ids already reported")
    args = ap.parse_args()
    seen_before = set()
    if args.state and os.path.exists(args.state):
        try:
            seen_before = set(json.load(open(args.state)))
        except Exception:
            seen_before = set()
    os.makedirs(args.out, exist_ok=True)

    it = InnerTube()
    log = []
    official_ids, interview_ids = {}, {}
    for h in OFFICIAL_HANDLES + INTERVIEW_HANDLES:
        cid = None
        try:
            cid = it.resolve_handle(h)
        except Exception as e:
            log.append(f"resolve {h} failed: {str(e)[:80]}")
        if not cid:
            try:
                cid, title = it.find_channel(h.lstrip("@"))
                if cid:
                    log.append(f"resolve {h}: used search fallback -> {title} ({cid})")
            except Exception as e:
                log.append(f"find_channel {h} failed: {str(e)[:80]}")
        if cid:
            (official_ids if h in OFFICIAL_HANDLES else interview_ids)[cid] = h
        else:
            log.append(f"resolve {h}: no channel id")

    found = {}

    def add(item):
        vid = item.get("video_id")
        if not vid:
            return
        if vid in found:
            found[vid]["sources"].add(item["source"])
            return
        item["sources"] = {item["source"]}
        found[vid] = item

    upload = "today" if args.hours <= 30 else ("week" if args.hours <= 24 * 7 else "month")
    for q in QUERIES:
        try:
            for item in it.search(q, upload=upload, pages=args.pages):
                add(item)
        except Exception as e:
            log.append(f"search '{q}' failed: {e}")
    for cid, handle in {**official_ids, **interview_ids}.items():
        tabs = ("videos", "streams") if cid in official_ids else ("videos",)
        for tab in tabs:
            try:
                for item in it.channel_videos(cid, limit=30, tab=tab):
                    item["source"] = f"channel:{handle}:{tab}"
                    add(item)
            except Exception as e:
                log.append(f"channel {handle} {tab} failed: {str(e)[:80]}")

    rows = []
    for v in found.values():
        v["sources"] = sorted(v["sources"])
        age = v.get("age_hours")
        if age is None or age > args.hours:
            continue
        secs = v.get("length_seconds")
        if secs is not None and secs < args.min_seconds and not v.get("is_live"):
            continue
        text = f"{v['title']} {v['channel']} {v.get('snippet','')}"
        musk = bool(re.search(r"\bmusk\b|\belon\b", text, re.I))
        musk_related = musk or bool(re.search(r"\b(tesla|spacex|xai|grok|starlink|starship|neuralink|roadster|cybercab|optimus)\b", text, re.I))
        official = v.get("channel_id") in official_ids
        if not official and not (musk if not v.get("channel_id") in interview_ids else musk_related):
            continue
        v["mentions_musk"] = musk
        v["latin_ratio"] = round(latin_ratio(v["title"]), 2)
        v["tier"] = classify(v, official_ids, interview_ids)
        v["seen_before"] = v["video_id"] in seen_before
        rows.append(v)

    order = {"official": 0, "interview_channel": 1, "likely_speaking": 2, "unknown": 3, "commentary": 4}
    rows.sort(key=lambda r: (order[r["tier"]], -(r.get("length_seconds") or 0)))

    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "hours": args.hours,
            "queries": QUERIES, "official_channels": official_ids, "interview_channels": interview_ids,
            "log": log, "count": len(rows)}
    with open(os.path.join(args.out, "candidates.json"), "w") as f:
        json.dump({"meta": meta, "videos": rows}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "candidates.md"), "w") as f:
        f.write(f"# Musk YouTube candidates, last {args.hours:g}h, generated {meta['generated_utc']}\n\n")
        f.write(f"{len(rows)} videos. Tiers: official, interview_channel, likely_speaking, unknown, commentary.\n\n")
        f.write("| tier | id | len | age | channel | title | musk? | latin | seen |\n|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['tier']} | {r['video_id']} | {r['length_text']} | {r['published_text']} | "
                    f"{r['channel']} | {r['title'].replace('|','/')} | {'y' if r['mentions_musk'] else 'n'} | {r['latin_ratio']} | {'y' if r['seen_before'] else ''} |\n")
        if log:
            f.write("\n## log\n" + "\n".join(f"- {l}" for l in log) + "\n")
    print(f"{len(rows)} candidates -> {args.out}/candidates.md")
    for l in log:
        print("LOG:", l, file=sys.stderr)


if __name__ == "__main__":
    main()
