"use strict";
// The create pages: Image, Video and Audio, each a floating prompt bar with chips under a list of what was made.
// The Generate button shows about how long the job takes on this machine (the studio keeps its own timings).

// ---------------------------------------------------------------- composer parts
// A chip that opens a menu above it. options: [[value, label, hint]] or {label} rows; onpick(value).
function chipMenu(label, value, options, onpick, o = {}) {
  const cur = options.find(x => Array.isArray(x) && String(x[0]) === String(value));
  const menu = h("div", { class: "popmenu", hidden: true, role: "menu" }, o.title ? h("div", { class: "lbl" }, o.title) : null,
    options.map(x => Array.isArray(x) ? h("button", { class: String(x[0]) === String(value) ? "on" : "", role: "menuitemradio", "aria-checked": String(x[0]) === String(value) ? "true" : "false",
      onclick: e => { e.stopPropagation(); menu.hidden = true; onpick(x[0]); } }, h("span", {}, x[1]), x[2] ? h("span", { class: "h" }, x[2]) : null) : h("div", { class: "lbl" }, x.label)));
  const btn = h("button", { class: "cchip", "aria-haspopup": "menu", title: o.tip || label, onclick: e => { e.stopPropagation(); const was = menu.hidden; closeMenus(); menu.hidden = !was; btn.classList.toggle("on", !menu.hidden); } },
    o.icon ? h("span", { "aria-hidden": "true" }, o.icon) : null, label ? h("span", { class: "k" }, label) : null, h("span", {}, o.short ? o.short(cur) : cur ? cur[1] : (o.none || "—")));
  return h("span", { style: { position: "relative", display: "inline-flex" } }, btn, menu);
}
function closeMenus() { document.querySelectorAll(".popmenu").forEach(m => { m.hidden = true; }); document.querySelectorAll(".cchip.on").forEach(c => c.classList.remove("on")); }
document.addEventListener("click", e => { if (!e.target.closest(".popmenu")) closeMenus(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenus(); });

function countChip(value, min, max, onchange, label) {
  const span = h("span", { "aria-live": "polite" }, value + (label || ""));
  const set = v => { v = Math.max(min, Math.min(max, v)); value = v; span.textContent = v + (label || ""); onchange(v); };
  return h("div", { class: "count", role: "group", "aria-label": "How many" },
    h("button", { "aria-label": "Fewer", onclick: () => set(value - 1) }, "−"), span, h("button", { "aria-label": "More", onclick: () => set(value + 1) }, "+"));
}
function toggleChip(label, on, onchange) {
  const b = h("button", { class: "cchip" + (on ? " lime" : ""), "aria-pressed": on ? "true" : "false", onclick: () => { on = !on; b.classList.toggle("lime", on); b.setAttribute("aria-pressed", on ? "true" : "false"); b.lastChild.textContent = on ? "on" : "off"; onchange(on); } },
    h("span", { class: "k" }, label), h("span", {}, on ? "on" : "off"));
  return b;
}
// The bar itself. Returns {el, textarea, setEst(text), setBusy(bool)}.
function composerBar(o) {
  const ta = h("textarea", { rows: 2, placeholder: o.placeholder, "aria-label": o.placeholder });
  ta.value = o.value || "";
  const grow = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 220) + "px"; };
  ta.addEventListener("input", () => { o.oninput(ta.value); grow(); });
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); o.onsubmit(); } });
  const est = h("span", { class: "est" });
  const go = h("button", { class: "go", onclick: () => o.onsubmit() }, h("span", {}, o.goLabel || "Generate"), est);
  const el = h("div", { class: "dock" }, h("div", { class: "composer" },
    h("div", { class: "left" }, o.attached || null, ta, h("div", { class: "chips" }, o.chips)), go));
  setTimeout(grow, 0);
  return { el, textarea: ta, setEst: t => { est.textContent = t || ""; }, setBusy: b => { go.disabled = b; } };
}
const about = s => s ? "≈ " + secs(s) : "";

// Pending jobs of a page, drawn as shimmering tiles until they end.
function pendingTiles(mine, kinds) {
  const box = h("div", { style: { display: "contents" } });
  const draw = () => {
    const live = S.state.jobs.filter(j => mine.has(j.id) && kinds.includes(j.kind) && (j.status === "queued" || j.status === "running"));
    box.replaceChildren(live.map(j => h("div", { class: "pending shimmer" }, h("div", {},
      h("div", { style: { fontWeight: 600, color: "var(--soft)" } }, j.status === "queued" ? "Waiting in the queue" : "Rendering"),
      h("div", {}, (j.progress && j.progress.text) || ""), j.eta ? h("div", { class: "faint" }, "about " + secs(Math.max(0, j.eta - Date.now() / 1000)) + " left") : null))));
  };
  const t = setInterval(() => { if (!box.isConnected) return clearInterval(t); draw(); }, 1200);
  draw();
  return box;
}
function trackJob(mine, j) { if (j && j.id) { mine.add(j.id); S.seen[j.id] = S.seen[j.id] || j.status; } }

// Pictures attached to a composer: small squares with their Picture number.
function attachedStrip(list, onchange, label) {
  return h("div", { class: "attached" }, list.map((p, i) => h("div", { class: "a", style: { backgroundImage: `url("${p.thumb || refThumb(p.ref)}")` }, title: p.ref },
    h("i", {}, label ? label(i) : "Picture " + (i + 1)), h("button", { "aria-label": "Remove", onclick: () => { list.splice(i, 1); onchange(); } }, "✕"))));
}
async function attachPictures(list, max, onchange) {
  const got = await pickAsset("image", { multiple: max > 1, title: "Pick pictures" });
  if (!got) return;
  const arr = Array.isArray(got) ? got : [got];
  for (const a of arr) if (list.length < max) list.push({ ref: a.ref, thumb: a.thumb });
  onchange();
}

// ---------------------------------------------------------------- Image
ROOMS.picture = { title: "Image", full: true, draw(root) {
  const pend = S.pending || {}; S.pending = null;
  const f = Object.assign({ prompt: "", mode: "make", template: "", size: "1344x768", takes: 2, seed: 0, attach: [], views: "around" }, ROOMS.picture.keep || {});
  if (pend.recreate) {
    const r = pend.recreate;
    Object.assign(f, { prompt: r.prompt || "", template: r.template || "", takes: r.takes || 1, seed: r.seed || 0, attach: (r.pictures || []).map(ref => ({ ref })) });
    if (r.width && r.height) f.size = r.width + "x" + r.height;
    f.mode = r.angles ? (r.angles === "sheet" ? "sheet" : "angles") : r.template === "propsheet" ? "propsheet" : f.attach.length ? "edit" : r.template === "portrait" ? "face" : r.template === "location" ? "place" : "make";
    toast("The settings of that picture are filled in" + (r.seed ? " (same seed)" : ""));
  }
  if (pend.attach) { f.attach = pend.attach.slice(0, 9); f.mode = "edit"; }
  ROOMS.picture.keep = f;
  const mine = new Set();
  const results = h("div", { class: "results" });
  const stage = h("div", { class: "stage" });
  const bar = h("div", {});
  const MODES = [["make", "Picture", "Any picture"], ["face", "Face", "A face for a character"], ["place", "Place", "An empty place, a plate"],
    ["edit", "Edit", "Change the attached picture in words"], ["angles", "Angles", "The attached subject from other sides"],
    ["sheet", "Outfit sheet", "Whole body, four views"], ["propsheet", "Prop sheet", "An object twice, on white"]];
  const TIPS = { make: "Describe the image you have in mind: who or what, where, the light, the lens…", face: "Describe the person: age, face, hair, clothes…",
    place: "Describe the empty place, seen from where the camera will stand…", edit: "Say how the picture should look: what changes, what stays…",
    angles: "Optional: anything to add to every view…", sheet: "Optional: the clothes, e.g. a dark green raincoat, jeans and brown boots…",
    propsheet: "What the object is: the small brown parcel with the red sticker…" };
  const needsPicture = () => ["edit", "angles", "sheet", "propsheet"].includes(f.mode);
  let est = null;
  const refreshEst = debounce(async () => { const n = f.mode === "angles" ? (P().angles.sets.find(s => s.id === f.views) || { views: [1] }).views.length : f.mode === "sheet" ? 1 : f.takes;
    const r = await tryApi("/api/estimate", { kind: "image", takes: n }); est = r && r.seconds; ui && ui.setEst(about(est)); }, 300);
  let ui = null;
  function drawBar() {
    const attached = f.attach.length ? attachedStrip(f.attach, () => { if (!f.attach.length && needsPicture()) f.mode = "make"; drawBar(); }) : null;
    const chips = [
      h("button", { class: "cchip icon", title: "Attach pictures (to edit, or as references)", "aria-label": "Attach pictures", onclick: () => attachPictures(f.attach, 9, () => { if (f.mode === "make") f.mode = "edit"; drawBar(); }) }, "+"),
      chipMenu("", f.mode, MODES.map(([v, l, hh]) => [v, l, hh]), v => { f.mode = v; if (v === "face") f.size = "1024x1024"; drawBar(); refreshEst(); }, { icon: "✦", title: "What to make" }),
      f.mode === "angles" ? chipMenu("Views", f.views, P().angles.sets.map(s => [s.id, s.name, s.views.length + " pictures"]), v => { f.views = v; drawBar(); refreshEst(); }) : null,
      ["edit", "make", "face", "place"].includes(f.mode) && !(f.mode === "edit" && f.keepSize !== false) ? chipMenu("", f.size, P().image_sizes.map(s => [s.width + "x" + s.height, s.name.replace(/\s+/, " ")]), v => { f.size = v; drawBar(); }, { icon: "▢", short: c => c ? c[1].split(" ")[0] : f.size }) : null,
      f.mode === "edit" ? toggleChip("Keep shape", f.keepSize !== false, v => { f.keepSize = v; drawBar(); }) : null,
      ["make", "face", "place", "edit", "propsheet"].includes(f.mode) ? countChip(f.takes, 1, 12, v => { f.takes = v; refreshEst(); }, f.takes === 1 ? "" : "") : null,
      chipMenu("Seed", f.seed ? "fixed" : "new", [["new", "A new seed each time"], ["fixed", "Keep seed " + (f.seed || "…"), "the same picture again"]], v => { if (v === "new") f.seed = 0; else if (!f.seed) f.seed = Math.floor(Math.random() * 1e9); drawBar(); }),
    ];
    ui = composerBar({ placeholder: TIPS[f.mode], value: f.prompt, oninput: v => { f.prompt = v; }, onsubmit: make, attached, chips });
    ui.setEst(about(est));
    bar.replaceChildren(ui.el);
  }
  async function make() {
    if (needsPicture() && !f.attach.length) return toast("Attach the picture first (+)", true);
    const [w, hh] = f.size.split("x").map(Number);
    const pics = f.attach.map(a => a.ref);
    let d;
    if (f.mode === "make" || f.mode === "face" || f.mode === "place") {
      if (!f.prompt.trim()) return toast("Describe the picture", true);
      d = { prompt: f.prompt, template: { face: "portrait", place: "location" }[f.mode] || "", width: w, height: hh, takes: f.takes, seed: f.seed || 0, pictures: pics };
      if (pics.length) d.keep_size = false;
    } else if (f.mode === "edit") {
      if (!f.prompt.trim()) return toast("Say how it should look", true);
      d = { prompt: f.prompt, pictures: pics, keep_size: f.keepSize !== false, width: w, height: hh, takes: f.takes, seed: f.seed || 0 };
    } else if (f.mode === "angles") {
      const set = P().angles.sets.find(s => s.id === f.views) || P().angles.sets[0];
      d = { prompt: f.prompt, pictures: [pics[0]], angles: set.views, keep_size: true, seed: f.seed || 0 };
    } else if (f.mode === "sheet") {
      d = { prompt: f.prompt, angles: "sheet", pictures: [pics[0]], width: 1536, height: 864, seed: f.seed || 0, name: "character sheet" };
    } else {
      if (!f.prompt.trim()) return toast("Say what the object is", true);
      d = { prompt: f.prompt, template: "propsheet", pictures: [pics[0]], width: 1536, height: 864, takes: f.takes, seed: f.seed || 0, name: "sheet " + f.prompt.slice(0, 24) };
    }
    const j = await tryApi("/api/images", d);
    if (j) { trackJob(mine, j); toast("Queued"); poll(); drawStage(); }
  }
  let items = [];
  async function load() { const r = await tryApi("/api/library?kind=image,sheet&limit=120"); if (r) { items = r.items; drawStage(); } }
  function drawStage() {
    const pend = pendingTiles(mine, ["image"]);
    if (!items.length && !mine.size) {
      stage.replaceChildren(h("div", { class: "welcome" },
        h("div", { class: "guidebar" }, h("div", {}, h("b", {}, "Not sure where to begin?"), h("span", {}, "The prompting guide has what works with this model")),
          h("button", { class: "small white", onclick: () => go("learn", "prompting") }, "Open guide")),
        h("div", { class: "fan" }, [0, 1, 2, 3].map(() => h("div", {}))),
        h("h1", { class: "display" }, "Make your first image with", h("br"), h("span", { class: "lime" }, "H3 Image")),
        h("p", {}, "Type a subject, a place, a mood or a style, then press Generate. Qwen-Image renders it on this computer in about half a minute.")));
      return;
    }
    results.replaceChildren(pend, items.map(a => post(a)));
    stage.replaceChildren(h("div", { class: "section-head" }, h("h2", {}, "Your pictures"), h("span", { class: "muted small" }, items.length + " in the Library")), results);
  }
  onJobEnd(j => { if (j.kind === "image") load(); });
  const wrap = h("div", { class: "studio", style: { height: "100%", position: "relative" } }, stage, bar);
  stage.style.overflowY = "auto";
  wrap.style.overflow = "hidden";
  root.append(wrap);
  drawBar(); drawStage(); load(); refreshEst();
} };

// ---------------------------------------------------------------- Video
const VideoForm = ROOMS.video;                      // the full form (create.js), still there under "Full form"
function formFromRecreate(d) {
  // A clip's saved request back into the full form's fields.
  const f = Object.assign(blankVideoForm(), {});
  for (const k of Object.keys(f)) if (d[k] !== undefined && d[k] !== null) f[k] = d[k];
  if (d.width && d.height) f.size = d.width + "x" + d.height;
  f.start = d.blockout ? "blockout" : d.last_frame ? "first_last" : d.first_frame ? "first" : (d.refs || []).length ? "refs" : "text";
  if ((d.beats || []).length) { f.long = true; f.beats = d.beats.join("\n"); }
  f.people = (d.people || []).map(p => Object.assign({ name: "", pronoun: "their", description: "", face: "", body: "", voice: "" }, p));
  f.lines = d.lines || [];
  return f;
}
ROOMS.video = { title: "Video", full: arg => !arg, draw(root, arg) {
  if (arg.startsWith("clip/")) return VideoForm.draw(root, arg);
  if (arg === "form") return VideoForm.draw(root, "");
  const pend = S.pending || {}; S.pending = null;
  if (pend.recreate) {
    const r = pend.recreate;
    const complex = (r.people || []).some(p => p.face || p.voice || p.body) || (r.refs || []).length || r.mode === "free" || r.blockout || (r.beats || []).length;
    if (complex) { ROOMS.video.keep = formFromRecreate(r); toast("That clip's settings are in the full form"); return go("video", "form"); }
  }
  const f = Object.assign({ action: "", place: "", sound: "", look: "cinematic", camera: "", framing: "", size: "1152x640", frames: 209, turbo: true, seed: 0,
    first: [], last: [], lines: [], one_take: true, notext: true, language: "English" }, ROOMS.video.quick || {});
  if (pend.recreate) {
    const r = pend.recreate;
    Object.assign(f, { action: r.action || r.prompt || "", place: r.place || "", sound: r.sound || "", look: r.look || "cinematic", camera: r.camera || "", framing: r.framing || "",
      frames: r.frames || 209, turbo: r.turbo !== false, seed: r.seed || 0, lines: (r.lines || []).map(l => ({ ...l })),
      first: r.first_frame ? [{ ref: r.first_frame }] : [], last: r.last_frame ? [{ ref: r.last_frame }] : [] });
    if (r.width && r.height) f.size = r.width + "x" + r.height;
    toast("The settings of that clip are filled in" + (r.seed ? " (same seed)" : ""));
  }
  if (pend.first_frame) f.first = [{ ref: pend.first_frame }];
  if (pend.start === "first_last" && pend.last_frame) f.last = [{ ref: pend.last_frame }];
  ROOMS.video.quick = f;
  const mine = new Set();
  const stage = h("div", { class: "stage" }), bar = h("div", {}), results = h("div", { class: "results" });
  let est = null, ui = null, warn = h("div", {});
  function payload() {
    const [width, height] = f.size.split("x").map(Number);
    const people = [...new Set(f.lines.map(l => (l.speaker || "").trim()).filter(Boolean))].map(n => ({ name: n, pronoun: "their", description: "" }));
    const d = { name: f.action.slice(0, 48), mode: "fields", place: f.place, action: f.action, sound: f.sound, framing: f.framing, camera: f.camera, look: f.look,
      width, height, frames: f.frames, turbo: f.turbo, seed: f.seed || 0, notext: f.notext, one_take: f.one_take, language: f.language, people,
      lines: f.lines.filter(l => (l.text || "").trim()), refs: [] };
    if (f.first.length) d.first_frame = f.first[0].ref;
    if (f.first.length && f.last.length) d.last_frame = f.last[0].ref;
    return d;
  }
  const refreshEst = debounce(async () => {
    try { const c = await api("/api/compose", payload()); est = c.estimate; ui && ui.setEst(about(est));
      warn.replaceChildren(c.fit && c.fit.text && !c.fit.ok ? h("div", { class: "note bad", style: { margin: "0 0 8px" } }, c.fit.text) : null); } catch (e) { /* the form is not complete yet */ }
  }, 500);
  function linesModal() {
    const lines = f.lines.length ? f.lines : [{ speaker: "", text: "", how: "" }];
    const box = h("div", {});
    const draw = () => box.replaceChildren(lines.map((l, i) => h("div", { class: "linerow" },
      text(l, "speaker", { placeholder: "Who: Mara" }), text(l, "text", { placeholder: "The exact words" }), text(l, "how", { placeholder: "How: quietly, smiling" }),
      h("button", { class: "ghost small", onclick: () => { lines.splice(i, 1); draw(); } }, "✕"))),
      h("button", { class: "small", onclick: () => { lines.push({ speaker: "", text: "", how: "" }); draw(); } }, "+ Line"));
    draw();
    modal(h("div", {}, h("h2", {}, "Spoken lines"), h("p", { class: "muted small" }, "Every word someone says, exactly. Without lines the model invents gibberish; a clip with no lines is told that nobody speaks."),
      box, h("div", { class: "row", style: { marginTop: "14px", gap: "6px" } }, h("button", { class: "primary", onclick: () => { f.lines = lines.filter(l => (l.text || "").trim()); closeModal(); drawBar(); refreshEst(); } }, "Done"))), true);
  }
  function wordsModal(key, title, ph, hint) {
    const o = { v: f[key] };
    modal(h("div", {}, h("h2", {}, title), field("", text(o, "v", { rows: 3, placeholder: ph }), hint),
      h("button", { class: "primary", onclick: () => { f[key] = o.v; closeModal(); drawBar(); refreshEst(); } }, "Done")), true);
  }
  function drawBar() {
    const attached = f.first.length ? h("div", { class: "attached" },
      attachedStrip(f.first, () => { f.last = []; drawBar(); refreshEst(); }, () => "First").firstChild,
      f.last.length ? attachedStrip(f.last, () => { drawBar(); refreshEst(); }, () => "Last").firstChild : null) : null;
    const VSIZES = [["1152x640", "16:9", "1152×640"], ["864x480", "16:9 draft", "864×480"], ["640x1152", "9:16", "640×1152"], ["480x864", "9:16 draft", "480×864"], ["768x768", "1:1", "768×768"], ["1344x576", "21:9", "1344×576"]];
    const chips = [
      h("button", { class: "cchip icon", title: f.first.length ? "Add a last frame" : "Start from a picture", "aria-label": "Attach a first or last frame",
        onclick: () => attachPictures(f.first.length ? f.last : f.first, 1, () => { drawBar(); refreshEst(); }) }, "+"),
      chipMenu("", f.look, lookOptions(), v => { f.look = v; drawBar(); refreshEst(); }, { icon: "☀", title: "Look" }),
      chipMenu("", f.camera, cameraOptions().flatMap(x => Array.isArray(x) ? [x] : [{ label: x.group }, ...x.items]), v => { f.camera = v; drawBar(); refreshEst(); }, { icon: "⌖", title: "Camera", none: "Camera", short: c => c && c[0] ? c[1] : "Camera" }),
      chipMenu("", f.framing, framingOptions(), v => { f.framing = v; drawBar(); refreshEst(); }, { icon: "▣", title: "Framing", short: c => c && c[0] ? c[1] : "Framing" }),
      chipMenu("", f.size, VSIZES, v => { f.size = v; drawBar(); refreshEst(); }, { icon: "▢", title: "Size", short: c => c ? c[1] : f.size }),
      chipMenu("", f.frames, lengthOptions(false).filter(x => !x[2]).map(x => [x[0], x[1].split("  ")[0], x[1].split("  ")[1]]), v => { f.frames = Number(v); drawBar(); refreshEst(); }, { icon: "◷", title: "Length", short: c => c ? c[1] : f.frames + " frames" }),
      toggleChip("Turbo", f.turbo, v => { f.turbo = v; refreshEst(); }),
      h("button", { class: "cchip" + (f.lines.length ? " lime" : ""), onclick: linesModal }, h("span", { class: "k" }, "Lines"), h("span", {}, f.lines.length || "none")),
      h("button", { class: "cchip" + (f.sound ? " lime" : ""), onclick: () => wordsModal("sound", "Sound", "Rain on the awnings, distant traffic, a dog barking far away.", "What is heard besides the words.") }, h("span", { class: "k" }, "Sound"), h("span", {}, f.sound ? "set" : "—")),
      h("button", { class: "cchip" + (f.place ? " lime" : ""), onclick: () => wordsModal("place", "The place", "A small corner café in the morning: wooden tables, a steaming espresso machine.", "Say what is there; a busy place needs people in it.") }, h("span", { class: "k" }, "Place"), h("span", {}, f.place ? "set" : "—")),
      h("button", { class: "cchip", title: "People with faces and voices, references, a blockout, a long take, several looks", onclick: () => { ROOMS.video.keep = formFromRecreate(payload()); go("video", "form"); } }, "Full form →"),
    ];
    ui = composerBar({ placeholder: f.first.length ? "What happens after the first frame, and how the camera moves…" : "Describe what happens: who, where, how the camera moves…",
      value: f.action, oninput: v => { f.action = v; refreshEst(); }, onsubmit: render, attached: [warn, attached], chips, goLabel: "Generate" });
    ui.setEst(about(est));
    bar.replaceChildren(ui.el);
  }
  async function render() {
    if (!f.action.trim()) return toast("Describe what happens", true);
    const r = await tryApi("/api/clips", payload());
    if (r) { trackJob(mine, r.job); toast("Queued"); poll(); drawStage(); }
  }
  let items = [];
  async function load() { const r = await tryApi("/api/library?kind=clip&limit=80"); if (r) { items = r.items.filter(a => a.surface !== "shorts"); drawStage(); } }
  function drawStage() {
    if (!items.length && !mine.size) {
      stage.replaceChildren(h("div", { class: "welcome" },
        h("div", { class: "fan" }, [0, 1, 2, 3].map(() => h("div", {}))),
        h("h1", { class: "display" }, "Picture and sound,", h("br"), h("span", { class: "lime" }, "in one take")),
        h("p", {}, "MiniMax H3 renders up to 15 seconds a part, with speech and sound, on this computer. Start from words, or press + to start from a picture.")));
      return;
    }
    results.replaceChildren(pendingTiles(mine, ["shot"]), items.map(a => post(a)));
    stage.replaceChildren(h("div", { class: "section-head" }, h("h2", {}, "Your clips"), h("button", { class: "ghost small", onclick: () => go("video", "form") }, "Full form →")), results);
  }
  onJobEnd(j => { if (j.kind === "shot") load(); });
  const wrap = h("div", { class: "studio", style: { height: "100%", position: "relative", overflow: "hidden" } }, stage, bar);
  root.append(wrap);
  drawBar(); drawStage(); load(); refreshEst();
} };

// ---------------------------------------------------------------- Audio
ROOMS.audio = { title: "Audio", full: true, async draw(root) {
  const f = Object.assign({ text: "", voice: "", seed: 1, name: "" }, ROOMS.audio.keep || {});
  ROOMS.audio.keep = f;
  const mine = new Set();
  const stage = h("div", { class: "stage" }), bar = h("div", {});
  let voices = [];
  function drawBar() {
    const ui = composerBar({ placeholder: "Type the words to speak: narration, or a voice sample for a character…", value: f.text, oninput: v => { f.text = v; }, onsubmit: speak, goLabel: "Speak",
      chips: [voices.length ? chipMenu("Voice", f.voice, voices.map(v => [v, v.replace(/\.(wav|mp3|flac)$/i, "")]), v => { f.voice = v; drawBar(); }, { icon: "♪" }) : h("span", { class: "chip warn" }, "No TTS voices: is the TTS Audio Suite installed and ComfyUI up?"),
        chipMenu("Seed", f.seed, [1, 2, 3, 4, 5].map(n => [n, String(n)]), v => { f.seed = Number(v); drawBar(); }),
        h("button", { class: "cchip", onclick: () => go("sound") }, "Voice samples & beats →")] });
    ui.setEst(f.text ? "≈ " + Math.max(5, Math.round(f.text.length / 12)) + " s" : "");
    bar.replaceChildren(ui.el);
  }
  async function speak() {
    if (!f.text.trim()) return toast("Type the words first", true);
    if (!f.voice) return toast("Pick a voice", true);
    const j = await tryApi("/api/tts", f);
    if (j) { trackJob(mine, j); toast("Queued"); poll(); load(); }
  }
  async function load() {
    const r = await tryApi("/api/library?kind=audio&limit=60");
    if (!r) return;
    stage.replaceChildren(r.items.length || mine.size ? [h("div", { class: "section-head" }, h("h2", {}, "Your sound"), h("span", { class: "muted small" }, "Give a sample to a character as their voice: the video model speaks their lines in it.")),
      h("div", { class: "results" }, pendingTiles(mine, ["tts"]), r.items.map(a => assetTile(a, { actions: x => assetActions(x) })))]
      : h("div", { class: "welcome" }, h("h1", { class: "display" }, "Voices for", h("br"), h("span", { class: "lime" }, "everything you make")),
        h("p", {}, "ChatterBox speaks your words in a voice from the TTS Audio Suite. Upload a 10 to 20 second sample under Voice samples to give a character a voice.")));
  }
  onJobEnd(j => { if (j.kind === "tts") load(); });
  root.append(h("div", { class: "studio", style: { height: "100%", position: "relative", overflow: "hidden" } }, stage, bar));
  drawBar(); load();
  const v = await tryApi("/api/voices");
  voices = (v && v.tts) || [];
  if (!f.voice && voices.length) f.voice = voices[0];
  drawBar();
} };
