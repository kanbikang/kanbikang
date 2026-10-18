# musk_tracker

Daily tracker for YouTube videos in which Elon Musk appears, with transcripts
bucketed into 3-minute windows for summarization.

- `discover.py` finds candidate videos uploaded in the last N hours (InnerTube search + official/interview channel uploads) and writes `candidates.md` / `candidates.json`.
- `transcript.py VIDEO_ID --out DIR` fetches the English transcript (auto-captions allowed) and writes `VIDEO_ID.md` with one section per 3-minute window. Needs `www.youtube.com` to be reachable.
- The model running the daily job reads `candidates.md`, decides which videos actually have Musk speaking, runs `transcript.py` for those, summarizes each window in Korean, and emails the result.

Dependencies: `pip install requests yt-dlp youtube-transcript-api`.
