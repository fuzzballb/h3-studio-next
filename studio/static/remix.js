"use strict";
// Remix: one picture and a direction make a moving take; as many takes as you like.
// Shorts: one idea becomes a vertical video in one continuous take (a few parts that continue each other).

const REMIX_DIRECTIONS = [
  ["Slow push in", "The camera pushes in slowly toward the subject. Everything else holds still, with only small natural motion: breathing, a little wind."],
  ["Half orbit", "The camera circles halfway around the subject at the same height, smooth and steady, keeping it in the middle of the picture."],
  ["Pull back and rise", "The camera pulls back slowly and rises, revealing the wider place around the subject."],
  ["Comes to life", "The person in the picture blinks, breathes and slowly turns their head toward the camera with a small smile."],
  ["Wind picks up", "A strong wind picks up: hair, clothes, leaves and dust move with it, and clouds race across the sky."],
  ["Rain starts", "Rain starts to fall. Drops hit every surface, puddles form and the light turns grey and soft."],
  ["Day into night", "The daylight fades into night; street lamps and windows switch on one by one."],
  ["Handheld walk", "A handheld camera walks forward through the scene at walking pace, with a slight natural sway."],
  ["Product turn", "The object turns slowly on its own axis in front of the camera while the studio light glides over its surfaces."],
];
const REMIX_FALLBACK = "The picture comes to life with gentle, natural motion; the camera holds still.";

function dropSlot(o) {
  // A picture slot: click to pick from the Library or upload, or drop a file on it.
  const slot = h("button", { class: "drop" + (o.value ? " has" : ""), style: o.value ? { backgroundImage: `url("${o.value.thumb}")` } : {} },
    o.value ? null : h("div", {}, h("b", {}, o.title), h("span", {}, o.hint)));
  slot.addEventListener("click", async () => { const a = await pickAsset("image", { title: o.title }); if (a) o.onpick(a); });
  slot.addEventListener("dragover", e => { e.preventDefault(); slot.classList.add("over"); });
  slot.addEventListener("dragleave", () => slot.classList.remove("over"));
  slot.addEventListener("drop", async e => {
    e.preventDefault(); slot.classList.remove("over");
    const files = [...(e.dataTransfer.files || [])].filter(f => f.type.startsWith("image/"));
    if (!files.length) return;
    try { const up = await upload(files.slice(0, 1)); if (up[0]) o.onpick(up[0]); } catch (err) { toast(err.message, true); }
  });
  return o.value ? h("div", { style: { position: "relative" } }, slot, h("button", { class: "small x", style: { position: "absolute", top: "8px", right: "8px" }, "aria-label": o.clear, onclick: () => o.onpick(null) }, "✕")) : slot;
}

ROOMS.remix = { title: "Remix", full: true, draw(root) {
  const pend = S.pending || {}; S.pending = null;
  const f = Object.assign({ source: null, end: null, usePrompt: true, prompt: "", mode: "standard", frames: 209, tab: "ideas", takes: 1 }, ROOMS.remix.keep || {});
  if (pend.asset) { f.source = { ref: pend.asset.ref, thumb: pend.asset.thumb, width: pend.asset.width, height: pend.asset.height }; f.end = null; }
  if (pend.form) {
    const r = pend.form;
    f.source = r.first_frame ? { ref: r.first_frame, thumb: refThumb(r.first_frame), width: r.width, height: r.height } : f.source;
    f.end = r.last_frame ? { ref: r.last_frame, thumb: refThumb(r.last_frame) } : null;
    f.prompt = r.action || ""; f.usePrompt = !!r.action && r.action !== REMIX_FALLBACK; f.mode = r.turbo === false ? "pro" : "standard"; f.frames = r.frames || 209;
    toast("That remix's settings are filled in");
  }
  ROOMS.remix.keep = f;
  const mine = new Set();
  const form = h("div", { class: "form" }), out = h("div", { class: "out" });
  let est = null;
  function size() {
    const s = f.source || {};
    const tall = (s.height || 0) > (s.width || 1) * 1.1, square = s.width && s.height && Math.abs(s.width - s.height) / s.width < 0.1;
    return square ? [768, 768] : tall ? [640, 1152] : [1152, 640];
  }
  function payload() {
    const [width, height] = size();
    const action = f.usePrompt && f.prompt.trim() ? f.prompt.trim() : REMIX_FALLBACK;
    const d = { name: "Remix · " + action.slice(0, 36), mode: "fields", action, first_frame: f.source && f.source.ref, width, height, frames: f.frames,
      turbo: f.mode === "standard", one_take: true, notext: true, look: "cinematic", surface: "remix", lines: [], people: [] };
    if (f.end) d.last_frame = f.end.ref;
    return d;
  }
  const refreshEst = debounce(async () => { if (!f.source) return; try { const c = await api("/api/compose", payload()); est = c.estimate; drawForm(); } catch (e) { /* not ready */ } }, 400);
  function drawForm() {
    form.replaceChildren(
      h("div", {}, h("div", { class: "kicker" }, "Picture to motion"), h("h1", { class: "display", style: { fontSize: "34px" } }, "Remix")),
      dropSlot({ value: f.source, title: "Add a source picture", hint: "to set it in motion · PNG, JPG or WebP", clear: "Remove the source picture",
        onpick: a => { f.source = a ? { ref: a.ref, thumb: a.thumb, width: a.width, height: a.height } : null; drawForm(); refreshEst(); } }),
      f.source ? dropSlot({ value: f.end, title: "Add an end picture", hint: "optional: the take lands on it", clear: "Remove the end picture",
        onpick: a => { f.end = a ? { ref: a.ref, thumb: a.thumb } : null; drawForm(); refreshEst(); } }) : null,
      h("div", {}, h("div", { class: "spread", style: { marginBottom: "6px" } }, h("label", { style: { margin: 0 } }, "Prompt"),
        (() => { const t = h("span", { class: "toggle" + (f.usePrompt ? " on" : ""), role: "switch", tabindex: "0", "aria-checked": f.usePrompt ? "true" : "false",
          onclick: () => { f.usePrompt = !f.usePrompt; drawForm(); refreshEst(); }, onkeydown: e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); t.click(); } } }, h("span", { class: "sw" })); return t; })()),
        f.usePrompt ? text(f, "prompt", { rows: 4, placeholder: "Describe the new version: what moves, how the camera moves, the light.", oninput: refreshEst })
          : h("div", { class: "muted small" }, "Off: the picture simply comes to life.")),
      h("div", {}, h("label", {}, "Mode"), h("div", { class: "segs" }, [["standard", "Standard", "turbo, quick"], ["pro", "Pro", "all steps, finer"]].map(([v, l, hh]) =>
        h("button", { class: f.mode === v ? "on" : "", onclick: () => { f.mode = v; drawForm(); refreshEst(); } }, l, h("span", { class: "h" }, hh))))),
      h("div", {}, h("label", {}, "Length"), h("div", { class: "segs" }, [[124, "5 s"], [209, "8.7 s"], [243, "10 s"]].map(([v, l]) =>
        h("button", { class: f.frames === v ? "on" : "", onclick: () => { f.frames = v; drawForm(); refreshEst(); } }, l)))),
      h("div", {}, h("label", {}, "Takes"), countChip(f.takes, 1, 6, v => { f.takes = v; })),
      h("div", { style: { marginTop: "auto" } }, h("button", { class: "go", style: { width: "100%", height: "58px", flexDirection: "row", gap: "10px" }, disabled: !f.source, onclick: make },
        h("span", {}, f.takes > 1 ? `Generate ${f.takes} takes` : "Generate"), h("span", { class: "est" }, est ? about(est * f.takes) : "")),
        f.source ? null : h("div", { class: "hint", style: { marginTop: "8px", textAlign: "center" } }, "Add a source picture first.")));
  }
  async function make() {
    if (!f.source) return toast("Add a source picture first", true);
    for (let i = 0; i < f.takes; i++) {
      const r = await tryApi("/api/clips", { ...payload(), seed: 0 });
      if (!r) return;
      trackJob(mine, r.job);
    }
    toast(f.takes > 1 ? f.takes + " takes queued" : "Queued"); poll(); f.tab = "history"; drawOut();
  }
  async function drawOut() {
    const bar = tabs([["ideas", "Directions"], ["history", "History"]], f.tab, t => { f.tab = t; drawOut(); });
    if (f.tab === "ideas") {
      out.replaceChildren(bar, h("div", { style: { margin: "4px 0 18px" } }, h("h1", { class: "display", style: { fontSize: "30px" } }, "One picture, many takes"),
        h("p", { class: "muted" }, "Start from a still of your own, pick a direction below or write your own, and get a new moving version of it, rendered on this computer.")),
        h("div", { class: "directions" }, REMIX_DIRECTIONS.map(([t, d]) => h("div", { class: "direction" }, h("b", {}, t), h("span", {}, d),
          h("button", { class: "small use", onclick: () => { f.prompt = d; f.usePrompt = true; drawForm(); refreshEst(); toast("Direction set: " + t); } }, "Use this direction")))));
      return;
    }
    const r = await tryApi("/api/library?kind=clip&surface=remix&limit=60");
    const items = r ? r.items : [];
    out.replaceChildren(bar, h("div", { class: "results" }, pendingTiles(mine, ["shot"]), items.map(a => post(a))),
      !items.length && !mine.size ? h("div", { class: "empty" }, h("b", {}, "Nothing remixed yet"), h("div", {}, "Add a picture on the left, give it a direction and press Generate.")) : null);
  }
  onJobEnd(j => { if (j.kind === "shot" && f.tab === "history") drawOut(); });
  root.append(h("div", { class: "sideform" }, form, out));
  drawForm(); drawOut(); refreshEst();
} };

// ---------------------------------------------------------------- Shorts
ROOMS.shorts = { title: "Shorts", full: true, draw(root) {
  const pend = S.pending || {}; S.pending = null;
  const f = Object.assign({ idea: "", parts: 3, size: "640x1152", face: "", voice: "", plan: null, busy: false }, ROOMS.shorts.keep || {});
  if (pend.plan) { f.plan = JSON.parse(JSON.stringify(pend.plan)); f.size = pend.size || f.size; f.parts = f.plan.beats.length; toast("That short's plan is filled in"); }
  ROOMS.shorts.keep = f;
  const form = h("div", { class: "form" }), out = h("div", { class: "out" });
  const lineText = b => (b.lines || []).map(l => (l.speaker ? l.speaker + ": " : "") + l.text).join("\n");
  const parseLines = t => t.split("\n").map(x => x.trim()).filter(Boolean).map(x => { const i = x.indexOf(":"); return i > 0 ? { speaker: x.slice(0, i).trim(), text: x.slice(i + 1).trim() } : { speaker: "", text: x }; });
  function drawForm() {
    form.replaceChildren(
      h("div", {}, h("div", { class: "kicker" }, "One idea, one take"), h("h1", { class: "display", style: { fontSize: "34px" } }, "Shorts")),
      field("The idea", text(f, "idea", { rows: 5, placeholder: "A street musician in the rain plays one last song, and a kid starts dancing in the puddles." }),
        "Claude Code on this computer splits it into parts; only these words are sent. You can change every part before anything renders."),
      h("div", {}, h("label", {}, "Length"), h("div", { class: "segs" }, [[2, "≈ 17 s"], [3, "≈ 25 s"], [4, "≈ 33 s"], [5, "≈ 41 s"]].map(([n, l]) =>
        h("button", { class: f.parts === n ? "on" : "", onclick: () => { f.parts = n; drawForm(); } }, l, h("span", { class: "h" }, n + " parts")))) ),
      h("div", {}, h("label", {}, "Size"), h("div", { class: "segs" }, [["640x1152", "9:16", "640×1152"], ["480x864", "9:16 draft", "quicker"]].map(([v, l, hh]) =>
        h("button", { class: f.size === v ? "on" : "", onclick: () => { f.size = v; drawForm(); } }, l, h("span", { class: "h" }, hh))))),
      h("details", {}, h("summary", { class: "muted", style: { cursor: "pointer" } }, "The first person's face and voice (optional)"),
        h("div", { style: { marginTop: "10px" } }, field("Face", refPicker(f, "face", { empty: "a tight face crop" })), field("Voice sample", refPicker(f, "voice", { kind: "audio", empty: "10–20 s of clean speech" })))),
      h("button", { class: f.plan ? "" : "primary", disabled: f.busy, onclick: plan }, f.busy ? "Planning…" : f.plan ? "Plan it again" : "Plan it"),
      f.plan ? h("button", { class: "go", style: { width: "100%", height: "58px", flexDirection: "row", gap: "10px" }, onclick: render },
        h("span", {}, "Render the short"), h("span", { class: "est" }, "≈ " + (f.plan.beats.length * (f.size === "480x864" ? 3 : 6)) + " min")) : null);
  }
  async function plan() {
    if (!f.idea.trim()) return toast("Write the idea first", true);
    f.busy = true; drawForm(); drawOut();
    const r = await tryApi("/api/shorts/plan", { idea: f.idea, parts: f.parts });
    f.busy = false;
    if (r) f.plan = r.plan;
    drawForm(); drawOut();
  }
  async function render() {
    const r = await tryApi("/api/shorts", { plan: f.plan, size: f.size, face: f.face, voice: f.voice });
    if (r) { toast(`Queued: ${r.parts} parts, rendered in order`); poll(); drawOut(); }
  }
  async function drawOut() {
    const parts = [];
    if (f.busy) parts.push(h("div", { class: "thinking", style: { margin: "20px 0" } }, h("i"), h("i"), h("i"), "Claude is planning the parts…"));
    if (f.plan) {
      const p = f.plan;
      parts.push(h("div", { class: "section-head" }, h("h2", {}, "The plan"), h("span", { class: "muted small" }, "Change anything; it renders as written.")),
        h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Title"), text(p, "title")), h("div", { class: "field" }, h("label", {}, "Look"), select(p, "look", lookOptions()))),
        field("The place", text(p, "place", { rows: 2 })),
        (p.people || []).length ? field("People", h("div", {}, p.people.map(x => h("div", { class: "row", style: { marginBottom: "6px" } },
          h("div", { class: "field fit", style: { width: "130px", marginBottom: 0 } }, text(x, "name")), h("div", { class: "field", style: { marginBottom: 0 } }, text(x, "description")))))) : null,
        p.beats.map((b, i) => h("div", { class: "beat" }, h("div", { class: "spread" }, h("span", { class: "n" }, `Part ${i + 1}` + (i ? " · continues" : " · opens")),
          p.beats.length > 1 ? h("button", { class: "ghost small", onclick: () => { p.beats.splice(i, 1); drawOut(); } }, "Remove") : null),
          field("What happens", text(b, "action", { rows: 2 })),
          h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Spoken lines (Name: words)"),
            (() => { const t = h("textarea", { rows: 2, placeholder: "Nobody speaks" }); t.value = lineText(b); t.addEventListener("input", () => { b.lines = parseLines(t.value); }); return t; })()),
            h("div", { class: "field" }, h("label", {}, "Sound"), text(b, "sound"))))),
        p.beats.length < 6 ? h("button", { class: "small", onclick: () => { p.beats.push({ action: "", sound: "", lines: [] }); drawOut(); } }, "+ Part") : null);
    }
    const r = await tryApi("/api/library?kind=clip&surface=shorts&limit=24");
    const made = r ? r.items : [];
    const live = S.state.jobs.filter(j => j.kind === "shot" && (j.status === "queued" || j.status === "running") && made.every(a => a.film !== j.film)).length;
    out.replaceChildren(parts.length ? parts : h("div", { style: { margin: "4px 0 22px" } }, h("h1", { class: "display", style: { fontSize: "30px" } }, "One idea, ", h("span", { class: "lime" }, "a short")),
      h("p", { class: "muted" }, "Write an idea on the left and press Plan it. The parts continue each other in one take: same place, same light, the camera goes on.")),
      h("div", { class: "section-head", style: { marginTop: "26px" } }, h("h2", {}, "Your shorts"), live ? h("span", { class: "chip accent" }, "rendering") : null),
      made.length ? h("div", { class: "row", style: { gap: "18px", alignItems: "flex-start" } }, made.map(a => h("div", { style: { display: "flex", flexDirection: "column", gap: "8px", alignItems: "center" } },
        h("div", { class: "phone" }, h("video", { src: a.url, controls: true, preload: "metadata", poster: a.thumb })),
        h("div", { class: "row", style: { gap: "6px" } }, h("button", { class: "small white", onclick: () => recreate(a) }, "↻ Recreate"), h("button", { class: "small", onclick: () => openAsset(a.id) }, "More…")))))
        : h("div", { class: "empty" }, "No shorts yet."));
  }
  onJobEnd(j => { if (j.kind === "shot") drawOut(); });
  root.append(h("div", { class: "sideform" }, form, out));
  drawForm(); drawOut();
} };
