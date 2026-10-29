"use strict";

const state = {
  token: localStorage.getItem("sns_token"),
  me: null,
};

// DOM helpers

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "value") el.value = value;
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

let toastTimer;
function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

function timeAgo(iso) {
  const seconds = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (seconds < 60) return "방금";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}시간 전`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)}일 전`;
  return new Date(iso).toLocaleDateString("ko-KR");
}

// Mirrors TAG_RE / MENTION_RE in services.py.
const RICH_RE = /(?<![\p{L}\p{M}\p{N}_#@])(#[\p{L}\p{M}\p{N}_]{1,50}|@[A-Za-z0-9_]{3,30})/gu;

function richText(text) {
  const frag = document.createDocumentFragment();
  let last = 0;
  for (const match of text.matchAll(RICH_RE)) {
    const token = match[0];
    frag.append(text.slice(last, match.index));
    frag.append(token[0] === "#"
      ? h("a", { href: `#/tag/${encodeURIComponent(token.slice(1).toLowerCase())}` }, token)
      : h("a", { href: `#/u/${token.slice(1)}` }, token));
    last = match.index + token.length;
  }
  frag.append(text.slice(last));
  return frag;
}

// API client

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function errorMessage(data) {
  if (!data) return null;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join(", ");
  return null;
}

async function api(method, path, body) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && state.token) {
      setToken(null);
      location.hash = "#/login";
    }
    throw new ApiError(res.status, errorMessage(data) || `요청에 실패했습니다 (${res.status})`);
  }
  return data;
}

function setToken(token) {
  state.token = token;
  state.me = null;
  if (token) localStorage.setItem("sns_token", token);
  else localStorage.removeItem("sns_token");
}

function qs(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

// Components

function userLink(user) {
  return h("a", { class: "name", href: `#/u/${user.username}` }, user.display_name);
}

function postCard(post) {
  const isMine = state.me && post.author.id === state.me.id;
  const body = h("div", { class: "post-body" }, richText(post.content));
  const likeBtn = h("button", { class: "link", onclick: toggleLike });
  const editedMark = h("span", { class: "meta" }, post.edited_at ? " · 수정됨" : "");

  function renderLike() {
    likeBtn.textContent = `좋아요 ${post.like_count}`;
    likeBtn.classList.toggle("on", post.liked_by_me);
  }

  async function toggleLike() {
    try {
      Object.assign(post, await api(post.liked_by_me ? "DELETE" : "PUT", `/posts/${post.id}/like`));
      renderLike();
    } catch (err) {
      toast(err.message);
    }
  }

  function edit() {
    const input = h("textarea", { maxlength: 500, value: post.content });
    const save = h("button", { class: "primary", onclick: async () => {
      try {
        Object.assign(post, await api("PATCH", `/posts/${post.id}`, { content: input.value }));
        body.replaceChildren(richText(post.content));
        editedMark.textContent = " · 수정됨";
      } catch (err) {
        toast(err.message);
      }
    } }, "저장");
    const cancel = h("button", { onclick: () => body.replaceChildren(richText(post.content)) }, "취소");
    body.replaceChildren(input, h("div", { class: "row start" }, save, cancel));
    input.focus();
  }

  async function remove() {
    if (!confirm("이 게시물을 삭제할까요?")) return;
    try {
      await api("DELETE", `/posts/${post.id}`);
      card.remove();
      toast("삭제했습니다");
    } catch (err) {
      toast(err.message);
    }
  }

  renderLike();
  const card = h("article", { class: "card" },
    h("div", { class: "post-head" },
      userLink(post.author),
      h("span", { class: "handle" }, `@${post.author.username}`),
      h("a", { class: "meta", href: `#/p/${post.id}` }, `· ${timeAgo(post.created_at)}`),
      editedMark,
      post.via ? h("span", { class: "via", title: "AI 비서 또는 API로 작성됨" }, `via ${post.via}`) : null,
    ),
    body,
    h("div", { class: "post-actions" },
      likeBtn,
      h("a", { class: "meta", href: `#/p/${post.id}` }, `댓글 ${post.comment_count}`),
      isMine ? h("button", { class: "link", onclick: edit }, "수정") : null,
      isMine ? h("button", { class: "link danger", onclick: remove }, "삭제") : null,
    ),
  );
  return card;
}

function composer(onCreated, placeholder = "무슨 일이 있나요? #해시태그 @멘션") {
  const input = h("textarea", { maxlength: 500, placeholder });
  const count = h("span", { class: "meta" }, "0 / 500");
  const button = h("button", { class: "primary", onclick: submit }, "게시");
  input.addEventListener("input", () => { count.textContent = `${input.value.length} / 500`; });

  async function submit() {
    const content = input.value.trim();
    if (!content) return;
    button.disabled = true;
    try {
      onCreated(await api("POST", "/posts", { content }));
      input.value = "";
      count.textContent = "0 / 500";
    } catch (err) {
      toast(err.message);
    } finally {
      button.disabled = false;
    }
  }

  return h("div", { class: "card" }, input, h("div", { class: "row" }, count, button));
}

// Appends items page by page; fetchPage(cursor) resolves to {items, next_cursor}.
function pagedList(root, fetchPage, renderItem, emptyText) {
  const list = h("div");
  const more = h("button", { onclick: load }, "더 보기");
  const moreRow = h("div", { class: "row", style: "justify-content:center" }, more);
  moreRow.hidden = true;
  root.append(list, moreRow);
  let cursor = null;

  async function load() {
    more.disabled = true;
    try {
      const page = await fetchPage(cursor);
      if (cursor === null && page.items.length === 0) list.append(h("div", { class: "empty" }, emptyText));
      for (const item of page.items) list.append(renderItem(item));
      cursor = page.next_cursor;
      moreRow.hidden = cursor == null;
    } catch (err) {
      toast(err.message);
    } finally {
      more.disabled = false;
    }
  }

  load();
  return {
    prepend(node) {
      list.querySelector(".empty")?.remove();
      list.prepend(node);
    },
  };
}

function userRow(user) {
  return h("div", { class: "card user-row" },
    h("div", {},
      userLink(user), " ", h("span", { class: "handle meta" }, `@${user.username}`),
      user.bio ? h("div", { class: "meta" }, user.bio) : null,
    ),
    user.is_me ? null : followButton(user),
  );
}

function followButton(user, onChange) {
  const button = h("button", { onclick: toggle });
  function render() {
    button.textContent = user.is_following ? "팔로잉" : "팔로우";
    button.className = user.is_following ? "" : "primary";
  }
  async function toggle() {
    try {
      Object.assign(user, await api(user.is_following ? "DELETE" : "PUT", `/users/${user.username}/follow`));
      render();
      onChange?.(user);
    } catch (err) {
      toast(err.message);
    }
  }
  render();
  return button;
}

function checkbox(text, checked, disabled = false) {
  const input = h("input", { type: "checkbox", checked, disabled });
  return { input, label: h("label", {}, input, text) };
}

function codeBlock(text) {
  const copy = h("button", { onclick: async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast("복사했습니다");
    } catch {
      toast("복사하지 못했습니다. 직접 선택해서 복사하세요.");
    }
  } }, "복사");
  return h("div", {},
    h("pre", { class: "code" }, text),
    h("div", { class: "row", style: "justify-content:flex-end;margin-top:-4px" }, copy),
  );
}

// Views. Each receives a root element that is already attached to the page.

function renderAuth(root, mode) {
  const isLogin = mode === "login";
  const username = h("input", { type: "text", autocomplete: "username", placeholder: "영문, 숫자, _ 3~30자" });
  const displayName = h("input", { type: "text", maxlength: 50, placeholder: "비워두면 아이디를 사용합니다" });
  const password = h("input", { type: "password", autocomplete: isLogin ? "current-password" : "new-password", placeholder: "8자 이상" });
  const error = h("div", { class: "error" });

  async function submit(event) {
    event.preventDefault();
    error.textContent = "";
    try {
      const body = { username: username.value.trim(), password: password.value };
      if (!isLogin) body.display_name = displayName.value.trim() || null;
      const result = await api("POST", isLogin ? "/auth/login" : "/auth/register", body);
      setToken(result.token);
      state.me = result.user;
      location.hash = "#/";
    } catch (err) {
      error.textContent = err.message;
    }
  }

  root.append(h("form", { class: "card", onsubmit: submit, style: "max-width:400px;margin:48px auto" },
    h("h2", {}, "Kanbikang"),
    h("p", { class: "meta" }, "AI 비서와 API로 연결되는 SNS"),
    h("label", {}, "아이디"), username,
    isLogin ? null : [h("label", {}, "이름"), displayName],
    h("label", {}, "비밀번호"), password,
    error,
    h("div", { class: "row" },
      h("a", { href: isLogin ? "#/register" : "#/login" }, isLogin ? "계정 만들기" : "이미 계정이 있습니다"),
      h("button", { class: "primary", type: "submit" }, isLogin ? "로그인" : "가입"),
    ),
  ));
  username.focus();
}

function renderHome(root) {
  let feed;
  root.append(composer((post) => feed.prepend(postCard(post))));
  root.append(h("div", { class: "section-title" }, "홈 피드 (나와 팔로우한 사람들의 글)"));
  feed = pagedList(root, (cursor) => api("GET", `/feed${qs({ cursor })}`), postCard,
    "아직 글이 없습니다. 탐색에서 다른 사용자를 팔로우해 보세요.");
}

function renderExplore(root) {
  const input = h("input", { type: "text", placeholder: "글 또는 사용자 검색" });
  const tabs = { posts: h("button", { class: "on" }, "글"), users: h("button", {}, "사용자") };
  const results = h("div");
  let mode = "posts";

  function search() {
    const q = input.value.trim();
    results.replaceChildren();
    if (mode === "users") {
      if (!q) {
        results.append(h("div", { class: "empty" }, "검색어를 입력하세요"));
        return;
      }
      api("GET", `/users${qs({ q })}`)
        .then((users) => {
          if (!users.length) results.append(h("div", { class: "empty" }, "검색 결과가 없습니다"));
          for (const user of users) results.append(userRow(user));
        })
        .catch((err) => toast(err.message));
    } else {
      pagedList(results, (cursor) => api("GET", `/posts${qs({ q, cursor })}`), postCard, "글이 없습니다");
    }
  }

  for (const [key, button] of Object.entries(tabs)) {
    button.addEventListener("click", () => {
      mode = key;
      for (const b of Object.values(tabs)) b.classList.toggle("on", b === button);
      search();
    });
  }
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") search(); });

  const trending = h("div", { class: "card" }, h("h3", {}, "인기 해시태그 (7일)"));
  root.append(h("div", { class: "card" }, input), trending, h("div", { class: "tabs" }, tabs.posts, tabs.users), results);

  api("GET", "/tags/trending")
    .then((tags) => {
      if (!tags.length) trending.append(h("div", { class: "meta" }, "아직 해시태그가 없습니다"));
      trending.append(h("div", { class: "row start", style: "flex-wrap:wrap" },
        tags.map((t) => h("a", { href: `#/tag/${encodeURIComponent(t.tag)}` }, `#${t.tag} (${t.count})`))));
    })
    .catch((err) => toast(err.message));
  search();
}

function renderTag(root, tag) {
  root.append(h("h2", {}, `#${tag}`));
  pagedList(root, (cursor) => api("GET", `/posts${qs({ tag, cursor })}`), postCard, "이 해시태그의 글이 없습니다");
}

async function renderProfile(root, username) {
  const user = await api("GET", `/users/${username}`).catch((err) => {
    root.append(h("div", { class: "empty" }, err.message));
    return null;
  });
  if (!user) return;

  const stats = h("div", { class: "stats" });
  function renderStats() {
    stats.replaceChildren(
      h("span", {}, h("b", {}, user.posts_count), " 게시물"),
      h("span", {}, h("b", {}, user.followers_count), " 팔로워"),
      h("span", {}, h("b", {}, user.following_count), " 팔로잉"),
      user.follows_you ? h("span", { class: "meta" }, "나를 팔로우합니다") : null,
    );
  }
  renderStats();

  const header = h("div", { class: "card" });
  function renderHeader() {
    header.replaceChildren(
      h("div", { class: "user-row" },
        h("div", {}, h("h2", { style: "margin:0" }, user.display_name), h("div", { class: "meta" }, `@${user.username}`)),
        user.is_me
          ? h("button", { onclick: editProfile }, "프로필 수정")
          : h("div", { class: "row start", style: "margin:0" },
              h("a", { href: `#/messages/${user.username}` }, "메시지"), followButton(user, renderStats)),
      ),
      user.bio ? h("p", {}, user.bio) : null,
      stats,
    );
  }

  function editProfile() {
    const name = h("input", { type: "text", maxlength: 50, value: user.display_name });
    const bio = h("textarea", { maxlength: 300, value: user.bio });
    header.replaceChildren(
      h("label", {}, "이름"), name, h("label", {}, "소개"), bio,
      h("div", { class: "row start" },
        h("button", { class: "primary", onclick: async () => {
          try {
            Object.assign(user, await api("PATCH", "/me", { display_name: name.value, bio: bio.value }));
            state.me = { ...state.me, ...user };
            renderHeader();
          } catch (err) {
            toast(err.message);
          }
        } }, "저장"),
        h("button", { onclick: renderHeader }, "취소"),
      ),
    );
  }

  renderHeader();
  const tabs = { posts: h("button", { class: "on" }, "게시물"), followers: h("button", {}, "팔로워"), following: h("button", {}, "팔로잉") };
  const content = h("div");
  function show(key) {
    for (const [k, b] of Object.entries(tabs)) b.classList.toggle("on", k === key);
    content.replaceChildren();
    if (key === "posts") {
      pagedList(content, (cursor) => api("GET", `/users/${user.username}/posts${qs({ cursor })}`), postCard, "아직 글이 없습니다");
    } else {
      pagedList(content, (cursor) => api("GET", `/users/${user.username}/${key}${qs({ cursor })}`), userRow, "아직 없습니다");
    }
  }
  for (const [key, button] of Object.entries(tabs)) button.addEventListener("click", () => show(key));
  root.append(header, h("div", { class: "tabs" }, Object.values(tabs)), content);
  show("posts");
}

async function renderPost(root, postId) {
  const post = await api("GET", `/posts/${postId}`).catch((err) => {
    root.append(h("div", { class: "empty" }, err.message));
    return null;
  });
  if (!post) return;
  root.append(postCard(post), h("div", { class: "section-title" }, "댓글"));

  function commentItem(comment) {
    const canDelete = state.me && (comment.author.id === state.me.id || post.author.id === state.me.id);
    const item = h("div", { class: "card" },
      h("div", { class: "post-head" },
        userLink(comment.author),
        h("span", { class: "handle" }, `@${comment.author.username}`),
        h("span", { class: "meta" }, `· ${timeAgo(comment.created_at)}`),
        comment.via ? h("span", { class: "via" }, `via ${comment.via}`) : null,
      ),
      h("div", { class: "post-body" }, richText(comment.content)),
      canDelete ? h("div", { class: "post-actions" }, h("button", { class: "link danger", onclick: async () => {
        if (!confirm("이 댓글을 삭제할까요?")) return;
        try {
          await api("DELETE", `/comments/${comment.id}`);
          item.remove();
        } catch (err) {
          toast(err.message);
        }
      } }, "삭제")) : null,
    );
    return item;
  }

  const comments = h("div");
  const input = h("textarea", { maxlength: 500, placeholder: "댓글을 입력하세요" });
  const send = h("button", { class: "primary", onclick: async () => {
    const content = input.value.trim();
    if (!content) return;
    try {
      comments.append(commentItem(await api("POST", `/posts/${post.id}/comments`, { content })));
      comments.querySelector(".empty")?.remove();
      input.value = "";
    } catch (err) {
      toast(err.message);
    }
  } }, "댓글 달기");
  root.append(comments, h("div", { class: "card" }, input, h("div", { class: "row", style: "justify-content:flex-end" }, send)));
  pagedList(comments, (cursor) => api("GET", `/posts/${post.id}/comments${qs({ cursor })}`), commentItem, "아직 댓글이 없습니다");
}

function renderNotifications(root) {
  const markAll = h("button", { onclick: async () => {
    try {
      await api("POST", "/notifications/read", {});
      for (const el of root.querySelectorAll(".notification.unread")) el.classList.remove("unread");
      refreshBadges();
    } catch (err) {
      toast(err.message);
    }
  } }, "모두 읽음으로 표시");
  root.append(h("div", { class: "row", style: "margin:0 0 12px" }, h("h2", { style: "margin:0" }, "알림"), markAll));
  pagedList(root, (cursor) => api("GET", `/notifications${qs({ cursor })}`), (n) => {
    const target = n.post_id ? `#/p/${n.post_id}` : `#/u/${n.actor.username}`;
    return h("a", { href: target, class: `card notification${n.read ? "" : " unread"}`, style: "display:block;color:inherit;text-decoration:none" },
      h("div", {}, n.summary),
      h("div", { class: "meta" }, timeAgo(n.created_at)));
  }, "알림이 없습니다");
}

function renderMessages(root) {
  const username = h("input", { type: "text", placeholder: "아이디를 입력해 새 대화 시작" });
  username.addEventListener("keydown", (event) => {
    const value = username.value.trim().replace(/^@/, "");
    if (event.key === "Enter" && value) location.hash = `#/messages/${value}`;
  });
  const list = h("div");
  root.append(h("h2", {}, "메시지"), h("div", { class: "card" }, username), list);
  api("GET", "/messages")
    .then((conversations) => {
      if (!conversations.length) list.append(h("div", { class: "empty" }, "대화가 없습니다"));
      for (const c of conversations) {
        const mine = c.last_message.sender.id === state.me.id;
        list.append(h("a", { href: `#/messages/${c.user.username}`, class: `card notification${c.unread_count ? " unread" : ""}`, style: "display:block;color:inherit;text-decoration:none" },
          h("div", { class: "user-row" },
            h("b", {}, c.user.display_name),
            c.unread_count ? h("span", { class: "badge" }, c.unread_count) : h("span", { class: "meta" }, timeAgo(c.last_message.created_at))),
          h("div", { class: "meta" }, `${mine ? "나: " : ""}${c.last_message.content}`)));
      }
    })
    .catch((err) => toast(err.message));
}

async function renderConversation(root, username) {
  const other = await api("GET", `/users/${username}`).catch((err) => {
    root.append(h("div", { class: "empty" }, err.message));
    return null;
  });
  if (!other) return;
  const thread = h("div", { class: "card" });
  const olderBtn = h("button", { onclick: () => load(cursor) }, "이전 메시지");
  const olderRow = h("div", { class: "row", style: "justify-content:center;margin:0 0 8px" }, olderBtn);
  olderRow.hidden = true;
  let cursor = null;

  function bubble(m) {
    const mine = m.sender.id === state.me.id;
    return h("div", { class: `bubble ${mine ? "mine" : "theirs"}` },
      m.content,
      h("span", { class: "meta" }, timeAgo(m.created_at), m.via ? ` · via ${m.via}` : "", mine && m.read ? " · 읽음" : ""));
  }

  async function load(before) {
    try {
      const page = await api("GET", `/messages/${other.username}${qs({ cursor: before })}`);
      const nodes = page.items.slice().reverse().map(bubble);
      if (before == null) thread.replaceChildren(olderRow, ...nodes);
      else olderRow.after(...nodes);
      if (before == null && !nodes.length) thread.append(h("div", { class: "empty" }, "첫 메시지를 보내보세요"));
      cursor = page.next_cursor;
      olderRow.hidden = cursor == null;
      refreshBadges();
    } catch (err) {
      toast(err.message);
    }
  }

  const input = h("textarea", { maxlength: 1000, placeholder: "메시지 입력" });
  const send = h("button", { class: "primary", onclick: async () => {
    const content = input.value.trim();
    if (!content) return;
    try {
      const message = await api("POST", `/messages/${other.username}`, { content });
      thread.querySelector(".empty")?.remove();
      thread.append(bubble(message));
      input.value = "";
    } catch (err) {
      toast(err.message);
    }
  } }, "보내기");

  root.append(
    h("div", { class: "row", style: "margin:0 0 12px" },
      h("h2", { style: "margin:0" }, other.display_name, " ", h("a", { class: "meta", href: `#/u/${other.username}` }, `@${other.username}`)),
      h("a", { href: "#/messages" }, "목록")),
    thread,
    h("div", { class: "card" }, input, h("div", { class: "row", style: "justify-content:flex-end" }, send)),
  );
  load(null);
}

function connectionGuide(token, mcpUrl) {
  const claudeCode = `claude mcp add --transport http kanbikang ${mcpUrl} --header "Authorization: Bearer ${token}"`;
  const desktopConfig = JSON.stringify({
    mcpServers: {
      kanbikang: {
        command: "npx",
        args: ["-y", "mcp-remote", mcpUrl, "--header", "Authorization:${SNS_AUTH}"],
        env: { SNS_AUTH: `Bearer ${token}` },
      },
    },
  }, null, 2);
  return h("div", { class: "card" },
    h("h3", {}, "토큰이 발급되었습니다"),
    h("p", { class: "meta" }, "이 토큰은 지금 한 번만 표시됩니다. 아래 설정에 붙여넣은 뒤 이 화면을 닫으세요."),
    codeBlock(token),
    h("div", { class: "section-title" }, "Claude Code"),
    codeBlock(claudeCode),
    h("div", { class: "section-title" }, "Claude Desktop (claude_desktop_config.json)"),
    codeBlock(desktopConfig),
    h("div", { class: "section-title" }, "기타 MCP 클라이언트 (Streamable HTTP)"),
    codeBlock(`URL: ${mcpUrl}\nHeader: Authorization: Bearer ${token}`),
  );
}

const SCOPE_LABELS = { read: "읽기", write: "쓰기", dm: "DM" };

function renderAI(root) {
  const mcpUrl = `${location.origin}/mcp`;
  root.append(h("div", { class: "card" },
    h("h2", {}, "AI 비서 연결"),
    h("p", {}, "개인 API 토큰을 발급해 Claude 같은 AI 비서를 MCP(Model Context Protocol)로 연결합니다. ",
      "연결된 AI 비서는 이 계정의 권한으로 피드를 읽고, 글과 댓글을 쓰고, 메시지를 보낼 수 있습니다."),
    h("p", { class: "meta" }, "AI 비서가 만든 글, 댓글, 메시지에는 'via 토큰이름'이 표시됩니다. 토큰은 언제든 폐기할 수 있습니다."),
    h("label", {}, "MCP 엔드포인트"),
    h("pre", { class: "code" }, mcpUrl),
    h("p", { class: "meta" }, "REST API 문서: ", h("a", { href: "/docs", target: "_blank" }, "/docs")),
  ));

  const name = h("input", { type: "text", maxlength: 50, value: "Claude" });
  const read = checkbox("읽기 (피드, 프로필, 알림)", true, true);
  const write = checkbox("쓰기 (글, 댓글, 좋아요, 팔로우)", true);
  const dm = checkbox("DM (메시지 읽기/보내기)", false);
  const result = h("div");
  const issue = h("button", { class: "primary", onclick: async () => {
    const scopes = ["read"];
    if (write.input.checked) scopes.push("write");
    if (dm.input.checked) scopes.push("dm");
    issue.disabled = true;
    try {
      const created = await api("POST", "/tokens", { name: name.value.trim(), scopes });
      result.replaceChildren(connectionGuide(created.token, mcpUrl));
      loadTokens();
    } catch (err) {
      toast(err.message);
    } finally {
      issue.disabled = false;
    }
  } }, "토큰 발급");

  root.append(h("div", { class: "card" },
    h("h3", {}, "새 토큰"),
    h("label", {}, "이름 (게시물에 'via 이름'으로 표시)"), name,
    h("label", {}, "권한"),
    h("div", { class: "checks" }, read.label, write.label, dm.label),
    h("div", { class: "row", style: "justify-content:flex-end" }, issue),
  ), result);

  const tokens = h("div");
  root.append(h("div", { class: "section-title" }, "발급한 토큰"), tokens);

  async function loadTokens() {
    try {
      const list = await api("GET", "/tokens");
      tokens.replaceChildren();
      if (!list.length) tokens.append(h("div", { class: "empty" }, "발급한 토큰이 없습니다"));
      for (const t of list) {
        tokens.append(h("div", { class: "card user-row" },
          h("div", {},
            h("b", {}, t.name), " ", h("span", { class: "meta" }, `${t.prefix}...`),
            h("div", { class: "meta" },
              `권한: ${Object.keys(SCOPE_LABELS).filter((s) => t.scopes.includes(s)).map((s) => SCOPE_LABELS[s]).join(", ")} · 발급 ${timeAgo(t.created_at)} · `,
              t.last_used_at ? `마지막 사용 ${timeAgo(t.last_used_at)}` : "사용 기록 없음")),
          h("button", { class: "danger", onclick: async () => {
            if (!confirm(`'${t.name}' 토큰을 폐기할까요? 이 토큰을 쓰는 AI 비서는 더 이상 접근할 수 없습니다.`)) return;
            try {
              await api("DELETE", `/tokens/${t.id}`);
              loadTokens();
            } catch (err) {
              toast(err.message);
            }
          } }, "폐기"),
        ));
      }
    } catch (err) {
      toast(err.message);
    }
  }
  loadTokens();

  const tools = h("div", { class: "card" }, h("h3", {}, "AI 비서가 사용할 수 있는 도구"));
  root.append(tools);
  api("GET", "/ai/tools")
    .then((list) => {
      for (const scope of ["read", "write", "dm"]) {
        tools.append(
          h("div", { class: "section-title" }, `${SCOPE_LABELS[scope]} 권한`),
          h("ul", { class: "tool-list" },
            list.filter((t) => t.scope === scope).map((t) => h("li", {}, h("code", {}, t.name), ` ${t.title}`))),
        );
      }
    })
    .catch((err) => toast(err.message));
}

// Router

const routes = [
  [/^#\/login$/, (root) => renderAuth(root, "login")],
  [/^#\/register$/, (root) => renderAuth(root, "register")],
  [/^#\/?$/, renderHome],
  [/^#\/explore$/, renderExplore],
  [/^#\/tag\/(.+)$/, (root, m) => renderTag(root, decodeURIComponent(m[1]))],
  [/^#\/me$/, (root) => renderProfile(root, state.me.username)],
  [/^#\/u\/(\w+)$/, (root, m) => renderProfile(root, m[1])],
  [/^#\/p\/(\d+)$/, (root, m) => renderPost(root, Number(m[1]))],
  [/^#\/notifications$/, renderNotifications],
  [/^#\/messages$/, renderMessages],
  [/^#\/messages\/(\w+)$/, (root, m) => renderConversation(root, m[1])],
  [/^#\/ai$/, renderAI],
];

function setBadge(id, count) {
  const el = document.getElementById(id);
  el.textContent = count;
  el.hidden = !count;
}

async function refreshBadges() {
  if (!state.token) return;
  try {
    const counts = await api("GET", "/me/unread");
    setBadge("badge-notifications", counts.notifications);
    setBadge("badge-messages", counts.messages ?? 0);
  } catch {
    // Badges are best effort.
  }
}

async function route() {
  const hash = location.hash || "#/";
  const isAuthPage = hash === "#/login" || hash === "#/register";
  if (!state.token && !isAuthPage) {
    location.hash = "#/login";
    return;
  }
  if (state.token && isAuthPage) {
    location.hash = "#/";
    return;
  }
  if (state.token && !state.me) {
    try {
      state.me = await api("GET", "/me");
    } catch {
      return;
    }
  }

  document.getElementById("topbar").hidden = !state.token;
  const section = hash.split("/")[1] || "home";
  for (const link of document.querySelectorAll("[data-nav]")) {
    link.classList.toggle("active", link.dataset.nav === section || (section === "u" && link.dataset.nav === "me" && hash === `#/u/${state.me?.username}`));
  }

  const app = document.getElementById("app");
  const root = h("div");
  app.replaceChildren(root);
  for (const [pattern, view] of routes) {
    const match = hash.match(pattern);
    if (match) {
      view(root, match);
      refreshBadges();
      return;
    }
  }
  root.append(h("div", { class: "empty" }, "페이지를 찾을 수 없습니다"));
}

document.getElementById("logout").addEventListener("click", async () => {
  try {
    await api("POST", "/auth/logout");
  } catch {
    // The session may already be gone; log out locally regardless.
  }
  setToken(null);
  location.hash = "#/login";
});

window.addEventListener("hashchange", route);
setInterval(refreshBadges, 30000);
route();
