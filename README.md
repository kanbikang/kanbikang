# Kanbikang

AI 비서와 API로 완전히 연결된 메신저입니다. 웹에서 할 수 있는 모든 일(1:1/그룹 대화, 답장, 수정/삭제,
읽음 처리, 친구 관리, 검색)을 AI 비서가 MCP(Model Context Protocol)로 똑같이 할 수 있습니다.
Claude Code, Claude Desktop 등 MCP를 지원하는 클라이언트에 개인 API 토큰 하나만 등록하면 연결됩니다.

## 기능

- 1:1 대화, 그룹 대화(초대, 이름 변경, 나가기). 새로 초대된 사람은 초대 이후 메시지만 볼 수 있습니다.
- WebSocket 실시간 전송. AI 비서가 MCP로 보낸 메시지도 상대 화면에 바로 나타납니다.
- 메시지별 안 읽은 사람 수, 대화방별 안 읽은 메시지 수
- 답장(인용), 수정, 모두에게서 삭제
- 친구 목록, 사용자 검색, 메시지 검색
- AI 비서용 개인 API 토큰: 권한(읽기/쓰기)과 접근할 대화방을 골라서 발급

## 구조

```
           웹 UI (messenger/static)                AI 비서 (Claude Code, Claude Desktop, ...)
            |                  ^                                   |
   REST API /api/*     WebSocket /ws (실시간 이벤트)      MCP /mcp (Streamable HTTP, 또는 stdio)
   (messenger/api.py)  (messenger/main.py)                (messenger/mcp_server.py)
            \                  ^                                   /
             +------ 서비스 계층 (messenger/services.py) ----------+
                               |        \
                     SQLAlchemy + SQLite  커밋 후 이벤트 발행 (messenger/events.py)
```

- REST API와 MCP 도구는 같은 서비스 함수를 호출합니다. 권한 검사와 입력 검증이 한 곳에 있으므로 두 경로의 동작이 항상 같습니다.
- 서비스 함수가 만든 이벤트는 DB 커밋이 성공한 뒤에만 WebSocket으로 전달됩니다. 그래서 REST, MCP 어느 쪽에서 보낸 메시지든 같은 방식으로 실시간 전달됩니다.
- REST 엔드포인트마다 대응하는 MCP 도구 이름이 OpenAPI 문서의 `x-mcp-tool` 항목에 기록됩니다.
  `tests/test_mcp.py`가 모든 REST 기능에 MCP 도구가 있는지(그 반대도) 검사하므로, 기능을 한쪽에만 추가하면 테스트가 실패합니다.

## 실행

Python 3.11 이상이 필요합니다.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/kanbikang-server        # http://127.0.0.1:8000
```

- 웹 UI: `http://127.0.0.1:8000/`
- REST API 문서(OpenAPI): `http://127.0.0.1:8000/docs`
- MCP 엔드포인트: `http://127.0.0.1:8000/mcp`
- 실시간 이벤트: `ws://127.0.0.1:8000/ws` (연결 후 첫 메시지로 `{"token": "<token>"}` 전송)

## AI 비서 연결

1. 웹 UI에서 가입한 뒤 **AI 연결** 메뉴에서 토큰 이름(예: `Claude`), 권한, 접근할 대화방을 골라 토큰을 발급합니다.
2. 발급 화면에 표시되는 설정을 AI 비서에 붙여넣습니다. 토큰은 이때 한 번만 표시됩니다.

**Claude Code**

```bash
claude mcp add --transport http kanbikang http://127.0.0.1:8000/mcp \
  --header "Authorization: Bearer kbk_..."
```

**Claude Desktop** (`claude_desktop_config.json`, `mcp-remote`로 HTTP 엔드포인트에 연결)

```json
{
  "mcpServers": {
    "kanbikang": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:8000/mcp", "--header", "Authorization:${KANBIKANG_AUTH}"],
      "env": { "KANBIKANG_AUTH": "Bearer kbk_..." }
    }
  }
}
```

**stdio 방식** (서버와 같은 컴퓨터에서 데이터베이스에 직접 접속)

```json
{
  "mcpServers": {
    "kanbikang": {
      "command": "/절대경로/.venv/bin/kanbikang-mcp-stdio",
      "env": {
        "KANBIKANG_API_TOKEN": "kbk_...",
        "KANBIKANG_DATABASE_URL": "sqlite:////절대경로/kanbikang.db"
      }
    }
  }
}
```

stdio 방식은 웹 서버와 다른 프로세스라서, 이 방식으로 보낸 메시지는 상대 화면에 실시간으로 뜨지 않고 새로고침해야 보입니다.
실시간 전달이 필요하면 HTTP 방식을 쓰세요.

연결 후 AI 비서에게 "안 읽은 대화 정리해줘", "밥한테 10분 늦는다고 보내줘", "프로젝트 A 방에 회의록 올려줘"처럼 요청하면 됩니다.
MCP 프롬프트 `catch_up`(안 읽은 대화 요약), `draft_reply`(답장 초안 작성 후 승인 시 전송)도 제공합니다.

## 권한과 개인정보

| 토큰 | 발급 | 권한 | 비고 |
| --- | --- | --- | --- |
| 세션 토큰 | 웹 로그인 | 전체 | 30일 후 만료. 토큰 관리는 세션 토큰으로만 가능 |
| 개인 API 토큰 | AI 연결 메뉴 | `read` + 선택한 `write` | 폐기 전까지 유효. 마지막 사용 시각 표시 |

- `read`: 대화방 목록, 메시지 읽기/검색, 안 읽은 메시지 모아보기, 친구 목록 (항상 포함)
- `write`: 메시지 보내기/수정/삭제, 읽음 처리, 대화방 만들기, 그룹 관리, 친구 관리, 프로필 수정
- **대화방 제한**: 토큰을 "선택한 대화방만"으로 발급하면 AI 비서는 그 대화방만 보고 쓸 수 있습니다. 목록, 검색, 실시간 이벤트에서도 다른 대화방은 보이지 않고, 새 대화방도 만들 수 없습니다.
- **읽음 처리 분리**: AI 비서가 메시지를 읽어도 읽음 처리되지 않으므로, 상대방에게 '읽음'으로 표시되지 않습니다. AI가 `mark_read`를 호출하거나 답장을 보낼 때만 읽음 처리됩니다(답장하면 읽음 처리되는 것은 일반 메신저와 같습니다).
- 개인 토큰으로 보낸 메시지에는 `via <토큰 이름>`이 기록되어 대화 상대에게도 표시됩니다.
- 개인 토큰으로는 토큰을 조회하거나 새로 만들 수 없습니다. AI 비서가 스스로 권한을 넓힐 수 없습니다.
- 토큰은 SHA-256 해시로, 비밀번호는 scrypt로 저장합니다.
- MCP 도구에는 `readOnlyHint`, `destructiveHint` 등 주석이 붙어 있어, 클라이언트가 삭제 같은 작업 전에 사용자 확인을 받을 수 있습니다.

## MCP 도구

| 권한 | 도구 |
| --- | --- |
| read | `get_me`, `search_users`, `get_user`, `list_contacts`, `list_conversations`, `get_conversation`, `read_messages`, `list_unread_messages`, `search_messages` |
| write | `update_profile`, `add_contact`, `remove_contact`, `open_direct_conversation`, `create_group`, `rename_group`, `add_members`, `leave_conversation`, `mark_read`, `send_message`, `send_direct_message`, `edit_message`, `delete_message` |

`read_messages`는 오래된 것부터 정렬된 한 페이지를 반환합니다. 응답의 `next_cursor`를 `before`로 넘기면 그 이전 메시지를 읽습니다.
도구 목록과 설명은 `GET /api/ai/tools`로도 확인할 수 있습니다.

## 설정

| 환경 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `KANBIKANG_DATABASE_URL` | `sqlite:///./kanbikang.db` | SQLAlchemy 데이터베이스 URL |
| `KANBIKANG_HOST` / `KANBIKANG_PORT` | `127.0.0.1` / `8000` | 서버 주소 |
| `KANBIKANG_ALLOWED_HOSTS` | `localhost:*,127.0.0.1:*,[::1]:*` | `/mcp`가 허용하는 Host 헤더 (DNS rebinding 방지). 외부 도메인으로 배포할 때 `chat.example.com` 등을 추가. `*`이면 검사 안 함 |
| `KANBIKANG_API_TOKEN` | 없음 | stdio 모드(`kanbikang-mcp-stdio`)에서 사용할 개인 API 토큰 |

외부에 공개할 때는 HTTPS 리버스 프록시 뒤에서 `KANBIKANG_HOST=0.0.0.0`, `KANBIKANG_ALLOWED_HOSTS=<도메인>`으로 실행하세요.
실시간 이벤트는 프로세스 안에서 전달되므로 서버는 프로세스 하나로 실행해야 합니다(여러 개로 늘리려면 Redis 같은 메시지 브로커가 필요합니다).

## 테스트

```bash
.venv/bin/pytest
```

REST API 시나리오, 토큰 권한과 대화방 제한, WebSocket 실시간 이벤트, 실제 HTTP 위에서의 MCP 호출(구 프로토콜 `initialize` 방식과 신규 프로토콜 모두),
MCP로 보낸 메시지의 실시간 전달, stdio 모드, REST와 MCP 기능 일치 여부를 검사합니다.

## 현재 범위 밖

- claude.ai 웹의 커스텀 커넥터는 OAuth 인증이 필요합니다. 현재는 Bearer 토큰 방식만 지원하므로 Claude Code, Claude Desktop(`mcp-remote`), 그 밖의 헤더 설정이 가능한 클라이언트로 연결합니다.
- 사진/파일 전송, 이모지 반응, 입력 중 표시, 푸시 알림, 차단/신고, 종단간 암호화는 아직 없습니다.
- AI 비서가 새 메시지를 기다리는 기능(MCP 구독)은 없습니다. AI 비서는 요청받을 때 `list_unread_messages` 등으로 확인합니다.
- 스키마 마이그레이션 도구 없이 시작 시 테이블을 생성합니다. 운영 환경에서는 PostgreSQL과 Alembic 도입을 권장합니다.
