"""Assemble the daily Musk YouTube email from out/<date>/.

Usage: python3 build_email.py --date 2026-10-19 [--selected ID ID ...] [--backfill ID ...] [--note "..."]
Reads candidates.json, transcripts/<id>.status.json and transcripts/<id>.summary.md,
writes email_subject.txt, email.txt, email.html in the same folder.
--backfill lists earlier-reported videos whose summaries were produced late (for example,
after YouTube access was restored); they get their own section and do not count as new.
"""
import argparse
import glob
import html
import json
import os
import re

REASON_KO = {
    "network_blocked": "자막 접근 차단 (환경 설정 Network access의 Allowed domains에 youtube.com, www.youtube.com 추가 필요)",
    "bot_wall": "유튜브 봇 차단으로 자막을 받지 못함",
    "no_captions": "자막 없음",
    "unavailable": "영상 비공개 또는 삭제",
    "error": "자막 추출 오류",
}


def md_to_html(md):
    out, in_list = [], False
    for line in md.splitlines():
        l = line.rstrip()
        if not l:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        e = html.escape(l)
        e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
        e = re.sub(r"(https?://[^\s<)]+)", r'<a href="\1">\1</a>', e)
        if l.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{e[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if l.startswith("### "):
            out.append(f"<h3>{e[4:]}</h3>")
        elif l.startswith("## "):
            out.append(f"<h2>{e[3:]}</h2>")
        elif l.startswith("# "):
            out.append(f"<h1>{e[2:]}</h1>")
        else:
            out.append(f"<p>{e}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def views_num(text):
    m = re.search(r"([\d.,]+)\s*([KMB]?)", text or "")
    if not m:
        return 0
    n = float(m.group(1).replace(",", ""))
    return int(n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--selected", nargs="*", default=None, help="video ids chosen as Musk-speaking (default: all with status files)")
    ap.add_argument("--backfill", nargs="*", default=[], help="earlier-reported video ids summarized late")
    ap.add_argument("--note", default="", help="extra line for the top of the email")
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    args = ap.parse_args()
    d = os.path.join(args.root, args.date)
    cand = json.load(open(os.path.join(d, "candidates.json")))
    meta = {}
    for p in sorted(glob.glob(os.path.join(args.root, "*", "candidates.json"))):
        try:
            for v in json.load(open(p)).get("videos", []):
                meta[v["video_id"]] = v
        except Exception:
            pass
    meta.update({v["video_id"]: v for v in cand["videos"]})
    tdir = os.path.join(d, "transcripts")
    statuses = {}
    for p in glob.glob(os.path.join(tdir, "*.status.json")):
        s = json.load(open(p))
        statuses[s["video_id"]] = s
    selected = args.selected if args.selected is not None else sorted(statuses)
    sel_set = set(selected)

    def label(vid):
        m = meta.get(vid, {})
        return f"{m.get('title', vid)} ({m.get('channel', '')}, {m.get('length_text', '')})"

    ok, failed = [], []
    for vid in selected:
        s = statuses.get(vid)
        sp = os.path.join(tdir, f"{vid}.summary.md")
        if s and s.get("ok") and os.path.exists(sp):
            ok.append(vid)
        else:
            failed.append((vid, (s or {}).get("reason", "not_attempted")))
    ok.sort(key=lambda v: -(meta.get(v, {}).get("length_seconds") or 0))
    back_ok = [v for v in args.backfill if (statuses.get(v) or {}).get("ok")
               and os.path.exists(os.path.join(tdir, f"{v}.summary.md"))]
    sel_set |= set(args.backfill)

    others = [v for v in cand["videos"] if v["video_id"] not in sel_set and v.get("latin_ratio", 1) >= 0.7]
    others.sort(key=lambda v: -views_num(v.get("views_text")))

    subject = f"일론 머스크 유튜브 데일리 {args.date} (영상 {len(selected)}개)"
    if back_ok:
        subject += f" + 이전 영상 소급 요약 {len(back_ok)}개"
    md = [f"# 일론 머스크 유튜브 데일리 {args.date}", ""]
    if args.note:
        md += [args.note, ""]
    md += [f"조사 범위: 최근 {cand['meta']['hours']:g}시간, 후보 {cand['meta']['count']}개 중 머스크 본인 발언 영상 {len(selected)}개 선별. "
           f"3분 단위 요약 {len(ok)}개, 자막 미확보 {len(failed)}개.", ""]
    md += ["## 선별 영상 목록", ""]
    for vid in selected:
        m = meta.get(vid, {})
        st = "요약 완료" if vid in ok else REASON_KO.get(dict(failed).get(vid, ""), dict(failed).get(vid, ""))
        md.append(f"- {label(vid)} {m.get('url', 'https://www.youtube.com/watch?v=' + vid)} [{st}]")
    md.append("")
    for vid in ok:
        md += ["## " + label(vid), ""]
        md += [open(os.path.join(tdir, f"{vid}.summary.md")).read().strip(), ""]
    if args.backfill:
        md += ["## 이전 보고 영상의 3분 단위 소급 요약", "",
               "앞서 자막 접근이 막혀 링크만 보냈던 영상들이다.", ""]
        back_failed = [v for v in args.backfill if v not in back_ok]
        if back_failed:
            md += [f"- {label(v)} https://www.youtube.com/watch?v={v} : 소급 요약 못 함, "
                   f"{REASON_KO.get((statuses.get(v) or {}).get('reason', ''), (statuses.get(v) or {}).get('reason', '시도하지 않음'))}"
                   for v in back_failed]
            md.append("")
        for vid in back_ok:
            md += ["## " + label(vid), ""]
            md += [open(os.path.join(tdir, f"{vid}.summary.md")).read().strip(), ""]
    if failed:
        md += ["## 자막을 받지 못한 영상", ""]
        for vid, reason in failed:
            md.append(f"- {label(vid)} {meta.get(vid, {}).get('url', '')} : {REASON_KO.get(reason, reason)}")
        md.append("")
    if others:
        md += ["## 참고: 제외된 영상 중 조회수 상위 10개 (해설, 리액션, 뉴스 요약 등)", ""]
        for v in others[:10]:
            md.append(f"- {v['title']} ({v['channel']}, {v.get('length_text','')}, {v.get('views_text','')}) {v['url']}")
        md.append("")
    text = "\n".join(md)
    open(os.path.join(d, "email_subject.txt"), "w").write(subject)
    open(os.path.join(d, "email.txt"), "w").write(text)
    open(os.path.join(d, "email.html"), "w").write(md_to_html(text))
    print(subject)
    print(f"ok={len(ok)} failed={len(failed)} others={len(others)} -> {d}/email.html ({len(text)} chars)")


if __name__ == "__main__":
    main()
