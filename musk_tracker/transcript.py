"""Fetch an English transcript for a YouTube video and bucket it into 3-minute windows.

Usage: python3 transcript.py VIDEO_ID --out out/2026-10-19/transcripts [--window 180]
Exit status 0 and a .md/.json pair on success; a .status.json with a reason on failure.
Needs network access to www.youtube.com (both backends use it).
"""
import argparse
import json
import os
import sys

WINDOW = 180


def _fmt(sec):
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def classify_error(err):
    s = str(err).lower()
    # YouTube's bot check redirects to google.com/sorry, which can also surface as a proxy error,
    # so look for the bot-check signals before the generic network ones.
    if any(k in s for k in ("not a bot", "/sorry/", "sign in to confirm", "ipblocked", "requestblocked", "too many requests", "429")):
        return "bot_wall"
    if any(k in s for k in ("name resolution", "nodename", "connection", "proxy", "tunnel", "403", "timed out", "max retries")):
        return "network_blocked"
    if any(k in s for k in ("transcriptsdisabled", "notranscriptfound", "no transcript", "subtitles are disabled", "no automatic captions")):
        return "no_captions"
    if "unavailable" in s or "private" in s:
        return "unavailable"
    return "error"


def via_transcript_api(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    tl = api.list(video_id)
    try:
        t = tl.find_transcript(["en", "en-US", "en-GB"])
    except Exception:
        t = tl.find_generated_transcript(["en", "en-US", "en-GB"])
    fetched = t.fetch()
    segs = [(float(x.start), float(x.duration), x.text) for x in fetched]
    return segs, {"backend": "youtube_transcript_api", "generated": bool(t.is_generated), "language": t.language_code}


def via_ytdlp(video_id, tmpdir):
    import glob
    import yt_dlp
    opts = {"skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-orig", "en.*"], "subtitlesformat": "json3",
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"), "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    files = glob.glob(os.path.join(tmpdir, f"{video_id}*.json3"))
    if not files:
        raise RuntimeError("no automatic captions or subtitles found")
    with open(files[0]) as f:
        data = json.load(f)
    segs = []
    for ev in data.get("events", []):
        text = "".join(s.get("utf8", "") for s in ev.get("segs", [])).replace("\n", " ").strip()
        if not text:
            continue
        start = ev.get("tStartMs", 0) / 1000
        dur = ev.get("dDurationMs", 0) / 1000
        segs.append((start, dur, text))
    meta = {"backend": "yt_dlp", "title": info.get("title"), "channel": info.get("channel") or info.get("uploader"),
            "duration": info.get("duration"), "upload_date": info.get("upload_date"), "chapters": info.get("chapters")}
    return segs, meta


def bucket(segs, window):
    buckets = {}
    for start, dur, text in segs:
        idx = int(start // window)
        buckets.setdefault(idx, []).append(text.strip())
    out = []
    for idx in sorted(buckets):
        out.append({"index": idx, "start": idx * window, "end": (idx + 1) * window,
                    "label": f"{_fmt(idx*window)}-{_fmt((idx+1)*window)}", "text": " ".join(buckets[idx])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--title", default="")
    ap.add_argument("--channel", default="")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    status_path = os.path.join(args.out, f"{args.video_id}.status.json")
    errors = {}
    segs, meta = None, {}
    for name, fn in (("youtube_transcript_api", lambda: via_transcript_api(args.video_id)),
                     ("yt_dlp", lambda: via_ytdlp(args.video_id, args.out))):
        try:
            segs, meta = fn()
            if segs:
                break
        except Exception as e:
            errors[name] = f"{type(e).__name__}: {str(e)[:300]}"
            segs = None
    if not segs:
        reason = classify_error(" | ".join(errors.values()))
        with open(status_path, "w") as f:
            json.dump({"video_id": args.video_id, "ok": False, "reason": reason, "errors": errors}, f, ensure_ascii=False, indent=1)
        print(f"FAIL {args.video_id} {reason}: {errors}", file=sys.stderr)
        sys.exit(2)
    windows = bucket(segs, args.window)
    total = max(s + d for s, d, _ in segs)
    title = args.title or meta.get("title") or args.video_id
    channel = args.channel or meta.get("channel") or ""
    with open(os.path.join(args.out, f"{args.video_id}.json"), "w") as f:
        json.dump({"video_id": args.video_id, "title": title, "channel": channel, "meta": meta,
                   "total_seconds": total, "window": args.window, "windows": windows}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, f"{args.video_id}.md"), "w") as f:
        f.write(f"# {title}\n\nchannel: {channel}  \nurl: https://www.youtube.com/watch?v={args.video_id}  \n"
                f"length: {_fmt(total)}  \nwindows: {len(windows)} x {args.window}s  \nbackend: {meta.get('backend')}\n\n")
        for w in windows:
            f.write(f"## [{w['label']}]\n\n{w['text']}\n\n")
    with open(status_path, "w") as f:
        json.dump({"video_id": args.video_id, "ok": True, "windows": len(windows), "total_seconds": total, "backend": meta.get("backend")}, f)
    print(f"OK {args.video_id}: {len(windows)} windows, {_fmt(total)}")


if __name__ == "__main__":
    main()
