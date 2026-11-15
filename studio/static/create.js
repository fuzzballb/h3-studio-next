"use strict";
// Create: Picture, Edit a picture, Video. And Home and Apps, which lead here.

// ---------------------------------------------------------------- Home
ROOMS.home = { title: "Home", draw(root) {
  const cards = h("div", { class: "tiles big" });
  const recent = h("div", { class: "tiles" });
  const filmsBox = h("div", {});
  // the same steps as the tabs of a film (films.STEPS), after the start
  const flow = [["writer", "▶", "Start: the Writer", "Tell it a small story; it writes steps 1, 3 and 4 for you. Or start an empty film."],
    ["films", "1", "Bible", "The logline, the look, the size."],
    ["films", "2", "Cast & places", "A face picture for each person, a voice, the places."],
    ["films", "3", "Shots", "What happens in each shot, in scenes."],
    ["films", "4", "Blockout", "Optional: a rough 3D scene, refined, then cut into its shots."],
    ["films", "5", "Storyboard", "Optional: a still of each shot."],
    ["films", "6", "Roll camera", "Preview, render and approve each shot in order."],
    ["films", "7", "Deliver", "Upscale; cut, mix and export on a timeline."]];
  root.append(head("H3 Studio", "A film studio on your own computer: pictures with Qwen-Image, video with sound with MiniMax H3, all rendered by the ComfyUI on this machine."),
    h("h2", {}, "Make a film, step by step"),
    h("div", { class: "flow" }, flow.map(([r, n, b, s]) => h("button", { onclick: () => go(r) }, h("b", {}, h("span", { class: "stepn" }, n), b), h("span", {}, s)))),
    filmsBox,
    h("h2", { style: { marginTop: "22px" } }, "Or make one thing"),
    h("div", { class: "choice" },
      [["picture", "A picture", "A scout, a face, a place, a product."], ["edit", "Edit a picture", "Change, extend or turn one you have."],
       ["video", "A clip", "From words, a first frame or reference pictures."], ["apps", "Apps", "One-click starts for every tool."]]
        .map(([r, b, s]) => h("button", { onclick: () => go(r) }, h("b", {}, b), h("span", {}, s)))),
    h("h2", { style: { marginTop: "22px" } }, "Newest in the Library"), recent,
    h("h2", { style: { marginTop: "22px" } }, "This machine"), cards);
  getMachine(true).then(m => {
    const g = m.gpus[0];
    const stat = (title, value, sub, cls) => h("div", { class: "card", style: { margin: 0 } }, h("h3", {}, title), h("div", { style: { fontSize: "20px", fontWeight: 650 }, class: cls || "" }, value), h("div", { class: "muted small" }, sub));
    const off = Object.values(m.features).filter(f => !f.ok);
    cards.replaceChildren(
      stat("ComfyUI", m.comfy.up ? "running" : "not running", m.comfy.up ? `${m.nodes} node types · ${m.comfy.running + m.comfy.pending} job(s) of its own` : (m.comfy.can_start ? "Start it from the queue panel." : "Start ComfyUI, then reload."), m.comfy.up ? "good" : "bad"),
      g ? stat("GPU", gb(g.total - g.used) + " free", `${g.name} · ${gb(g.total)}`) : stat("GPU", "unknown", "nvidia-smi not found"),
      stat("Memory", gb(m.memory.available) + " free", "of " + gb(m.memory.total)),
      stat("Disk for renders", gb(m.disk.free) + " free", m.disk.path, m.disk.free < 20 * 2 ** 30 ? "warn" : ""),
      m.comfy.up ? stat("What can run", off.length ? `${Object.keys(m.features).length - off.length} of ${Object.keys(m.features).length}` : "everything", off.length ? off.map(f => f.title).join("; ") : "Every feature has its nodes and models.", off.length ? "warn" : "good") : null);
  }).catch(() => {});
  api("/api/films").then(list => filmsBox.replaceChildren(list.length ? [h("h3", {}, "Your films, and the step each is at"), h("div", { class: "tiles big" }, list.slice(0, 6).map(f =>
    h("button", { class: "app card", style: { margin: 0 }, onclick: () => go("films", f.id + (f.next ? "/" + f.next.id : "")) }, h("b", {}, f.name),
      h("span", {}, `${f.shots} shots · ${f.approved} approved · ${secs(f.seconds)}`),
      f.review ? h("span", { class: "chip warn" }, f.review + " at the gate") : f.next ? h("span", { style: { color: "var(--text)" } }, `Next: ${f.next.n} · ${f.next.label}`) : h("span", { class: "good" }, "✓ Finished"))))]
    : h("div", { class: "empty" }, "No films yet: start with step 1."))).catch(() => {});
  api("/api/library?limit=12").then(r => recent.replaceChildren(r.items.length ? r.items.map(a => assetTile(a)) : h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, "Nothing made yet."))).catch(() => {});
} };

// ---------------------------------------------------------------- Apps
ROOMS.apps = { title: "Apps", draw(root) {
  const st = { q: "", group: "All" };
  const grid = h("div", {});
  let feats = null;
  getMachine().then(m => { feats = m.features; draw(); }).catch(() => {});
  function draw() {
    const q = st.q.toLowerCase();
    const apps = P().apps.apps.filter(a => (st.group === "All" || a.group === st.group) && (!q || (a.name + " " + a.line).toLowerCase().includes(q)));
    const groups = [...new Set(apps.map(a => a.group))];
    grid.replaceChildren(groups.length ? groups.map(g => [h("h3", { style: { marginTop: "18px" } }, g), h("div", { class: "tiles big" }, apps.filter(a => a.group === g).map(a => {
      const missing = feats ? (a.needs || []).filter(n => feats[n] && !feats[n].ok) : [];
      return h("button", { class: "app card", style: { margin: 0 }, disabled: missing.length > 0, title: missing.length ? feats[missing[0]].why : "",
        onclick: () => go(a.room, (a.form && a.form.tab) || "", a.form ? { ...a.form, app: a.id } : undefined) },
        h("b", {}, a.name), h("span", {}, a.line),
        missing.length ? h("span", { class: "chip bad" }, "cannot run here: " + feats[missing[0]].why) : null,
        a.lora ? h("span", { class: "chip" }, "better with a “" + a.lora.replace(/[.?]/g, " ").trim() + "” LoRA") : null);
    }))]) : h("div", { class: "empty" }, "No app matches."));
  }
  root.append(head("Apps", "Every tool of the studio as a one-click start. An app opens the studio's own form with its choices made; nothing is added or sent anywhere."),
    h("div", { class: "row" }, h("div", { class: "field" }, (() => { const i = h("input", { type: "search", placeholder: "Search the apps…", "aria-label": "Search the apps" }); i.addEventListener("input", () => { st.q = i.value; draw(); }); return i; })())),
    h("div", { class: "choice" }, ["All", ...P().apps.groups].map(g => { const b = h("button", { class: st.group === g ? "on" : "", onclick: () => { st.group = g; root.querySelectorAll(".choice button").forEach(x => x.classList.toggle("on", x.textContent === g)); draw(); } }, g); return b; })),
    grid);
  draw();
} };

// ---------------------------------------------------------------- results of picture jobs, shared by Picture and Edit
function resultsBox(note) {
  const box = h("div", { class: "tiles", style: { marginTop: "14px" } });
  const mine = new Set();
  onJobEnd(async j => {
    if (!mine.has(j.id) || j.status !== "done") return;
    for (const id of (j.result && j.result.assets) || []) { const a = await tryApi("/api/library/" + id); if (a) box.prepend(assetTile(a, { actions: x => assetActions(x) })); }
  });
  return { box, track: j => { mine.add(j.id); S.seen[j.id] = S.seen[j.id] || j.status; } };
}

// ---------------------------------------------------------------- Picture
ROOMS.picture = { title: "Picture", draw(root) {
  const pend = S.pending || {}; S.pending = null;
  const f = { prompt: "", template: pend.template || "", size: (pend.width || 1344) + "x" + (pend.height || 768), takes: pend.takes || 2, seed: 0, name: "" };
  const res = resultsBox();
  const tips = { "": "Describe the picture: who or what, where, the light, the lens.", portrait: "Describe the person: age, face, hair, clothes. The studio adds the framing of a face reference.",
    location: "Describe the empty place, seen from where the camera will stand. The same plate in every new shot keeps a place the same." };
  const hint = h("div", { class: "hint" }, tips[f.template]);
  async function make() {
    if (!f.prompt.trim()) return toast("Write what the picture shows", true);
    const [w, hh] = f.size.split("x").map(Number);
    const j = await tryApi("/api/images", { prompt: f.prompt, template: f.template, width: w, height: hh, takes: f.takes, seed: f.seed || 0, name: f.name });
    if (j) { res.track(j); toast("Queued"); poll(); }
  }
  root.append(head("Picture", "Qwen-Image 2.1 on this machine: about 10 to 30 seconds a picture. Use it for scouts, faces, places and products before any video is rendered."),
    h("div", { class: "card" },
      h("div", { class: "row" },
        h("div", { class: "field" }, h("label", {}, "Kind"), select(f, "template", [["", "Any picture"], ["portrait", "A face for a character"], ["location", "An empty place (a plate)"]], { onchange: v => { hint.textContent = tips[v]; if (v === "portrait") { f.size = "1024x1024"; } route.keep = f; } })),
        h("div", { class: "field" }, h("label", {}, "Size"), select(f, "size", P().image_sizes.map(s => [s.width + "x" + s.height, s.name]))),
        h("div", { class: "field fit" }, h("label", {}, "Takes"), number(f, "takes", { min: 1, max: 12 })),
        h("div", { class: "field fit" }, h("label", {}, "Seed (0 = new)"), number(f, "seed", { min: 0, blankZero: true }))),
      h("div", { class: "field" }, h("label", {}, "What the picture shows"), text(f, "prompt", { rows: 4, placeholder: "A weathered fisherman in his sixties mending a net on a wooden quay, low morning sun, 50mm photo." }), hint),
      h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Name (optional)"), text(f, "name", { placeholder: "how it is listed in the Library" })),
        h("div", { class: "field fit" }, h("button", { class: "primary", onclick: make }, "Make")))),
    h("h2", {}, "Made here"), res.box);
} };

// ---------------------------------------------------------------- Edit a picture
ROOMS.edit = { title: "Edit a picture", draw(root) {
  const pend = S.pending || {}; S.pending = null;
  const f = { picture: pend.picture || "", mode: pend.mode || (pend.angles ? "angles" : pend.template ? "sheet" : "words"), prompt: "", set: pend.angles && pend.angles !== "sheet" ? pend.angles : "around",
    views: [], sheet: pend.template === "propsheet" ? "propsheet" : pend.angles === "sheet" ? "turnaround" : "turnaround", more: [], keep: true, size: "1344x768", seed: 0, takes: 1 };
  if (pend.angles === "sheet") f.mode = "sheet";
  const res = resultsBox();
  const body = h("div", {});
  function drawBody() {
    const A = P().angles;
    if (f.mode === "angles" && !f.views.length) f.views = [...(A.sets.find(s => s.id === f.set) || A.sets[0]).views];
    body.replaceChildren(
      f.mode === "words" ? [
        field("What changes", text(f, "prompt", { rows: 3, placeholder: "The same statue at night under a full moon, wet paving stones, a lantern on the wall behind it." }),
          "Describe the result. What is not mentioned is meant to stay; small things still shift. Further pictures are Picture 2, Picture 3…: “the man of Picture 2 stands in the room of Picture 1”."),
        h("h3", {}, "Further pictures (up to nine)"),
        h("div", { class: "tiles", style: { marginBottom: "12px" } }, f.more.map((m, i) => h("div", { class: "tile" }, h("div", { class: "pic", style: { backgroundImage: `url("${refThumb(m)}")` } }),
          h("div", { class: "meta" }, h("div", { class: "name" }, "Picture " + (i + 2))), h("div", { class: "acts" }, h("button", { class: "small ghost", onclick: () => { f.more.splice(i, 1); drawBody(); } }, "Remove"))))),
        f.more.length < 9 ? h("button", { class: "small", onclick: async () => { const got = await pickAsset("image", { multiple: true }); if (got) { f.more.push(...got.map(a => a.ref)); f.more = f.more.slice(0, 9); drawBody(); } } }, "+ Add pictures") : null,
        h("div", { class: "row", style: { marginTop: "12px" } },
          h("div", { class: "field fit" }, check(f, "keep", "Keep the picture's own shape", { onchange: drawBody })),
          f.keep ? null : h("div", { class: "field" }, h("label", {}, "New canvas"), select(f, "size", P().image_sizes.map(s => [s.width + "x" + s.height, s.name]))),
          h("div", { class: "field fit" }, h("label", {}, "Takes"), number(f, "takes", { min: 1, max: 8 })))]
      : f.mode === "angles" ? [
        h("div", { class: "choice" }, A.sets.map(s => h("button", { class: f.set === s.id ? "on" : "", onclick: () => { f.set = s.id; f.views = [...s.views]; drawBody(); } }, h("b", {}, s.name), h("span", {}, s.views.length + " pictures")))),
        h("div", { class: "choice" }, A.views.map(v => h("button", { class: "small" + (f.views.includes(v.id) ? " on" : ""), onclick: () => { f.views.includes(v.id) ? f.views.splice(f.views.indexOf(v.id), 1) : f.views.push(v.id); f.set = ""; drawBody(); } }, v.name))),
        h("div", { class: "note" }, "One picture a view, from one load of the model. Check a set before you build on it: left and right can come out facing the same way.")]
      : [
        h("div", { class: "choice" }, [["turnaround", "Character sheet", "The person, whole body, four views on a plain background: an outfit reference."],
          ["propsheet", "Product or prop sheet", "The object twice, side and three-quarter view, on white."]].map(([id, b, s]) => h("button", { class: f.sheet === id ? "on" : "", onclick: () => { f.sheet = id; drawBody(); } }, h("b", {}, b), h("span", {}, s)))),
        field(f.sheet === "propsheet" ? "What the object is" : "The clothes (optional)", text(f, "prompt", { rows: 2, placeholder: f.sheet === "propsheet" ? "the small brown cardboard parcel with the red sticker" : "wearing a dark green raincoat, jeans and brown boots" }),
          f.sheet === "propsheet" ? "A prop that is only described in words changes from part to part. A sheet as a reference keeps it the same." : "Leave empty to keep the clothes of the picture.")]);
  }
  async function make() {
    if (!f.picture) return toast("Pick the picture to edit first", true);
    let d;
    if (f.mode === "words") {
      if (!f.prompt.trim()) return toast("Say what changes", true);
      const [w, hh] = f.size.split("x").map(Number);
      d = { prompt: f.prompt, pictures: [f.picture, ...f.more], keep_size: f.keep, width: w, height: hh, takes: f.takes, seed: f.seed || 0 };
    } else if (f.mode === "angles") {
      if (!f.views.length) return toast("Pick at least one view", true);
      d = { pictures: [f.picture], angles: f.views, keep_size: true, seed: f.seed || 0 };
    } else if (f.sheet === "propsheet") {
      if (!f.prompt.trim()) return toast("Say what the object is", true);
      d = { prompt: f.prompt, template: "propsheet", pictures: [f.picture], width: 1536, height: 864, takes: 2, seed: f.seed || 0, name: "sheet " + f.prompt.slice(0, 24) };
    } else {
      d = { prompt: f.prompt, angles: "sheet", pictures: [f.picture], width: 1536, height: 864, seed: f.seed || 0, name: "character sheet" };
    }
    const j = await tryApi("/api/images", d);
    if (j) { res.track(j); toast("Queued"); poll(); }
  }
  root.append(head("Edit a picture", "The picture model re-draws a picture you give it: change it in words, turn the subject to other angles, or make a reference sheet."),
    h("div", { class: "card" },
      field("The picture", refPicker(f, "picture", { empty: "pick or upload a picture" })),
      tabs([["words", "Change it in words"], ["angles", "Other angles"], ["sheet", "Reference sheet"]], f.mode, m => { f.mode = m; root.querySelectorAll(".tabs .tab").forEach((t, i) => { const on = ["words", "angles", "sheet"][i] === m; t.classList.toggle("on", on); t.setAttribute("aria-selected", on); }); drawBody(); }),
      body,
      h("div", { class: "row", style: { marginTop: "14px" } }, h("div", { class: "field fit" }, h("label", {}, "Seed (0 = new)"), number(f, "seed", { min: 0, blankZero: true })),
        h("div", { class: "field fit" }, h("button", { class: "primary", onclick: make }, "Make")))),
    h("h2", {}, "Made here"), res.box);
  drawBody();
} };

// ---------------------------------------------------------------- Video
function blankVideoForm() {
  return { start: "text", mode: "fields", name: "", place: "", action: "", sound: "", framing: "", camera: "", look: "cinematic", lens: "", light: "", style: "",
    people: [], lines: [], refs: [], first_frame: "", last_frame: "", size: "1152x640", frames: 243, turbo: true, seed: 0, notext: true, one_take: true,
    talking_head: false, prompt: "", long: false, beats: "", variants: false, looks: [], language: "English", loras: [],
    blockout: "", blockout_shapes: "", blockout_start: 0, blockout_strength: 0 };
}
function videoPayload(f) {
  const [width, height] = f.size.split("x").map(Number);
  const d = { name: f.name, mode: f.mode, place: f.place, action: f.action, sound: f.sound, framing: f.framing, camera: f.camera, look: f.look, lens: f.lens, light: f.light,
    style: f.style, people: f.people.filter(p => p.name.trim()), lines: f.lines.filter(l => l.text.trim()), refs: f.refs, width, height, frames: f.frames, turbo: f.turbo,
    seed: f.seed || 0, notext: f.notext, one_take: f.one_take, talking_head: f.talking_head, prompt: f.prompt, language: f.language, loras: f.loras.filter(l => l.file) };
  if (f.start === "first" || f.start === "first_last") d.first_frame = f.first_frame;
  if (f.start === "first_last") d.last_frame = f.last_frame;
  if (f.start === "blockout") Object.assign(d, { blockout: f.blockout, blockout_shapes: f.blockout_shapes, blockout_start: f.blockout_start || 0, blockout_strength: f.blockout_strength || 0 });
  if (f.long) d.beats = f.beats.split("\n").map(s => s.trim()).filter(Boolean);
  return d;
}
function personCard(p, onchange, onremove) {
  return h("div", { class: "person" },
    h("div", { class: "row" },
      h("div", { class: "field" }, h("label", {}, "Name"), text(p, "name", { placeholder: "Mara", oninput: onchange })),
      h("div", { class: "field fit" }, h("label", {}, "Their…"), select(p, "pronoun", [["her", "her"], ["his", "his"], ["their", "their"]], { onchange })),
      onremove ? h("div", { class: "field fit" }, h("button", { class: "ghost small", onclick: onremove }, "Remove")) : null),
    field("Looks like", text(p, "description", { rows: 2, placeholder: "a woman in her thirties with shoulder-length dark hair, wearing a grey sweater", oninput: onchange }),
      "Describe only what a picture does not show, or what should differ from it."),
    h("div", { class: "row" },
      h("div", { class: "field" }, h("label", {}, "Face"), refPicker(p, "face", { onchange, empty: "a tight face crop" })),
      h("div", { class: "field" }, h("label", {}, "Outfit sheet"), refPicker(p, "body", { onchange, empty: "whole body, several views" })),
      h("div", { class: "field" }, h("label", {}, "Voice sample"), refPicker(p, "voice", { kind: "audio", onchange, empty: "10–20 s of clean speech" }))));
}

ROOMS.video = { title: "Video", draw(root, arg) {
  if (arg.startsWith("clip/")) return drawClip(root, arg.slice(5));
  const pend = S.pending || {}; S.pending = null;
  const f = Object.assign(blankVideoForm(), ROOMS.video.keep || {});
  if (Object.keys(pend).length) {
    Object.assign(f, blankVideoForm());
    for (const k of ["start", "framing", "camera", "look", "action", "sound", "frames", "talking_head", "first_frame", "last_frame", "long", "variants"]) if (pend[k] !== undefined) f[k] = pend[k];
    if (pend.size) { const s = P().sizes.find(x => x.name === pend.size); if (s) f.size = s.width + "x" + s.height; }
    if (pend.refs) f.refs = pend.refs;
    if (pend.action && pend.action.includes("{who}")) f.people = [{ name: "", pronoun: "their", description: "", face: "", body: "", voice: "" }];
  }
  ROOMS.video.keep = f;
  const form = h("div", {}), side = h("div", {}), clips = h("div", { class: "tiles big" });
  const refreshPreview = debounce(preview, 500);
  const changed = () => refreshPreview();

  function drawForm() {
    const speakers = () => f.people.filter(p => p.name.trim()).map(p => [p.name, p.name]);
    form.replaceChildren(
      h("div", { class: "card" },
        h("h3", {}, "The clip starts from"),
        h("div", { class: "choice" }, [["text", "Words only", "The model invents everything."], ["first", "A first frame", "It opens on your picture."],
          ["first_last", "First and last frame", "It opens on one picture and ends on another."], ["refs", "References", "People, a place, things that must look the same."],
          ["blockout", "A blockout video", "A rough video (grey shapes from Blender, a phone clip) sets the camera, positions and motion."]]
          .map(([id, b, s]) => h("button", { class: f.start === id ? "on" : "", onclick: () => { f.start = id; drawForm(); changed(); } }, h("b", {}, b), h("span", {}, s)))),
        f.start === "first" || f.start === "first_last" ? h("div", { class: "row" },
          h("div", { class: "field" }, h("label", {}, "First frame"), refPicker(f, "first_frame", { onchange: changed, empty: "pick, upload, or make one in Picture" })),
          f.start === "first_last" ? h("div", { class: "field" }, h("label", {}, "Last frame"), refPicker(f, "last_frame", { onchange: changed })) : null) : null,
        f.start === "blockout" ? [
          h("div", { class: "row" },
            h("div", { class: "field" }, h("label", {}, "The blockout video"), refPicker(f, "blockout", { kind: "clip", onchange: changed, empty: "pick or upload a video" })),
            h("div", { class: "field fit" }, h("label", {}, "Starts at frame"), number(f, "blockout_start", { min: 0, blankZero: true, oninput: changed, placeholder: "0" })),
            h("div", { class: "field fit" }, h("label", {}, "Strength"), number(f, "blockout_strength", { min: 0.9, max: 1, step: 0.0005, blankZero: true, oninput: changed, placeholder: "0.997" }))),
          field("What the shapes are", text(f, "blockout_shapes", { oninput: changed, placeholder: "the grey figure is Mara; the red box is her car" }),
            "The clip keeps the blockout's camera, framing, positions and timing; the model paints real people and places over it. Leave Framing and Camera below empty. Strength: 0.997 looks real and follows the camera; 0.994 leaves flat textured blocks; 0.9995 often loses the camera. A long take reads on in the same blockout.")] : null,
        h("div", { class: "spread" }, h("h3", { style: { margin: "6px 0" } }, "People"), h("button", { class: "small", onclick: () => { f.people.push({ name: "", pronoun: "their", description: "", face: "", body: "", voice: "" }); drawForm(); } }, "+ Person")),
        f.people.length ? f.people.map((p, i) => personCard(p, changed, () => { f.people.splice(i, 1); drawForm(); changed(); }))
          : h("div", { class: "faint small", style: { marginBottom: "12px" } }, "Add a person to give them a face picture, an outfit sheet or a voice, and to write their lines."),
        h("div", { class: "spread" }, h("h3", { style: { margin: "6px 0" } }, "Further reference pictures"),
          h("button", { class: "small", onclick: async () => { const got = await pickAsset("image", { multiple: true }); if (got) { f.refs.push(...got.map(a => ({ file: a.ref, label: a.name }))); drawForm(); changed(); } } }, "+ Pictures")),
        f.refs.length ? h("div", { class: "tiles", style: { marginBottom: "12px" } }, f.refs.map((r, i) => h("div", { class: "tile" }, h("div", { class: "pic", style: { backgroundImage: `url("${refThumb(r.file)}")` } }),
          h("div", { class: "meta" }, text(r, "label", { placeholder: "what it is", oninput: changed })), h("div", { class: "acts" }, h("button", { class: "small ghost", onclick: () => { f.refs.splice(i, 1); drawForm(); changed(); } }, "Remove"))))) : null),

      h("div", { class: "card" },
        tabs([["fields", "In fields"], ["free", "My own prompt"]], f.mode, m => { f.mode = m; drawForm(); changed(); }),
        f.mode === "free" ? [
          field("The whole prompt", text(f, "prompt", { rows: 9, mono: true, oninput: changed, placeholder: "[Shot 1] A narrow street market at night…\n\noverall_soundscape:\nRain on awnings, distant traffic." }),
            "Sent as written, after the look's opening line. Name pictures as the list on the right numbers them (Picture 1…). {DIALOGUE} is where the lines go; without it they are added at the end.")]
        : [
          field("The place", text(f, "place", { rows: 2, oninput: changed, placeholder: "A small corner café in the morning: wooden tables, a steaming espresso machine behind the counter. Other guests sit at the back tables; they stay in the background." }),
            "Say what is there. A busy place needs people in it."),
          f.people.filter(p => p.name.trim()).length ? h("div", { class: "field" }, h("label", {}, "Where each one is"),
            f.people.filter(p => p.name.trim()).map(p => { f.staging = f.staging || {}; return h("div", { class: "row", style: { marginBottom: "6px" } }, h("div", { class: "fit muted", style: { width: "110px" } }, p.name),
              h("div", { class: "field", style: { marginBottom: 0 } }, text(f.staging, p.name, { oninput: changed, placeholder: "sits at the table on the left side of the picture" }))); }),
            h("div", { class: "hint" }, "Name the side of the picture: left and right are not guessed.")) : null,
          h("div", { class: "row" },
            h("div", { class: "field" }, h("label", {}, "Framing"), select(f, "framing", framingOptions(), { onchange: changed })),
            h("div", { class: "field" }, h("label", {}, "Camera"), select(f, "camera", cameraOptions(), { onchange: changed }))),
          field("What happens", text(f, "action", { rows: 3, oninput: changed, placeholder: "Mara stirs her coffee and looks up as Tom sits down across from her." }),
            "Few actions in one part. Every word someone says goes in a line below, never in here."),
          h("div", { class: "field" }, h("label", {}, "Spoken lines"), linesEditor(f.lines, speakers, changed),
            f.people.length ? null : h("div", { class: "hint" }, "Add people above to pick who speaks.")),
          field("Sound", text(f, "sound", { oninput: changed, placeholder: "Cups clinking, a quiet espresso machine, soft chatter far in the back." }))]),

      h("div", { class: "card" },
        h("div", { class: "row" },
          h("div", { class: "field" }, h("label", {}, "Look"), select(f, "look", lookOptions(), { onchange: changed })),
          h("div", { class: "field" }, h("label", {}, "Lens"), select(f, "lens", lensOptions(), { onchange: changed })),
          h("div", { class: "field" }, h("label", {}, "Light"), select(f, "light", lightOptions(), { onchange: changed }))),
        field("Or the look in your own words", text(f, "style", { oninput: changed, placeholder: "The video is in … style: …  (replaces the look, lens and light above)" })),
        h("div", { class: "row" },
          h("div", { class: "field" }, h("label", {}, "Size"), select(f, "size", sizeOptions(), { onchange: changed })),
          h("div", { class: "field" }, h("label", {}, "Length"), select(f, "frames", lengthOptions(false), { number: true, onchange: changed })),
          h("div", { class: "field fit" }, h("label", {}, "Seed (0 = new)"), number(f, "seed", { min: 0, blankZero: true })),
          h("div", { class: "field fit" }, h("label", {}, "Language"), text(f, "language", { oninput: changed }))),
        h("div", { class: "row" },
          h("div", { class: "fit" }, check(f, "turbo", "Turbo (8 steps)", { onchange: changed })),
          h("div", { class: "fit" }, check(f, "one_take", "One continuous take", { onchange: changed })),
          h("div", { class: "fit" }, check(f, "notext", "Keep lettering out", { onchange: changed })),
          h("div", { class: "fit" }, check(f, "talking_head", "Speaks to the camera", { onchange: changed }))),
        h("details", {}, h("summary", { class: "muted", style: { cursor: "pointer", marginBottom: "10px" } }, "LoRAs, a long take, several looks"),
          h("h3", {}, "LoRAs"), lorasEditor(f.loras, changed),
          h("div", { style: { marginTop: "14px" } }, check(f, "long", "A long take: more parts that continue this one", { onchange: () => drawForm() })),
          f.long ? field("What happens next, one line a part", text(f, "beats", { rows: 4, placeholder: "She stands up and walks to the window.\nShe opens the window and leans out." }),
            "Each line is a part of 8.5 s that continues the one before in latent space: the place, the light and the sound carry through.") : null,
          check(f, "variants", "Render it in several looks", { onchange: () => drawForm() }),
          f.variants ? h("div", { class: "choice" }, P().looks.styles.map(s => h("button", { class: "small" + (f.looks.includes(s.id) ? " on" : ""), onclick: e => { f.looks.includes(s.id) ? f.looks.splice(f.looks.indexOf(s.id), 1) : f.looks.push(s.id); e.currentTarget.classList.toggle("on"); } }, s.name))) : null)));
  }

  async function preview() {
    let c;
    try { c = await api("/api/compose", videoPayload(f)); } catch (e) { side.replaceChildren(h("div", { class: "note bad" }, e.message)); return; }
    side.replaceChildren(
      h("div", { class: "card" },
        h("div", { class: "spread" }, h("h3", { style: { margin: 0 } }, "What the model gets"),
          h("span", { class: "muted small" }, `${c.width}x${c.height} · ${c.frames} frames · ${(c.frames / 24).toFixed(1)} s` + (c.estimate ? " · about " + secs(c.estimate) : ""))),
        c.blockout ? h("div", { class: "note", style: { marginTop: "10px" } }, `Follows the blockout from frame ${c.blockout.start} to ${c.blockout.end - 1} (${(c.blockout.start / 24).toFixed(1)}–${(c.blockout.end / 24).toFixed(1)} s)` + (c.blockout.frames ? ` of its ${c.blockout.frames}` : "") + `, strength ${c.blockout.strength}.`) : null,
        h("div", { class: "prompt", style: { marginTop: "10px" } }, c.prompt),
        c.pictures.length ? h("div", { class: "small", style: { marginTop: "8px" } }, c.pictures.map(p => h("div", {}, h("b", {}, "Picture " + p.n), " — " + p.what))) : null,
        c.audios.length ? h("div", { class: "small" }, c.audios.map(a => h("div", {}, h("b", {}, "Audio " + a.n), " — " + a.speaker + "'s voice"))) : null,
        c.fit && c.fit.text ? h("div", { class: "note " + (c.fit.ok ? "warn" : "bad"), style: { marginTop: "10px" } }, c.fit.text) : null,
        h("div", { style: { marginTop: "12px" } }, h("button", { class: "primary", onclick: render }, f.variants && f.looks.length ? `Render ${f.looks.length} looks` : f.long ? "Render the long take" : "Render"))),
      h("div", { class: "card" }, h("h3", {}, "Prompt check"), findingsList(c.findings)));
  }
  async function render() {
    const d = videoPayload(f);
    if (f.mode === "fields" && !f.action.trim() && !f.place.trim()) return toast("Describe the place or what happens", true);
    if ((f.start === "first" || f.start === "first_last") && !f.first_frame) return toast("Pick the first frame", true);
    if (f.start === "blockout" && !f.blockout) return toast("Pick the blockout video", true);
    const r = f.variants && f.looks.length ? await tryApi("/api/clips/variants", { ...d, looks: f.looks }) : await tryApi("/api/clips", d);
    if (r) { toast("Queued"); poll(); loadClips(); }
  }
  async function loadClips() {
    const list = await tryApi("/api/films?quick=1");
    if (!list) return;
    clips.replaceChildren(list.length ? list.slice(0, 12).map(c => h("button", { class: "app card", style: { margin: 0 }, onclick: () => go("video", "clip/" + c.id) },
      h("b", {}, c.name), h("span", {}, `${c.shots} part(s) · ${secs(c.seconds)} · ${ago(c.updated)}`), c.review ? h("span", { class: "chip warn" }, "look at it") : null))
      : h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, "Clips you render appear here."));
  }
  onJobEnd(j => { if (j.kind === "shot") loadClips(); });
  root.append(head("Video", "MiniMax H3 makes picture and sound together. One part is up to 15 s; longer shots are parts that continue each other."),
    h("div", { class: "grid2" }, form, h("div", { style: { position: "sticky", top: 0 } }, side)),
    h("h2", { style: { marginTop: "10px" } }, "Your clips"), clips);
  drawForm(); preview(); loadClips();
} };

// One quick clip: its video, its takes and checks, extend, render again, upscale.
async function drawClip(root, fid) {
  const box = h("div", {});
  root.append(h("button", { class: "ghost small", onclick: () => go("video") }, "← Video"), box);
  const ext = { action: "", lines: [], frames: 243, sound: "" };
  async function load() {
    const f = await tryApi("/api/films/" + fid);
    if (!f) return;
    const busy = S.state.jobs.some(j => j.film === fid && (j.status === "queued" || j.status === "running"));
    const last = f.shots[f.shots.length - 1];
    const speakers = () => f.cast.map(c => [c.id, c.name]);
    box.replaceChildren(head(f.name, `${f.shots.length} part(s) · ${f.bible.width}x${f.bible.height}`),
      h("div", { class: "grid2" },
        h("div", {},
          f.full_upscaled ? h("div", { class: "card" }, h("h3", {}, "Upscaled"), h("video", { src: media(f.full_upscaled) + "?t=" + f.updated, controls: true, style: { width: "100%" } })) : null,
          f.full ? h("div", { class: "card" }, h("video", { src: media(f.full) + "?t=" + f.updated, controls: true, style: { width: "100%", background: "#000" } }),
            h("div", { class: "row", style: { marginTop: "10px", gap: "6px" } },
              h("button", { disabled: busy, onclick: async () => { if (await tryApi(`/api/films/${fid}/upscale`, {})) { toast("Upscale queued"); poll(); } } }, "Upscale ×1.5, 48 fps"),
              f.asset ? h("button", { onclick: () => addToTimeline([f.asset]) }, "+ Timeline") : null,
              f.asset ? h("button", { onclick: () => openAsset(f.asset) }, "More…") : null))
            : h("div", { class: "empty" }, busy ? "Rendering…" : "Not rendered yet."),
          h("div", { class: "card" }, h("h3", {}, "Carry it on"),
            field("What happens next", text(ext, "action", { rows: 2, placeholder: "She puts the cup down and looks out of the window." }),
              "A new part that continues the last frames and their sound. Describe only what is in view at the end of the clip."),
            h("div", { class: "field" }, h("label", {}, "Spoken lines"), linesEditor(ext.lines, speakers)),
            h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Adds"), select(ext, "frames", lengthOptions(true), { number: true })),
              h("div", { class: "field fit" }, h("button", { class: "primary", disabled: busy || !last || !last.part, onclick: async () => {
                if (await tryApi(`/api/clips/${fid}/extend`, ext)) { toast("Queued"); ext.action = ""; ext.lines = []; poll(); load(); } } }, "Extend"))))),
        h("div", {}, f.shots.map((s, i) => h("div", { class: "card" },
          h("div", { class: "spread" }, h("h3", { style: { margin: 0 } }, "Part " + (i + 1) + (i && !s.new_shot ? " (continues)" : "")), statusChip(s.status)),
          s.error ? h("div", { class: "note bad", style: { marginTop: "8px" } }, s.error) : null,
          s.takes.slice().reverse().map(t => h("div", { class: "take" + (t.n === s.circled ? " active" : ""), style: { marginTop: "10px" } },
            h("div", { class: "spread" }, h("b", {}, "Take " + t.n), h("span", { class: "muted small" }, "seed " + t.seed + " · " + secs(t.seconds_taken))),
            checkChips(t.checks), checkDetails(t.checks),
            t.sheet ? h("img", { src: media(t.sheet), alt: "Contact sheet of take " + t.n, loading: "lazy" }) : null,
            h("details", { style: { marginTop: "6px" } }, h("summary", { class: "muted small", style: { cursor: "pointer" } }, "Prompt"), h("div", { class: "prompt" }, t.prompt)))),
          h("div", { class: "row", style: { marginTop: "8px", gap: "6px" } },
            h("button", { class: "small", disabled: busy, onclick: async () => { if (await tryApi(`/api/films/${fid}/render/${s.id}`, { force: true })) { toast("Queued at a new seed"); poll(); load(); } } }, s.takes.length ? "Render again (new seed)" : "Render")))))));
  }
  onJobEnd(j => { if (j.film === fid) load(); });
  load();
}
