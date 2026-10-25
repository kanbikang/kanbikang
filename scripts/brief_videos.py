"""Add transcript-based summaries of the YouTube videos recommended in a daily brief.

  python3 scripts/brief_videos.py fetch 2026-10-25
      Finds YouTube links in the brief's "## 영상과 팟캐스트 추천" section, runs
      musk_tracker/transcript.py on each (3-minute windows) into
      musk_tracker/out/brief-<date>/transcripts/, and writes manifest.json there.
      After the first network_blocked result it stops trying the rest.
  Then one subagent per video with status ok writes <id>.brief.md there,
  following scripts/BRIEF_VIDEO_PROMPT.md.
  python3 scripts/brief_videos.py insert 2026-10-25
      Puts a "## 영상 요약 (자막 기반)" section right after the recommendations,
      built from the .brief.md files, and notes videos without summaries in the
      "조사 한계:" line. Running it again replaces the section.
"""
import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC_HEADER = "## 영상과 팟캐스트 추천"
SUM_HEADER = "## 영상 요약 (자막 기반)"
YT = re.compile(r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})")
REASON_KO = {
    "network_blocked": "자막 접근 차단, youtube.com 미허용",
    "bot_wall": "유튜브 봇 차단",
    "no_captions": "자막 없음",
    "unavailable": "비공개 또는 삭제",
    "error": "자막 추출 오류",
    "not_attempted": "앞 영상에서 접근 차단이 확인돼 시도하지 않음",
}


def paths(date, brief=None, tdir=None):
    brief = brief or os.path.join(REPO, "briefs", f"{date}.md")
    tdir = tdir or os.path.join(REPO, "musk_tracker", "out", f"brief-{date}", "transcripts")
    return brief, tdir


def section_bounds(lines, header):
    """Index of the header line and of the first line after its section."""
    start = next((i for i, l in enumerate(lines) if l.strip() == header), None)
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") or lines[i].startswith("조사 한계:"):
            end = i
            break
    return start, end


def recommended_videos(md, limit):
    lines = md.splitlines()
    s, e = section_bounds(lines, REC_HEADER)
    if s is None:
        return []
    out, seen = [], set()
    for l in lines[s + 1:e]:
        if not l.startswith("- "):
            continue
        m = YT.search(l)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        text = re.sub(r"^(참고|예정)(\([^)]*\))?:\s*", "", l[2:])
        title = text.split(" (")[0].strip()
        inner = text[len(title):].strip()
        channel = inner[1:].split(",")[0].strip() if inner.startswith("(") else ""
        out.append({"video_id": m.group(1), "title": title, "channel": channel,
                    "url": f"https://www.youtube.com/watch?v={m.group(1)}"})
    return out[:limit]


def cmd_fetch(args):
    brief, tdir = paths(args.date, args.brief, args.tdir)
    vids = recommended_videos(open(brief).read(), args.max)
    os.makedirs(tdir, exist_ok=True)
    tx = os.path.join(REPO, "musk_tracker", "transcript.py")
    blocked = False
    for v in vids:
        if blocked:
            v["status"] = "not_attempted"
            continue
        r = subprocess.run([sys.executable, tx, v["video_id"], "--out", tdir,
                            "--title", v["title"], "--channel", v["channel"]],
                           capture_output=True, text=True, timeout=600)
        st_path = os.path.join(tdir, f"{v['video_id']}.status.json")
        st = json.load(open(st_path)) if os.path.exists(st_path) else {"ok": False, "reason": "error"}
        v["status"] = "ok" if st.get("ok") else st.get("reason", "error")
        v["windows"] = st.get("windows")
        if v["status"] == "network_blocked":
            blocked = True
    json.dump({"date": args.date, "videos": vids}, open(os.path.join(tdir, "manifest.json"), "w"),
              ensure_ascii=False, indent=1)
    for v in vids:
        print(f"{v['status']:>15}  {v['video_id']}  {v['title'][:70]}")
    print(f"manifest: {os.path.join(tdir, 'manifest.json')}")


def cmd_insert(args):
    brief, tdir = paths(args.date, args.brief, args.tdir)
    man_path = os.path.join(tdir, "manifest.json")
    vids = json.load(open(man_path))["videos"] if os.path.exists(man_path) else []
    lines = open(brief).read().splitlines()
    s, e = section_bounds(lines, SUM_HEADER)
    if s is not None:
        del lines[s:e]
    done, missing = [], []
    for v in vids:
        p = os.path.join(tdir, f"{v['video_id']}.brief.md")
        if v.get("status") == "ok" and os.path.exists(p):
            done.append(open(p).read().strip())
        else:
            reason = v.get("status") if v.get("status") != "ok" else "error"
            missing.append((v, reason))
    if done:
        block = [SUM_HEADER, "추천 영상의 자막을 읽고 정리한 요약이다. 시각은 영상 안의 위치다.", ""]
        for d in done:
            block += [d, ""]
        rs, re_ = section_bounds(lines, REC_HEADER)
        at = re_ if rs is not None else next((i for i, l in enumerate(lines) if l.startswith("조사 한계:")), len(lines))
        lines[at:at] = block
    if missing:
        reasons = sorted({REASON_KO.get(r, r) for _, r in missing if r != "not_attempted"}) or [REASON_KO["not_attempted"]]
        note = f" 추천 영상 {len(missing)}개는 자막을 받지 못해 요약하지 못했다({', '.join(reasons)})."
        idx = next((i for i, l in enumerate(lines) if l.startswith("조사 한계:")), None)
        if idx is None:
            lines += ["", "조사 한계:" + note]
        elif "자막을 받지 못해 요약하지 못했다" not in lines[idx]:
            lines[idx] += note
    open(brief, "w").write("\n".join(lines).rstrip() + "\n")
    print(f"inserted {len(done)} summaries, {len(missing)} without summary -> {brief}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "insert"):
        p = sub.add_parser(name)
        p.add_argument("date")
        p.add_argument("--brief", help="brief markdown path (default briefs/<date>.md)")
        p.add_argument("--tdir", help="transcript folder (default musk_tracker/out/brief-<date>/transcripts)")
        p.add_argument("--max", type=int, default=5)
    args = ap.parse_args()
    {"fetch": cmd_fetch, "insert": cmd_insert}[args.cmd](args)


if __name__ == "__main__":
    main()
