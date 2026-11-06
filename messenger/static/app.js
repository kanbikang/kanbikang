"use strict";

const state = {
  token: localStorage.getItem("kbk_token"),
  me: null,
  conversations: new Map(), // id -> ConversationOut
  chat: null, // controller of the open conversation
  ws: null,
  wsRetry: 0,
};

// Helpers

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

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function timeOf(iso) {
  return new Date(iso).toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" });
}

function dayOf(iso) {
  return new Date(iso).toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "long" });
}

function listTime(iso) {
  const date = new Date(iso);
  return date.toDateString() === new Date().toDateString()
    ? timeOf(iso)
    : date.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}

function qs(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
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
  const res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && state.token) signOut();
    throw new ApiError(res.status, errorMessage(data) || `요청에 실패했습니다 (${res.status})`);
  }
  return data;
}

function setToken(token) {
  state.token = token;
  state.me = null;
  if (token) localStorage.setItem("kbk_token", token);
  else localStorage.removeItem("kbk_token");
}

function signOut() {
  disconnect();
  setToken(null);
  state.conversations.clear();
  state.chat = null;
  location.hash = "#/login";
}

// Conversation list

async function loadConversations() {
  const list = await api("GET", "/conversations?limit=100");
  state.conversations = new Map(list.map((c) => [c.id, c]));
  renderConversationList();
}

const reloadConversations = debounce(() => loadConversations().catch(() => {}), 200);

function sortedConversations() {
  return [...state.conversations.values()].sort(
    (a, b) => (b.last_message?.id ?? 0) - (a.last_message?.id ?? 0) || b.id - a.id,
  );
}

function previewText(conversation) {
  const m = conversation.last_message;
  if (!m) return "아직 메시지가 없습니다";
  if (m.deleted) return "삭제된 메시지입니다";
  if (m.kind === "system") return m.content;
  if (m.sender?.id === state.me.id) return `나: ${m.content}`;
  return conversation.kind === "group" ? `${m.sender.display_name}: ${m.content}` : m.content;
}

function renderConversationList() {
  const root = document.getElementById("conversation-list");
  const items = sortedConversations();
  root.replaceChildren(...(items.length
    ? items.map((c) => h("a", { href: `#/c/${c.id}`, class: `conversation-item${state.chat?.id === c.id ? " active" : ""}` },
      h("div", { class: "top" },
        h("span", { class: "title" }, c.title, c.kind === "group" ? h("span", { class: "member-count" }, c.members.length) : null),
        h("span", { class: "time" }, c.last_message ? listTime(c.last_message.created_at) : "")),
      h("div", { class: "bottom" },
        h("span", { class: "preview" }, previewText(c)),
        c.unread_count ? h("span", { class: "badge" }, c.unread_count > 99 ? "99+" : c.unread_count) : null)))
    : [h("div", { class: "empty" }, "대화가 없습니다. '새 대화'로 시작하세요.")]));
  const total = items.reduce((sum, c) => sum + c.unread_count, 0);
  document.title = total ? `(${total}) Kanbikang` : "Kanbikang";
}

// Realtime

function connect() {
  if (!state.token || state.ws) return;
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  state.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({ token: state.token }));
  ws.onmessage = (event) => handleEvent(JSON.parse(event.data));
  ws.onclose = (event) => {
    if (state.ws !== ws) return; // Replaced or closed on purpose.
    state.ws = null;
    if (!state.token) return;
    if (event.code === 4401) {
      signOut();
      return;
    }
    document.getElementById("connection").hidden = false;
    setTimeout(connect, Math.min(30000, 1000 * 2 ** state.wsRetry++));
  };
}

function disconnect() {
  const ws = state.ws;
  state.ws = null;
  ws?.close();
}

function handleEvent(event) {
  switch (event.type) {
    case "ready": {
      const reconnected = state.wsRetry > 0;
      state.wsRetry = 0;
      document.getElementById("connection").hidden = true;
      if (reconnected) {
        reloadConversations();
        state.chat?.reload();
      }
      break;
    }
    case "message":
      onMessage(event.message);
      break;
    case "message_updated":
      onMessageUpdated(event.message);
      break;
    case "read":
      if (event.user_id === state.me.id) reloadConversations();
      if (state.chat?.id === event.conversation_id) state.chat.refreshReadCounts();
      break;
    case "conversation":
      reloadConversations();
      if (state.chat?.id === event.conversation_id) state.chat.refreshInfo();
      break;
  }
}

function onMessage(message) {
  const conversation = state.conversations.get(message.conversation_id);
  if (!conversation) {
    reloadConversations();
  } else if (!conversation.last_message || conversation.last_message.id <= message.id) {
    const isNew = conversation.last_message?.id !== message.id;
    conversation.last_message = message;
    const viewing = state.chat?.id === conversation.id && document.visibilityState === "visible";
    if (isNew && message.kind === "text" && message.sender?.id !== state.me.id && !viewing) conversation.unread_count += 1;
    renderConversationList();
  }
  if (state.chat?.id === message.conversation_id) state.chat.addMessage(message);
}

function onMessageUpdated(message) {
  const conversation = state.conversations.get(message.conversation_id);
  if (conversation?.last_message?.id === message.id) {
    conversation.last_message = message;
    renderConversationList();
  }
  if (state.chat?.id === message.conversation_id) state.chat.updateMessage(message);
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") state.chat?.markRead();
});

// Chat view

function renderChat(main, conversationId) {
  const chat = {
    id: conversationId,
    conversation: null,
    messages: [],
    olderCursor: null,
    replyTo: null,
    editingId: null,
    editDraft: "",
  };
  state.chat = chat;
  const isCurrent = () => state.chat === chat;

  const titleEl = h("div", { class: "title" });
  const subEl = h("div", { class: "sub" });
  const actionsEl = h("div", { class: "actions" });
  const panel = h("div", { class: "panel" });
  panel.hidden = true;
  const list = h("div", { class: "messages" });
  const input = h("textarea", { rows: 1, maxlength: 2000, placeholder: "메시지 입력", title: "Enter 전송, Shift+Enter 줄바꿈" });
  const sendBtn = h("button", { class: "primary", onclick: send }, "전송");
  const replyBar = h("div", { class: "reply-bar" });
  replyBar.hidden = true;

  main.append(
    h("div", { class: "chat-head" },
      h("div", { style: "min-width:0" }, h("a", { class: "back", href: "#/" }, "목록 "), titleEl, subEl),
      actionsEl),
    panel,
    list,
    h("div", { class: "composer" }, replyBar, h("div", { class: "row" }, input, sendBtn)),
  );

  function autosize() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight + 2, 160)}px`;
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (event) => {
    // isComposing: Enter that confirms a Korean IME syllable must not send the message.
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      send();
    }
  });

  function renderHead() {
    const c = chat.conversation;
    titleEl.replaceChildren(c.title);
    if (c.kind === "group") titleEl.append(h("span", { class: "member-count" }, c.members.length));
    subEl.textContent = c.kind === "group"
      ? c.members.map((m) => m.display_name).join(", ")
      : `@${c.members.find((m) => m.id !== state.me.id)?.username ?? ""}`;
    actionsEl.replaceChildren(...(c.kind === "group" ? [
      h("button", { class: "small", onclick: toggleInvite }, "초대"),
      h("button", { class: "small", onclick: rename }, "이름 변경"),
      h("button", { class: "small danger", onclick: leave }, "나가기"),
    ] : []));
  }

  function toggleInvite() {
    if (!panel.hidden) {
      panel.hidden = true;
      return;
    }
    const search = h("input", { type: "search", placeholder: "초대할 사람의 이름 또는 아이디" });
    const results = h("div");
    const run = debounce(async () => {
      const q = search.value.trim();
      if (!q) {
        results.replaceChildren();
        return;
      }
      try {
        const users = await api("GET", `/users${qs({ q })}`);
        const memberIds = new Set(chat.conversation.members.map((m) => m.id));
        results.replaceChildren(...users.filter((u) => !memberIds.has(u.id)).map((u) => h("div", { class: "user-row" },
          h("div", {}, h("span", { class: "name" }, u.display_name), " ", h("span", { class: "meta" }, `@${u.username}`)),
          h("button", { class: "small primary", onclick: async () => {
            try {
              chat.conversation = await api("POST", `/conversations/${chat.id}/members`, { usernames: [u.username] });
              renderHead();
              panel.hidden = true;
            } catch (err) {
              toast(err.message);
            }
          } }, "초대"))));
      } catch (err) {
        toast(err.message);
      }
    }, 250);
    search.addEventListener("input", run);
    panel.replaceChildren(search, results);
    panel.hidden = false;
    search.focus();
  }

  async function rename() {
    const title = prompt("새 그룹 이름", chat.conversation.title);
    if (!title || !title.trim()) return;
    try {
      chat.conversation = await api("PATCH", `/conversations/${chat.id}`, { title: title.trim() });
      renderHead();
    } catch (err) {
      toast(err.message);
    }
  }

  async function leave() {
    if (!confirm("이 대화방에서 나갈까요? 나가면 대화 내용을 볼 수 없습니다.")) return;
    try {
      await api("DELETE", `/conversations/${chat.id}/members/me`);
      state.conversations.delete(chat.id);
      location.hash = "#/";
    } catch (err) {
      toast(err.message);
    }
  }

  function setReply(message) {
    chat.replyTo = message;
    replyBar.hidden = !message;
    if (message) {
      replyBar.replaceChildren(
        h("span", {}, `답장: ${message.sender?.display_name ?? ""} - ${message.content}`),
        h("button", { class: "link", onclick: () => setReply(null) }, "취소"));
      input.focus();
    }
  }

  async function send() {
    const content = input.value.trim();
    if (!content) return;
    sendBtn.disabled = true;
    try {
      const message = await api("POST", `/conversations/${chat.id}/messages`, { content, reply_to_id: chat.replyTo?.id ?? null });
      input.value = "";
      autosize();
      setReply(null);
      onMessage(message);
      render("bottom");
    } catch (err) {
      toast(err.message);
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  function startEdit(message) {
    chat.editingId = message.id;
    chat.editDraft = message.content;
    render("keep");
    list.querySelector(".msg textarea")?.focus();
  }

  function editor(message) {
    const field = h("textarea", { maxlength: 2000, value: chat.editDraft, style: "min-width:240px" });
    const cancel = () => {
      chat.editingId = null;
      render("keep");
    };
    const save = async () => {
      try {
        const updated = await api("PATCH", `/messages/${message.id}`, { content: field.value });
        chat.editingId = null;
        chat.updateMessage(updated);
      } catch (err) {
        toast(err.message);
      }
    };
    field.addEventListener("input", () => { chat.editDraft = field.value; });
    field.addEventListener("keydown", (event) => {
      if (event.key === "Escape") cancel();
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        save();
      }
    });
    return h("div", {}, field, h("div", { class: "row end" },
      h("button", { class: "small", onclick: cancel }, "취소"),
      h("button", { class: "small primary", onclick: save }, "저장")));
  }

  async function remove(message) {
    if (!confirm("메시지를 삭제할까요? 대화방의 모든 사람에게서 삭제됩니다.")) return;
    try {
      chat.updateMessage(await api("DELETE", `/messages/${message.id}`));
    } catch (err) {
      toast(err.message);
    }
  }

  function messageNode(m, prev) {
    if (m.kind === "system") return h("div", { class: "system" }, h("span", {}, m.content));
    const mine = m.sender?.id === state.me.id;
    const continued = prev && prev.kind === "text" && prev.sender?.id === m.sender?.id;
    const showSender = !mine && chat.conversation.kind === "group" && !continued;
    const bubble = chat.editingId === m.id
      ? editor(m)
      : h("div", { class: `bubble${m.deleted ? " deleted" : ""}` },
        m.reply_to ? h("div", { class: "quote" },
          `${m.reply_to.sender?.display_name ?? ""}: ${m.reply_to.deleted ? "삭제된 메시지" : m.reply_to.content}`) : null,
        m.deleted ? "삭제된 메시지입니다" : m.content);
    const node = h("div", { class: `msg${mine ? " mine" : ""}`, "data-id": m.id },
      showSender ? h("div", { class: "sender" }, m.sender?.display_name ?? "알 수 없음") : null,
      h("div", { class: "line" },
        bubble,
        h("div", { class: "side" },
          m.unread_count ? h("span", { class: "unread", title: "아직 읽지 않은 사람 수" }, m.unread_count) : null,
          m.via ? h("span", { class: "via", title: "AI 비서 또는 API로 보낸 메시지" }, `via ${m.via}`) : null,
          m.edited_at && !m.deleted ? h("span", {}, "수정됨") : null,
          h("span", {}, timeOf(m.created_at))),
        m.deleted || chat.editingId === m.id ? null : h("div", { class: "msg-actions" },
          h("button", { class: "link", onclick: () => setReply(m) }, "답장"),
          mine ? h("button", { class: "link", onclick: () => startEdit(m) }, "수정") : null,
          mine ? h("button", { class: "link danger", onclick: () => remove(m) }, "삭제") : null)));
    // Touch screens have no hover: tapping a bubble reveals its actions.
    if (chat.editingId !== m.id) bubble.addEventListener("click", () => node.classList.toggle("selected"));
    return node;
  }

  // mode: "bottom" scrolls to the newest message, "prepend" keeps the view steady after older
  // messages are inserted above, "keep" leaves the position alone unless already at the bottom.
  function render(mode = "keep") {
    if (!isCurrent()) return;
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
    const prevHeight = list.scrollHeight;
    const prevTop = list.scrollTop;
    const nodes = [];
    if (chat.olderCursor) {
      nodes.push(h("div", { class: "load-older" }, h("button", { class: "small", onclick: loadOlder }, "이전 메시지 불러오기")));
    }
    let lastDay = null;
    let prev = null;
    for (const m of chat.messages) {
      const day = new Date(m.created_at).toDateString();
      if (day !== lastDay) {
        nodes.push(h("div", { class: "day" }, dayOf(m.created_at)));
        lastDay = day;
        prev = null;
      }
      nodes.push(messageNode(m, prev));
      prev = m;
    }
    if (!chat.messages.length) nodes.push(h("div", { class: "empty" }, "첫 메시지를 보내보세요"));
    list.replaceChildren(...nodes);
    if (mode === "bottom" || (mode === "keep" && nearBottom)) list.scrollTop = list.scrollHeight;
    else if (mode === "prepend") list.scrollTop = prevTop + (list.scrollHeight - prevHeight);
    else list.scrollTop = prevTop;
  }

  async function loadOlder() {
    try {
      const page = await api("GET", `/conversations/${chat.id}/messages${qs({ before: chat.olderCursor, limit: 50 })}`);
      if (!isCurrent()) return;
      chat.messages = [...page.items, ...chat.messages];
      chat.olderCursor = page.next_cursor;
      render("prepend");
    } catch (err) {
      toast(err.message);
    }
  }

  chat.addMessage = (message) => {
    const index = chat.messages.findIndex((m) => m.id === message.id);
    if (index >= 0) chat.messages[index] = message;
    else {
      chat.messages.push(message);
      chat.messages.sort((a, b) => a.id - b.id);
    }
    render("keep");
    if (message.sender?.id !== state.me.id) chat.markRead();
  };

  chat.updateMessage = (message) => {
    const index = chat.messages.findIndex((m) => m.id === message.id);
    if (index >= 0) {
      chat.messages[index] = message;
      render("keep");
    }
  };

  chat.markRead = debounce(async () => {
    if (!isCurrent() || document.visibilityState !== "visible" || !chat.messages.length) return;
    try {
      const updated = await api("POST", `/conversations/${chat.id}/read`, {});
      state.conversations.set(updated.id, updated);
      renderConversationList();
    } catch {
      // Read receipts are best effort.
    }
  }, 300);

  chat.refreshReadCounts = debounce(async () => {
    if (!isCurrent() || !chat.messages.length) return;
    try {
      const page = await api("GET", `/conversations/${chat.id}/messages${qs({ limit: Math.min(chat.messages.length, 100) })}`);
      const counts = new Map(page.items.map((m) => [m.id, m.unread_count]));
      for (const m of chat.messages) if (counts.has(m.id)) m.unread_count = counts.get(m.id);
      render("keep");
    } catch {
      // Read receipts are best effort.
    }
  }, 300);

  chat.refreshInfo = debounce(async () => {
    try {
      chat.conversation = await api("GET", `/conversations/${chat.id}`);
      if (isCurrent()) renderHead();
    } catch (err) {
      if (isCurrent() && err.status === 404) location.hash = "#/";
    }
  }, 200);

  chat.reload = async () => {
    try {
      const [conversation, page] = await Promise.all([
        api("GET", `/conversations/${chat.id}`),
        api("GET", `/conversations/${chat.id}/messages${qs({ limit: 50 })}`),
      ]);
      if (!isCurrent()) return;
      chat.conversation = conversation;
      chat.messages = page.items;
      chat.olderCursor = page.next_cursor;
      renderHead();
      render("bottom");
      chat.markRead();
    } catch (err) {
      if (!isCurrent()) return;
      main.replaceChildren(h("div", { class: "placeholder" }, err.message));
    }
  };

  chat.reload().then(() => input.focus());
}

// Other views. Each receives the main pane, already attached and empty.

function pageShell(main, title) {
  const page = h("div", { class: "page" });
  page.append(h("div", { class: "row start", style: "margin:0 0 12px" },
    h("a", { class: "back", href: "#/" }, "목록"), h("h2", { style: "margin:0" }, title)));
  main.append(page);
  return page;
}

function userRow(user, ...actions) {
  return h("div", { class: "user-row" },
    h("div", { style: "min-width:0" },
      h("span", { class: "name" }, user.display_name), " ", h("span", { class: "meta" }, `@${user.username}`),
      user.status_message ? h("div", { class: "meta" }, user.status_message) : null),
    h("div", { class: "row", style: "margin:0;flex-shrink:0" }, actions));
}

async function openDirect(username) {
  try {
    const conversation = await api("POST", "/conversations/direct", { username });
    state.conversations.set(conversation.id, conversation);
    location.hash = `#/c/${conversation.id}`;
  } catch (err) {
    toast(err.message);
  }
}

function renderNew(main) {
  const page = pageShell(main, "새 대화");
  const selected = new Map();
  const title = h("input", { type: "text", maxlength: 100, placeholder: "그룹 이름 (비워두면 참여자 이름으로 표시)" });
  const chips = h("div", { class: "chips" });
  const createBtn = h("button", { class: "primary", onclick: createGroup, disabled: true }, "그룹 만들기");
  const search = h("input", { type: "search", placeholder: "이름 또는 아이디로 사람 찾기" });
  const results = h("div");

  function renderChips() {
    chips.replaceChildren(...[...selected.values()].map((u) => h("span", { class: "chip" }, u.display_name,
      h("button", { "aria-label": `${u.display_name} 빼기`, onclick: () => { selected.delete(u.id); renderChips(); } }, "x"))));
    createBtn.disabled = selected.size === 0;
  }

  function showUsers(users, emptyText) {
    results.replaceChildren(...(users.filter((u) => !u.is_me).length
      ? users.filter((u) => !u.is_me).map((u) => userRow(u,
        h("button", { class: "small", onclick: () => openDirect(u.username) }, "1:1 대화"),
        h("button", { class: "small", onclick: () => { selected.set(u.id, u); renderChips(); } }, "그룹에 추가")))
      : [h("div", { class: "empty" }, emptyText)]));
  }

  const run = debounce(async () => {
    const q = search.value.trim();
    try {
      if (q) showUsers(await api("GET", `/users${qs({ q })}`), "검색 결과가 없습니다");
      else showUsers(await api("GET", "/contacts"), "친구가 없습니다. 이름이나 아이디로 검색하세요.");
    } catch (err) {
      toast(err.message);
    }
  }, 250);

  async function createGroup() {
    try {
      const conversation = await api("POST", "/conversations/group", {
        title: title.value.trim() || null,
        usernames: [...selected.values()].map((u) => u.username),
      });
      state.conversations.set(conversation.id, conversation);
      location.hash = `#/c/${conversation.id}`;
    } catch (err) {
      toast(err.message);
    }
  }

  search.addEventListener("input", run);
  page.append(
    h("div", { class: "card" }, search, h("div", { class: "section-title" }, "사람"), results),
    h("div", { class: "card" }, h("h3", {}, "그룹 만들기"), title,
      h("div", { class: "meta", style: "margin-top:8px" }, "위 목록에서 '그룹에 추가'로 참여자를 고르세요."),
      chips, h("div", { class: "row end" }, createBtn)),
  );
  run();
  search.focus();
}

function renderContacts(main) {
  const page = pageShell(main, "친구");
  const contacts = h("div");
  const search = h("input", { type: "search", placeholder: "이름 또는 아이디로 친구 찾기" });
  const results = h("div");

  async function load() {
    try {
      const list = await api("GET", "/contacts");
      contacts.replaceChildren(...(list.length ? list.map((u) => userRow(u,
        h("button", { class: "small primary", onclick: () => openDirect(u.username) }, "대화"),
        h("button", { class: "small danger", onclick: async () => {
          try {
            await api("DELETE", `/contacts/${u.username}`);
            load();
          } catch (err) {
            toast(err.message);
          }
        } }, "삭제"))) : [h("div", { class: "empty" }, "친구가 없습니다")]));
    } catch (err) {
      toast(err.message);
    }
  }

  const run = debounce(async () => {
    const q = search.value.trim();
    if (!q) {
      results.replaceChildren();
      return;
    }
    try {
      const users = (await api("GET", `/users${qs({ q })}`)).filter((u) => !u.is_me);
      results.replaceChildren(...(users.length ? users.map((u) => userRow(u, u.is_contact
        ? h("span", { class: "meta" }, "친구")
        : h("button", { class: "small", onclick: async () => {
          try {
            await api("PUT", `/contacts/${u.username}`);
            run();
            load();
          } catch (err) {
            toast(err.message);
          }
        } }, "친구 추가"))) : [h("div", { class: "empty" }, "검색 결과가 없습니다")]));
    } catch (err) {
      toast(err.message);
    }
  }, 250);
  search.addEventListener("input", run);

  page.append(h("div", { class: "card" }, search, results), h("div", { class: "card" }, contacts));
  load();
}

function renderSettings(main) {
  const page = pageShell(main, "설정");
  const name = h("input", { type: "text", maxlength: 50, value: state.me.display_name });
  const status = h("input", { type: "text", maxlength: 100, value: state.me.status_message, placeholder: "친구에게 보일 한 줄" });
  page.append(h("div", { class: "card" },
    h("label", {}, "아이디"), h("div", {}, `@${state.me.username}`),
    h("label", {}, "이름"), name,
    h("label", {}, "상태 메시지"), status,
    h("div", { class: "row end" }, h("button", { class: "primary", onclick: async () => {
      try {
        state.me = await api("PATCH", "/me", { display_name: name.value, status_message: status.value });
        toast("저장했습니다");
      } catch (err) {
        toast(err.message);
      }
    } }, "저장"))));
}

function checkbox(text, checked, disabled = false) {
  const input = h("input", { type: "checkbox", checked, disabled });
  return { input, label: h("label", {}, input, text) };
}

function radio(name, text, checked) {
  const input = h("input", { type: "radio", name, checked });
  return { input, label: h("label", {}, input, text) };
}

function codeBlock(text) {
  const copy = h("button", { class: "small", onclick: async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast("복사했습니다");
    } catch {
      toast("복사하지 못했습니다. 직접 선택해서 복사하세요.");
    }
  } }, "복사");
  return h("div", { style: "margin-bottom:8px" }, h("pre", { class: "code" }, text), h("div", { class: "row end", style: "margin-top:4px" }, copy));
}

function connectionGuide(token, mcpUrl) {
  const claudeCode = `claude mcp add --transport http kanbikang ${mcpUrl} --header "Authorization: Bearer ${token}"`;
  const desktopConfig = JSON.stringify({
    mcpServers: {
      kanbikang: {
        command: "npx",
        args: ["-y", "mcp-remote", mcpUrl, "--header", "Authorization:${KANBIKANG_AUTH}"],
        env: { KANBIKANG_AUTH: `Bearer ${token}` },
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

const SCOPE_LABELS = { read: "읽기", write: "쓰기" };

function renderAI(main) {
  const page = pageShell(main, "AI 비서 연결");
  const mcpUrl = `${location.origin}/mcp`;
  page.append(h("div", { class: "card" },
    h("p", { style: "margin-top:0" }, "개인 API 토큰을 발급해 Claude 같은 AI 비서를 MCP(Model Context Protocol)로 연결합니다. ",
      "연결된 AI 비서는 이 계정으로 대화를 읽고, 안 읽은 메시지를 정리하고, 메시지를 보낼 수 있습니다."),
    h("p", { class: "meta" }, "AI 비서가 보낸 메시지에는 'via 토큰이름'이 표시되어 대화 상대도 알 수 있습니다. ",
      "AI 비서가 메시지를 읽어도 읽음 처리되지 않으며, 토큰은 언제든 폐기할 수 있습니다."),
    h("label", {}, "MCP 엔드포인트"),
    h("pre", { class: "code" }, mcpUrl),
    h("p", { class: "meta" }, "REST API 문서: ", h("a", { href: "/docs", target: "_blank" }, "/docs")),
  ));

  const name = h("input", { type: "text", maxlength: 50, value: "Claude" });
  const read = checkbox("읽기: 대화방, 메시지, 친구 목록 보기", true, true);
  const write = checkbox("쓰기: 메시지 보내기/수정/삭제, 읽음 처리, 그룹 관리, 친구 관리", true);
  const all = radio("scope", "모든 대화방", true);
  const some = radio("scope", "선택한 대화방만", false);
  const picks = sortedConversations().map((c) => ({ id: c.id, ...checkbox(c.title, false) }));
  const pickList = h("div", { class: "checks", style: "margin:6px 0 0 24px" },
    picks.length ? picks.map((p) => p.label) : h("span", { class: "meta" }, "대화방이 없습니다"));
  pickList.hidden = true;
  all.input.addEventListener("change", () => { pickList.hidden = true; });
  some.input.addEventListener("change", () => { pickList.hidden = false; });

  const result = h("div");
  const issue = h("button", { class: "primary", onclick: async () => {
    const body = { name: name.value.trim(), scopes: write.input.checked ? ["read", "write"] : ["read"] };
    if (some.input.checked) body.conversation_ids = picks.filter((p) => p.input.checked).map((p) => p.id);
    issue.disabled = true;
    try {
      const created = await api("POST", "/tokens", body);
      result.replaceChildren(connectionGuide(created.token, mcpUrl));
      loadTokens();
    } catch (err) {
      toast(err.message);
    } finally {
      issue.disabled = false;
    }
  } }, "토큰 발급");

  page.append(h("div", { class: "card" },
    h("h3", {}, "새 토큰"),
    h("label", {}, "이름 (메시지에 'via 이름'으로 표시)"), name,
    h("label", {}, "권한"), h("div", { class: "checks" }, read.label, write.label),
    h("label", {}, "접근할 수 있는 대화방"), h("div", { class: "checks" }, all.label, some.label), pickList,
    h("div", { class: "row end" }, issue),
  ), result);

  const tokens = h("div", { class: "card" });
  page.append(h("div", { class: "section-title" }, "발급한 토큰"), tokens);

  function scopeText(token) {
    if (!token.conversation_ids) return "모든 대화방";
    const titles = token.conversation_ids.map((id) => state.conversations.get(id)?.title ?? `#${id}`);
    return `대화방 ${titles.length}개 (${titles.join(", ")})`;
  }

  async function loadTokens() {
    try {
      const list = await api("GET", "/tokens");
      tokens.replaceChildren(...(list.length ? list.map((t) => h("div", { class: "user-row" },
        h("div", { style: "min-width:0" },
          h("span", { class: "name" }, t.name), " ", h("span", { class: "meta" }, `${t.prefix}...`),
          h("div", { class: "meta" }, `${t.scopes.map((s) => SCOPE_LABELS[s]).join(", ")} · ${scopeText(t)}`),
          h("div", { class: "meta" }, `발급 ${listTime(t.created_at)} · `,
            t.last_used_at ? `마지막 사용 ${listTime(t.last_used_at)}` : "사용 기록 없음")),
        h("button", { class: "small danger", onclick: async () => {
          if (!confirm(`'${t.name}' 토큰을 폐기할까요? 이 토큰을 쓰는 AI 비서는 더 이상 접근할 수 없습니다.`)) return;
          try {
            await api("DELETE", `/tokens/${t.id}`);
            loadTokens();
          } catch (err) {
            toast(err.message);
          }
        } }, "폐기"))) : [h("div", { class: "empty" }, "발급한 토큰이 없습니다")]));
    } catch (err) {
      toast(err.message);
    }
  }
  loadTokens();

  const tools = h("div", { class: "card" }, h("h3", {}, "AI 비서가 사용할 수 있는 도구"));
  page.append(tools);
  api("GET", "/ai/tools")
    .then((list) => {
      for (const scope of ["read", "write"]) {
        tools.append(
          h("div", { class: "section-title" }, `${SCOPE_LABELS[scope]} 권한`),
          h("ul", { class: "tool-list" },
            list.filter((t) => t.scope === scope).map((t) => h("li", {}, h("code", {}, t.name), ` ${t.title}`))));
      }
    })
    .catch((err) => toast(err.message));
}

// Sign in

function renderAuth(mode) {
  const isLogin = mode === "login";
  const root = document.getElementById("auth");
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
      await loadConversations();
      connect();
      location.hash = "#/";
    } catch (err) {
      error.textContent = err.message;
    }
  }

  root.replaceChildren(h("form", { class: "card", onsubmit: submit },
    h("h2", {}, "Kanbikang"),
    h("p", { class: "meta" }, "AI 비서와 API로 연결되는 메신저"),
    h("label", {}, "아이디"), username,
    isLogin ? null : [h("label", {}, "이름"), displayName],
    h("label", {}, "비밀번호"), password,
    error,
    h("div", { class: "row" },
      h("a", { href: isLogin ? "#/register" : "#/login" }, isLogin ? "계정 만들기" : "이미 계정이 있습니다"),
      h("button", { class: "primary", type: "submit" }, isLogin ? "로그인" : "가입")),
  ));
  username.focus();
}

// Router

const routes = [
  [/^#\/?$/, null],
  [/^#\/c\/(\d+)$/, (main, m) => renderChat(main, Number(m[1]))],
  [/^#\/new$/, renderNew],
  [/^#\/contacts$/, renderContacts],
  [/^#\/ai$/, renderAI],
  [/^#\/settings$/, renderSettings],
];

async function route() {
  const hash = location.hash || "#/";
  const isAuthPage = hash === "#/login" || hash === "#/register";
  const authRoot = document.getElementById("auth");
  const shell = document.getElementById("shell");
  if (!state.token) {
    if (!isAuthPage) {
      location.hash = "#/login";
      return;
    }
    shell.hidden = true;
    authRoot.hidden = false;
    renderAuth(hash === "#/register" ? "register" : "login");
    return;
  }
  if (isAuthPage) {
    location.hash = "#/";
    return;
  }
  if (!state.me) {
    try {
      state.me = await api("GET", "/me");
      await loadConversations();
      connect();
    } catch {
      return;
    }
  }
  authRoot.hidden = true;
  shell.hidden = false;

  state.chat = null;
  const main = document.getElementById("main");
  main.replaceChildren();
  const section = hash.split("/")[1] || "";
  for (const link of document.querySelectorAll("[data-nav]")) link.classList.toggle("active", link.dataset.nav === section);

  const match = routes.find(([pattern]) => pattern.test(hash));
  const view = match ? match[1] : null;
  shell.classList.toggle("has-main", Boolean(view) || !match);
  if (!match) main.append(h("div", { class: "placeholder" }, "페이지를 찾을 수 없습니다"));
  else if (view) view(main, hash.match(match[0]));
  else main.append(h("div", { class: "placeholder" }, "대화를 선택하세요"));
  renderConversationList();
}

document.getElementById("logout").addEventListener("click", async () => {
  try {
    await api("POST", "/auth/logout");
  } catch {
    // The session may already be gone; sign out locally regardless.
  }
  signOut();
});

window.addEventListener("hashchange", route);
route();
