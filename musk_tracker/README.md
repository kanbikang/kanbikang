# musk_tracker

Daily tracker for YouTube videos in which Elon Musk appears, with transcripts
bucketed into 3-minute windows for summarization.

- `discover.py` finds candidate videos uploaded in the last N hours (InnerTube search + official/interview channel uploads) and writes `candidates.md` / `candidates.json`.
- `transcript.py VIDEO_ID --out DIR` fetches the English transcript (auto-captions allowed) and writes `VIDEO_ID.md` with one section per 3-minute window. Needs `www.youtube.com` to be reachable.
- The model running the daily job reads `candidates.md`, decides which videos actually have Musk speaking, runs `transcript.py` for those, summarizes each window in Korean, and emails the result.

Dependencies: `pip install requests yt-dlp youtube-transcript-api`.

## 소급 요약과 브리핑 영상 요약 (2026-10-25 추가)

- `build_email.py --backfill ID ...`: 자막 접근이 막혀 링크만 보냈던 이전 영상의 3분 단위 요약을 별도 섹션으로 넣는다. 제목과 채널은 out/*/candidates.json 전체에서 찾는다.
- `../scripts/brief_videos.py fetch|insert <날짜>`: 데일리 브리핑의 "영상과 팟캐스트 추천" 링크마다 transcript.py로 자막을 받고, 서브에이전트가 `../scripts/BRIEF_VIDEO_PROMPT.md` 규칙으로 쓴 요약을 "영상 요약 (자막 기반)" 섹션으로 넣는다. 자막을 못 받으면 조사 한계 줄에 사유를 적는다.
- 두 기능 모두 www.youtube.com 접근이 허용돼야 실제 요약이 생긴다.
