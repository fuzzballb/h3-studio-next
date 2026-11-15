"use strict";
// Parts every room uses: form fields bound to an object, pickers for pictures and sound, the list of findings,
// Library tiles and the detail view of one file.

// ---------------------------------------------------------------- form fields
function field(label, control, hint) {
  const id = "f" + Math.random().toString(36).slice(2, 8);
  if (control && control.tagName && ["INPUT", "SELECT", "TEXTAREA"].includes(control.tagName)) control.id = id;
  return h("div", { class: "field" }, label ? h("label", { for: id }, label) : null, control, hint ? h("div", { class: "hint" }, hint) : null);
}
function text(obj, key, o = {}) {
  const e = o.rows ? h("textarea", { rows: o.rows, placeholder: o.placeholder || "" }) : h("input", { type: "text", placeholder: o.placeholder || "" });
  e.value = obj[key] === undefined || obj[key] === null ? "" : obj[key];
  e.addEventListener("input", () => { obj[key] = e.value; if (o.oninput) o.oninput(e.value); });
  if (o.onchange) e.addEventListener("change", () => o.onchange(e.value));
  if (o.mono) e.classList.add("mono");
  return e;
}
function number(obj, key, o = {}) {
  const e = h("input", { type: "number", min: o.min, max: o.max, step: o.step || 1, placeholder: o.placeholder || "" });
  e.value = obj[key] === undefined || obj[key] === null || obj[key] === 0 && o.blankZero ? "" : obj[key];
  e.addEventListener("input", () => { obj[key] = e.value === "" ? (o.blankZero ? 0 : null) : Number(e.value); if (o.oninput) o.oninput(obj[key]); });
  return e;
}
function select(obj, key, options, o = {}) {
  // options: [[value, label]] or [{group, items: [[value, label, disabled?]]}]
  const opt = ([v, label, off]) => h("option", { value: v, selected: String(obj[key] ?? "") === String(v), disabled: !!off }, label);
  const e = h("select", {}, options.map(x => Array.isArray(x) ? opt(x) : h("optgroup", { label: x.group }, x.items.map(opt))));
  e.addEventListener("change", () => { obj[key] = o.number ? Number(e.value) : e.value; if (o.onchange) o.onchange(obj[key]); });
  return e;
}
function check(obj, key, label, o = {}) {
  const e = h("input", { type: "checkbox", checked: !!obj[key] });
  e.addEventListener("change", () => { obj[key] = e.checked; if (o.onchange) o.onchange(e.checked); });
  return h("label", { class: "check" }, e, h("span", {}, label));
}
function tabs(names, current, onpick) {
  return h("div", { class: "tabs", role: "tablist" }, names.map(([id, label, badge]) =>
    h("button", { class: "tab" + (id === current ? " on" : ""), role: "tab", "aria-selected": id === current ? "true" : "false", onclick: () => onpick(id) },
      label, badge ? h("span", { class: "badge", style: { marginLeft: "6px" } }, badge) : null)));
}
function head(title, sub, right) {
  return h("div", { class: "spread", style: { alignItems: "flex-start", marginBottom: "4px" } },
    h("div", {}, h("h1", {}, title), sub ? h("p", { class: "sub" }, sub) : null), right || null);
}

// ---------------------------------------------------------------- presets as options
const P = () => S.presets;
function cameraOptions() {
  const groups = {};
  for (const m of P().cameras.moves) (groups[m.group] = groups[m.group] || []).push([m.id, m.name]);
  return [["", "(not said)"], ...Object.entries(groups).map(([group, items]) => ({ group, items }))];
}
const framingOptions = () => [["", "(not said)"], ...P().cameras.framings.map(f => [f.id, f.name])];
const lookOptions = () => P().looks.styles.map(s => [s.id, s.name]);
const lensOptions = () => [["", "(none)"], ...P().looks.lenses.map(s => [s.id, s.name])];
const lightOptions = () => [["", "(none)"], ...P().looks.lights.map(s => [s.id, s.name])];
function lengthOptions(continuation) {
  return P().lengths.filter(l => l.frames >= 39).map(l => {
    const fits = continuation ? l.continuation : l.new_shot;
    const s = continuation ? l.continuation_seconds : l.seconds;
    return [l.frames, `${s.toFixed(1)} s${continuation ? " added" : ""}  (${l.frames} frames)` + (fits ? "" : " — too short for sound"), !fits];
  });
}
const sizeOptions = () => P().sizes.map(s => [s.width + "x" + s.height, s.name]);

// ---------------------------------------------------------------- machine facts, fetched once
let machinePromise = null;
function getMachine(refresh) {
  if (!machinePromise || refresh) machinePromise = api("/api/machine" + (refresh ? "?refresh=1" : "")).catch(e => { machinePromise = null; throw e; });
  return machinePromise;
}

// ---------------------------------------------------------------- uploading and picking files
function chooseFiles(accept, multiple) {
  return new Promise(resolve => {
    const i = h("input", { type: "file", accept, multiple: !!multiple, style: { display: "none" } });
    i.addEventListener("change", () => { resolve([...i.files]); i.remove(); });
    document.body.append(i);
    i.click();
  });
}
async function upload(files) {
  const out = [];
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f, f.name);
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "upload failed");
    out.push(...j.items);
  }
  return out;
}
const ACCEPT = { image: "image/png,image/jpeg,image/webp", audio: "audio/*,.wav,.flac,.mp3,.m4a,.ogg", clip: "video/*,.mkv" };

// A modal that lists the Library (one kind) and lets the user upload; resolves with the chosen asset(s) or null.
function pickAsset(kind, o = {}) {
  return new Promise(resolve => {
    const kinds = kind === "image" ? ["image", "sheet"] : kind === "clip" ? ["clip", "film", "export"] : [kind];
    let items = [], q = "";
    const chosen = new Set();
    const grid = h("div", { class: "tiles", style: { marginTop: "12px" } });
    const done = v => { closeModal(); resolve(v); };
    async function load() {
      const got = [];
      for (const k of kinds) got.push(...(await api(`/api/library?kind=${k}&q=${encodeURIComponent(q)}`)).items);
      items = got.sort((a, b) => b.created - a.created);
      draw();
    }
    function draw() {
      grid.replaceChildren(items.length ? items.map(a => h("div", { class: "tile" + (chosen.has(a.id) ? " sel" : "") },
        a.kind === "audio" ? h("button", { class: "pic audio", onclick: () => pick(a) }, "♪")
          : h("button", { class: "pic", style: { backgroundImage: `url("${a.thumb}")` }, "aria-label": a.name, onclick: () => pick(a) }),
        h("div", { class: "meta" }, h("div", { class: "name", title: a.name }, a.name),
          a.kind === "audio" ? h("audio", { src: a.url, controls: true, style: { width: "100%", height: "30px" } }) : null)))
        : h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, "Nothing here yet. Upload a file, or make one first."));
    }
    function pick(a) {
      if (!o.multiple) return done(a);
      chosen.has(a.id) ? chosen.delete(a.id) : chosen.add(a.id);
      draw();
    }
    modal(h("div", {},
      h("div", { class: "spread" }, h("h2", {}, o.title || "Pick from the Library"), h("button", { class: "ghost", onclick: () => done(null) }, "Close")),
      h("div", { class: "row" },
        h("div", { class: "field" }, (() => { const i = h("input", { type: "search", placeholder: "Search by name or prompt…", "aria-label": "Search" });
          i.addEventListener("input", debounce(() => { q = i.value; load(); }, 250)); return i; })()),
        h("div", { class: "field fit" }, h("button", { onclick: async () => {
          const files = await chooseFiles(ACCEPT[kind] || "", o.multiple);
          if (!files.length) return;
          try { const up = await upload(files); if (!o.multiple) return done(up[0]); up.forEach(a => chosen.add(a.id)); await load(); } catch (e) { toast(e.message, true); }
        } }, "Upload…")),
        o.multiple ? h("div", { class: "field fit" }, h("button", { class: "primary", onclick: () => done(items.filter(a => chosen.has(a.id))) }, "Use these")) : null),
      grid));
    load().catch(e => toast(e.message, true));
  });
}

// A picture or sound slot bound to obj[key] (a loader name). Buttons: pick, upload, clear.
function refPicker(obj, key, o = {}) {
  const kind = o.kind || "image";
  const box = h("div", { class: "refpick" });
  function draw() {
    const name = obj[key] || "";
    box.replaceChildren(
      kind === "audio"
        ? h("div", { class: "th" }, "♪")
        : h("div", { class: "th", style: name ? { backgroundImage: `url("${refThumb(name)}")` } : {} }, name ? "" : "+"),
      h("div", { style: { minWidth: 0, flex: 1 } },
        name ? h("div", { class: "nm", title: name }, name.replace(/ \[output\]$/, "").split("/").pop()) : h("div", { class: "nm faint" }, o.empty || "none"),
        name && kind === "audio" ? h("audio", { src: refUrl(name), controls: true, style: { width: "100%", height: "28px" } }) : null,
        h("div", { style: { display: "flex", gap: "4px", marginTop: "4px", flexWrap: "wrap" } },
          name && kind === "clip" ? h("button", { class: "small", onclick: () => playModal(refUrl(name), name.replace(/ \[output\]$/, "").split("/").pop()) }, "▶ Play") : null,
          h("button", { class: "small", onclick: async () => { const a = await pickAsset(kind, { title: o.title }); if (a) set(a.ref); } }, name ? "Change" : "Pick…"),
          o.make ? h("button", { class: "small", onclick: o.make }, o.makeLabel || "Make one") : null,
          name ? h("button", { class: "small ghost", onclick: () => set("") }, "Clear") : null)));
  }
  function set(v) { obj[key] = v; draw(); if (o.onchange) o.onchange(v); }
  draw();
  return box;
}

// ---------------------------------------------------------------- findings and check results
function findingsList(findings) {
  if (!findings || !findings.length) return h("div", { class: "note good" }, "The prompt check found nothing.");
  const order = [...findings].sort((a, b) => (a.level === "warn" ? 0 : 1) - (b.level === "warn" ? 0 : 1));
  return h("div", {}, order.map(f => h("div", { class: "finding lv-" + f.level }, h("span", { class: "lv" }, f.level), h("span", {}, f.text))));
}
function checkChips(report) {
  if (!report || !report.checks) return null;
  const cls = { pass: "good", fail: "bad", skip: "", note: "info" };
  return h("div", { class: "checks" }, report.checks.map(c => h("span", { class: "chip " + (cls[c.status] || ""), title: c.text }, c.name + ": " + c.status)));
}
function checkDetails(report) {
  if (!report || !report.checks) return null;
  return h("div", { class: "small" }, report.checks.map(c => h("div", { class: c.status === "fail" ? "bad" : c.status === "pass" ? "" : "muted", style: { margin: "2px 0" } },
    h("b", {}, c.name), " — ", c.text)));
}

// ---------------------------------------------------------------- lines of dialogue
function linesEditor(lines, speakers, onchange) {
  const box = h("div", {});
  function draw() {
    box.replaceChildren(
      lines.map((ln, i) => h("div", { class: "linerow" },
        speakers().length ? select(ln, "speaker", [["", "(who)"], ...speakers().map(s => [s[0], s[1]])], { onchange })
          : text(ln, "speaker", { placeholder: "who", oninput: onchange }),
        text(ln, "text", { placeholder: "the exact words", oninput: onchange }),
        text(ln, "how", { placeholder: "how it is said: warm, half whispering…", oninput: onchange }),
        h("button", { class: "ghost small", "aria-label": "Remove this line", onclick: () => { lines.splice(i, 1); draw(); onchange && onchange(); } }, "✕"))),
      h("button", { class: "small", onclick: () => { lines.push({ speaker: speakers().length ? speakers()[lines.length % speakers().length][0] : "", text: "", how: "" }); draw(); onchange && onchange(); } }, "+ Line"),
      lines.length ? null : h("span", { class: "faint small", style: { marginLeft: "10px" } }, "No lines: the part stays without words."));
  }
  draw();
  return box;
}

// ---------------------------------------------------------------- LoRAs
function lorasEditor(list, onchange) {
  const box = h("div", {});
  async function draw() {
    let m = { loras: [] };
    try { m = await getMachine(); } catch (e) { /* ComfyUI down: show what is set */ }
    const opts = [["", "(pick a LoRA)"], ...m.loras.map(l => [l, l])];
    box.replaceChildren(
      list.map((l, i) => h("div", { class: "row", style: { marginBottom: "6px" } },
        h("div", { class: "field", style: { marginBottom: 0 } }, select(l, "file", opts.some(o => o[0] === l.file) ? opts : [...opts, [l.file, l.file + " (not installed)"]], { onchange })),
        h("div", { class: "field fit", style: { marginBottom: 0 } }, number(l, "strength", { min: 0, max: 2, step: 0.05, oninput: onchange })),
        h("button", { class: "ghost small fit", "aria-label": "Remove this LoRA", onclick: () => { list.splice(i, 1); draw(); onchange && onchange(); } }, "✕"))),
      h("button", { class: "small", onclick: () => { list.push({ file: "", strength: 0.8 }); draw(); } }, "+ LoRA"));
  }
  draw();
  return box;
}

// ---------------------------------------------------------------- Library tiles and the detail of one file
function assetTile(a, o = {}) {
  const pic = a.kind === "audio" ? h("button", { class: "pic audio", onclick: () => (o.onopen || openAsset)(a.id) }, "♪")
    : h("button", { class: "pic", style: { backgroundImage: `url("${a.thumb}")` }, "aria-label": "Open " + a.name, onclick: () => (o.onopen || openAsset)(a.id) });
  return h("div", { class: "tile" + (o.selected ? " sel" : "") }, pic,
    h("span", { class: "kind" }, a.kind + (a.duration ? " · " + secs(a.duration) : "")),
    o.onselect ? h("input", { type: "checkbox", class: "pick", checked: !!o.selected, "aria-label": "Select " + a.name, onchange: () => o.onselect(a) }) : null,
    h("div", { class: "meta" }, h("div", { class: "name", title: a.name }, a.name),
      a.ok === false ? h("span", { class: "chip bad", title: a.summary || "" }, "check failed") : a.ok === true ? h("span", { class: "chip good" }, "checks passed") : null,
      a.kind === "audio" ? h("audio", { src: a.url, controls: true, style: { width: "100%", height: "30px", marginTop: "4px" } }) : null),
    o.actions ? h("div", { class: "acts" }, o.actions(a)) : null);
}
function viewer(a) {
  if (a.kind === "audio") return h("audio", { src: a.url, controls: true, style: { width: "100%" } });
  if (a.kind === "image" || a.kind === "sheet") return h("img", { class: "big", src: a.url, alt: a.name });
  return h("video", { src: a.url, controls: true, preload: "metadata", poster: a.thumb });
}
async function openAsset(id) {
  const a = await tryApi("/api/library/" + id);
  if (!a) return;
  modal(h("div", {},
    h("div", { class: "spread" }, h("h2", {}, a.name), h("button", { class: "ghost", onclick: closeModal }, "Close")),
    viewer(a),
    h("div", { class: "row", style: { gap: "6px", marginBottom: "12px" } }, assetActions(a, true)),
    a.summary ? h("div", { class: "note " + (a.ok === false ? "bad" : "good") }, a.summary) : null,
    a.checks ? checkDetails({ checks: a.checks }) : null,
    a.transcript ? field("Heard in it", h("div", { class: "prompt" }, a.transcript)) : null,
    a.prompt ? field("Prompt", h("div", { class: "prompt" }, a.prompt)) : null,
    h("div", { class: "small muted" }, [a.width && a.height ? a.width + "x" + a.height : "", a.fps ? a.fps + " fps" : "", a.duration ? secs(a.duration) : "",
      a.seed ? "seed " + a.seed : "", a.size ? (a.size / 2 ** 20).toFixed(1) + " MB" : "", "output/" + a.path].filter(Boolean).join(" · "))));
}
async function runJob(kind, params, title, okText) {
  const j = await tryApi("/api/jobs", { kind, params, title });
  if (j) { toast(okText || "Queued"); poll(); }
  return j;
}
// What can be done with a file, as buttons. `full` = in the detail view (more of them).
function assetActions(a, full) {
  const b = (label, fn, cls) => h("button", { class: "small" + (cls ? " " + cls : ""), onclick: e => { e.stopPropagation(); fn(); } }, label);
  const out = [];
  const leave = fn => () => { closeModal(); fn(); };
  if (a.kind === "image" || a.kind === "sheet") {
    out.push(b("Animate", leave(() => go("video", "", { start: "first", first_frame: a.ref })), "primary"));
    out.push(b("Edit", leave(() => go("picture", "", { attach: [{ ref: a.ref, thumb: a.thumb }] }))));
    if (full) out.push(b("Remix", leave(() => go("remix", "", { asset: a }))));
    if (full) {
      out.push(b("As a reference", leave(() => go("video", "", { start: "refs", refs: [{ file: a.ref, label: a.name }] }))));
      out.push(b("Ends a clip", leave(() => go("video", "", { start: "first_last", last_frame: a.ref }))));
      out.push(b("Other angles", leave(() => go("edit", "", { picture: a.ref, mode: "angles" }))));
    }
  } else if (a.kind === "clip" || a.kind === "film" || a.kind === "export") {
    if (a.quick && a.film) out.push(b("Extend", leave(() => go("video", "clip/" + a.film)), "primary"));
    if (a.film && !a.quick && full) out.push(b("Open the film", leave(() => go("films", a.film + "/roll"))));
    out.push(b("+ Timeline", leave(() => addToTimeline([a.id]))));
    if (full) {
      if (a.film && !a.upscaled) out.push(b("Upscale", async () => { if (await tryApi(`/api/films/${a.film}/upscale`, {})) { toast("Upscale queued"); poll(); } }));
      out.push(b("Last frame → picture", async () => { const p = await tryApi("/api/frame", { asset: a.id, at: "last" }); if (p) { toast("Saved to the Library"); closeModal(); openAsset(p.id); } }));
      out.push(b("Captions", () => runJob("captions", { asset: a.id }, "Captions · " + a.name)));
      out.push(b("Check again", () => runJob("review", { asset: a.id }, "Check · " + a.name)));
      out.push(b("Location sound", () => runJob("location_sound", { asset: a.id }, "Location sound · " + a.name)));
      out.push(b("ProRes for Resolve", () => runJob("resolve", { asset: a.id }, "ProRes · " + a.name)));
    }
  } else if (a.kind === "audio" && full) {
    out.push(b("Find the beats", async () => { const r = await tryApi("/api/beats", { asset: a.id }); if (r) toast(`${r.bpm} BPM, ${r.beats.length} beats, ${r.bars} bars`); }));
  }
  if (full) {
    out.push(h("a", { class: "btn small", href: a.url, download: a.path.split("/").pop() }, "Download"));
    out.push(b("Delete", async () => { const r = await tryApi("/api/library/trash", { ids: [a.id] }); if (r) { toast(r.moved.length ? "Moved to the trash" : (r.kept[0] || [])[1] || "Kept", !r.moved.length); closeModal(); if (S.room === "library") route(); } }, "danger"));
  }
  return out;
}
async function addToTimeline(ids) {
  let list = await tryApi("/api/timelines");
  if (!list) return;
  let tid = list[0] && list[0].id;
  if (!tid) { const t = await tryApi("/api/timelines", { name: "Timeline" }); if (!t) return; tid = t.id; }
  if (await tryApi(`/api/timelines/${tid}/clips`, { assets: ids })) toast("Added to the timeline “" + ((list[0] || {}).name || "Timeline") + "”");
}
async function openFilmOrClip(fid) {
  const f = await tryApi("/api/films/" + fid);
  if (!f) return;
  if (f.quick) go("video", "clip/" + fid); else go("films", fid + "/roll");
}
function statusChip(s) {
  const map = { todo: ["to do", ""], queued: ["queued", "info"], rendering: ["rendering", "accent"], review: ["at the gate", "warn"], approved: ["approved", "good"],
    stale: ["stale", "bad"], failed: ["failed", "bad"] };
  const [label, cls] = map[s] || [s, ""];
  return h("span", { class: "chip " + cls }, label);
}

// ---------------------------------------------------------------- blockout videos
// A video that plays only frames start..end (24 fps): a continuation follows a stretch of its take's blockout.
function rangeVideo(src, start = 0, end = 0, o = {}) {
  const v = h("video", { src, controls: true, muted: true, preload: "metadata", playsinline: true,
    style: { width: "100%", borderRadius: "4px", background: "#000", ...(o.style || {}) } });
  const a = start / 24, b = end ? end / 24 : 0;
  v.addEventListener("loadedmetadata", () => { if (a) v.currentTime = a; });
  v.addEventListener("timeupdate", () => { if (b && v.currentTime >= b) { v.pause(); v.currentTime = a; } else if (v.currentTime < a - 0.05) v.currentTime = a; });
  return v;
}
// The blockout and a take side by side, started together.
function compareModal(blockout, take, title) {
  const left = rangeVideo(blockout.src, blockout.start, blockout.end), right = rangeVideo(take, 0, 0);
  right.muted = false;
  const both = async () => { left.currentTime = (blockout.start || 0) / 24; right.currentTime = 0; await Promise.all([left.play(), right.play()]).catch(() => {}); };
  modal(h("div", {},
    h("div", { class: "spread" }, h("h2", {}, title || "The blockout and the take"), h("button", { class: "ghost", onclick: closeModal }, "Close")),
    h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" } },
      h("div", {}, h("div", { class: "muted small" }, "Blockout"), left), h("div", {}, h("div", { class: "muted small" }, "Take"), right)),
    h("div", { class: "row", style: { marginTop: "10px", gap: "6px" } }, h("button", { class: "primary", onclick: both }, "▶ Play both"),
      h("button", { onclick: () => { left.pause(); right.pause(); } }, "Pause"))));
}
// Play a clip in a window of its own.
function playModal(src, title) {
  modal(h("div", {}, h("div", { class: "spread" }, h("h2", {}, title || "Clip"), h("button", { class: "ghost", onclick: closeModal }, "Close")),
    h("video", { src, controls: true, autoplay: true, style: { width: "100%", borderRadius: "4px", background: "#000" } })));
}
