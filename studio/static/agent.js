"use strict";
// The Agent: a chat that plans and makes things with the studio's tools. Each thing it wants to make comes as a card
// with what it will make and about how long that takes; nothing renders until you allow it (unless "Ask before making"
// is off for the chat). Claude Code on this computer does the thinking; only text is sent to it.

const TOOL_NAMES = { make_picture: "Make a picture", edit_picture: "Edit a picture", animate_picture: "Animate a picture", make_clip: "Make a clip", start_film: "Start a film" };
const TOOL_TIME = { make_picture: a => 25 * (a.count || 1), edit_picture: () => 35, animate_picture: a => (a.seconds || 8.5) * 30, make_clip: a => (a.seconds || 8.5) * 30, start_film: () => 120 };

ROOMS.agent = { title: "Agent", full: true, async draw(root, arg) {
  const st = { chats: [], chat: null, busy: false, draft: "", ok: true, why: "" };
  const side = h("aside", { "aria-label": "Chats" }), msgs = h("div", { class: "msgs" }), bar = h("div", {});
  const main = h("div", { class: "main" }, msgs, bar);
  root.append(h("div", { class: "agent" }, side, main));

  async function loadList() {
    const r = await tryApi("/api/agent");
    if (!r) return;
    st.chats = r.chats; st.ok = r.state.ok; st.why = r.state.why;
    drawSide();
  }
  function drawSide() {
    side.replaceChildren(
      h("button", { class: "item", onclick: newChat }, h("span", { class: "ico" }, "+"), h("span", { class: "ti" }, "New chat")),
      h("button", { class: "item", onclick: () => go("writer") }, h("span", { class: "ico" }, "✎"), h("span", { class: "ti" }, "The Writer")),
      h("button", { class: "item", onclick: () => go("library") }, h("span", { class: "ico" }, "▤"), h("span", { class: "ti" }, "Library")),
      h("div", { class: "lbl" }, "Chats"),
      st.chats.length ? st.chats.map(c => h("button", { class: "item" + (st.chat && st.chat.id === c.id ? " on" : ""), onclick: () => go("agent", c.id), title: c.title },
        h("span", { class: "ti" }, c.title))) : h("div", { class: "faint small", style: { padding: "4px 10px" } }, "No chats yet."),
      h("div", { class: "tip" }, h("span", { class: "kicker" }, "How it works"), h("b", {}, "It asks before it renders"),
        "Each picture or clip it wants comes as a card with what it makes and about how long it takes. Allow it and it joins the queue; the result shows up in the chat."));
  }
  async function newChat() {
    const c = await tryApi("/api/agent", {});
    if (c) go("agent", c.id);
  }
  async function loadChat(id) {
    const c = await tryApi("/api/agent/" + id);
    if (!c) return go("agent");
    st.chat = c; drawMsgs(); drawBar(); drawSide();
  }
  function card(a) {
    const time = TOOL_TIME[a.tool] ? TOOL_TIME[a.tool](a) : 0;
    const kv = [];
    if (a.prompt) kv.push(["Prompt", a.prompt]);
    if (a.story) kv.push(["Story", a.story]);
    if (a.lines && a.lines.length) kv.push(["Lines", a.lines.map(l => (l.speaker ? l.speaker + ": " : "") + l.text).join("\n")]);
    if (a.sound) kv.push(["Sound", a.sound]);
    const facts = [a.tool === "make_picture" ? a.count + " × " + a.shape : null, a.tool === "make_clip" ? a.shape : null,
      a.seconds && a.tool !== "make_picture" ? a.seconds + " s" : null].filter(Boolean).join(" · ");
    const state = { proposed: ["wait", "Waiting for you"], queued: ["wait", "In the queue"], running: ["wait", a.progress || "Rendering…"], done: ["ok", "✓ Done"],
      failed: ["bad", "✕ " + (a.error || "failed")], denied: ["wait", "Turned down"] }[a.status] || ["wait", a.status];
    return h("div", { class: "actcard" },
      h("div", { class: "top" }, h("span", { class: "sh" }, "◈"), TOOL_NAMES[a.tool] || a.tool, facts ? h("span", { class: "muted small", style: { fontWeight: 400 } }, "· " + facts) : null),
      a.why ? h("div", { class: "muted small", style: { marginTop: "4px" } }, a.why) : null,
      a.source ? h("div", { class: "made" }, h("img", { src: a.source.thumb, alt: a.source.name, onclick: () => openAsset(a.source.id) })) : null,
      h("div", { class: "kv" }, kv.map(([k, v]) => [h("div", {}, h("div", { class: "k" }, k), h("div", { class: "v" }, v)), h("div")]),
        h("div", {}, h("div", { class: "k" }, "Takes about"), h("div", { class: "v" }, time ? secs(time) : "—")), h("div", { style: { textAlign: "right" } }, h("div", { class: "k" }, "Runs on"), h("div", { class: "v" }, a.tool === "start_film" ? "Claude (text)" : "this GPU"))),
      h("div", { class: "state " + state[0] }, state[0] === "wait" && ["queued", "running"].includes(a.status) ? h("span", { class: "thinking" }, h("i"), h("i"), h("i")) : null, state[1]),
      a.status === "proposed" ? h("div", { class: "row", style: { gap: "6px", marginTop: "10px" } },
        h("button", { class: "small primary", onclick: () => act(a, true) }, "Allow"), h("button", { class: "small", onclick: () => act(a, false) }, "Not now")) : null,
      a.status === "denied" ? h("button", { class: "small", style: { marginTop: "8px" }, onclick: () => act(a, true) }, "Allow after all") : null,
      a.status === "failed" && !a.writer ? h("button", { class: "small", style: { marginTop: "8px" }, onclick: () => act(a, true) }, "Try again") : null,
      a.writer ? h("button", { class: "small", style: { marginTop: "8px" }, onclick: () => go("writer", a.writer) }, a.status === "done" ? "Open it in the Writer →" : "Watch it in the Writer →") : null,
      a.assets && a.assets.length ? h("div", { class: "made" }, a.assets.map(x => isMov(x) ? h("video", { src: x.url, controls: true, preload: "metadata", poster: x.thumb })
        : h("img", { src: x.thumb, alt: x.name, onclick: () => openAsset(x.id) }))) : null);
  }
  function drawMsgs() {
    const c = st.chat;
    const inner = h("div", {});
    if (!c || !c.turns.length) {
      inner.append(h("div", { class: "welcome", style: { padding: "8vh 0 0", display: "flex", flexDirection: "column", alignItems: "center", gap: "12px", textAlign: "center" } },
        h("h1", { class: "display" }, "What should we ", h("span", { class: "lime" }, "make?")),
        h("p", { class: "muted", style: { maxWidth: "56ch" } }, "Ask for pictures, a clip, or a whole film. The agent plans it, shows you what it wants to render and how long it takes, and renders on this computer when you allow it."),
        st.ok ? null : h("div", { class: "note bad" }, "The agent needs Claude Code on this computer: " + st.why),
        h("div", { class: "row", style: { justifyContent: "center", gap: "8px", marginTop: "8px" } },
          ["Three portraits of a lighthouse keeper for a short film", "Animate my newest picture: slow push in, wind in the hair", "A 10 second clip of a fox crossing a snowy street at night", "Write a short film about a lost umbrella"].map(t =>
            h("button", { class: "small", onclick: () => { st.draft = t; drawBar(); } }, t)))));
    } else {
      for (const t of c.turns) {
        if (t.role === "user") inner.append(h("div", { class: "msg-user" }, h("div", {}, t.text)));
        else inner.append(h("div", { class: "msg-agent" }, h("div", { class: "av" }, "✦"), h("div", { class: "body" }, t.say ? h("div", { class: "say" }, t.say) : null, (t.actions || []).map(card))));
      }
    }
    if (st.busy) inner.append(h("div", { class: "msg-agent" }, h("div", { class: "av" }, "✦"), h("div", { class: "body" }, h("div", { class: "thinking" }, h("i"), h("i"), h("i"), "Thinking…"))));
    const atEnd = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 80;
    msgs.replaceChildren(inner);
    if (atEnd || st.busy) msgs.scrollTop = msgs.scrollHeight;
  }
  function drawBar() {
    const c = st.chat;
    const ask = !c || c.ask_first !== false;
    const ta = h("textarea", { rows: 2, placeholder: c && c.turns.length ? "Reply, or ask for something new…" : "Ask for something to make…", "aria-label": "Message" });
    ta.value = st.draft;
    ta.addEventListener("input", () => { st.draft = ta.value; });
    ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
    const tg = h("span", { class: "toggle" + (ask ? " on" : ""), role: "switch", tabindex: "0", "aria-checked": ask ? "true" : "false", title: "Show a card and wait for Allow before anything renders",
      onclick: async () => { if (!st.chat) { st.chat = await tryApi("/api/agent", {}); if (!st.chat) return; history.replaceState(null, "", "#agent/" + st.chat.id); }
        const r = await tryApi("/api/agent/" + st.chat.id, { ask_first: !(st.chat.ask_first !== false) }, "PATCH"); if (r) { st.chat = r; drawBar(); } } },
      h("span", { class: "sw" }), "Ask before making");
    bar.replaceChildren(h("div", { class: "dock" }, h("div", { class: "composer", style: { flexDirection: "column", gap: "6px" } },
      ta, h("div", { class: "agentbar" }, tg, h("div", { class: "row", style: { gap: "8px", alignItems: "center" } }, h("span", { class: "faint" }, "Enter sends · Shift+Enter: new line"),
        h("button", { class: "small primary", disabled: st.busy || !st.ok, "aria-label": "Send", onclick: send }, "↑ Send"))))));
    if (!st.busy) setTimeout(() => ta.focus(), 0);
  }
  async function send() {
    const textv = st.draft.trim();
    if (!textv || st.busy) return;
    if (!st.chat) { st.chat = await tryApi("/api/agent", {}); if (!st.chat) return; history.replaceState(null, "", "#agent/" + st.chat.id); }
    st.chat.turns.push({ role: "user", text: textv });
    st.busy = true; st.draft = ""; drawMsgs(); drawBar();
    const r = await tryApi(`/api/agent/${st.chat.id}/say`, { text: textv });
    st.busy = false;
    if (r) st.chat = r; else { st.chat.turns.pop(); st.draft = textv; }
    drawMsgs(); drawBar(); loadList(); poll();
  }
  async function act(a, allow) {
    const r = await tryApi(`/api/agent/${st.chat.id}/act`, { action: a.id, allow });
    if (r) { st.chat = r; drawMsgs(); if (allow) { toast("Queued"); poll(); } }
  }
  // follow running actions
  const timer = setInterval(async () => {
    if (!root.isConnected) return clearInterval(timer);
    if (!st.chat || st.busy) return;
    const live = st.chat.turns.some(t => (t.actions || []).some(a => ["queued", "running"].includes(a.status)));
    if (!live) return;
    const r = await api("/api/agent/" + st.chat.id).catch(() => null);
    if (r && root.isConnected) { st.chat = r; drawMsgs(); }
  }, 2500);
  await loadList();
  if (arg) await loadChat(arg); else { drawMsgs(); drawBar(); }
} };
