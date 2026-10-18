#!/usr/bin/env bash
# Usage: ./run_daily.sh [HOURS]   -> discovers candidates into out/<UTC date>/
# then: python3 transcript.py <ID> --out out/<date>/transcripts   for each selected video
set -u
cd "$(dirname "$0")"
HOURS="${1:-26}"
DATE="$(date -u +%F)"
OUT="out/$DATE"
mkdir -p "$OUT"
python3 -c "import requests, yt_dlp, youtube_transcript_api" 2>/dev/null || pip install --quiet --disable-pip-version-check requests yt-dlp youtube-transcript-api
python3 discover.py --hours "$HOURS" --out "$OUT" --pages 3
echo "candidates: $OUT/candidates.md"
