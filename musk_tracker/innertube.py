"""Minimal YouTube InnerTube client (youtubei.googleapis.com) for discovery.

Only the endpoints that work from this environment are used: search, next,
browse, navigation/resolve_url. The player endpoint is bot-walled here, so
transcripts come from transcript.py instead.
"""
import base64
import re
import time

import requests

HOST = "https://youtubei.googleapis.com/youtubei/v1/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
CLIENT_VERSION = "2.20251010.01.00"


def _varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def _fld(num, wire, payload):
    return _varint((num << 3) | wire) + payload


def search_params(upload="today", sort_by_date=True, videos_only=True):
    """Build the `sp` filter blob: sort by upload date + upload window + type=video."""
    up = {"hour": 1, "today": 2, "week": 3, "month": 4, "year": 5}[upload]
    filters = _fld(1, 0, _varint(up))
    if videos_only:
        filters += _fld(2, 0, _varint(1))
    msg = (_fld(1, 0, _varint(2)) if sort_by_date else b"") + _fld(2, 2, _varint(len(filters)) + filters)
    return base64.urlsafe_b64encode(msg).decode().rstrip("=")


def walk(obj, key):
    """Yield every value stored under `key` anywhere inside a nested JSON object."""
    if isinstance(obj, dict):
        if key in obj:
            yield obj[key]
        for v in obj.values():
            yield from walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, key)


def runs_text(node):
    if not node:
        return ""
    if "simpleText" in node:
        return node["simpleText"]
    return "".join(r.get("text", "") for r in node.get("runs", []))


def parse_age_hours(text):
    """'21 hours ago' / 'Streamed 2 days ago' / '3 weeks ago' -> hours (float) or None."""
    if not text:
        return None
    m = re.search(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", text)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    mult = {"second": 1 / 3600, "minute": 1 / 60, "hour": 1, "day": 24, "week": 168, "month": 720, "year": 8760}[unit]
    return n * mult


def parse_length_seconds(text):
    if not text:
        return None
    parts = text.strip().split(":")
    if not all(p.isdigit() for p in parts):
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


class InnerTube:
    def __init__(self, hl="en", gl="US", sleep=0.6):
        self.s = requests.Session()
        self.visitor = None
        self.hl, self.gl, self.sleep = hl, gl, sleep

    def call(self, endpoint, body, retries=3):
        hdr = {
            "Content-Type": "application/json",
            "User-Agent": UA,
            "X-Youtube-Client-Name": "1",
            "X-Youtube-Client-Version": CLIENT_VERSION,
            "Origin": "https://www.youtube.com",
            "Referer": "https://www.youtube.com/",
            "Accept-Language": "en-US,en;q=0.9",
        }
        client = {"clientName": "WEB", "clientVersion": CLIENT_VERSION, "hl": self.hl, "gl": self.gl}
        if self.visitor:
            hdr["X-Goog-Visitor-Id"] = self.visitor
            client["visitorData"] = self.visitor
        last = ""
        for i in range(retries):
            try:
                r = self.s.post(HOST + endpoint, params={"prettyPrint": "false"},
                                json={"context": {"client": client}, **body}, headers=hdr, timeout=40)
                if r.status_code == 200:
                    data = r.json()
                    v = data.get("responseContext", {}).get("visitorData")
                    if v and not self.visitor:
                        self.visitor = v
                    time.sleep(self.sleep)
                    return data
                last = f"HTTP {r.status_code}: {r.text[:200]}"
            except Exception as e:  # network errors
                last = repr(e)
            time.sleep(2 * (i + 1))
        raise RuntimeError(f"innertube {endpoint} failed: {last}")

    # ---- parsing helpers -------------------------------------------------
    @staticmethod
    def _video_from_renderer(v, source):
        owner = v.get("ownerText") or v.get("shortBylineText") or {}
        owner_runs = owner.get("runs", [{}])
        channel_id = (owner_runs[0].get("navigationEndpoint", {}).get("browseEndpoint", {}).get("browseId")
                      if owner_runs else None)
        snippet = ""
        for s in v.get("detailedMetadataSnippets", []):
            snippet += runs_text(s.get("snippetText", {}))
        if not snippet:
            snippet = runs_text(v.get("descriptionSnippet", {}))
        badges = [b.get("metadataBadgeRenderer", {}).get("label", "") for b in v.get("badges", [])]
        published = runs_text(v.get("publishedTimeText", {}))
        length = runs_text(v.get("lengthText", {}))
        return {
            "video_id": v.get("videoId"),
            "title": runs_text(v.get("title", {})),
            "channel": runs_text(owner),
            "channel_id": channel_id,
            "length_text": length,
            "length_seconds": parse_length_seconds(length),
            "published_text": published,
            "age_hours": parse_age_hours(published),
            "views_text": runs_text(v.get("viewCountText", {})),
            "snippet": snippet,
            "badges": badges,
            "is_live": any("LIVE" in b.upper() for b in badges) or ("thumbnailOverlayTimeStatusRenderer" in str(v.get("thumbnailOverlays", "")) and "LIVE" in str(v.get("thumbnailOverlays", ""))),
            "url": f"https://www.youtube.com/watch?v={v.get('videoId')}",
            "source": source,
        }

    @staticmethod
    def _video_from_lockup(l, source):
        """Parse the newer lockupViewModel item used on channel pages (and some search results)."""
        if l.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
            return None
        md = l.get("metadata", {}).get("lockupMetadataViewModel", {})
        title = md.get("title", {}).get("content", "")
        parts = []
        for row in md.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", []):
            for part in row.get("metadataParts", []):
                t = part.get("text", {}).get("content")
                if t:
                    parts.append(t)
        published = next((t for t in parts if " ago" in t or t.startswith(("Scheduled", "Premieres", "Streamed"))), "")
        views = next((t for t in parts if "view" in t or "watching" in t), "")
        channel = next((t for t in parts if t not in (published, views) and not re.search(r"\d", t)), "")
        length, live = "", False
        for ov in l.get("contentImage", {}).get("thumbnailViewModel", {}).get("overlays", []):
            for b in ov.get("thumbnailBottomOverlayViewModel", {}).get("badges", []):
                t = b.get("thumbnailBadgeViewModel", {}).get("text", "")
                if re.fullmatch(r"\d+(:\d{2})+", t):
                    length = t
                elif "LIVE" in t.upper():
                    live = True
        return {
            "video_id": l.get("contentId"), "title": title, "channel": channel, "channel_id": None,
            "length_text": length, "length_seconds": parse_length_seconds(length),
            "published_text": published, "age_hours": parse_age_hours(published), "views_text": views,
            "snippet": "", "badges": [], "is_live": live or "watching" in views,
            "url": f"https://www.youtube.com/watch?v={l.get('contentId')}", "source": source,
        }

    # ---- endpoints -------------------------------------------------------
    def search(self, query, upload="today", pages=3):
        """Search videos sorted by upload date; returns list of dicts."""
        out, seen = [], set()
        data = self.call("search", {"query": query, "params": search_params(upload)})
        for page in range(pages):
            items = [self._video_from_renderer(v, f"search:{query}") for v in walk(data, "videoRenderer")]
            items += [self._video_from_lockup(l, f"search:{query}") for l in walk(data, "lockupViewModel")]
            for item in items:
                if item and item["video_id"] and item["video_id"] not in seen:
                    seen.add(item["video_id"])
                    out.append(item)
            token = None
            for cont in walk(data, "continuationCommand"):
                token = cont.get("token")
                if token:
                    break
            if not token or page == pages - 1:
                break
            data = self.call("search", {"continuation": token})
        return out

    def resolve_handle(self, handle):
        """'@tesla' -> channel browseId (UC...)."""
        data = self.call("navigation/resolve_url", {"url": f"https://www.youtube.com/{handle}"})
        for ep in walk(data, "browseEndpoint"):
            bid = ep.get("browseId")
            if bid and bid.startswith("UC"):
                return bid
        return None

    TAB_PARAMS = {"videos": "EgZ2aWRlb3PyBgQKAjoA", "streams": "EgdzdHJlYW1z8gYECgJ6AA%3D%3D"}

    def find_channel(self, name):
        """Search for a channel by name; returns (browseId, title) of the first channel hit."""
        filters = _fld(2, 0, _varint(2))  # type = channel
        sp = base64.urlsafe_b64encode(_fld(2, 2, _varint(len(filters)) + filters)).decode().rstrip("=")
        data = self.call("search", {"query": name, "params": sp})
        for ch in walk(data, "channelRenderer"):
            cid = ch.get("channelId")
            if cid:
                return cid, runs_text(ch.get("title", {}))
        return None, None

    def channel_videos(self, channel_id, limit=30, tab="videos"):
        """Latest uploads of a channel. tab = 'videos' (uploads) or 'streams' (live tab)."""
        data = self.call("browse", {"browseId": channel_id, "params": self.TAB_PARAMS[tab]})
        title = ""
        for h in walk(data, "c4TabbedHeaderRenderer"):
            title = h.get("title", "")
            break
        if not title:
            for m in walk(data, "metadata"):
                if isinstance(m, dict) and "channelMetadataRenderer" in m:
                    title = m["channelMetadataRenderer"].get("title", "")
                    break
        out = []
        items = [self._video_from_renderer(v, f"channel:{channel_id}:{tab}") for v in walk(data, "videoRenderer")]
        items += [self._video_from_lockup(l, f"channel:{channel_id}:{tab}") for l in walk(data, "lockupViewModel")]
        for item in items:
            if not item or not item.get("video_id"):
                continue
            if not item["channel"]:
                item["channel"] = title
            item["channel_id"] = channel_id
            out.append(item)
            if len(out) >= limit:
                break
        return out

    def video_details(self, video_id):
        """Title, exact date text, owner, description, chapters from the watch `next` response."""
        data = self.call("next", {"videoId": video_id})
        out = {"video_id": video_id}
        for pri in walk(data, "videoPrimaryInfoRenderer"):
            out["title"] = runs_text(pri.get("title", {}))
            out["date_text"] = runs_text(pri.get("dateText", {}))
            out["views_text"] = runs_text(pri.get("viewCount", {}).get("videoViewCountRenderer", {}).get("viewCount", {}))
            break
        for sec in walk(data, "videoSecondaryInfoRenderer"):
            owner = sec.get("owner", {}).get("videoOwnerRenderer", {})
            out["channel"] = runs_text(owner.get("title", {}))
            out["channel_id"] = owner.get("navigationEndpoint", {}).get("browseEndpoint", {}).get("browseId")
            out["description"] = sec.get("attributedDescription", {}).get("content", "")
            break
        chapters = []
        for ch in walk(data, "macroMarkersListItemRenderer"):
            chapters.append({"title": runs_text(ch.get("title", {})), "time": runs_text(ch.get("timeDescription", {}))})
        if chapters:
            out["chapters"] = chapters
        return out
