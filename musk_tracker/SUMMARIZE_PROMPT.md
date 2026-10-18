# Per-video summarization instructions (used by the daily job's subagents)

Input: `out/<date>/transcripts/<video_id>.md`, which has one `## [MM:SS-MM:SS]` section per 3-minute window of the English transcript (auto-captions, so names and numbers may be garbled; fix obvious ASR errors using context, and mark anything uncertain with "(불확실)").

Output: `out/<date>/transcripts/<video_id>.summary.md`, Korean, no emotional language, no emoji. Structure:

```
### <영상 제목> (<채널>, 길이 <H:MM:SS>)
<url>

핵심 요약 (3~5문장): 이 영상에서 머스크가 말한 가장 중요한 내용. 숫자, 날짜, 고유명사는 원문 그대로.

구간별 요약
- [00:00-03:00] 2~4문장. 누가 무엇을 말했는지. 머스크 발언은 "머스크:"로 시작. 진행자/타인 발언은 이름 또는 역할로 표시.
- [03:00-06:00] ...
(모든 구간을 빠짐없이, 순서대로. 광고나 침묵 구간은 "광고/무음"으로 한 줄.)

주목할 발언 (3~8개): 인용 가능한 머스크의 직접 발언을 원문(영어)과 한국어 번역으로, 구간 표시와 함께.
```

Rules: do not skip windows; do not merge windows; do not add facts that are not in the transcript; if the speaker cannot be determined from context, write "발언자 불명".
