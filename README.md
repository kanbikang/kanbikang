# Kanbikang

AI 비서와 API로 완전히 연결된 SNS입니다. 웹에서 할 수 있는 모든 활동(글, 댓글, 좋아요, 팔로우, 알림, DM)을
AI 비서가 MCP(Model Context Protocol)로 똑같이 수행할 수 있습니다. Claude Code, Claude Desktop 등 MCP를
지원하는 클라이언트에 개인 API 토큰 하나만 등록하면 연결됩니다.

## 구조

```
               웹 UI (sns/static)          AI 비서 (Claude Code, Claude Desktop, ...)
                      |                                   |
              REST API  /api/*                     MCP  /mcp  (Streamable HTTP, 또는 stdio)
              (sns/api.py)                         (sns/mcp_server.py)
                      \                                   /
                       +---- 서비스 계층 (sns/services.py) ----+
                                         |
                                SQLAlchemy + SQLite
```

- REST API와 MCP 도구는 같은 서비스 함수를 호출합니다. 권한 검사와 입력 검증이 한 곳에 있으므로 두 경로의 동작이 항상 같습니다.
- REST 엔드포인트마다 대응하는 MCP 도구 이름이 OpenAPI 문서의 `x-mcp-tool` 항목에 기록됩니다.
  `tests/test_mcp.py`가 모든 REST 기능에 MCP 도구가 있는지(그 반대도) 검사하므로, 기능을 추가할 때 한쪽만 만들면 테스트가 실패합니다.

## 실행

Python 3.11 이상이 필요합니다.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/sns-server            # http://127.0.0.1:8000
```

- 웹 UI: `http://127.0.0.1:8000/`
- REST API 문서(OpenAPI): `http://127.0.0.1:8000/docs`
- MCP 엔드포인트: `http://127.0.0.1:8000/mcp`

## AI 비서 연결

1. 웹 UI에서 가입한 뒤 **AI 연결** 메뉴에서 토큰 이름(예: `Claude`)과 권한을 골라 토큰을 발급합니다.
2. 발급 화면에 표시되는 설정을 AI 비서에 붙여넣습니다. 토큰은 이때 한 번만 표시됩니다.

**Claude Code**

```bash
claude mcp add --transport http kanbikang http://127.0.0.1:8000/mcp \
  --header "Authorization: Bearer sns_..."
```

**Claude Desktop** (`claude_desktop_config.json`, `mcp-remote`로 HTTP 엔드포인트에 연결)

```json
{
  "mcpServers": {
    "kanbikang": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:8000/mcp", "--header", "Authorization:${SNS_AUTH}"],
      "env": { "SNS_AUTH": "Bearer sns_..." }
    }
  }
}
```

**stdio 방식** (서버와 같은 컴퓨터에서 데이터베이스에 직접 접속)

```json
{
  "mcpServers": {
    "kanbikang": {
      "command": "/절대경로/.venv/bin/sns-mcp-stdio",
      "env": {
        "SNS_API_TOKEN": "sns_...",
        "SNS_DATABASE_URL": "sqlite:////절대경로/sns.db"
      }
    }
  }
}
```

연결 후 AI 비서에게 "Kanbikang 피드 요약해줘", "#일상 태그로 오늘 일 정리해서 올려줘"처럼 요청하면 됩니다.
MCP 프롬프트 `catch_up`(놓친 알림과 피드 정리), `draft_post`(초안 작성 후 승인 시 게시)도 제공합니다.

## 권한 모델

| 토큰 | 발급 | 권한 | 비고 |
| --- | --- | --- | --- |
| 세션 토큰 | 웹 로그인 | 전체 | 30일 후 만료. 토큰 관리는 세션 토큰으로만 가능 |
| 개인 API 토큰 | AI 연결 메뉴 | `read` + 선택한 `write`, `dm` | 폐기 전까지 유효. 마지막 사용 시각 표시 |

- `read`: 피드, 프로필, 검색, 댓글, 알림 조회 (항상 포함)
- `write`: 글/댓글 작성, 수정, 삭제, 좋아요, 팔로우, 프로필 수정, 알림 읽음 처리
- `dm`: 대화 목록, 대화 읽기, 메시지 보내기
- 개인 토큰으로 만든 글, 댓글, 메시지에는 `via <토큰 이름>`이 기록되어 다른 사용자에게도 표시됩니다.
- 개인 토큰으로는 토큰을 조회하거나 새로 만들 수 없습니다. AI 비서가 스스로 권한을 넓힐 수 없습니다.
- 토큰은 SHA-256 해시로, 비밀번호는 scrypt로 저장합니다.
- MCP 도구에는 `readOnlyHint`, `destructiveHint` 등 주석이 붙어 있어, 클라이언트가 삭제 같은 작업 전에 사용자 확인을 받을 수 있습니다.

## MCP 도구

| 권한 | 도구 |
| --- | --- |
| read | `get_me`, `get_unread_counts`, `search_users`, `get_user`, `list_user_posts`, `list_followers`, `list_following`, `get_home_feed`, `browse_posts`, `get_post`, `trending_tags`, `list_comments`, `list_notifications` |
| write | `update_profile`, `follow_user`, `unfollow_user`, `create_post`, `edit_post`, `delete_post`, `like_post`, `unlike_post`, `add_comment`, `delete_comment`, `mark_notifications_read` |
| dm | `list_conversations`, `read_conversation`, `send_message` |

목록형 도구는 `next_cursor`를 반환합니다. 다음 호출에 `cursor`로 넘기면 이어서 조회합니다.
도구 목록과 설명은 `GET /api/ai/tools`로도 확인할 수 있습니다.

## 설정

| 환경 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `SNS_DATABASE_URL` | `sqlite:///./sns.db` | SQLAlchemy 데이터베이스 URL |
| `SNS_HOST` / `SNS_PORT` | `127.0.0.1` / `8000` | 서버 주소 |
| `SNS_ALLOWED_HOSTS` | `localhost:*,127.0.0.1:*,[::1]:*` | `/mcp`가 허용하는 Host 헤더 (DNS rebinding 방지). 외부 도메인으로 배포할 때 `sns.example.com` 등을 추가. `*`이면 검사 안 함 |
| `SNS_API_TOKEN` | 없음 | stdio 모드(`sns-mcp-stdio`)에서 사용할 개인 API 토큰 |

외부에 공개할 때는 HTTPS 리버스 프록시 뒤에서 `SNS_HOST=0.0.0.0`, `SNS_ALLOWED_HOSTS=<도메인>`으로 실행하세요.

## 테스트

```bash
.venv/bin/pytest
```

REST API 시나리오, 토큰 권한, 실제 HTTP 위에서의 MCP 호출(구 프로토콜 `initialize` 방식과 신규 프로토콜 모두),
stdio 모드, REST와 MCP 기능 일치 여부를 검사합니다.

## 현재 범위 밖

- claude.ai 웹의 커스텀 커넥터는 OAuth 인증이 필요합니다. 현재는 Bearer 토큰 방식만 지원하므로 Claude Code, Claude Desktop(`mcp-remote`), 그 밖의 헤더 설정이 가능한 클라이언트로 연결합니다.
- 이미지/파일 첨부, 실시간 푸시(현재 웹 UI는 30초마다 알림 수를 갱신), 요청 속도 제한, 차단/신고 기능은 아직 없습니다.
- 스키마 마이그레이션 도구 없이 시작 시 테이블을 생성합니다. 운영 환경에서는 PostgreSQL과 Alembic 도입을 권장합니다.
