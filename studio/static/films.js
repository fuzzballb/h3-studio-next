"use strict";
// Films: the list, and one film in seven tabs, the steps of making it (films.STEPS).
// Also the Cast library and the Night shift.

const nid = () => "x" + Math.random().toString(36).slice(2, 9);

ROOMS.films = { title: "Films", draw(root, arg) {
  if (arg) return drawFilm(root, arg);
  const list = h("div", { class: "tiles big" }), adoptBox = h("div", {});
  const nf = { name: "" };
  root.append(head("Films", "A film is made in seven steps, each a tab of the film: Bible, Cast & places, Shots, Blockout, Storyboard, Roll camera, Deliver. Each card says the step a film is at."),
    h("div", { class: "card" }, h("div", { class: "row" },
      h("div", { class: "field fit" }, h("label", {}, "A new film from a story"), h("button", { class: "primary", onclick: () => go("writer") }, "✎ Write it with the Writer")),
      h("div", { class: "field" }, h("label", {}, "Or start one empty and fill in each step yourself"), text(nf, "name", { placeholder: "The name of the film" })),
      h("div", { class: "field fit" }, h("label", {}, "\u00a0"), h("button", { onclick: async () => { const f = await tryApi("/api/films", { name: nf.name || "Untitled" }); if (f) go("films", f.id + "/bible"); } }, "Start empty")))),
    list, adoptBox);
  api("/api/projects").then(ps => { if (!ps.length) return; const a = { project: ps[0].project, story: "" };
    adoptBox.replaceChildren(h("div", { class: "card", style: { marginTop: "16px" } }, h("h3", {}, "Bring in a project made outside the studio"),
      h("p", { class: "muted small" }, "Long-video projects made with the story kit or the ComfyUI workflows. Each part becomes a shot with its take; the project folder stays where it is. The nodes keep no prompts: give the story-kit file the project was made from and its prompts, lines, cast, places and props come along. Without it the shots are empty, but you can cut, upscale and add shots after the last part."),
      h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "The project"), select(a, "project", ps.map(p => [p.project, `${p.project} · ${p.parts} parts`]))),
        h("div", { class: "field" }, h("label", {}, "Its story file (optional)"), text(a, "story", { placeholder: "/path/to/the_story.py" })),
        h("div", { class: "field fit" }, h("button", { onclick: async e => { e.target.disabled = true; toast("Reading the parts…"); const f = await tryApi("/api/films/adopt", a); e.target.disabled = false; if (f) go("films", f.id + (f.story ? "/shots" : "/roll")); } }, "Open as a film"))),
      h("div", { class: "hint muted small" }, "A story file is a program; it is run to be read, like the story kit does."))); }).catch(() => {});
  api("/api/films").then(fs => list.replaceChildren(fs.length ? fs.map(f => h("div", { class: "card", style: { margin: 0 } },
    h("div", { class: "spread" }, h("h2", { style: { margin: 0 } }, f.name), f.clip ? h("span", { class: "chip" }, "clip from Video") : null, f.running ? h("span", { class: "chip accent" }, "rendering") : f.review ? h("span", { class: "chip warn" }, f.review + " at the gate") : null),
    h("p", { class: "muted small", style: { margin: "6px 0 10px" } }, f.logline || (f.clip ? "Made in Video in parts; its own page shows the whole clip." : "No logline yet.")),
    h("div", { class: "muted small" }, `${f.shots} shots · ${f.approved} approved · ${secs(f.seconds)} · ${ago(f.updated)}`),
    h("div", { class: "small", style: { marginTop: "6px" } }, f.next ? [h("b", {}, `Next: ${f.next.n} · ${f.next.label}`), f.next.todo ? h("span", { class: "muted" }, " — " + f.next.todo) : null] : h("span", { class: "good" }, "✓ Finished")),
    h("div", { class: "row", style: { marginTop: "10px", gap: "6px" } }, f.clip ? h("button", { class: "primary small", onclick: () => go("video", "clip/" + f.id) }, "Open the clip") : null,
      h("button", { class: f.clip ? "small" : "primary small", onclick: () => go("films", f.id + (f.next ? "/" + f.next.id : "")) }, f.clip ? "Open as a film" : f.next ? "Go on" : "Open"),
      h("button", { class: "small danger", onclick: async () => { if (!confirm(`Move “${f.name}” and its renders to the trash?`)) return; if (await tryApi("/api/films/" + f.id, undefined, "DELETE")) { toast("Moved to the trash"); route(); } } }, "Delete"))))
    : h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, "No films yet."))).catch(e => toast(e.message, true));
} };

async function drawFilm(root, arg) {
  const [fid, tabArg, shotArg] = arg.split("/");
  let film = await tryApi("/api/films/" + fid);
  if (!film) { root.append(h("div", { class: "note bad" }, "This film was not found."), h("button", { onclick: () => go("films") }, "← Films")); return; }
  // open where the work is: Roll camera once anything is rendered, else the first step that is not done
  const firstOpen = (film.steps || []).find(s => !s.done && !s.optional);
  const rendered = film.shots.some(s => (s.takes || []).length || s.status === "review");
  const ui = { tab: tabArg || (rendered ? "roll" : firstOpen ? firstOpen.id : film.shots.length ? "roll" : "bible"), shot: shotArg || (film.shots[0] || {}).id || "", dirty: false, saving: false, pre: {} };
  const body = h("div", {}), tabBar = h("div", {}), saveNote = h("span", { class: "muted small" });
  let machine = { loras: [], roles: [] };
  // the list of LoRAs comes after the first draw: a dropdown always offers the file it holds, and is filled when the list is there
  getMachine().then(m => { machine = m; if (["cast", "bible", "shots"].includes(ui.tab) && !["INPUT", "TEXTAREA", "SELECT"].includes((document.activeElement || {}).tagName)) draw(); }).catch(() => {});

  // -------- saving: what the user edits is merged into the film; the runner's own fields stay the server's
  const save = debounce(async () => {
    if (ui.saving) { ui.dirty = true; return; }
    ui.saving = true; ui.dirty = false; saveNote.textContent = "saving…";
    try {
      const r = await api("/api/films/" + fid, { name: film.name, bible: film.bible, cast: film.cast, locations: film.locations, props: film.props, gate: film.gate, notes: film.notes, shots: film.shots,
        blockouts: (film.blockouts || []).map(b => ({ id: b.id, scene_name: b.scene_name, scene: b.scene, cuts: b.cuts || {} })) }, "PUT");
      mergeServer(r.film);
      saveNote.textContent = "saved";
      if (r.report.stale.length || r.report.moved.length) { toast(`The order changed: ${r.report.moved.length} part(s) renumbered, ${r.report.stale.length} continuation(s) need rendering again.`); draw(); }
    } catch (e) { saveNote.textContent = "not saved: " + e.message; }
    ui.saving = false;
    if (ui.dirty) save();
  }, 600);
  const edited = () => { saveNote.textContent = "…"; save(); };
  function mergeServer(sv) {       // keep what is being typed, take the server's ids and runner fields
    for (const g of ["cast", "locations", "props"]) film[g].forEach((x, i) => { if (!x.id && sv[g][i]) x.id = sv[g][i].id; });
    film.shots.forEach((s, i) => { const t = sv.shots[i]; if (!t) return; if (!s.id) s.id = t.id; for (const k of ["status", "takes", "circled", "part", "storyboard", "error"]) s[k] = t[k]; });
    for (const k of ["long_project", "run", "full", "full_upscaled", "updated", "asset", "upscaled_asset", "steps"]) film[k] = sv[k];
    (film.blockouts || []).forEach((b, i) => { const t = (sv.blockouts || []).find(x => x.id === b.id) || sv.blockouts[i]; if (!t) return;
      b.id = t.id; for (const k of ["video", "made", "stats", "state", "stretches"]) b[k] = t[k]; });
    drawSteps();
  }
  async function reload() { const sv = await tryApi("/api/films/" + fid); if (sv) { if (ui.saving || ui.dirty) mergeServer(sv); else film = sv; draw(); } }
  onJobEnd(j => { if (j.film === fid) reload(); });
  const shotById = id => film.shots.find(s => s.id === id);
  const sceneName = x => (x || "").trim();
  const sceneBlockout = name => (film.blockouts = film.blockouts || []).find(b => sceneName(b.scene_name) === sceneName(name));
  const castOptions = () => film.cast.map(c => [c.id, c.name || "(no name)"]);
  const busyJobs = () => S.state.jobs.filter(j => j.film === fid && (j.status === "queued" || j.status === "running"));

  // ------------------------------------------------------------------ Bible
  function tabBible() {
    const b = film.bible;
    b.size = b.width + "x" + b.height;
    return h("div", { class: "grid2" },
      h("div", {},
        h("div", { class: "card" },
          field("Name", text(film, "name", { oninput: edited })),
          field("Logline", text(b, "logline", { rows: 2, oninput: edited, placeholder: "Two friends on a night out are pulled into a chase across a neon city." })),
          field("World and tone (a note for you)", text(b, "world", { rows: 2, oninput: edited }))),
        h("div", { class: "card" }, h("h3", {}, "The look of every shot"),
          h("div", { class: "row" },
            h("div", { class: "field" }, h("label", {}, "Look"), select(b, "look", lookOptions().concat(b.look === "none" ? [["none", "None: every shot opens in its own words"]] : []), { onchange: edited })),
            h("div", { class: "field" }, h("label", {}, "Lens"), select(b, "lens", lensOptions(), { onchange: edited })),
            h("div", { class: "field" }, h("label", {}, "Light"), select(b, "light", lightOptions(), { onchange: edited }))),
          field("Or in your own words", text(b, "style", { rows: 2, oninput: edited, placeholder: "The video is in … style: …" }), "This line opens every prompt of the film. It replaces the look, lens and light."),
          h("div", { class: "row" }, h("div", { class: "fit" }, check(b, "notext", "Keep lettering out of every shot", { onchange: edited })),
            h("div", { class: "fit" }, check(b, "one_take", "One continuous take a shot", { onchange: edited }))))),
      h("div", {},
        h("div", { class: "card" }, h("h3", {}, "How it renders"),
          h("div", { class: "row" },
            h("div", { class: "field" }, h("label", {}, "Size"), select(b, "size", sizeOptions().some(o => o[0] === b.size) ? sizeOptions() : [...sizeOptions(), [b.size, b.size]], { onchange: v => { [b.width, b.height] = v.split("x").map(Number); edited(); } })),
            h("div", { class: "field" }, h("label", {}, "Length of a shot"), select(b, "frames", lengthOptions(true), { number: true, onchange: edited }))),
          h("div", { class: "row" }, h("div", { class: "field fit" }, h("label", {}, "Spoken language"), text(b, "language", { oninput: edited })),
            h("div", { class: "fit" }, check(b, "turbo", "Turbo (8 steps)", { onchange: edited }))),
          field("Base model (only when a person LoRA was trained on another one)", select(b, "unet", [["", "The studio's video model"], ...((machine.roles.find(r => r.role === "video_unet") || { options: [] }).options.map(o => [o, o]))], { onchange: edited })),
          h("h3", { style: { marginTop: "6px" } }, "LoRAs on every shot"), lorasEditor(b.loras = b.loras || [], edited)),
        h("div", { class: "card" }, h("h3", {}, "The gate"),
          h("div", { class: "choice" }, [["hold", "Hold every take", "Each part waits until you approve it. Slower, and it catches what no check can see."],
            ["auto", "Approve what passes", "A take that passes the automatic checks is approved; one that fails is rendered again, then waits for you."]]
            .map(([id, bb, s]) => h("button", { class: film.gate.mode === id ? "on" : "", onclick: () => { film.gate.mode = id; edited(); draw(); } }, h("b", {}, bb), h("span", {}, s)))),
          h("div", { class: "row" }, h("div", { class: "field fit" }, h("label", {}, "Automatic retakes"), number(film.gate, "retries", { min: 0, max: 5, oninput: edited }))),
          h("div", { class: "note" }, "The automatic checks see cuts, a jump at a join, wrong or unwanted speech and shouted lines. A wrong prop, an empty bar or the wrong car door they do not see."))));
  }

  // ------------------------------------------------------------------ Cast & places
  function tabCast() {
    const person = (c, i) => h("div", { class: "person" },
      h("div", { class: "row" },
        h("div", { class: "field" }, h("label", {}, "Name"), text(c, "name", { oninput: edited })),
        h("div", { class: "field fit" }, h("label", {}, "Their…"), select(c, "pronoun", [["her", "her"], ["his", "his"], ["their", "their"]], { onchange: edited })),
        h("div", { class: "field fit" }, h("button", { class: "ghost small", onclick: () => { film.cast.splice(i, 1); edited(); draw(); } }, "Remove"))),
      field("Looks like", text(c, "description", { rows: 2, oninput: edited, placeholder: "a woman in her early thirties with a soft oval face and shoulder-length wavy dark hair; she wears a yellow sweater" }),
        "With a face picture, describe only what should differ from it. Clothes that are not in a picture are described here."),
      h("div", { class: "row" },
        h("div", { class: "field" }, h("label", {}, "Face"), refPicker(c, "face", { onchange: edited, empty: "a tight face crop", makeLabel: "Invent one", make: () => go("picture", "", { template: "portrait", width: 1024, height: 1024, takes: 3, prompt: [c.name, c.description].filter(Boolean).join(": "),
          back: ["films", film.id + "/cast"], backLabel: "the cast of " + film.name }) })),
        h("div", { class: "field" }, h("label", {}, "Outfit sheet"), refPicker(c, "body", { onchange: edited, empty: "whole body, several views", makeLabel: "From the face", make: () => c.face ? go("edit", "", { picture: c.face, angles: "sheet", back: ["films", film.id + "/cast"], backLabel: "the cast of " + film.name }) : toast("Pick the face first", true) })),
        h("div", { class: "field" }, h("label", {}, "Voice sample"), refPicker(c, "voice", { kind: "audio", onchange: edited, empty: "10–20 s of clean speech" }))),
      h("div", { class: "row" },
        h("div", { class: "field" }, h("label", {}, "Person LoRA"), (() => { c.lora = c.lora || {}; return select(c.lora, "file", [["", "(none)"], ...[...new Set([c.lora.file, ...machine.loras].filter(Boolean))].map(l => [l, l])], { onchange: edited }); })()),
        h("div", { class: "field fit" }, h("label", {}, "Strength"), number(c.lora, "strength", { min: 0, max: 2, step: 0.05, oninput: edited, placeholder: "1.0" }))));
    const place = (l, i) => h("div", { class: "person" },
      h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Name"), text(l, "name", { oninput: edited })),
        h("div", { class: "field fit" }, h("button", { class: "ghost small", onclick: () => { film.locations.splice(i, 1); edited(); draw(); } }, "Remove"))),
      field("The place", text(l, "description", { rows: 3, oninput: edited, placeholder: "A narrow street-food alley at night: red paper lanterns above, a small open noodle bar with a steel counter and round stools, wet pavement. Other customers sit on some of the stools; they stay in the background." })),
      field("Plate (an empty picture of the place)", refPicker(l, "plate", { onchange: edited, empty: "the same plate in every new shot keeps the place the same", makeLabel: "Make one", make: () => go("picture", "", { template: "location", width: 1440, height: 800, takes: 3, prompt: [l.name, l.description].filter(Boolean).join(": "),
          back: ["films", film.id + "/cast"], backLabel: "the places of " + film.name }) })));
    const prop = (p, i) => h("div", { class: "person" },
      h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Name"), text(p, "name", { oninput: edited, placeholder: "the dark futuristic car" })),
        h("div", { class: "field" }, h("label", {}, "Token to write in a shot"), text(p, "token", { oninput: edited, placeholder: "<CAR>", mono: true })),
        h("div", { class: "field fit" }, h("button", { class: "ghost small", onclick: () => { film.props.splice(i, 1); edited(); draw(); } }, "Remove"))),
      field("Sheet", refPicker(p, "sheet", { onchange: edited, empty: "the thing on white, two views", makeLabel: "Make one", make: () => go("picture", "", { template: "prop", width: 1024, height: 1024, takes: 2, prompt: "Product photo of " + (p.name || "the object") + ", alone on a plain white background, soft studio light, the whole object in frame.", back: ["films", film.id + "/cast"], backLabel: "the cast of " + film.name }) }),
        "Make one: a photo of the thing, then attach it and choose Prop sheet. Write “the car from " + (p.token || "<CAR>") + "” in a shot: the token becomes its Picture number, and the sheet is attached only to shots that name it."));
    return h("div", {},
      h("div", { class: "spread" }, h("h2", {}, "Cast"), h("div", { class: "row", style: { gap: "6px" } },
        h("button", { class: "small", onclick: async () => { const lib = await tryApi("/api/cast"); if (!lib) return; if (!lib.length) return toast("The cast library is empty. Save a character to it first."); pickFromCast(lib); } }, "From the cast library"),
        h("button", { class: "small primary", onclick: () => { film.cast.push({ id: nid(), name: "", pronoun: "their", description: "", face: "", body: "", voice: "", lora: {} }); edited(); draw(); } }, "+ Character"))),
      film.cast.length ? film.cast.map((c, i) => h("div", {}, person(c, i), h("button", { class: "ghost small", style: { margin: "-6px 0 12px" }, onclick: async () => { const lib = (await tryApi("/api/cast")) || []; lib.push({ ...clone(c), id: "" }); if (await tryApi("/api/cast", { cast: lib }, "PUT")) toast("Saved to the cast library"); } }, "Save to the cast library")))
        : h("div", { class: "empty" }, "No characters yet. A face picture is what keeps a person the same from shot to shot."),
      h("div", { class: "spread", style: { marginTop: "22px" } }, h("h2", {}, "Places"), h("button", { class: "small primary", onclick: () => { film.locations.push({ id: nid(), name: "", description: "", plate: "" }); edited(); draw(); } }, "+ Place")),
      film.locations.length ? film.locations.map(place) : h("div", { class: "empty" }, "No places yet. A place can also be written in each shot."),
      h("div", { class: "spread", style: { marginTop: "22px" } }, h("h2", {}, "Props"), h("button", { class: "small primary", onclick: () => { film.props.push({ id: nid(), name: "", token: "", sheet: "" }); edited(); draw(); } }, "+ Prop")),
      film.props.length ? film.props.map(prop) : h("div", { class: "empty" }, "No props. A prop that is only described in words changes from shot to shot; a sheet keeps it the same."));
  }
  function pickFromCast(lib) {
    modal(h("div", {}, h("div", { class: "spread" }, h("h2", {}, "Cast library"), h("button", { class: "ghost", onclick: closeModal }, "Close")),
      lib.map(c => h("div", { class: "spread", style: { padding: "8px 0", borderBottom: "1px solid var(--line)" } },
        h("div", { class: "refpick" }, h("div", { class: "th", style: c.face ? { backgroundImage: `url("${refThumb(c.face)}")` } : {} }), h("div", {}, h("b", {}, c.name), h("div", { class: "muted small" }, (c.description || "").slice(0, 90)))),
        h("button", { class: "small primary", onclick: () => { film.cast.push({ ...clone(c), id: nid() }); edited(); closeModal(); draw(); } }, "Add")))), true);
  }

  // ------------------------------------------------------------------ Shots
  function tabShots() {
    const cur = shotById(ui.shot) || film.shots[0];
    if (cur) ui.shot = cur.id;
    const idx = cur ? film.shots.indexOf(cur) : -1;
    const move = d => { const j = idx + d; if (j < 0 || j >= film.shots.length) return; film.shots.splice(j, 0, film.shots.splice(idx, 1)[0]); edited(); draw(); };
    const plan = { plan: "arrive-talk", a: (film.cast[0] || {}).id || "", b: (film.cast[1] || {}).id || "", place: (film.locations[0] || {}).id || "", logline: film.bible.logline || "", scenes: 2, shots: 3 };
    const adder = h("div", { class: "card" }, h("h3", {}, "Add shots"),
      h("div", { class: "row" },
        h("div", { class: "field" }, h("label", {}, "A coverage plan"), select(plan, "plan", P().coverage.plans.map(p => [p.id, p.name + " — " + p.line]))),
        h("div", { class: "field" }, h("label", {}, "First person"), select(plan, "a", [["", "(none)"], ...castOptions()])),
        h("div", { class: "field" }, h("label", {}, "Second person"), select(plan, "b", [["", "(none)"], ...castOptions()])),
        h("div", { class: "field" }, h("label", {}, "Place"), select(plan, "place", [["", "(none)"], ...film.locations.map(l => [l.id, l.name])])),
        h("div", { class: "field fit" }, h("button", { onclick: async () => { await flush(); const r = await tryApi(`/api/films/${fid}/outline`, { plan: plan.plan, a: plan.a, b: plan.b, place: plan.place }); if (r) { film = r.film; toast(r.added.shots + " shots added"); draw(); } } }, "Add these shots"))),
      h("details", {}, h("summary", { class: "muted small", style: { cursor: "pointer" } }, "Or from a logline, with the writing help"),
        h("div", { class: "row", style: { marginTop: "10px" } },
          h("div", { class: "field" }, h("label", {}, "Logline"), text(plan, "logline", {})),
          h("div", { class: "field fit" }, h("label", {}, "Scenes"), number(plan, "scenes", { min: 1, max: 8 })),
          h("div", { class: "field fit" }, h("label", {}, "Shots a scene"), number(plan, "shots", { min: 1, max: 8 })),
          h("div", { class: "field fit" }, h("button", { onclick: async e => { e.target.disabled = true; await flush(); toast("Asking the writing help…"); const r = await tryApi(`/api/films/${fid}/outline`, { logline: plan.logline, scenes: plan.scenes, shots: plan.shots }); e.target.disabled = false;
            if (r) { film = r.film; toast(`${r.added.shots} shots, ${r.added.cast} characters, ${r.added.locations} places added`); draw(); } } }, "Write the shots"))),
        h("div", { class: "hint" }, "Needs a writing help set in Machine → Settings (a language model on this computer, or a command). Only text is sent to it.")));
    if (!cur) return h("div", {}, adder, h("div", { class: "empty" }, "No shots yet. Add them from a coverage plan, or one by one. ",
      h("button", { class: "small primary", onclick: addShot }, "+ Shot")));
    const cont = idx > 0 && !cur.new_shot;
    const speakers = () => cur.cast.map(id => [id, (film.cast.find(c => c.id === id) || {}).name || id]);
    const placeField = () => h("div", { class: "field" }, h("label", {}, "Place"), select(cur, "location", [["", cur.mode === "free" ? "(no picture of the place)" : "(written below)"], ...film.locations.map(l => [l.id, l.name])], { onchange: () => { edited(); draw(); } }));
    const whoField = () => h("div", { class: "field" }, h("label", {}, "Who is in it"), h("div", { class: "choice", style: { marginBottom: "6px" } }, film.cast.length ? film.cast.map(c => h("button", { class: "small" + (cur.cast.includes(c.id) ? " on" : ""),
      onclick: () => { cur.cast.includes(c.id) ? cur.cast.splice(cur.cast.indexOf(c.id), 1) : cur.cast.push(c.id); edited(); draw(); } }, c.name || "(no name)")) : h("span", { class: "faint small" }, "Add characters in Cast & places.")));
    // the pictures that go with the prompt, numbered as the model counts them (the same order as compose.pictures)
    const picsBox = h("div", { class: "note" });
    const picsNote = () => {
      const pics = [];
      if (cur.first_frame && !cont) pics.push("the first frame");
      if (cur.last_frame) pics.push("the last frame");
      for (const id of cur.cast) { const c = film.cast.find(x => x.id === id); if (!c) continue; if (c.face) pics.push(c.name + "’s face"); if (c.body) pics.push(c.name + "’s outfit sheet"); }
      const l = film.locations.find(x => x.id === cur.location);
      if (l && l.plate && !cont) pics.push("the place: " + l.name);
      for (const pr of film.props) if (pr.sheet && pr.token && (cur.prompt || "").includes(pr.token)) pics.push(`${pr.name || pr.token} (${pr.token} in the prompt)`);
      for (const r of cur.refs || []) if (r.file) pics.push(r.label || "a further picture");
      picsBox.textContent = pics.length ? "Sent with the prompt: " + pics.map((x, i) => `Picture ${i + 1} = ${x}`).join(" · ") + "." : "No pictures go with this prompt. Choose who is in it and the place, or name a prop by its token.";
    };
    picsNote();
    // the blockout of this shot's scene (made in the Blockout step), or a video of the shot's own
    const sb = sceneBlockout(cur.scene);
    const myStretch = sb && (sb.stretches || []).find(c => c.id === cur.id);
    function blockoutBox() {
      const own = !!(cur.blockout || "").trim();
      const strength = h("div", { class: "field fit", title: "How little of the blockout's own look is kept. 0.997 looks real and follows the camera; 0.994 leaves flat textured blocks; 0.9995 often loses the camera." },
        h("label", {}, "Strength"), number(cur, "blockout_strength", { min: 0.9, max: 1, step: 0.0005, blankZero: true, oninput: edited, placeholder: "0.997" }));
      const shapes = field("What the shapes are", text(cur, "blockout_shapes", { oninput: edited, placeholder: sb && !own ? "empty: said from the scene's things (\u201cthe blue figure is Mara\u201d)" : "the brown figure is Henk; the red box is the sled; the coloured blocks are wrapped presents" }));
      return h("div", { class: "card", style: { background: "var(--panel2)", margin: "6px 0 12px", padding: "12px" } },
        h("div", { class: "spread" }, h("b", {}, "Blockout"),
          h("button", { class: "small", onclick: async () => { await flush(); ui.bscene = (cur.scene || "").trim(); pick("blockout"); } }, sb ? "Open the scene's blockout →" : "Make one in step 4 →")),
        own ? h("div", { class: "small", style: { marginTop: "4px" } }, "This shot follows a video of its own (below), not the scene's blockout.")
          : sb && sb.video ? h("div", { class: "small", style: { marginTop: "4px" } }, `Follows its stretch of the blockout of scene ${sb.scene_name || "(no name)"}` + (myStretch ? `: frames ${myStretch.start}–${myStretch.end - 1} (${(myStretch.start / 24).toFixed(1)}–${(myStretch.end / 24).toFixed(1)} s).` : ".") + (sb.state && !sb.state.current ? " It changed since it was made: make it again." : ""))
          : sb ? h("div", { class: "small", style: { marginTop: "4px" } }, `Scene ${sb.scene_name || "(no name)"} has a blockout that is not made yet; this shot will follow its stretch of it.`)
          : h("div", { class: "muted small", style: { marginTop: "4px" } }, "None: the shot is made from its words. A blockout of the scene pins the camera, the positions and the timing."),
        (sb && sb.video) || own ? h("div", { class: "row", style: { marginTop: "8px" } }, h("div", { class: "field" }, shapes), strength) : null,
        h("details", { open: own }, h("summary", { class: "muted small", style: { cursor: "pointer", marginTop: "6px" } }, "Follow a video of its own instead (a phone clip, another render)"),
          h("div", { class: "row", style: { marginTop: "8px" } },
            h("div", { class: "field" }, h("label", {}, "The video"), refPicker(cur, "blockout", { kind: "clip", onchange: () => { edited(); draw(); }, empty: sb ? "none: the scene's blockout" : "none" })),
            own ? h("div", { class: "field fit" }, h("label", {}, "Starts at frame"), number(cur, "blockout_start", { min: 0, blankZero: true, oninput: edited, placeholder: cont ? "auto" : "0" })) : null)));
    }
    const editor = h("div", { class: "card" },
      h("div", { class: "row" },
        h("div", { class: "field" }, h("label", {}, "Title"), text(cur, "title", { oninput: v => { edited(); const r = body.querySelector(".shotrow.on .ti"); if (r) r.textContent = v || "Shot " + (idx + 1); } })),
        h("div", { class: "field" }, h("label", {}, "Scene"), text(cur, "scene", { oninput: edited })),
        h("div", { class: "field" }, h("label", {}, "Length"), select(cur, "frames", [[0, "The film's"], ...lengthOptions(cont)], { number: true, onchange: edited }))),
      idx > 0 ? h("div", { class: "choice" }, [[true, "A new shot", "A cut: a new place, size or angle."], [false, "Continues the shot before", "The same place and camera; its last frames and sound carry through."]]
        .map(([v, bb, s]) => h("button", { class: cur.new_shot === v ? "on" : "", onclick: () => { cur.new_shot = v; edited(); draw(); } }, h("b", {}, bb), h("span", {}, s)))) : null,
      cont ? h("div", { class: "note" }, "A continuation must only name what is in view at the END of the shot before. Something off-screen makes the model cut to it, or swap the background at the join.") : null,
      tabs([["fields", "In fields"], ["free", "My own prompt"]], cur.mode, m => { cur.mode = m; edited(); draw(); }),
      cur.mode === "free" ? [
        field("The whole prompt", text(cur, "prompt", { rows: 9, mono: true, oninput: () => { edited(); picsNote(); } }), "Sent as written, after the film's opening line. {DIALOGUE} is where the lines go. Prop tokens become Picture numbers."),
        h("div", { class: "row" }, cont ? null : placeField(), whoField()),
        picsBox,
        h("div", { class: "field" }, h("label", {}, "Spoken lines"), linesEditor(cur.lines, speakers, edited),
          h("div", { class: "hint" }, "The exact words. They go into the prompt at {DIALOGUE}, or at its end. A prompt that already speaks its lines itself (<d>…</d>) is sent as it is: these are then what the speech check listens for, so keep the two the same."))]
      : [
        cont ? null : h("div", { class: "row" },
          placeField(),
          h("div", { class: "field" }, h("label", {}, "Framing"), select(cur, "framing", framingOptions(), { onchange: edited })),
          h("div", { class: "field" }, h("label", {}, "Camera"), select(cur, "camera", cameraOptions(), { onchange: edited }))),
        cont ? null : field("The place, in this shot's own words (optional)", text(cur, "place", { rows: 2, oninput: edited })),
        whoField(),
        cur.cast.length ? h("div", { class: "field" }, h("label", {}, "Where each one is"), cur.cast.map(id => { cur.staging = cur.staging || {}; const c = film.cast.find(x => x.id === id) || {};
          return h("div", { class: "row", style: { marginBottom: "6px" } }, h("div", { class: "fit muted", style: { width: "110px" } }, c.name),
            h("div", { class: "field", style: { marginBottom: 0 } }, text(cur.staging, id, { oninput: edited, placeholder: "sits in the booth on the left side of the picture" }))); })) : null,
        field("What happens", text(cur, "action", { rows: 3, oninput: edited }), film.props.length ? "Props: " + film.props.map(p => p.token).filter(Boolean).join(", ") : null),
        h("div", { class: "field" }, h("label", {}, "Spoken lines"), linesEditor(cur.lines, speakers, edited)),
        field("Sound", text(cur, "sound", { oninput: edited, placeholder: "what is heard besides the words" })),
        cont ? field("Camera, in words (optional)", text(cur, "camera_text", { oninput: edited })) : null],
      blockoutBox(),
      h("details", {}, h("summary", { class: "muted small", style: { cursor: "pointer", margin: "6px 0 10px" } }, "First and last frame, LoRAs, seed, notes"),
        h("div", { class: "row" },
          cont ? null : h("div", { class: "field" }, h("label", {}, "Opens on (a first frame)"), refPicker(cur, "first_frame", { onchange: edited, empty: "e.g. a storyboard still" })),
          h("div", { class: "field" }, h("label", {}, "Ends on (a last frame)"), refPicker(cur, "last_frame", { onchange: edited })),
          h("div", { class: "field fit" }, h("label", {}, "Seed (0 = new)"), number(cur, "seed", { min: 0, blankZero: true, oninput: edited }))),
        h("div", { class: "row" }, h("div", { class: "fit" }, check(cur, "talking_head", "Speaks to the camera", { onchange: edited }))),
        h("h3", {}, "LoRAs on this shot"), lorasEditor(cur.loras = cur.loras || [], edited),
        field("Notes (not sent to the model)", text(cur, "notes", { rows: 2, oninput: edited }))),
      h("div", { class: "row", style: { marginTop: "8px", gap: "6px" } },
        h("button", { class: "primary", onclick: async () => { await flush(); go("films", fid + "/roll/" + cur.id); } }, "To Roll camera →"),
        h("button", { class: "small", onclick: () => move(-1), disabled: idx === 0 }, "↑ Earlier"), h("button", { class: "small", onclick: () => move(1), disabled: idx === film.shots.length - 1 }, "↓ Later"),
        h("button", { class: "small", onclick: () => { const c = clone(cur); c.id = nid(); c.takes = []; c.status = "todo"; c.part = 0; c.circled = 0; c.storyboard = []; c.title = (c.title || "Shot") + " (copy)"; film.shots.splice(idx + 1, 0, c); edited(); draw(); } }, "Duplicate"),
        h("button", { class: "small danger", onclick: () => { if (cur.takes.length && !confirm("This shot has takes. Remove it? Its takes go to the trash, and continuations after it must be rendered again.")) return; film.shots.splice(idx, 1); ui.shot = (film.shots[Math.max(0, idx - 1)] || {}).id || ""; edited(); draw(); } }, "Remove")));
    return h("div", {}, h("div", { class: "split" },
      h("div", {}, shotList(), h("button", { class: "small primary", style: { marginTop: "8px" }, onclick: addShot }, "+ Shot")), editor), adder);
  }
  function addShot() {
    const last = film.shots[film.shots.length - 1];
    const s = { id: "", title: "", scene: last ? last.scene : "", new_shot: true, mode: "fields", place: "", location: last ? last.location : "", cast: last ? [...last.cast] : [], staging: {}, framing: "", camera: "",
      camera_text: "", action: "", lines: [], sound: last ? last.sound : "", props: [], refs: [], first_frame: "", last_frame: "", prompt: "", frames: 0, seed: 0, loras: [], one_take: null, talking_head: false, notes: "",
      blockout: "", blockout_start: 0, blockout_strength: 0, blockout_shapes: "",
      status: "todo", takes: [], circled: 0, part: 0, storyboard: [] };
    s.id = nid();
    film.shots.push(s); ui.shot = s.id; edited(); draw();
  }
  function shotList(onpick) {
    return h("div", { class: "shotlist" }, film.shots.map((s, i) => h("button", { class: "shotrow" + (s.id === ui.shot ? " on" : ""), onclick: () => { ui.shot = s.id; (onpick || draw)(); } },
      h("span", { class: "n" }, i + 1), h("span", { class: "ti" }, s.title || "Shot " + (i + 1)), i > 0 && !s.new_shot ? h("span", { class: "cont", title: "continues the shot before" }, "↳") : null, statusChip(s.status))));
  }
  const flush = () => new Promise(res => { const wait = () => (ui.saving || saveNote.textContent === "…" || ui.dirty) ? setTimeout(wait, 120) : res(); wait(); });

  // ------------------------------------------------------------------ Storyboard
  function tabStoryboard() {
    const inFilm = s => (s.takes || []).find(t => t.n === s.circled && t.preview);       // the take a shot has in the film
    return h("div", {},
      h("div", { class: "spread", style: { marginBottom: "12px" } },
        h("p", { class: "sub", style: { margin: 0 } }, "A still for every shot, drawn by the picture model from the shot's words and the film's own pictures: seconds each, and looked at before any clip is rendered. A still you like can be the frame its shot opens on. A shot that is rendered shows a frame of its take: that is the film itself; a drawn still only resembles it."),
        h("div", { class: "row", style: { gap: "6px" } },
          h("button", { onclick: async () => { await flush(); const ids = film.shots.filter(s => !(s.storyboard || []).length && !inFilm(s)).map(s => s.id); if (!ids.length) return toast("Every shot has a still or a take"); if (await tryApi(`/api/films/${fid}/storyboard`, { shots: ids })) { toast(ids.length + " stills queued"); poll(); } } }, "Stills for shots without a picture"),
          h("button", { class: "primary", onclick: async () => { await flush(); if (await tryApi(`/api/films/${fid}/storyboard`, {})) { toast("Queued"); poll(); } } }, "A still for every shot"))),
      film.shots.length ? h("div", { class: "tiles big" }, film.shots.map((s, i) => h("div", { class: "card", style: { margin: 0 } },
        h("div", { class: "spread" }, h("b", {}, (i + 1) + ". " + (s.title || "Shot")), i > 0 && !s.new_shot ? h("span", { class: "chip" }, "continues") : null),
        h("div", { class: "muted small", style: { margin: "4px 0 8px" } }, (s.action || s.prompt || "").slice(0, 140)),
        inFilm(s) ? h("div", { style: { marginBottom: "8px" } },
          h("img", { src: `/takeframe/${fid}/${s.id}.jpg?n=${s.circled}&t=${Math.round(inFilm(s).time || 0)}`, alt: "A frame of the take of shot " + (i + 1), loading: "lazy", title: "Open this shot in Roll camera",
            style: { width: "100%", borderRadius: "4px", display: "block", cursor: "pointer" }, onclick: () => go("films", fid + "/roll/" + s.id) }),
          h("div", { class: "muted small", style: { marginTop: "4px" } }, "From take " + s.circled + ", the one in the film")) : null,
        (s.storyboard || []).length ? s.storyboard.slice().reverse().map(st => h("div", { style: { marginBottom: "8px" } },
          h("img", { src: refUrl(st.file), alt: "Still of shot " + (i + 1), loading: "lazy", style: { width: "100%", borderRadius: "4px", display: "block", cursor: "zoom-in" }, onclick: () => openAsset(st.asset) }),
          h("div", { class: "row", style: { gap: "4px", marginTop: "4px" } },
            (i === 0 || s.new_shot) ? h("button", { class: "small" + (s.first_frame === st.file ? " primary" : ""), onclick: () => { s.first_frame = s.first_frame === st.file ? "" : st.file; edited(); draw(); } }, s.first_frame === st.file ? "Opens on this ✓" : "Open the shot on this") : null,
            h("button", { class: "small ghost", onclick: async () => { const r = await tryApi(`/api/films/${fid}/storyboard/${s.id}/remove`, { asset: st.asset }); if (r) { mergeServer(r); draw(); } } }, "Remove"))))
          : inFilm(s) ? null : h("div", { class: "empty small" }, "no still yet"),
        h("button", { class: "small", onclick: async () => { await flush(); if (await tryApi(`/api/films/${fid}/storyboard`, { shots: [s.id] })) { toast("Queued"); poll(); } } }, "Another still"))))
        : h("div", { class: "empty" }, "Add shots first."));
  }

  // ------------------------------------------------------------------ Blockout: one per scene, refined, then cut into its shots
  function tabBlockout() {
    if (!film.shots.length) return h("div", { class: "empty" }, "Write the shots first (step 3): a blockout is made for a scene of them.");
    const scenes = [];
    film.shots.forEach((s, i) => { const k = sceneName(s.scene); let sc = scenes.find(x => x.name === k); if (!sc) scenes.push(sc = { name: k, shots: [] }); sc.shots.push(i); });
    if (!scenes.some(x => x.name === sceneName(ui.bscene))) ui.bscene = (scenes.find(x => sceneBlockout(x.name)) || scenes[0]).name;
    const sc = scenes.find(x => x.name === sceneName(ui.bscene));
    const label = n => n ? "Scene " + n : "The shots without a scene";
    const status = b => !b ? ["", "none"] : b.state && b.state.current ? ["good", "made"] : b.video ? ["warn", "changed"] : ["warn", "not made"];
    const list = h("div", { class: "shotlist" }, scenes.map(x => { const b = sceneBlockout(x.name), [cls, txt] = status(b);
      return h("button", { class: "shotrow" + (x === sc ? " on" : ""), onclick: () => { ui.bscene = x.name; draw(); } },
        h("span", { class: "ti" }, label(x.name)), h("span", { class: "faint small" }, x.shots.length + " shot" + (x.shots.length > 1 ? "s" : "")), h("span", { class: "chip " + cls }, txt)); }));
    const b = sceneBlockout(sc.name);
    const intro = h("p", { class: "sub", style: { marginTop: 0 } }, "A blockout is a rough 3D version of a whole scene, rendered in Blender: the set, the people and vehicles, and the camera. Make it after the shots are written, look at it and refine it until it works; it is then cut into the scene's shots, and each shot keeps its stretch's camera, positions and timing.");
    if (!b) return h("div", {}, intro, h("div", { class: "split" }, list,
      h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, label(sc.name)),
        h("p", { class: "muted" }, "No blockout: the shots of this scene are made from their words alone. Block it when the camera or the staging matters (a chase, a camera that follows or circles, vehicles, a fall, people placed exactly)."),
        h("div", { class: "row", style: { gap: "8px" } },
          h("button", { class: "primary", onclick: () => { film.blockouts.push({ id: nid(), scene_name: sc.name, scene: null, cuts: {} }); edited(); draw(); } }, "+ A blockout for this scene"),
          h("button", { onclick: async () => { await flush(); go("writer", "film/" + fid); } }, "✎ Ask the Writer to block it")))));

    // the player: the whole blockout, or one shot's stretch of it
    const st = b.state || {}, cuts = b.stretches || [];
    const total = Math.max(st.frames || 0, ...cuts.map(c => c.end), 1);
    const range = { a: 0, b: 0 };
    const vid = h("video", { controls: true, muted: true, preload: "metadata", style: { width: "100%", maxHeight: "360px", background: "#000", borderRadius: "4px" } });
    if (b.video) vid.src = refUrl(b.video) + "?m=" + (b.made || "");
    vid.addEventListener("timeupdate", () => { if (range.b && vid.currentTime >= range.b / 24) { vid.pause(); vid.currentTime = range.a / 24; } });
    const playing = h("span", { class: "muted small" }, "the whole blockout");
    const play = (c, n) => { range.a = c ? c.start : 0; range.b = c ? c.end : 0; vid.currentTime = range.a / 24; vid.play().catch(() => {});
      playing.textContent = c ? `shot ${n}: frames ${c.start}–${c.end - 1} (${(c.start / 24).toFixed(1)}–${(c.end / 24).toFixed(1)} s)` : "the whole blockout"; };
    const bar = h("div", { class: "cutbar" }, cuts.map((c, k) => { const s = film.shots[c.index] || {};
      return h("button", { class: "cut" + (c.continuation ? " cont" : ""), style: { left: (100 * c.start / total) + "%", width: (100 * c.frames / total) + "%", top: (k % 2 ? 26 : 0) + "px" },
        title: `${c.index + 1}. ${s.title || "Shot"}: frames ${c.start}–${c.end - 1}` + (c.continuation ? " (continues the shot before: it starts 39 frames before that one ends)" : ""),
        onclick: () => play(c, c.index + 1) }, `${c.index + 1} · ${s.title || "Shot"}`); }));
    const rows = h("div", { class: "small", style: { marginTop: "6px" } }, cuts.map(c => { const s = film.shots[c.index] || {};
      b.cuts = b.cuts || {};
      const box = { v: b.cuts[c.id] !== undefined ? b.cuts[c.id] : "" };
      return h("div", { class: "spread", style: { padding: "4px 0", borderBottom: "1px solid var(--line)" } },
        h("span", {}, h("b", {}, `${c.index + 1}. ${s.title || "Shot"}`), h("span", { class: "muted" }, ` · ${(c.frames / 24).toFixed(1)} s` + (c.continuation ? " · continues the one before" : ""))),
        h("span", { class: "row", style: { gap: "6px", alignItems: "center" } },
          c.continuation || c === cuts[0] ? h("span", { class: "muted" }, `from frame ${c.start}`)
            : h("span", { class: "row", style: { gap: "4px", alignItems: "center" } }, h("span", { class: "muted" }, "from frame"),
                h("input", { type: "number", min: 0, value: box.v, placeholder: String(c.start), style: { width: "90px" }, title: "Empty: where the shot before ends. A number moves this cut, and the shots after it.",
                  onchange: e => { const v = e.target.value; if (v === "") delete b.cuts[c.id]; else b.cuts[c.id] = Math.max(0, parseInt(v, 10) || 0); edited(); } })),
          b.video ? h("button", { class: "small", onclick: () => play(c, c.index + 1) }, "▶") : null,
          h("button", { class: "small ghost", onclick: async () => { await flush(); go("films", fid + "/roll/" + c.id); } }, "Roll camera")));
    }));

    // the scene, as data for Blender
    ui.bText = ui.bText || {};
    if (ui.bText[b.id] === undefined) ui.bText[b.id] = b.scene ? JSON.stringify(b.scene, null, 1) : "";
    const msg = h("div", { class: "hint" });
    const area = h("textarea", { rows: 16, class: "mono", placeholder: "Write the scene here, ask the Writer to block it, or press Example to see the form." });
    area.value = ui.bText[b.id];
    area.addEventListener("input", () => {
      ui.bText[b.id] = area.value;
      if (!area.value.trim()) { b.scene = null; msg.textContent = ""; edited(); return; }
      try { b.scene = JSON.parse(area.value); msg.textContent = ""; msg.className = "hint"; edited(); }
      catch (e) { msg.textContent = "Not valid JSON yet: " + e.message; msg.className = "hint bad"; }
    });
    const who = (film.cast[0] || {}).name || "Mara";
    const example = { sky: "dusk", ground: "asphalt",
      set: [{ type: "street", name: "", at: [-40, 0, 0], size: [200, 14, 13], turn: 0, color: "stone" }],
      things: [{ name: who, kind: "person", color: "blue", scale: 1,
        keys: [{ t: 0, at: [0, -3, 0], face: null, pose: "walk" }, { t: 8, at: [11, -3, 0], face: null, pose: "walk" }, { t: 10, at: [12, -3, 0], face: 90, pose: "look_up" }] }],
      camera: { lens: 35, shake: 0, keys: [{ t: 0, at: [5, -3.5, 1.6], look_at: [0, 0, 0], follow: who, lens: 0, cut: false },
        { t: 8, at: [16, -3.5, 1.6], look_at: [0, 0, 0], follow: who, lens: 0, cut: false },
        { t: 8.5, at: [12, -6, 0.4], look_at: [0, 0, 0], follow: who, lens: 28, cut: true }] } };
    const making = (S.state.jobs || []).find(j => j.kind === "blockout" && j.film === fid && (j.status === "queued" || j.status === "running") && (j.title || "").includes(sc.name || "(no name)"));
    const notes = [
      st.error && b.scene ? h("div", { class: "note bad" }, "The scene: " + st.error) : null,
      b.scene && !st.error && !b.video ? h("div", { class: "note warn" }, "Not made yet: press Make the blockout.") : null,
      b.video && !st.current && !st.error ? h("div", { class: "note warn" }, "The scene, or the length of one of its shots, changed since it was made: make it again.") : null,
      (st.small || []).length ? h("div", { class: "note warn" }, "Too small in the picture: " + st.small.map(([n, w]) => n + " " + w).join("; ") + ". The render then draws it the size the words ask for and stops following the blockout; bring the camera closer or use a longer lens.") : null];
    return h("div", {}, intro, h("div", { class: "split" }, list,
      h("div", {},
        h("div", { class: "card" },
          h("div", { class: "spread" }, h("h2", { style: { margin: 0 } }, label(sc.name)), h("span", { class: "muted small" }, `${cuts.length} shot(s) · ${(total / 24).toFixed(1)} s`)),
          b.video ? [h("div", { style: { marginTop: "10px" } }, vid),
            h("div", { class: "spread", style: { margin: "6px 0" } }, h("span", { class: "muted small" }, "Cut into shots: click one to play its stretch."), h("span", {}, playing, " ", h("button", { class: "small ghost", onclick: () => play(null) }, "Whole"))),
            bar] : h("div", { class: "empty", style: { marginTop: "10px" } }, making ? "Blender is making it…" : "Not made yet."),
          rows, notes),
        h("div", { class: "card" },
          h("div", { class: "spread" }, h("h3", { style: { margin: 0 } }, "The scene"), h("button", { class: "small ghost", onclick: async () => { await flush(); go("writer", "film/" + fid); } }, "✎ Ask the Writer to change it")),
          h("div", { class: "hint", style: { margin: "6px 0" } }, "The set, the people and vehicles with where they are at which second, and the camera; metres and seconds, z up. Time runs through the scene's shots in the order above. A camera key with \"cut\": true jumps there: a cut to another angle where a new shot starts. Learn → Prompting → Blockouts has the full form."),
          area, msg,
          h("div", { class: "row", style: { gap: "6px", marginTop: "8px" } },
            h("button", { class: "small", onclick: () => { area.value = JSON.stringify(example, null, 1); area.dispatchEvent(new Event("input")); } }, "Example"),
            h("button", { class: "small", onclick: async () => { const r = await tryApi("/api/blockout/check", { scene: area.value }); if (!r) return; msg.className = r.error ? "hint bad" : "hint good"; msg.textContent = r.error ? r.error : `The scene is fine: ${r.scene.set.length} set pieces, ${r.scene.things.length} things, ${r.scene.camera.keys.length} camera keys.` + (r.blender ? "" : " Blender was not found on this computer: set its path in Machine → Settings."); } }, "Check"),
            h("button", { class: "primary", disabled: !b.scene || !!making, onclick: async () => { await flush(); const r = await tryApi(`/api/films/${fid}/blockouts/${b.id}/make`, {}); if (r) { toast("Making the blockout in Blender"); poll(); draw(); } } }, making ? "Making…" : b.video ? "Make it again" : "Make the blockout"),
            h("button", { class: "small danger", style: { marginLeft: "auto" }, onclick: () => { if (!confirm(`Remove the blockout of ${label(sc.name).toLowerCase()}? Its shots are then made from their words alone.`)) return; film.blockouts.splice(film.blockouts.indexOf(b), 1); edited(); draw(); } }, "Remove the blockout"))))));
  }

  // ------------------------------------------------------------------ Roll camera: render, check, gate
  function tabRoll() {
    if (!film.shots.length) return h("div", { class: "empty" }, "Add shots first.");
    const cur = shotById(ui.shot) || film.shots[0];
    ui.shot = cur.id;
    const idx = film.shots.indexOf(cur);
    const run = film.run || {};
    const jobs = busyJobs();
    const mine = jobs.find(j => j.shot === cur.id);
    const rp = { mode: film.gate.mode, retries: film.gate.retries, upscale: false };
    const pre = h("div", {});
    async function preflight() {
      await flush();
      const c = await tryApi(`/api/films/${fid}/compose/${cur.id}`, {});
      if (!c) return;
      ui.pre[cur.id] = c;
      if (c.blockout) fillBlockout(c.blockout);
      const look = c.findings.filter(f => f.level !== "note").length;
      pre.replaceChildren(
        c.eligible ? null : h("div", { class: "note warn" }, c.why),
        c.fit && c.fit.text ? h("div", { class: "note " + (c.fit.ok ? "warn" : "bad") }, c.fit.text) : null,
        h("details", { open: look > 0 || ui.preOpen === cur.id, ontoggle: e => { ui.preOpen = e.target.open ? cur.id : null; } },
          h("summary", { class: "muted small", style: { cursor: "pointer" } },
            `Part ${c.part} · ${c.width}x${c.height} · ${c.frames} frames` + (c.continuation ? `, adds ${((c.frames - 39) / 24).toFixed(1)} s` : ` · ${(c.frames / 24).toFixed(1)} s`) +
            (c.estimate ? " · about " + secs(c.estimate) : "") + " · the prompt and its checks" +
            (look ? ` (${look} to look at)` : c.findings.length ? ` (${c.findings.length} note${c.findings.length > 1 ? "s" : ""})` : "")),
          h("div", { style: { marginTop: "8px" } },
            c.continuation && c.previous_sheet ? h("div", { class: "field" }, h("label", {}, "How the shot before ends (its last frames are on the right)"), h("img", { src: media(c.previous_sheet), alt: "Contact sheet of the shot before", style: { width: "100%", borderRadius: "4px" } })) : null,
            h("div", { class: "prompt" }, c.prompt),
            c.pictures.length ? h("div", { class: "small", style: { marginTop: "8px" } }, c.pictures.map(p => h("div", {}, h("b", {}, "Picture " + p.n), " — " + p.what))) : null,
            c.audios.length ? h("div", { class: "small" }, c.audios.map(a => h("div", {}, h("b", {}, "Audio " + a.n), " — " + a.speaker + "'s voice"))) : null,
            c.loras.length ? h("div", { class: "small muted" }, "LoRAs: " + c.loras.map(l => l[0].split("/").pop() + " " + l[1]).join(", ")) : null,
            c.findings.length ? h("div", { style: { marginTop: "10px" } }, findingsList(c.findings)) : null)));
    }
    // one player for what there is to look at before a take: the preview, the stretch of the blockout this shot
    // follows (a continuation reads on from where the shot before stopped), or the two side by side
    const rsb = !(cur.blockout || "").trim() && sceneBlockout(cur.scene);
    const rst = rsb && rsb.video && (rsb.stretches || []).find(c => c.id === cur.id);
    const stretch = (cur.blockout || "").trim() ? { src: refUrl(cur.blockout), start: 0, end: 0, known: false }
      : rst ? { src: refUrl(rsb.video) + "?m=" + (rsb.made || ""), start: rst.start, end: rst.end, known: true } : null;
    ui.view = ui.view || {};
    const viewBox = h("div", { style: { marginBottom: "10px" } });
    function drawViewer() {
      const pv = cur.preview;
      const pvSrc = pv ? media(pv.file) + "?t=" + Math.round(pv.time) : "";
      const opts = [pv ? ["preview", "Preview"] : null, stretch ? ["blockout", "Blockout"] : null, pv && stretch ? ["both", "Side by side"] : null].filter(Boolean);
      if (!opts.length) { viewBox.replaceChildren(); return; }
      let v = ui.view[cur.id];
      if (!opts.some(o => o[0] === v)) v = opts[0][0];
      const bs = stretch && pv && pv.blockout ? { ...stretch, start: pv.blockout.start, end: pv.blockout.end } : stretch;
      const vid = { width: "100%", maxHeight: "320px", background: "#000", borderRadius: "4px" };
      let body, caption;
      if (v === "preview") {
        body = h("video", { src: pvSrc, controls: true, preload: "metadata", style: vid });
        caption = `${pv.width}x${pv.height} · ${secs(pv.seconds_taken)} · ${ago(pv.time)} · the full render comes out differently, the staging and camera carry over`;
      } else if (v === "blockout") {
        body = rangeVideo(stretch.src, stretch.start, stretch.end, { style: { maxHeight: "320px" } });
        caption = stretch.known ? `frames ${stretch.start}–${stretch.end - 1} (${(stretch.start / 24).toFixed(1)}–${(stretch.end / 24).toFixed(1)} s) of the take's blockout` : "the take's blockout";
      } else {
        const a = rangeVideo(bs.src, bs.start, bs.end, { style: { maxHeight: "240px" } }), b2 = rangeVideo(pvSrc, 0, 0, { style: { maxHeight: "240px" } });
        b2.muted = false;
        body = h("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" } }, a, b2);
        caption = h("button", { class: "small", onclick: () => { a.currentTime = (bs.start || 0) / 24; b2.currentTime = 0; a.play().catch(() => {}); b2.play().catch(() => {}); } }, "▶ Play both");
      }
      viewBox.replaceChildren(
        h("div", { class: "spread", style: { marginBottom: "6px", gap: "8px" } },
          opts.length > 1 ? h("div", { class: "seg" }, opts.map(([id, label]) => h("button", { class: "small" + (id === v ? " on" : ""), onclick: () => { ui.view[cur.id] = id; drawViewer(); } }, label))) : h("span", { class: "muted small" }, opts[0][1]),
          typeof caption === "string" ? h("span", { class: "faint small", style: { textAlign: "right" } }, caption) : caption),
        body);
    }
    function fillBlockout(b) {
      if (!stretch || !b || stretch.known) return;
      Object.assign(stretch, { start: b.start, end: b.end, known: true });
      drawViewer();
    }
    drawViewer();
    if (stretch && (ui.pre[cur.id] || {}).blockout) fillBlockout(ui.pre[cur.id].blockout);
    else if (stretch && cur.takes.length) api(`/api/films/${fid}/compose/${cur.id}`, {}).then(c => { if (c) { ui.pre[cur.id] = c; fillBlockout(c.blockout); } }).catch(() => {});
    const previewing = (S.state.jobs || []).find(j => j.kind === "preview" && j.shot === cur.id && (j.status === "queued" || j.status === "running"));
    const takeCard = t => h("div", { class: "take" + (t.n === cur.circled ? " active" : "") },
      h("div", { class: "spread" }, h("b", {}, "Take " + t.n + (t.n === cur.circled ? " (in the film)" : "")),
        h("span", { class: "muted small" }, `seed ${t.seed} · ${secs(t.seconds_taken)} · ${t.verdict}` + (t.needs_look ? " · to look at" : ""))),
      t.preview ? h("video", { src: media(t.preview), controls: true, preload: "metadata", style: { marginTop: "6px" } }) : null,
      checkChips(t.checks), checkDetails(t.checks),
      t.sheet ? h("img", { src: media(t.sheet), alt: "Contact sheet of take " + t.n, loading: "lazy" }) : null,
      h("div", { class: "row", style: { gap: "6px", marginTop: "8px" } },
        t.n === cur.circled && cur.status === "review" ? h("button", { class: "primary", onclick: async () => { const r = await tryApi(`/api/films/${fid}/approve/${cur.id}`, {}); if (r) { toast("Approved"); poll(); reload(); } } }, "Approve") : null,
        t.n !== cur.circled && t.kept && t.kept.segment ? h("button", { class: "small", onclick: async () => { if (!confirm("Put take " + t.n + " back as this shot? Continuations after it must be rendered again.")) return; const r = await tryApi(`/api/films/${fid}/take/${cur.id}`, { n: t.n }); if (r) { film = r.film; draw(); } } }, "Put this take back") : null,
        stretch && t.preview ? h("button", { class: "small", onclick: () => compareModal(stretch, media(t.preview), `Take ${t.n} next to the blockout`) }, "Next to the blockout") : null,
        t.identity ? h("button", { class: "small", onclick: () => modal(h("div", {}, h("div", { class: "spread" }, h("h2", {}, "Same face, hair and clothes?"), h("button", { class: "ghost", onclick: closeModal }, "Close")), h("img", { class: "big", src: media(t.identity), alt: "Three frames of the take side by side" }))) }, "Three frames") : null,
        h("details", {}, h("summary", { class: "muted small", style: { cursor: "pointer" } }, "Prompt"), h("div", { class: "prompt" }, t.prompt))));
    const runBox = h("div", { class: "card" },
      h("div", { class: "spread" }, h("h3", { style: { margin: 0 } }, "Render the film"), run.active ? h("span", { class: "chip accent" }, "running · " + ({ hold: "holding every take", auto: "approving what passes", keep_going: "keeps going" }[run.mode] || run.mode)) : null),
      run.active ? h("div", { class: "row", style: { marginTop: "10px" } }, h("button", { onclick: async () => { await tryApi(`/api/films/${fid}/stop`, {}); reload(); poll(); } }, "Stop the run"))
        : h("div", { class: "row", style: { marginTop: "10px" } },
          h("div", { class: "field" }, h("label", {}, "After each take"), select(rp, "mode", [["hold", "Hold it for me"], ["auto", "Approve what passes; hold what fails"], ["keep_going", "Keep going (look at it later)"]])),
          h("div", { class: "field fit" }, h("label", {}, "Retakes"), number(rp, "retries", { min: 0, max: 5 })),
          h("div", { class: "fit" }, check(rp, "upscale", "Upscale at the end")),
          h("div", { class: "field fit" }, h("button", { class: "primary", onclick: async () => { await flush(); const r = await tryApi(`/api/films/${fid}/run`, rp); if (r) { toast("The run started"); poll(); reload(); } } }, "Render every shot without a take"))),
      (run.log || []).length ? h("div", { class: "small muted", style: { marginTop: "8px", maxHeight: "110px", overflow: "auto" } }, run.log.slice(-8).reverse().map(([t, m]) => h("div", {}, new Date(t * 1000).toLocaleTimeString() + "  " + m))) : null);
    const out = h("div", {}, runBox, h("div", { class: "split" }, h("div", {}, shotList()),
      h("div", {},
        h("div", { class: "card" },
          h("div", { class: "spread" }, h("h2", { style: { margin: 0 } }, (idx + 1) + ". " + (cur.title || "Shot")), h("div", { class: "row", style: { gap: "6px" } }, statusChip(mine ? (mine.status === "running" ? "rendering" : "queued") : cur.status),
            h("button", { class: "small ghost", onclick: () => go("films", fid + "/shots/" + cur.id) }, "Edit the shot"))),
          cur.error ? h("div", { class: "note bad", style: { marginTop: "8px" } }, cur.error) : null,
          cur.status === "stale" ? h("div", { class: "note warn", style: { marginTop: "8px" } }, "The shot before this one changed, so this continuation no longer fits it. Render it again.") : null,
          h("div", { class: "row", style: { gap: "6px", margin: "10px 0", flexWrap: "wrap" } },
            h("button", { class: cur.takes.length ? "" : "primary", disabled: !!mine, onclick: async () => { await flush(); const r = await tryApi(`/api/films/${fid}/render/${cur.id}`, {}); if (r) { toast("Queued"); poll(); reload(); } } }, cur.takes.length ? "Render again (a new take)" : "Render this shot"),
            h("div", { class: "seg" },
              h("button", { disabled: !!previewing, title: "A very small render (448x256) into a project of its own: the staging, the action and the camera in about two minutes. Nothing in the film changes.",
                onclick: async () => { await flush(); const r = await tryApi(`/api/films/${fid}/preview/${cur.id}`, {}); if (r) { toast("Preview queued"); poll(); } } }, previewing ? "Previewing…" : "Preview (low res)"),
              !cur.new_shot && idx > 0 ? h("button", { disabled: !!previewing, title: "Preview every shot of this take up to this one, in order: a continuation's preview continues the one before it, so the joins show.",
                onclick: async () => { await flush(); const r = await tryApi(`/api/films/${fid}/preview/${cur.id}`, { take: true }); if (r) { toast(r.jobs.length + " previews queued"); poll(); } } }, "with the shots before") : null),
            h("button", { class: "ghost", onclick: () => { ui.preOpen = cur.id; preflight(); } }, "Preflight")),
          viewBox,
          pre),
        cur.takes.length ? cur.takes.slice().reverse().map(takeCard) : h("div", { class: "empty" }, "No take yet."))));
    if (ui.pre[cur.id] === undefined && !cur.takes.length) preflight();
    return out;
  }

  // ------------------------------------------------------------------ Deliver
  function tabDeliver() {
    const done = film.shots.filter(s => s.part).length;
    const d = { start: "idle", retries: 1, upscale: true };
    return h("div", { class: "grid2" },
      h("div", {},
        h("div", { class: "card" }, h("h3", {}, "The film so far"),
          film.full ? h("video", { src: media(film.full) + "?t=" + film.updated, controls: true, style: { width: "100%", background: "#000" } }) : h("div", { class: "empty" }, "Nothing rendered yet."),
          h("div", { class: "muted small", style: { marginTop: "8px" } }, `${done} of ${film.shots.length} shots rendered · ${film.shots.filter(s => s.status === "approved").length} approved`)),
        film.full_upscaled ? h("div", { class: "card" }, h("h3", {}, "Upscaled"), h("video", { src: media(film.full_upscaled) + "?t=" + film.updated, controls: true, style: { width: "100%", background: "#000" } })) : null),
      h("div", {},
        h("div", { class: "card" }, h("h3", {}, "Finish"),
          h("div", { class: "stack" },
            h("button", { disabled: !done, onclick: async () => { if (await tryApi(`/api/films/${fid}/upscale`, {})) { toast("Upscale queued: about six minutes a part"); poll(); } } }, "Upscale ×1.5 and 48 fps"),
            h("div", { class: "hint" }, "Parts are upscaled in order; each join is crossfaded into the part before. A person LoRA of the cast is used in the upscale too."),
            h("button", { disabled: !done, onclick: async () => { const t = await tryApi(`/api/films/${fid}/timeline`, {}); if (t) go("timeline", t.id); } }, "To a timeline (levels, music, captions, export)"),
            film.full_upscaled ? h("button", { onclick: async () => { const t = await tryApi(`/api/films/${fid}/timeline`, { upscaled: true }); if (t) go("timeline", t.id); } }, "The upscaled parts to a timeline") : null,
            h("button", { disabled: !done, onclick: async () => { const j = await tryApi("/api/dailies", { film: fid }); if (j) { toast("Reel queued"); poll(); } } }, "A reel of every take, with what the checks found"),
            h("a", { class: "btn", href: `/api/films/${fid}/story`, download: fid + ".py" }, "Export as a story-kit file (.py)"))),
        h("div", { class: "card" }, h("h3", {}, "Render the rest tonight"),
          h("div", { class: "row" },
            h("div", { class: "field" }, h("label", {}, "Start"), select(d, "start", [["idle", "When the machine has been idle for two minutes"], ["now", "Now"], ["23:00", "At 23:00"], ["01:00", "At 01:00"]])),
            h("div", { class: "field fit" }, h("label", {}, "Retakes"), number(d, "retries", { min: 0, max: 5 })),
            h("div", { class: "fit" }, check(d, "upscale", "Upscale"))),
          h("button", { onclick: async () => { await flush(); const s = await tryApi("/api/nightshift", { film: fid, ...d }); if (s) { toast(`Night shift planned: ${s.shots} shot(s)`); go("nightshift"); } } }, "Plan a night shift"))));
  }

  // ------------------------------------------------------------------ the frame around the tabs
  // the steps of making the film, in order (the server says which are done: film.steps)
  const stepNote = h("div", {});
  const pick = async t => { await flush(); ui.tab = t; history.replaceState(null, "", "#films/" + fid + "/" + t); draw(); $("#room").scrollTop = 0; };
  const stepsOf = () => film.steps || [];
  const stepLabel = s => h("span", {}, h("span", { class: "stepn" + (s.done ? " done" : "") }, s.done ? "✓" : String(s.n)), s.label + (s.optional ? " (optional)" : ""));
  function drawSteps() {
    const st = stepsOf(), gate = film.shots.filter(s => s.status === "review").length;
    if (!st.length) return;
    tabBar.replaceChildren(tabs(st.map(s => [s.id, stepLabel(s), s.id === "roll" ? (gate || null) : null]), ui.tab, pick));
    const i = st.findIndex(s => s.id === ui.tab), here = st[i];
    const earlier = st.slice(0, i).find(s => !s.done && !s.optional);
    stepNote.replaceChildren(
      here && !here.done && here.todo ? h("div", { class: "note" + (here.optional ? "" : " warn"), style: { marginTop: 0 } }, h("b", {}, `Step ${here.n}, ${here.label}: `), here.todo + ".") : null,
      earlier ? h("div", { class: "note", style: { marginTop: 0 } }, "An earlier step is not done: ",
        h("a", { href: "#films/" + fid + "/" + earlier.id, onclick: e => { e.preventDefault(); pick(earlier.id); } }, `${earlier.n} · ${earlier.label}`), " (" + earlier.todo + ").") : null);
  }
  function stepFoot() {
    const st = stepsOf(), i = st.findIndex(s => s.id === ui.tab);
    if (i < 0) return null;
    const prev = st[i - 1], next = st[i + 1], here = st[i];
    return h("div", { class: "stepfoot" },
      prev ? h("button", { class: "ghost", onclick: () => pick(prev.id) }, `← ${prev.n} · ${prev.label}`) : h("span", {}),
      next ? h("div", { class: "row", style: { gap: "10px", alignItems: "center", justifyContent: "flex-end" } },
        h("span", { class: "muted small" }, "Next: " + next.what),
        h("button", { class: here.done ? "primary" : "", onclick: () => pick(next.id) }, `${next.n} · ${next.label} →`)) : h("span", { class: "muted small" }, "This is the last step."));
  }
  function draw() {
    drawSteps();
    body.replaceChildren({ bible: tabBible, cast: tabCast, shots: tabShots, blockout: tabBlockout, storyboard: tabStoryboard, roll: tabRoll, deliver: tabDeliver }[ui.tab](), stepFoot());
  }
  // a film brought in from a project has no prompts until its story file is read
  const storyBox = h("div", {});
  if (film.adopted && !film.story) {
    const st = { path: "" };
    storyBox.append(h("div", { class: "card" }, h("h3", {}, "This film was brought in without its story"),
      h("p", { class: "muted small" }, `Its parts come from the project “${film.long_project}”, and the nodes keep no prompts. If it was made with the story kit, give its story file: the prompt and lines of every part, the cast, the places and the props are read from it. The file is a program; it is run to be read.`),
      h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "The story file"), text(st, "path", { placeholder: "/path/to/the_story.py" })),
        h("div", { class: "field fit" }, h("button", { class: "primary", onclick: async e => {
          e.target.disabled = true; await flush();
          const r = await tryApi(`/api/films/${fid}/story`, { path: st.path });
          e.target.disabled = false;
          if (!r) return;
          const rep = r.report;
          toast(`Read ${rep.parts} parts: ${rep.cast.length} in the cast, ${rep.places.length} place(s), ${rep.props.length} prop(s).` + (rep.added ? ` ${rep.added} part(s) of the story are not rendered yet: they are shots to render.` : "")
            + (rep.differ.length ? ` Part ${rep.differ.join(", ")} would not be sent exactly as the story kit sends it: look at the prompt before rendering it again.` : "")
            + (rep.missing.length ? ` Not in ComfyUI's input folder: ${rep.missing.join(", ")}.` : ""), rep.missing.length > 0);
          go("films", fid + "/shots");
        } }, "Read the story")))));
  }
  root.append(h("div", { class: "spread" }, h("button", { class: "ghost small", onclick: () => go("films") }, "← Films"),
      h("div", { class: "row", style: { gap: "10px", alignItems: "center" } }, saveNote, h("button", { class: "small", onclick: async () => { await flush(); go("writer", "film/" + fid); } }, "✎ Talk to the Writer about this film"))),
    head(film.name, film.bible.logline || ""), storyBox, tabBar, stepNote, body);
  draw();
}

// ---------------------------------------------------------------- Cast library
ROOMS.cast = { title: "Cast", async draw(root) {
  let cast = (await tryApi("/api/cast")) || [];
  const box = h("div", {}), note = h("span", { class: "muted small" });
  const save = debounce(async () => { note.textContent = "saving…"; const r = await tryApi("/api/cast", { cast }, "PUT"); if (r) { cast.forEach((c, i) => c.id = r[i].id); note.textContent = "saved"; } }, 600);
  function draw() {
    box.replaceChildren(cast.length ? cast.map((c, i) => h("div", {}, personCard(c, save, () => { cast.splice(i, 1); save(); draw(); }))) : h("div", { class: "empty" }, "No characters yet."));
  }
  root.append(h("div", { class: "spread" }, head("Cast", "Characters kept across films: a face, an outfit sheet, a voice. A film takes a copy, so changing one here leaves finished films alone."), note),
    h("div", { class: "row", style: { gap: "6px", marginBottom: "14px" } },
      h("button", { class: "primary", onclick: () => { cast.push({ id: "", name: "", pronoun: "their", description: "", face: "", body: "", voice: "", lora: {} }); draw(); } }, "+ Character"),
      h("button", { onclick: () => go("picture", "", { template: "portrait", width: 1024, height: 1024, takes: 3 }) }, "Invent a face"),
      h("button", { onclick: () => go("edit", "", { angles: "sheet" }) }, "Make an outfit sheet from a face")),
    box,
    h("div", { class: "note" }, "A trained person LoRA (face and voice) is set per film in Cast & places. Training one is not part of the studio: it needs a rented GPU or a long local run; see Learn."));
  draw();
} };

// ---------------------------------------------------------------- Night shift
ROOMS.nightshift = { title: "Night shift", async draw(root) {
  const box = h("div", {});
  const films = (await tryApi("/api/films")) || [];
  const d = { film: (films[0] || {}).id || "", start: "idle", retries: 1, upscale: true };
  async function load() {
    const list = (await tryApi("/api/nightshift")) || [];
    box.replaceChildren(list.length ? list.map(s => h("div", { class: "card" },
      h("div", { class: "spread" }, h("b", {}, s.name), h("span", { class: "chip " + ({ planned: "info", running: "accent", finishing: "accent", done: "good", cancelled: "" }[s.status] || "") }, s.status)),
      h("div", { class: "muted small", style: { margin: "4px 0 8px" } }, `${s.shots} shot(s) · starts ${s.start === "idle" ? "when idle" : s.start === "now" ? "now" : "at " + s.start} · ${s.retries} retake(s)` + (s.upscale ? " · upscale" : "") + (s.run_stopped ? " · " + s.run_stopped : "")),
      s.dailies && s.dailies.reel ? h("video", { src: media(s.dailies.reel), controls: true, preload: "metadata", style: { width: "100%", maxWidth: "720px", background: "#000", borderRadius: "4px" } }) : null,
      h("div", { class: "row", style: { gap: "6px", marginTop: "8px" } },
        s.status === "planned" ? h("button", { class: "small primary", onclick: async () => { if (await tryApi(`/api/nightshift/${s.id}/start`, {})) { toast("Started"); load(); poll(); } } }, "Start now") : null,
        s.status === "planned" || s.status === "running" ? h("button", { class: "small", onclick: async () => { await tryApi(`/api/nightshift/${s.id}/cancel`, {}); load(); poll(); } }, s.status === "running" ? "Stop" : "Cancel") : null,
        s.dailies && s.dailies.notes ? h("a", { class: "btn small", href: media(s.dailies.notes), target: "_blank" }, "Notes") : null,
        h("button", { class: "small ghost", onclick: () => go("films", s.film + "/roll") }, "Open the film"))))
      : h("div", { class: "empty" }, "No shifts yet."));
  }
  onJobEnd(j => { if (j.kind === "dailies" || j.kind === "shot") load(); });
  root.append(head("Night shift", "Render the rest of a film while you are away. A take that fails its checks is rendered again; one that still fails is kept so the run can go on, and the notes list it first. In the morning: a reel of every take after a title card, and the notes."),
    h("div", { class: "card" }, films.length ? h("div", { class: "row" },
      h("div", { class: "field" }, h("label", {}, "Film"), select(d, "film", films.map(f => [f.id, f.name]))),
      h("div", { class: "field" }, h("label", {}, "Start"), select(d, "start", [["idle", "When the machine has been idle for two minutes"], ["now", "Now"], ["22:00", "At 22:00"], ["23:00", "At 23:00"], ["01:00", "At 01:00"]])),
      h("div", { class: "field fit" }, h("label", {}, "Retakes"), number(d, "retries", { min: 0, max: 5 })),
      h("div", { class: "fit" }, check(d, "upscale", "Upscale at the end")),
      h("div", { class: "field fit" }, h("button", { class: "primary", onclick: async () => { const s = await tryApi("/api/nightshift", d); if (s) { toast(`Planned: ${s.shots} shot(s)`); load(); } } }, "Plan it")))
      : h("div", { class: "muted" }, "Plan a film first.")),
    box);
  load();
} };
