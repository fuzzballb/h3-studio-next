"use strict";
// H3 Studio: the page. No framework and no build step: `h()` makes elements, each room is a function that draws
// itself into #room, and one poll of /api/state keeps the queue and the gate up to date.

// ---------------------------------------------------------------- small helpers
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "value") e.value = v;
    else if (k === "checked" || k === "disabled" || k === "selected" || k === "hidden" || k === "multiple" || k === "controls" || k === "open") e[k] = !!v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return e;
}
const $ = (sel, root) => (root || document).querySelector(sel);
// Rooms build their content as nested lists with gaps (a part that does not apply is null). The DOM's own append and
// replaceChildren would print those as text, so here they take lists and skip the gaps, like h() does.
const flatKids = kids => kids.flat(Infinity).filter(k => k !== null && k !== undefined && k !== false);
for (const m of ["replaceChildren", "append", "prepend"]) {
  const orig = Element.prototype[m];
  Element.prototype[m] = function (...kids) { return orig.apply(this, flatKids(kids)); };
}

async function api(path, data, method) {
  const opt = { method: method || (data === undefined ? "GET" : "POST"), headers: {} };
  if (data !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(data); }
  let r;
  try { r = await fetch(path, opt); } catch (e) { throw new Error("the studio does not answer"); }
  const text = await r.text();
  let out;
  try { out = text ? JSON.parse(text) : {}; } catch (e) { out = { error: text.slice(0, 300) }; }
  if (!r.ok) throw new Error(out.error || ("HTTP " + r.status));
  return out;
}
async function tryApi(path, data, method) {      // the same, with the failure shown instead of thrown
  try { return await api(path, data, method); } catch (e) { toast(e.message, true); return null; }
}
function toast(text, bad) {
  const t = h("div", { class: "toast" + (bad ? " bad" : ""), role: bad ? "alert" : "status" }, text);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), bad ? 9000 : 3500);
}
function modal(content, narrow) {
  const m = $("#modal");
  m.replaceChildren(h("div", { class: "sheet" + (narrow ? " narrow" : ""), role: "dialog", "aria-modal": "true" }, content));
  m.hidden = false;
  m.onclick = e => { if (e.target === m) closeModal(); };
  const f = m.querySelector("input, textarea, select, button");
  if (f) f.focus();
}
function closeModal() { const m = $("#modal"); m.hidden = true; m.replaceChildren(); }
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#modal").hidden) closeModal(); });

const secs = s => s === null || s === undefined ? "" : (s >= 90 ? Math.floor(s / 60) + " min " + Math.round(s % 60) + " s" : (Math.round(s * 10) / 10) + " s");
const ago = t => { if (!t) return ""; const d = Date.now() / 1000 - t; return d < 60 ? "just now" : d < 3600 ? Math.floor(d / 60) + " min ago" : d < 86400 ? Math.floor(d / 3600) + " h ago" : new Date(t * 1000).toLocaleDateString(); };
const gb = b => (b / 2 ** 30).toFixed(b > 2 ** 33 ? 0 : 1) + " GB";
const media = rel => rel ? "/media/" + rel.split("/").map(encodeURIComponent).join("/") : "";
function refUrl(name) {
  if (!name) return "";
  if (name.endsWith(" [output]")) return media(name.slice(0, -9));
  return "/input/" + name.replace(/ \[input\]$/, "").split("/").map(encodeURIComponent).join("/");
}
const refThumb = name => name ? "/refthumb?name=" + encodeURIComponent(name) : "";
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
const clone = o => JSON.parse(JSON.stringify(o));

// ---------------------------------------------------------------- state
const S = {
  room: "home", arg: "", presets: null, state: { comfy: { up: false }, jobs: [], gate: [], busy: {} },
  pending: null,            // a form an app or a Library action hands to the next room
  watchers: [],             // room callbacks when a job ends: fn(job)
  seen: {},                 // job id -> last status, to notice endings
};
const ROOMS = {};           // name -> {title, draw(root, arg)}
// The top bar: the studios a thing is made in, then the film rooms; everything else is under More.
const NAV = [["home", "Explore"], ["picture", "Image"], ["video", "Video"], ["audio", "Audio"], ["remix", "Remix", "New"], ["shorts", "Shorts", "New"], "|",
  ["writer", "Writer"], ["films", "Films"], ["agent", "Agent", "New"], ["canvas", "Canvas"], ["apps", "Apps"]];
const MORE = [
  ["Make", [["edit", "Edit a picture", "◩"], ["nightshift", "Night shift", "☾"], ["cast", "Cast library", "☺"]]],
  ["Finish", [["timeline", "Timeline", "═"], ["sound", "Sound", "♪"], ["library", "Library", "▤"]]],
  ["Studio", [["machine", "Machine", "⚙"], ["learn", "Learn", "?"]]],
];
let QOPEN = false;
try { QOPEN = localStorage.getItem("h3next.queue") === "1"; } catch (e) { /* private window */ }
function setQueue(open) {
  QOPEN = open;
  try { localStorage.setItem("h3next.queue", open ? "1" : "0"); } catch (e) { /* not remembered */ }
  document.body.classList.toggle("qopen", open);
  drawSide();
}

function go(room, arg, pending) {
  if (pending !== undefined) S.pending = pending;
  const hash = "#" + room + (arg ? "/" + arg : "");
  if (location.hash === hash) route(); else location.hash = hash;
}
function route() {
  const [room, ...rest] = (location.hash.slice(1) || "home").split("/");
  S.room = ROOMS[room] ? room : "home";
  S.arg = rest.join("/");
  S.watchers = [];
  drawSide();
  const root = $("#room");
  root.replaceChildren();
  root.scrollTop = 0;
  const r = ROOMS[S.room];
  root.classList.toggle("full", !!(r.full && (typeof r.full !== "function" || r.full(S.arg))));
  document.title = r.title + " · H3 Studio";
  try { r.draw(root, S.arg); } catch (e) { root.classList.remove("full"); root.append(h("div", { class: "note bad" }, "This page failed to draw: " + e.message)); console.error(e); }
}
window.addEventListener("hashchange", route);

document.addEventListener("click", e => { const p = $(".morepop"); if (p && !p.hidden && !p.contains(e.target)) p.hidden = true; });
document.addEventListener("keydown", e => { const p = $(".morepop"); if (e.key === "Escape" && p) p.hidden = true; });
function drawSide() {
  const st = S.state, gate = st.gate.length;
  const live = st.jobs.filter(j => j.status === "running" || j.status === "queued").length;
  const pop = h("div", { class: "morepop", hidden: true, role: "menu" },
    MORE.map(([grp, items]) => [h("div", { class: "grp" }, grp), items.map(([id, label, ico]) => h("button", { class: S.room === id ? "on" : "", role: "menuitem",
      onclick: () => { pop.hidden = true; go(id); } }, h("span", { class: "ico" }, ico), label))]),
    h("div", { class: "grp" }, "ComfyUI"),
    h("button", { role: "menuitemcheckbox", "aria-checked": TERM.open ? "true" : "false", onclick: () => { pop.hidden = true; setTerm(!TERM.open); } },
      h("span", { class: "ico" }, "❯"), (TERM.open ? "Hide" : "Show") + " ComfyUI's output"));
  const more = h("button", { class: "iconbtn", title: "More", "aria-label": "More rooms", "aria-haspopup": "menu", onclick: e => { e.stopPropagation(); pop.hidden = !pop.hidden; } }, "☰");
  $("#top").replaceChildren(
    h("button", { class: "logo", onclick: () => go("home"), "aria-label": "H3 Studio, Explore" },
      h("span", { class: "mark", "aria-hidden": "true" }, (() => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("width", "16"); s.setAttribute("height", "16"); s.setAttribute("viewBox", "0 0 24 24");
        s.innerHTML = '<path d="M7 5v14l12-7z" fill="#131517"/>'; return s; })()),
      h("span", { class: "name" }, "H3 Studio"), h("span", { class: "ver" }, "next")),
    h("nav", { "aria-label": "Rooms" }, NAV.map(x => x === "|" ? h("span", { class: "sep" }) :
      h("button", { class: "navlink" + (S.room === x[0] ? " on" : ""), "aria-current": S.room === x[0] ? "page" : null, onclick: () => go(x[0]) }, x[1],
        x[0] === "films" && gate ? h("span", { class: "badge", title: gate + " take(s) at the gate" }, gate) : x[2] ? h("span", { class: "tag" + (x[2] === "New" ? " lime" : "") }, x[2]) : null))),
    h("div", { class: "right" },
      h("button", { class: "iconbtn" + (S.room === "library" ? " on" : ""), title: "Library", "aria-label": "Library", onclick: () => go("library") }, "▤"),
      h("button", { class: "queuebtn" + (live ? " busy" : ""), "aria-pressed": QOPEN ? "true" : "false", title: "The queue: what is rendering", onclick: () => setQueue(!QOPEN) },
        h("span", { class: "dot " + (st.comfy.up ? (live ? "" : "good") : "bad") }), live ? live + " rendering" : "Queue",
        gate ? h("span", { class: "badge", title: "at the gate" }, gate) : null),
      more),
    pop);
}

// ---------------------------------------------------------------- the queue, a drawer on the right
function jobCard(j) {
  const p = j.progress || {};
  const live = j.status === "running" || j.status === "queued";
  const res = j.result || {};
  const links = [];
  if (j.status === "done") {
    if (res.assets && res.assets.length) links.push(h("button", { class: "small", onclick: () => openAsset(res.assets[0]) }, "Open"));
    if (res.asset) links.push(h("button", { class: "small", onclick: () => openAsset(res.asset) }, "Open"));
    if (j.kind === "preview" && res.preview) links.push(h("button", { class: "small", onclick: () => playModal(media(res.preview) + "?t=" + Date.now(), j.title) }, "▶ Play"),
      h("button", { class: "small ghost", onclick: () => go("films", j.film + "/roll/" + res.shot) }, "The shot"));
    if (j.kind === "blockout" && res.blockout) links.push(h("button", { class: "small", onclick: () => playModal(refUrl(res.blockout), j.title) }, "▶ Play"),
      h("button", { class: "small ghost", onclick: () => go("films", j.film + "/blockout") }, "Cut into shots"));
    if (j.film && j.kind === "shot") links.push(h("button", { class: "small", onclick: () => openFilmOrClip(j.film) }, res.ok === false ? "Look at it" : "Open"));
    if (res.folder) links.push(h("span", { class: "small muted" }, "output/" + res.folder));
  }
  let line = j.status === "running" ? (p.text || "working") : j.status === "queued" ? "waiting" : j.status === "failed" ? (j.error || "failed") : j.status === "cancelled" ? "cancelled" :
    (res.summary || res.note || (res.seconds ? (j.kind === "export" ? "done: a cut of " : "done in ") + secs(res.seconds) : "done"));
  if (j.status === "running" && j.eta) { const left = j.eta - Date.now() / 1000; if (left > 5) line += " · about " + secs(left) + " left"; }
  return h("div", { class: "job " + j.status },
    h("div", { class: "t" }, h("b", { title: j.title }, j.title),
      h("button", { class: "ghost small", title: live ? "Cancel" : "Remove from the list", "aria-label": live ? "Cancel" : "Remove", onclick: async () => { await tryApi("/api/jobs/" + j.id, undefined, "DELETE"); poll(); } }, "✕")),
    j.status === "running" ? h("div", { class: "bar" + (p.max ? "" : " busy") }, h("i", { style: p.max ? { width: Math.round(100 * (p.value || 0) / p.max) + "%" } : {} })) : null,
    h("div", { class: "s" }, line, p.max && j.status === "running" ? " " + p.value + "/" + p.max : "",
      j.status === "done" && res.ok === false ? h("span", { class: "chip bad", style: { marginLeft: "6px" } }, "check failed") : null),
    links.length ? h("div", { class: "row", style: { marginTop: "6px", gap: "6px" } }, links) : null);
}
function drawQueue() {
  const st = S.state;
  const live = st.jobs.filter(j => j.status === "running" || j.status === "queued");
  // finished previews and blockouts: only the newest per shot (a new one overwrites the file the older card would play)
  const seenOut = new Set();
  const done = st.jobs.filter(j => !(j.status === "running" || j.status === "queued")).filter(j => {
    if (j.status !== "done" || (j.kind !== "preview" && j.kind !== "blockout")) return true;
    const k = j.kind + "/" + j.film + "/" + (j.kind === "blockout" ? j.title : j.shot);
    if (seenOut.has(k)) return false;
    seenOut.add(k); return true;
  }).slice(0, 14);
  $("#queue").replaceChildren(
    h("div", { class: "spread", style: { marginBottom: "10px" } }, h("h2", { style: { margin: 0 } }, "Queue"),
      h("button", { class: "ghost small", "aria-label": "Close the queue", onclick: () => setQueue(false) }, "✕")),
    h("div", { class: "spread", style: { marginBottom: "12px" } },
      h("div", { class: "pill" }, h("span", { class: "dot " + (st.comfy.up ? "good" : st.comfy.starting ? "warn" : "bad") }),
        st.comfy.up ? "ComfyUI is up" : st.comfy.starting ? "ComfyUI is starting…" : "ComfyUI does not answer"),
      st.comfy.up ? null : st.comfy.starting ? (TERM.open ? null : h("button", { class: "small", onclick: () => setTerm(true) }, "Show its output")) :
        h("button", { class: "small", onclick: async () => { toast("Starting ComfyUI…"); setTimeout(poll, 700); if (await tryApi("/api/machine/comfy", { action: "start" })) toast("ComfyUI is up"); poll(); } }, "Start it")),
    st.gate.length ? [h("h3", {}, "At the gate"), st.gate.map(g => h("div", { class: "job" },
      h("div", { class: "t" }, h("b", {}, g.film_name + " · " + (g.title || "shot " + g.index))),
      h("div", { class: "s" + (g.ok ? "" : " bad") }, g.ok ? "passed the automatic checks" : g.summary),
      h("div", { class: "row", style: { marginTop: "6px", gap: "6px" } },
        h("button", { class: "small primary", onclick: () => go("films", g.film + "/roll/" + g.shot) }, "Review"),
        h("button", { class: "small", onclick: async () => { if (await tryApi(`/api/films/${g.film}/approve/${g.shot}`, {})) { toast("Approved"); poll(); } } }, "Approve"))))] : null,
    h("h3", { style: { marginTop: st.gate.length ? "16px" : "0" } }, "Rendering"),
    live.length ? live.map(jobCard) : h("div", { class: "muted small", style: { marginBottom: "12px" } }, "Nothing is rendering."),
    done.length ? [h("div", { class: "spread", style: { margin: "14px 0 8px" } }, h("h3", { style: { margin: 0 } }, "Finished"),
      h("button", { class: "ghost small", onclick: async () => { await tryApi("/api/jobs/clear", { statuses: ["failed", "cancelled", "done"] }); poll(); } }, "Clear")), done.map(jobCard)] : null);
}
let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer);
  try {
    const st = await api("/api/state");
    const gateChanged = JSON.stringify(st.gate.map(g => g.shot + g.take)) !== JSON.stringify(S.state.gate.map(g => g.shot + g.take));
    S.state = st;
    for (const j of st.jobs) {
      const before = S.seen[j.id];
      S.seen[j.id] = j.status;
      if (before && before !== j.status && ["done", "failed", "cancelled"].includes(j.status)) {
        if (j.status === "failed") toast(j.title + ": " + (j.error || "failed"), true);
        for (const w of S.watchers) { try { w(j); } catch (e) { console.error(e); } }
      }
    }
    drawQueue();
    const live = st.jobs.filter(j => j.status === "running" || j.status === "queued").length;
    if (gateChanged || live !== S.live) { S.live = live; drawSide(); }
  } catch (e) {
    $("#queue").replaceChildren(h("div", { class: "note bad" }, "The studio's server does not answer. Start it again with ./run_studio.sh"));
  }
  const busy = S.state.comfy.starting || S.state.jobs.some(j => j.status === "running" || j.status === "queued");
  pollTimer = setTimeout(poll, busy ? 1200 : 4000);
}
function onJobEnd(fn) { S.watchers.push(fn); }

// ---------------------------------------------------------------- ComfyUI's terminal output, in the bottom half
// A switch in the menu. The studio's server hands over what ComfyUI printed last (or, while ComfyUI is loading or after
// it died, the end of its log file); this draws it the way a terminal would.
const TERM = { open: false, timer: null, shown: null, follow: true, out: null, grip: null, size: 50 };     // size: % of the window's height
try {
  TERM.open = localStorage.getItem("h3studio.term") === "1";
  const size = parseFloat(localStorage.getItem("h3studio.term.size"));
  if (size > 0) TERM.size = size;
} catch (e) { /* a private window: it starts closed, at half the window */ }
const TERM_MIN = 90, TERM_KEEP = 132;       // px: the least of the pane (its bar and three lines); the least left above it (the menu's top and its switch)
const TERM_COLORS = { 0: "var(--faint)", 1: "var(--bad)", 2: "var(--good)", 3: "var(--warn)", 4: "var(--info)", 5: "#c792ea", 6: "#6cc7c7", 7: "" };

function termNodes(text) {
  // A carriage return starts the line over, so of a progress bar only its last state shows. Colour codes colour the
  // text that follows them; every other control code is dropped.
  const out = [];
  let color = "", bold = false;
  const put = t => {
    t = t.replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
    if (t) out.push(color || bold ? h("span", { style: { color: color, fontWeight: bold ? "650" : "" } }, t) : t);
  };
  const code = /\x1b\[([0-9;?]*)([A-Za-z])/g;
  text.replace(/\r\n/g, "\n").split("\n").forEach((line, i) => {
    if (i) out.push("\n");
    const states = line.split("\r").filter(p => p.replace(code, "") !== "");
    line = states.length ? states[states.length - 1] : "";
    let at = 0, m;
    code.lastIndex = 0;
    while ((m = code.exec(line))) {
      put(line.slice(at, m.index));
      at = code.lastIndex;
      if (m[2] !== "m") continue;
      for (const c of (m[1] || "0").split(";").map(Number)) {
        if (c === 38 || c === 48) break;                      // a colour from a longer table: the numbers after it are its value
        if (c === 0) { color = ""; bold = false; } else if (c === 1) bold = true; else if (c === 22) bold = false; else if (c === 39) color = "";
        else if (c >= 30 && c <= 37) color = TERM_COLORS[c - 30]; else if (c >= 90 && c <= 97) color = TERM_COLORS[c - 90];
      }
    }
    put(line.slice(at));
  });
  return out;
}

function termSize(percent, keep) {
  // The pane's height as a share of the window. `keep` remembers it; without it the height is only shown (a drag in
  // progress, or a window that changed size).
  const win = window.innerHeight || 800;
  const px = Math.round(Math.min(Math.max(percent / 100 * win, TERM_MIN), Math.max(TERM_MIN, win - TERM_KEEP)));
  document.documentElement.style.setProperty("--term-h", px + "px");
  if (TERM.grip) TERM.grip.setAttribute("aria-valuenow", Math.round(px / win * 100));
  if (TERM.out && TERM.follow) TERM.out.scrollTop = TERM.out.scrollHeight;
  if (keep) {
    TERM.size = px / win * 100;
    try { localStorage.setItem("h3studio.term.size", TERM.size.toFixed(2)); } catch (e) { /* not remembered then */ }
  }
}
window.addEventListener("resize", () => { if (TERM.open) termSize(TERM.size); });

function setTerm(open) {
  TERM.open = open;
  try { localStorage.setItem("h3studio.term", open ? "1" : "0"); } catch (e) { /* not remembered then */ }
  drawSide(); drawQueue(); drawTerm();
}

function drawTerm() {
  const el = $("#term");
  clearTimeout(TERM.timer);
  document.body.classList.toggle("term", TERM.open);
  el.hidden = !TERM.open;
  if (!TERM.open) { el.replaceChildren(); TERM.out = TERM.grip = null; return; }
  TERM.shown = null; TERM.follow = true;
  // the pane's top edge: drag it, or use the arrow keys on it, to change the height; a double click is half the window
  const grip = h("div", { class: "grip", role: "separator", "aria-orientation": "horizontal", "aria-label": "Height of ComfyUI's output", tabindex: "0",
    title: "Drag to change the height. Double click: half the window.",
    ondblclick: () => termSize(50, true),
    onkeydown: e => { const step = e.key === "ArrowUp" ? 4 : e.key === "ArrowDown" ? -4 : 0; if (step) { e.preventDefault(); termSize(TERM.size + step, true); } },
    onpointerdown: e => {
      if (e.button) return;
      e.preventDefault();
      const grab = e.clientY - el.getBoundingClientRect().top;          // where on the edge it was taken
      const share = ev => (window.innerHeight - (ev.clientY - grab)) / window.innerHeight * 100;
      const move = ev => termSize(share(ev));
      const done = ev => {
        grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", done); grip.removeEventListener("pointercancel", done);
        document.body.classList.remove("term-drag");
        termSize(share(ev), true);
      };
      grip.setPointerCapture(e.pointerId);
      document.body.classList.add("term-drag");
      grip.addEventListener("pointermove", move); grip.addEventListener("pointerup", done); grip.addEventListener("pointercancel", done);
    } });
  const src = h("span", { class: "src" });
  const latest = h("button", { class: "small", hidden: true, onclick: () => { out.scrollTop = out.scrollHeight; } }, "↓ Latest");
  const out = h("pre", { tabindex: "0", "aria-label": "What ComfyUI printed", onscroll: () => { TERM.follow = out.scrollHeight - out.scrollTop - out.clientHeight < 30; latest.hidden = TERM.follow; } });
  el.replaceChildren(grip, h("div", { class: "head" }, h("b", {}, "ComfyUI output"), src, latest,
    h("button", { class: "ghost small", title: "Close", "aria-label": "Close ComfyUI's output", onclick: () => setTerm(false) }, "✕")), out);
  TERM.out = out; TERM.grip = grip;
  termSize(TERM.size);
  const tick = async () => {
    let d = null;
    try { d = await api("/api/machine/comfy/output"); } catch (e) { src.textContent = e.message; }
    if (!TERM.open || !out.isConnected) return;
    if (d) {
      const from = d.source ? d.source + (d.written ? ", written " + ago(d.written) : "") : "";
      src.textContent = d.live ? "live" : d.starting ? "ComfyUI is starting" + (from ? " · " + from : "") :
        !d.up ? "ComfyUI does not answer" + (from ? " · this is the end of " + from : "") : from ? "from " + from : "";
      const text = d.text || (d.up ? "This ComfyUI does not hand out what it prints, and it left no log file on this computer."
        : d.starting ? "Waiting for ComfyUI's first lines…" : "ComfyUI does not answer, and it left no log file on this computer.");
      const key = d.source + "\n" + text;
      const sel = window.getSelection();                      // text being selected in it is left alone
      const selecting = sel && !sel.isCollapsed && out.contains(sel.anchorNode);
      if (key !== TERM.shown && !selecting) {
        TERM.shown = key;
        const follow = TERM.follow, top = out.scrollTop;
        out.replaceChildren(termNodes(text));
        out.scrollTop = follow ? out.scrollHeight : top;
      }
    }
    TERM.timer = setTimeout(tick, document.hidden ? 5000 : 1000);
  };
  tick();
}

// ---------------------------------------------------------------- a little Markdown, for the Learn room
function md(text) {
  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = s => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>").replace(/!\[([^\]]*)\]\(([\w./-]+\.(?:png|jpg|webp))\)/g, (m, alt, src) => `<img src="/docs/${src.replace(/^\.?\//, "")}" alt="${alt}" loading="lazy">`)
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, "")
    .replace(/\[([^\]]+)\]\(([\w./-]+\.mp4)\)/g, (m, t, src) => `<a href="/docs/${src.replace(/^\.?\//, "")}" target="_blank" rel="noopener">${t}</a>`).replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>').replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  const out = [];
  const lines = text.split("\n");
  let i = 0, list = null;
  const close = () => { if (list) { out.push("</" + list + ">"); list = null; } };
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith("```")) { close(); const buf = []; i++; while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]); out.push("<pre>" + esc(buf.join("\n")) + "</pre>"); i++; continue; }
    if (/^\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      close(); const row = r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      let t = "<table><tr>" + row(l).map(c => "<th>" + inline(c) + "</th>").join("") + "</tr>"; i += 2;
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) t += "<tr>" + row(lines[i++]).map(c => "<td>" + inline(c) + "</td>").join("") + "</tr>";
      out.push(t + "</table>"); continue;
    }
    if (/^-{3,}\s*$/.test(l)) { close(); out.push("<hr>"); i++; continue; }
    const hd = /^(#{1,4})\s+(.*)$/.exec(l);
    if (hd) { close(); out.push(`<h${hd[1].length}>${inline(hd[2])}</h${hd[1].length}>`); i++; continue; }
    const li = /^\s*(?:[-*]|\d+\.)\s+(.*)$/.exec(l);
    if (li) { const kind = /^\s*\d+\./.test(l) ? "ol" : "ul"; if (list !== kind) { close(); out.push("<" + kind + ">"); list = kind; }
      let item = li[1]; i++; while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*(?:[-*]|\d+\.)\s+/.test(lines[i])) item += " " + lines[i++].trim();
      out.push("<li>" + inline(item) + "</li>"); continue; }
    if (!l.trim()) { close(); i++; continue; }
    close(); let para = l; i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*(?:[-*]|\d+\.)\s|\|)/.test(lines[i])) para += " " + lines[i++];
    out.push("<p>" + inline(para) + "</p>");
  }
  close();
  const d = h("div", { class: "md" });
  d.innerHTML = out.join("\n");
  return d;
}

async function boot() {
  try { S.presets = await api("/api/presets"); } catch (e) { $("#room").append(h("div", { class: "note bad" }, "The studio's server does not answer: " + e.message)); return; }
  document.body.classList.toggle("qopen", QOPEN);
  await poll();
  route();
  drawTerm();
}
