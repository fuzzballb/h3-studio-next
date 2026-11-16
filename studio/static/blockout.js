"use strict";
// Blockout: a rough 3D sketch of a shot (grey set pieces, simple figures, a camera path) that Blender renders into a
// video, which a clip then follows for its camera, positions and timing (Video → full form → A blockout video).
// The 3D view here plays the scene the way the Blender script (studio/blender/blockout.py) moves it: the same keys,
// the same smooth paths, the same camera. Coordinates are the scene's own: metres, z up, facing 0 = +x.

const BO = {
  SKIES: ["day", "dusk", "night", "indoor"],
  GROUNDS: ["grass", "snow", "asphalt", "sand", "floor", "water", "none"],
  SET_TYPES: ["street", "room", "building", "city", "box", "wall", "cylinder", "ball", "cone", "tree"],
  KINDS: ["person", "child", "cyclist", "car", "coupe", "sports car", "suv", "pickup", "van", "truck", "bus", "tram", "train", "bike", "horse", "dog", "animal", "bird", "box", "ball", "sled", "boat", "plane"],
  POSES: ["stand", "walk", "run", "sit", "lie", "crouch", "look_up", "look_down", "wave"],
  SET_SIZE: { street: [200, 14, 13], room: [8, 6, 3], building: [10, 10, 15], city: [300, 300, 16], box: [1, 1, 1], wall: [4, 0.2, 3], cylinder: [1, 1, 2], ball: [1, 1, 1], cone: [1, 1, 2], tree: [3, 3, 6] },
  SET_ABOUT: { street: "a road with houses on both sides, running along +x from its start", room: "a floor with walls at the back and sides, open to the front", building: "one block-shaped building", city: "blocks of houses, for flying over roofs", box: "a box", wall: "a flat wall", cylinder: "a pillar, a barrel, a tower", ball: "a ball or dome", cone: "a cone", tree: "a tree" },
  COLORS: { red: [0.55, 0.05, 0.05], "dark red": [0.3, 0.03, 0.03], orange: [0.8, 0.35, 0.05], yellow: [0.85, 0.7, 0.1], gold: [0.75, 0.6, 0.2], green: [0.12, 0.45, 0.15], "dark green": [0.05, 0.22, 0.08],
    blue: [0.12, 0.25, 0.6], "light blue": [0.4, 0.6, 0.85], navy: [0.05, 0.08, 0.25], purple: [0.35, 0.12, 0.45], pink: [0.85, 0.45, 0.55], white: [0.9, 0.9, 0.9], grey: [0.45, 0.45, 0.47],
    "dark grey": [0.18, 0.18, 0.2], black: [0.04, 0.04, 0.05], brown: [0.32, 0.2, 0.12], "light brown": [0.55, 0.4, 0.25], beige: [0.75, 0.65, 0.5], brick: [0.42, 0.22, 0.16], stone: [0.55, 0.53, 0.5],
    wood: [0.45, 0.3, 0.17], glass: [0.55, 0.7, 0.8], silver: [0.7, 0.72, 0.75], skin: [0.85, 0.62, 0.5], snow: [0.82, 0.84, 0.88], grass: [0.2, 0.42, 0.15], asphalt: [0.2, 0.2, 0.22], sand: [0.76, 0.66, 0.45],
    floor: [0.5, 0.42, 0.33], water: [0.1, 0.25, 0.4], "tinted glass": [0.35, 0.45, 0.5], headlight: [1.0, 0.95, 0.75], taillight: [0.8, 0.04, 0.04] },
  CARS: ["car", "coupe", "sports car", "suv", "pickup"],          // drawn from car_shapes.json, like Blender does
  KIND_ABOUT: { car: "a saloon", coupe: "a two-door coupe with a sloping back", "sports car": "a low, wide sports car with a spoiler", suv: "a tall SUV with roof rails", pickup: "a pickup truck with an open bed" },
  SKY: { day: [0.55, 0.7, 0.9], dusk: [0.45, 0.32, 0.36], night: [0.05, 0.07, 0.15], indoor: [0.22, 0.22, 0.24] },
  VEHICLE: { car: [4.7, 1.82, 1.45], coupe: [4.55, 1.85, 1.35], "sports car": [4.5, 1.95, 1.2], suv: [4.8, 1.95, 1.75], pickup: [5.4, 2.0, 1.85], van: [5.2, 2.0, 2.3], truck: [8.0, 2.5, 3.3], bus: [12, 2.55, 3.2], tram: [30, 2.4, 3.4], train: [60, 3.0, 4.0] },
  ANIMAL: { horse: [2.0, 0.55, 0.9, 0.8], dog: [0.75, 0.25, 0.35, 0.3], animal: [1.3, 0.42, 0.5, 0.55] },
  STRIDE: { person: 1.5, child: 1.0, horse: 2.4, dog: 0.9, animal: 1.8, cyclist: 4.0 },
  POSE: { stand: [0, 0, 0, 0, 0], walk: [0, 0, 0, 0, 3], run: [0, 0, 0, 0, 10], sit: [0, 1, 0, 0, 0], lie: [90, 0, 0, 0, 0], look_up: [0, 0, 35, 0, 0], look_down: [0, 0, -30, 0, 0], wave: [0, 0, 0, 150, 0], crouch: [0, 0.6, -15, 0, 15] },
};
const THREE_URL = "/static/vendor/three-0.170.0.module.min.js";
let THREE_P = null;
const loadThree = () => (THREE_P = THREE_P || import(THREE_URL));
let CAR_SHAPES = null;                       // static/car_shapes.json: the same car parts Blender builds
const loadCars = async () => (CAR_SHAPES = CAR_SHAPES || await (await fetch("/static/car_shapes.json")).json());
const deg = Math.PI / 180;

// ------------------------------------------------------------------ motion, as the Blender script does it
const boSmooth = u => { u = Math.min(1, Math.max(0, u)); return u * u * (3 - 2 * u); };
const vsub = (a, b) => a.map((x, i) => x - b[i]);
const vlen = a => Math.hypot(...a);
function boTrack(keys, val) {                 // Hermite through the keys; still at the ends and where it holds
  const ts = keys.map(k => k.t), vs = keys.map(val), n = keys.length;
  const tan = vs.map((v, i) => (i === 0 || i === n - 1 || vlen(vsub(vs[i], vs[i - 1])) < 1e-4 || vlen(vsub(vs[i + 1], vs[i])) < 1e-4)
    ? [0, 0, 0] : vsub(vs[i + 1], vs[i - 1]).map(x => x / Math.max(1e-6, ts[i + 1] - ts[i - 1])));
  return t => {
    if (!n) return [0, 0, 0];
    if (t <= ts[0]) return vs[0].slice();
    if (t >= ts[n - 1]) return vs[n - 1].slice();
    let i = 0; while (i < n - 2 && ts[i + 1] <= t) i++;
    const dt = Math.max(1e-6, ts[i + 1] - ts[i]), u = (t - ts[i]) / dt;
    const h00 = 2 * u ** 3 - 3 * u ** 2 + 1, h10 = u ** 3 - 2 * u ** 2 + u, h01 = -2 * u ** 3 + 3 * u ** 2, h11 = u ** 3 - u ** 2;
    return [0, 1, 2].map(j => vs[i][j] * h00 + tan[i][j] * h10 * dt + vs[i + 1][j] * h01 + tan[i + 1][j] * h11 * dt);
  };
}
function boStepped(keys, val) {               // eases from one key's value to the next
  return t => {
    if (!keys.length) return 0;
    if (t <= keys[0].t) return val(keys[0]);
    for (let i = 0; i < keys.length - 1; i++) {
      const a = keys[i], b = keys[i + 1];
      if (a.t <= t && t <= b.t) { const u = boSmooth((t - a.t) / Math.max(1e-6, b.t - a.t)); return val(a) + (val(b) - val(a)) * u; }
    }
    return val(keys[keys.length - 1]);
  };
}
const xyz = (v, d = [0, 0, 0]) => [0, 1, 2].map(i => Number.isFinite(+(v || [])[i]) ? +v[i] : d[i]);
const sortKeys = keys => (keys || []).slice().sort((a, b) => (+a.t || 0) - (+b.t || 0));

function boMotion(scene) {                    // { things: {name: {pos(t), face(t), pose(t)->[5], height, dist(t)}}, camera(t) }
  const things = {};
  for (const th of scene.things || []) {
    const keys = sortKeys(th.keys).map(k => ({ ...k, t: +k.t || 0, at: xyz(k.at) }));
    if (!keys.length) continue;
    const pos = boTrack(keys, k => k.at);
    const given = keys.filter(k => k.face !== null && k.face !== undefined && k.face !== "");
    const pose = [0, 1, 2, 3, 4].map(i => boStepped(keys, k => (BO.POSE[k.pose] || BO.POSE.stand)[i]));
    let first = 0;
    for (let i = 0; i < keys.length - 1; i++) { const d = vsub(keys[i + 1].at, keys[i].at); if (Math.hypot(d[0], d[1]) > 0.05) { first = Math.atan2(d[1], d[0]); break; } }
    const face = t => {
      if (given.length) {
        const before = given.filter(k => k.t <= t), after = given.filter(k => k.t > t);
        if (!before.length) return +given[0].face * deg;
        if (!after.length) return +before[before.length - 1].face * deg;
        const a = before[before.length - 1], b = after[0], u = boSmooth((t - a.t) / Math.max(1e-6, b.t - a.t));
        const d = ((+b.face - +a.face + 540) % 360) - 180;
        return (+a.face + d * u) * deg;
      }
      for (let tt = t; tt >= -0.01; tt -= 0.2) { const d = vsub(pos(tt + 0.1), pos(tt - 0.1)); if (Math.hypot(d[0], d[1]) > 0.02) return Math.atan2(d[1], d[0]); }
      return first;
    };
    const s = +th.scale || 1;
    const height = { person: 1.75, child: 1.22, cyclist: 1.75, bike: 1.1 }[th.kind] * s || (BO.VEHICLE[th.kind] ? BO.VEHICLE[th.kind][2] * s : BO.ANIMAL[th.kind] ? (BO.ANIMAL[th.kind][3] + BO.ANIMAL[th.kind][2] * 1.6) * s : s);
    const dist = t => { let d = 0, p = pos(0); for (let tt = 0.1; tt <= t + 1e-9; tt += 0.1) { const q = pos(tt); d += vlen(vsub(q, p)); p = q; } return d; };
    things[th.name] = { pos, face, pose: t => pose.map(f => f(t)), height, dist, keys };
  }
  const cam = scene.camera || {}, lens0 = +cam.lens || 35;
  const ck = sortKeys(cam.keys).map(k => ({ ...k, t: +k.t || 0, at: xyz(k.at, [0, -10, 1.6]), look_at: xyz(k.look_at) }));
  const segs = [[]];
  for (const k of ck) { if (k.cut && segs[segs.length - 1].length) segs.push([]); segs[segs.length - 1].push(k); }
  const moves = segs.filter(s => s.length).map(sg => ({ sg, cpos: boTrack(sg, k => k.at), lens: boStepped(sg, k => +k.lens || lens0) }));
  const target = (k, t) => { const f = k.follow && things[k.follow]; if (f) { const p = f.pos(t); return [p[0], p[1], p[2] + f.height * 0.75]; } return k.look_at; };
  const camera = t => {
    if (!moves.length) return { at: [0, -10, 1.6], look: [0, 0, 1], lens: lens0 };
    const m = moves.slice().reverse().find(m => m.sg[0].t <= t) || moves[0];
    const before = m.sg.filter(k => k.t <= t), after = m.sg.filter(k => k.t > t);
    const a = (before.length ? before : m.sg.slice(0, 1)).slice(-1)[0], b = (after.length ? after : m.sg.slice(-1))[0];
    const u = b !== a ? boSmooth((t - a.t) / Math.max(1e-6, b.t - a.t)) : 0;
    const ta = target(a, t), tb = target(b, t);
    return { at: m.cpos(t), look: ta.map((x, i) => x + (tb[i] - x) * u), lens: m.lens(t) };
  };
  const ends = [...ck.map(k => k.t), ...Object.values(things).flatMap(x => x.keys.map(k => k.t))];
  return { things, camera, duration: Math.max(1, ...ends), lens0 };
}

// ------------------------------------------------------------------ Claude Code writes or changes a scene, with progress
// Starts the task, shows how far it is in `box` (what it is doing, a bar of the answer written so far, the time, Stop),
// and resolves with {scene, say, problem}; rejects with the error (or "Stopped.").
async function writeSceneWithProgress(params, box, running) {
  const t0 = running || await api("/api/blockouts/write", { ...params, progress: true });
  const bar = h("div", { class: "bobar" }, h("i")), line = h("div", { class: "small" }), sub = h("div", { class: "muted small" });
  const stop = h("button", { class: "small ghost danger", onclick: () => tryApi(`/api/blockouts/write/${t0.task}`, undefined, "DELETE") }, "Stop");
  box.hidden = false;
  box.replaceChildren(h("div", { class: "boprog" }, h("div", { class: "spread" }, line, stop), bar, sub));
  const fmt = n => n.toLocaleString("en");
  return new Promise((resolve, reject) => {
    const tick = async () => {
      let t; try { t = await api("/api/blockouts/write/" + t0.task); } catch (e) { box.hidden = true; return reject(e); }
      const secs = Math.round(t.seconds), typ = t.typical ? ` · usually about ${Math.round(t.typical)} s` : "";
      let share;
      if (t.phase === "writing") {
        // past the estimate the bar keeps creeping on (it never stops while the answer still grows)
        const over = t.chars > t.expect * 0.95, expect = over ? t.chars * 1.15 : t.expect;
        share = 0.15 + 0.83 * Math.min(1, t.chars / Math.max(1, expect));
        line.textContent = over ? "Writing the scene (longer than usual)" : "Writing the scene";
        sub.textContent = (over ? `${fmt(t.chars)} characters so far` : `${fmt(t.chars)} of about ${fmt(t.expect)} characters`) + ` · ${secs} s${typ}`;
      } else {
        share = t.phase === "thinking" ? 0.08 + 0.07 * Math.min(1, t.seconds / 60) : 0.03;
        line.textContent = t.phase === "thinking" ? "Thinking about the shot" : "Starting Claude Code";
        sub.textContent = `${secs} s${typ} · it writes the scene once it has thought it through`;
      }
      bar.firstChild.style.width = Math.round(100 * (t.done ? 1 : Math.min(0.98, share))) + "%";
      if (!t.done) return setTimeout(tick, 700);
      box.hidden = true;
      if (t.error) reject(new Error(t.error));
      else if (!t.result || !t.result.scene || typeof t.result.scene !== "object") reject(new Error("Claude sent no scene; nothing was changed"));
      else resolve(t.result);
    };
    tick();
  });
}

// ------------------------------------------------------------------ the room
ROOMS.blockout = { title: "Blockout", full: arg => !!arg, async draw(root, arg) {
  if (!arg) return drawBlockoutList(root);
  return drawBlockoutEditor(root, arg);
} };

async function drawBlockoutList(root) {
  const grid = h("div", { class: "boards" });
  const idea = h("textarea", { rows: 3, placeholder: "A cyclist rides toward the camera down a snowy street at night, a tram crosses behind her, and the camera pulls back as she passes." });
  const busy = h("div", { hidden: true });
  let writing = false;
  async function fromWords() {
    if (!idea.value.trim()) return toast("Describe the shot first", true);
    if (writing) return;
    writing = true;
    try {
      const r = await writeSceneWithProgress({ idea: idea.value }, busy);
      const b = await api("/api/blockouts", { name: idea.value.trim().split(/[.,;\n]/)[0].slice(0, 60), idea: idea.value, scene: r.scene });
      go("blockout", b.id);
    } catch (e) { toast(e.message, true); }
    finally { writing = false; }
  }
  async function make(scene) { const b = await tryApi("/api/blockouts", { name: "", scene }); if (b) go("blockout", b.id); }
  root.append(
    h("div", { class: "section-head" }, h("div", {},
      h("h1", { class: "display", style: { fontSize: "34px" } }, "Blockout"),
      h("p", { class: "muted", style: { margin: "6px 0 0", maxWidth: "760px" } },
        "A rough 3D sketch of a shot: grey shapes for the set, simple figures for people and vehicles, and a camera path. Blender renders it into a video, and a clip made from it keeps its camera, positions and timing while the model paints the real thing over it. Use it when words cannot hold the shot: a camera that circles or follows, a car that stops and turns, people placed exactly."))),
    h("div", { class: "bosteps" },
      [["1", "Sketch it", "Describe the shot and Claude Code builds the scene, or start from a street and change it yourself in the 3D view."],
       ["2", "Look at it", "Play it in the 3D view, from anywhere or through the camera. Drag things around; the timeline sets when."],
       ["3", "Render it", "Blender makes the grey video on this computer, in a minute or two. It lands in the Library."],
       ["4", "Use it", "Use in a video opens the Video form with the blockout filled in. Describe there what the shapes really are."]]
        .map(([n, t, s]) => h("div", { class: "card" }, h("span", { class: "num" }, n), h("b", {}, t), h("p", { class: "muted small" }, s)))),
    h("div", { class: "card", style: { maxWidth: "980px" } },
      h("h3", { style: { marginTop: 0 } }, "Start a new blockout"),
      h("div", { class: "field" }, h("label", {}, "Describe the shot (Claude Code writes the scene; only these words are sent)"), idea),
      h("div", { class: "row", style: { gap: "8px", alignItems: "center" } },
        h("button", { class: "primary", onclick: fromWords }, "Build it from my words"),
        h("button", { onclick: () => make(null) }, "Start from a street"),
        h("button", { class: "ghost", onclick: () => make({ sky: "day", ground: "grass", set: [], things: [], camera: { lens: 35, shake: 0, keys: [{ t: 0, at: [-8, -8, 3], look_at: [0, 0, 1], follow: "", lens: 0, cut: false }] } }) }, "Empty scene")),
      busy),
    h("h2", {}, "Your blockouts"), grid);
  const r = await tryApi("/api/blockouts");
  if (!r) return;
  if (!r.blender) root.insertBefore(h("div", { class: "note warn" }, "Blender was not found on this computer, so blockouts can be built and played here but not rendered. Set its path in ☰ → Machine → Settings (blender)."), grid.previousSibling);
  const thumbs = {};
  await Promise.all(r.items.filter(b => b.asset).map(b => api("/api/library/" + b.asset).then(a => { thumbs[b.id] = a; }).catch(() => {})));
  grid.replaceChildren(r.items.length ? r.items.map(b => h("div", { style: { position: "relative" } },
    h("button", { class: "boardcard", style: { width: "100%" }, onclick: () => go("blockout", b.id) },
      h("div", { class: "prev one", style: thumbs[b.id] ? { backgroundImage: `url("${thumbs[b.id].thumb}")` } : {} }, thumbs[b.id] ? null : h("span", { class: "muted small" }, "not rendered yet")),
      h("div", { class: "info" }, h("b", {}, b.name), h("span", {}, `${b.things} thing(s) · ${b.size} · ${ago(b.updated)}`))),
    h("button", { class: "small danger", style: { position: "absolute", top: "8px", right: "8px" }, onclick: async () => {
      if (!confirm(`Delete the blockout “${b.name}”? A video already rendered stays in the Library.`)) return;
      if (await tryApi("/api/blockouts/" + b.id, undefined, "DELETE")) route(); } }, "Delete")))
    : h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, "No blockouts yet."));
}

async function drawBlockoutEditor(root, id) {
  let b;
  try { b = await api("/api/blockouts/" + id); } catch (e) { toast(e.message, true); return go("blockout"); }
  if (typeof b.scene === "string") { try { b.scene = JSON.parse(b.scene); } catch (e) { b.scene = null; } }
  if (!b.scene || typeof b.scene !== "object") b.scene = { sky: "day", ground: "grass", set: [], things: [], camera: { lens: 35, shake: 0, keys: [] } };
  const sc = b.scene;
  sc.set = sc.set || []; sc.things = sc.things || []; sc.camera = sc.camera || { lens: 35, shake: 0, keys: [] }; sc.camera.keys = sc.camera.keys || [];
  let THREE;
  try { THREE = await loadThree(); await loadCars(); } catch (e) { root.append(h("div", { class: "note bad" }, "The 3D view could not load: " + e.message)); return; }
  THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

  const ui = { sel: { type: "scene" }, t: 0, playing: false, view: "free", undo: [], redo: [], state: b.state, job: b.job, blenderSeen: b.blender_at || 0, blender: false };
  let motion = boMotion(sc);
  const [W, H] = (b.size || "1152x640").split("x").map(Number);

  // ---------------- saving and undo
  const saveNow = async why => {
    ui.saving = true;
    try { const r = await api("/api/blockouts/" + id, { name: b.name, size: b.size, idea: b.idea, scene: sc, why: typeof why === "string" ? why : "" }, "PUT"); ui.state = r.state; b.updated = r.updated; drawRender(); }
    catch (e) { toast(e.message, true); }
    finally { ui.saving = false; }
  };
  const saveSoon = debounce(saveNow, 500);
  const save = () => { ui.saving = true; saveSoon(); };            // waiting to be saved: outside changes wait too
  const snap = () => JSON.stringify(sc);
  function change(fn, keepPanels) {                           // every edit: remember the scene before, apply, redraw, save
    ui.undo.push(snap()); if (ui.undo.length > 120) ui.undo.shift(); ui.redo = [];
    fn();
    rebuild(); if (!keepPanels) { drawOutline(); drawInspector(); } save();
  }
  function restore(from, to) {
    if (!from.length) return;
    to.push(snap());
    const s = JSON.parse(from.pop());
    for (const k of Object.keys(sc)) delete sc[k];
    Object.assign(sc, s);
    if (ui.sel.i !== undefined && !(ui.sel.type === "set" ? sc.set[ui.sel.i] : ui.sel.type === "thing" ? sc.things[ui.sel.i] : true)) ui.sel = { type: "scene" };
    rebuild(); drawOutline(); drawInspector(); save();
  }

  // ---------------- the 3D view
  const canvas = h("canvas", { class: "bocanvas", tabindex: "0", "aria-label": "3D view of the blockout" });
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene3 = new THREE.Scene();
  const free = new THREE.PerspectiveCamera(50, 1, 0.05, 6000);
  const shot = new THREE.PerspectiveCamera(40, W / H, 0.05, 6000);
  const orbit = { target: new THREE.Vector3(0, 0, 1), dist: 30, yaw: -2.2, pitch: 0.45 };
  const placeFree = () => {
    const cp = Math.cos(orbit.pitch);
    free.position.set(orbit.target.x + orbit.dist * cp * Math.cos(orbit.yaw), orbit.target.y + orbit.dist * cp * Math.sin(orbit.yaw), orbit.target.z + orbit.dist * Math.sin(orbit.pitch));
    free.lookAt(orbit.target);
  };
  scene3.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(30, -40, 80); scene3.add(sun);
  const world = new THREE.Group(); scene3.add(world);
  const overlay = new THREE.Group(); scene3.add(overlay);
  const mats = {};
  const mat = c => {
    c = String(c || "grey").trim().toLowerCase();
    if (!mats[c]) {
      const m = new THREE.MeshLambertMaterial();
      if (/^#[0-9a-f]{6}$/.test(c)) m.color.set(c); else { const v = BO.COLORS[c] || BO.COLORS.grey; m.color.setRGB(v[0], v[1], v[2]); }
      if (c === "tinted glass") { m.transparent = true; m.opacity = 0.3; m.depthWrite = false; }
      mats[c] = m;
    }
    return mats[c];
  };
  const boxM = (sx, sy, sz, color, x, y, z, parent) => { const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), mat(color)); m.position.set(x, y, z); parent.add(m); return m; };
  const cylM = (r1, r2, hgt, color, x, y, z, parent, seg = 16) => { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, hgt, seg), mat(color)); m.rotation.x = Math.PI / 2; m.position.set(x, y, z); parent.add(m); return m; };
  const ballM = (r, color, x, y, z, parent) => { const m = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), mat(color)); m.position.set(x, y, z); parent.add(m); return m; };
  const tag = (obj, sel) => { obj.traverse(o => { o.userData.sel = sel; }); return obj; };

  function setPiece(it, i) {
    const g = new THREE.Group(), t = it.type, size = xyz(it.size, BO.SET_SIZE[t] || [1, 1, 1]).map((v, j) => v > 0 ? v : (BO.SET_SIZE[t] || [1, 1, 1])[j]);
    const [x, y, z] = xyz(it.at), [a, bb, c] = size, col = it.color;
    let rnd = 7 + i; const rand = () => ((rnd = (rnd * 16807) % 2147483647) / 2147483647);
    if (t === "street") {
      boxM(a, bb, 0.04, sc.ground === "snow" ? "snow" : "asphalt", x + a / 2, y, z + 0.02, g);
      for (const side of [-1, 1]) {
        boxM(a, 2.4, 0.15, "stone", x + a / 2, y + side * (bb / 2 + 1.2), z + 0.075, g);
        let px = x;
        while (px < x + a) { const w = 6 + rand() * 3, hh = c * (0.8 + rand() * 0.3); boxM(w - 0.15, 10, hh, col || "brick", px + w / 2, y + side * (bb / 2 + 2.4 + 5), z + hh / 2, g); px += w; }
      }
    } else if (t === "room") {
      boxM(a, bb, 0.05, "floor", x, y, z + 0.025, g);
      boxM(a, 0.15, c, col || "beige", x, y + bb / 2, z + c / 2, g);
      boxM(0.15, bb, c, col || "beige", x - a / 2, y, z + c / 2, g);
      boxM(0.15, bb, c, col || "beige", x + a / 2, y, z + c / 2, g);
    } else if (t === "city") {
      for (let bx = Math.floor(x - a / 2); bx < x + a / 2; bx += 26) for (let by = Math.floor(y - bb / 2); by < y + bb / 2; by += 26) for (let k = 0; k < 3; k++) {
        const hh = (0.6 + rand() * 0.4) * c; boxM(6.4, 18, hh, col || "brick", bx + k * 7, by, z + hh / 2, g);
      }
    } else {
      const inner = new THREE.Group(); inner.position.set(x, y, z); inner.rotation.z = (+it.turn || 0) * deg; g.add(inner);
      if (t === "box" || t === "wall" || t === "building") boxM(a, bb, c, col || (t === "building" ? "brick" : "grey"), 0, 0, c / 2, inner);
      else if (t === "cylinder") { const m = cylM(0.5, 0.5, 1, col || "grey", 0, 0, c / 2, inner, 24); m.scale.set(a, c, bb); }
      else if (t === "ball") { const m = ballM(0.5, col || "grey", 0, 0, c / 2, inner); m.scale.set(a, bb, c); }
      else if (t === "cone") { const m = cylM(0, 0.5, 1, col || "grey", 0, 0, c / 2, inner, 24); m.scale.set(a, c, bb); }
      else if (t === "tree") { cylM(0.15 * a, 0.15 * a, c * 0.35, "wood", 0, 0, c * 0.175, inner, 8); cylM(0, a / 2, c * 0.75, col || "dark green", 0, 0, c * 0.6, inner, 12); }
    }
    if (t === "street" || t === "room" || t === "city") g.rotation.z = 0;
    return tag(g, { type: "set", i });
  }

  function figure(th, i) {                     // built facing +x, origin on the ground; parts to pose kept in .rig
    const root = new THREE.Group(), body = new THREE.Group(); root.add(body);
    const k = th.kind, s = +th.scale || 1, col = th.color || (["person", "child", "cyclist", "horse", "dog", "animal"].includes(k) ? "brown" : "red");
    const rig = { body, legs: [], head: null, arm: null, wheels: [], height: 1 };
    const person = (parent, c, kk) => {
      for (const side of [-0.11, 0.11]) {
        const hip = new THREE.Group(); hip.position.set(0, side * kk, 0.9 * kk); parent.add(hip);
        cylM(0.08 * kk, 0.08 * kk, 0.88 * kk, "dark grey", 0, 0, -0.45 * kk, hip, 8);
        boxM(0.28 * kk, 0.11 * kk, 0.08 * kk, "black", 0.06 * kk, 0, -0.88 * kk, hip);
        rig.legs.push({ hip, off: side < 0 ? 0 : Math.PI, amp: 0.42 });
      }
      const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.2 * kk, 0.3 * kk, 0.75 * kk, 12), mat(c)); torso.rotation.x = Math.PI / 2; torso.position.set(0, 0, 1.25 * kk); parent.add(torso);
      const head = new THREE.Group(); head.position.set(0, 0, 1.62 * kk); parent.add(head);
      const face = ballM(0.12 * kk, "skin", 0, 0, 0.06 * kk, head); face.scale.set(1, 0.9, 1.15);
      boxM(0.06 * kk, 0.04 * kk, 0.05 * kk, "skin", 0.12 * kk, 0, 0.06 * kk, head);
      const arm = new THREE.Group(); arm.position.set(0, 0.27 * kk, 1.5 * kk); parent.add(arm);
      const ua = new THREE.Mesh(new THREE.CylinderGeometry(0.055 * kk, 0.055 * kk, 0.6 * kk, 8), mat(c)); ua.rotation.x = Math.PI / 2; ua.position.set(0, 0, -0.3 * kk); arm.add(ua);
      const arm2 = new THREE.Group(); arm2.position.set(0, -0.27 * kk, 1.5 * kk); parent.add(arm2);
      const ub = ua.clone(); arm2.add(ub);
      return { head, arm };
    };
    if (k === "person" || k === "child") { const kk = k === "child" ? 0.7 * s : s; const p = person(body, col, kk); rig.head = p.head; rig.arm = p.arm; rig.height = 1.75 * kk; }
    else if (BO.CARS.includes(k) && CAR_SHAPES && CAR_SHAPES[k]) {
      const shp = CAR_SHAPES[k], pick = c => c === "body" ? col : c;
      body.scale.setScalar(s);
      for (const p of shp.parts) {
        if (p.p === "prism") {
          const sh = new THREE.Shape(p.pts.map(([x, z]) => new THREE.Vector2(x, z)));
          const m = new THREE.Mesh(new THREE.ExtrudeGeometry(sh, { depth: p.w, bevelEnabled: false }), mat(pick(p.c)));
          m.rotation.x = Math.PI / 2; m.position.y = p.y + p.w / 2; body.add(m);   // the profile's z up, pushed out across y
        } else if (p.p === "box") boxM(p.s[0], p.s[1], p.s[2], pick(p.c), p.at[0], p.at[1], p.at[2], body);
        else if (p.p === "disc") { const m = new THREE.Mesh(new THREE.CylinderGeometry(p.r, p.r, p.w, 16), mat(p.c)); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(Math.cos(25 * deg), 0, Math.sin(25 * deg))); m.position.set(...p.at); body.add(m); }
        else if (p.p === "wheel") {
          const w = new THREE.Mesh(new THREE.CylinderGeometry(p.r, p.r, p.w, 16), mat("black")); w.position.set(...p.at); body.add(w);
          const rim = new THREE.Mesh(new THREE.CylinderGeometry(p.r * 0.6, p.r * 0.6, p.w + 0.02, 12), mat("silver")); rim.position.set(...p.at); body.add(rim);
        }
      }
      if (th.driver) {                         // seated, hands on the wheel (as in Blender)
        const [x, y, z] = shp.seat, [wx, , wz] = shp.wheel_at, dr = String(th.driver);
        boxM(0.45, 0.32, 0.14, "dark grey", x + 0.22, y, z + 0.02, body);
        const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.58, 12), mat(dr)); torso.rotation.x = Math.PI / 2; torso.position.set(x - 0.05, y, z + 0.32); body.add(torso);
        const head = ballM(0.11, "skin", x - 0.02, y, z + 0.74, body); head.scale.set(1, 0.9, 1.15);
        const hair = ballM(0.115, dr === "dark grey" ? "black" : "dark grey", x - 0.05, y, z + 0.78, body); hair.scale.set(1, 0.95, 0.8);
        for (const side of [0.16, -0.16]) {
          const sx = x - 0.03, sz = z + 0.55, dx = wx - sx, dz = wz - sz, len = Math.hypot(dx, dz);
          const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, len, 8), mat(dr));
          arm.position.set(sx + dx / 2, y + side, sz + dz / 2);
          arm.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(dx / len, 0, dz / len)); body.add(arm);
        }
      }
      rig.height = shp.size[2] * s;
    } else if (BO.VEHICLE[k]) {
      const [L, Wd, Ht] = BO.VEHICLE[k].map(d => d * s), low = 0.35 * s;
      if (k === "tram" || k === "train") {
        const cars = k === "tram" ? 3 : 4;
        for (let n = 0; n < cars; n++) { const seg = L / cars, x = -L / 2 + seg * (n + 0.5); boxM(seg - 0.3 * s, Wd, Ht - low, col, x, 0, low + (Ht - low) / 2, body); boxM(seg - 1.2 * s, Wd + 0.04, 0.9 * s, "glass", x, 0, low + (Ht - low) * 0.62, body); }
      } else {
        boxM(L, Wd, Ht * 0.45, col, 0, 0, low + Ht * 0.225, body);
        const cabL = L * (k === "car" ? 0.5 : 0.28), cabX = k === "car" ? -0.1 * L : L / 2 - cabL / 2;
        boxM(cabL, Wd * 0.92, Ht * 0.5, k === "car" ? "glass" : col, cabX, 0, low + Ht * 0.7, body);
        if (k !== "car") boxM(L - cabL, Wd, Ht - low, col, -cabL / 2, 0, low + (Ht - low) / 2, body);
        for (const wx of [L * 0.32, -L * 0.32]) for (const wy of [Wd / 2, -Wd / 2]) { const w = new THREE.Mesh(new THREE.CylinderGeometry(low, low, 0.25 * s, 14), mat("black")); w.position.set(wx, wy, low); body.add(w); }
      }
      rig.height = Ht;
    } else if (k === "bike" || k === "cyclist") {
      for (const wx of [0.55 * s, -0.55 * s]) { const w = new THREE.Mesh(new THREE.TorusGeometry(0.33 * s, 0.03 * s, 6, 20), mat("black")); w.rotation.x = Math.PI / 2; w.position.set(wx, 0, 0.35 * s); body.add(w); }
      const fr = boxM(1.1 * s, 0.06 * s, 0.06 * s, k === "cyclist" ? "dark grey" : col, 0, 0, 0.65 * s, body); fr.rotation.y = 10 * deg;
      boxM(0.06 * s, 0.6 * s, 0.06 * s, "black", 0.5 * s, 0, 1.0 * s, body);
      rig.height = 1.1 * s;
      if (k === "cyclist") {
        const rider = new THREE.Group(); rider.position.set(-0.15 * s, 0, 0.12 * s); rider.rotation.y = 25 * deg; body.add(rider);
        const p = person(rider, col, s); rig.head = p.head; rig.arm = p.arm; rig.height = 1.75 * s;
        rig.legs.forEach(l => { l.hip.rotation.y = -60 * deg; l.amp = -3; });
      }
    } else if (BO.ANIMAL[k]) {
      const [L, Wd, Bh, leg] = BO.ANIMAL[k].map(d => d * s);
      boxM(L, Wd, Bh, col, 0, 0, leg + Bh / 2, body);
      const neck = boxM(0.25 * L, Wd * 0.5, Bh * 1.1, col, L * 0.5, 0, leg + Bh, body); neck.rotation.y = -30 * deg;
      const head = new THREE.Group(); head.position.set(L * 0.62, 0, leg + Bh * 1.55); body.add(head); boxM(L * 0.3, Wd * 0.55, Bh * 0.45, col, L * 0.1, 0, 0, head);
      for (const lx of [L * 0.38, -L * 0.38]) for (const ly of [Wd * 0.35, -Wd * 0.35]) {
        const hip = new THREE.Group(); hip.position.set(lx, ly, leg); body.add(hip);
        boxM(0.12 * Wd + 0.05 * s, 0.12 * Wd + 0.05 * s, leg, col, 0, 0, -leg / 2, hip);
        rig.legs.push({ hip, off: (lx > 0 ? 0 : Math.PI) + (ly > 0 ? 0 : Math.PI / 2), amp: 0.6 });
      }
      rig.head = head; rig.height = leg + Bh * 1.6;
    } else if (k === "ball") { ballM(0.25 * s, col, 0, 0, 0.25 * s, body); rig.height = 0.5 * s; }
    else if (k === "sled") { boxM(2.6 * s, 1.5 * s, 0.7 * s, col, 0, 0, 0.7 * s, body); boxM(0.25 * s, 1.5 * s, s, col, -1.2 * s, 0, 1.2 * s, body); rig.height = 1.5 * s; }
    else if (k === "boat") { boxM(6 * s, 2.2 * s, s, col, 0, 0, 0.3 * s, body); boxM(2 * s, 1.6 * s, 1.2 * s, "white", -0.8 * s, 0, 1.4 * s, body); rig.height = 2 * s; }
    else if (k === "plane") { const f = new THREE.Mesh(new THREE.CylinderGeometry(1.6 * s, 1.6 * s, 30 * s, 16), mat(col)); f.rotation.z = Math.PI / 2; body.add(f); boxM(5 * s, 32 * s, 0.4 * s, col, s, 0, 0, body); boxM(3 * s, 0.3 * s, 5 * s, col, -13 * s, 0, 2.5 * s, body); rig.height = 4 * s; }
    else if (k === "bird") { const bd = ballM(0.12 * s, col, 0, 0, 0, body); bd.scale.set(1.6, 1, 1); boxM(0.2 * s, 0.8 * s, 0.02 * s, col, 0, 0, 0, body); rig.height = 0.3 * s; }
    else { boxM(s, s, s, col, 0, 0, s / 2, body); rig.height = s; }
    root.userData.rig = rig;
    return tag(root, { type: "thing", i });
  }

  let figures = [], camGizmo = null, aimGizmo = null, shotFrame = null;
  function line(points, color, dashed) {
    const g = new THREE.BufferGeometry().setFromPoints(points.map(p => new THREE.Vector3(...p)));
    const m = dashed ? new THREE.LineDashedMaterial({ color, dashSize: 0.6, gapSize: 0.4 }) : new THREE.LineBasicMaterial({ color });
    const l = new THREE.Line(g, m); if (dashed) l.computeLineDistances(); return l;
  }
  function rebuild() {
    motion = boMotion(sc);
    world.clear(); overlay.clear(); figures = [];
    const sky = BO.SKY[sc.sky] || BO.SKY.day;
    scene3.background = new THREE.Color().setRGB(sky[0], sky[1], sky[2]);
    if (sc.ground !== "none") { const g = new THREE.Mesh(new THREE.PlaneGeometry(4000, 4000), mat(sc.ground || "grass")); g.userData.ground = true; world.add(g); }
    const grid = new THREE.GridHelper(200, 100, 0x000000, 0x000000); grid.rotation.x = Math.PI / 2; grid.position.z = 0.01; grid.material.opacity = 0.12; grid.material.transparent = true; overlay.add(grid);
    sc.set.forEach((it, i) => world.add(setPiece(it, i)));
    sc.things.forEach((th, i) => { if (!(th.keys || []).length) return; const f = figure(th, i); f.userData.name = th.name; world.add(f); figures.push(f); });
    // paths and keys of the things, and the camera's
    const selName = ui.sel.type === "thing" ? (sc.things[ui.sel.i] || {}).name : null;
    for (const [name, m] of Object.entries(motion.things)) {
      if (m.keys.length > 1) { const pts = []; for (let t = 0; t <= m.keys[m.keys.length - 1].t + 1e-6; t += 0.1) { const p = m.pos(t); pts.push([p[0], p[1], p[2] + 0.05]); } overlay.add(line(pts, name === selName ? 0xd1fe17 : 0xffffff)); }
      const ti = sc.things.findIndex(x => x.name === name);
      m.keys.forEach((k, j) => { const d = ballM(name === selName ? 0.22 : 0.14, name === selName ? "#d1fe17" : "white", k.at[0], k.at[1], k.at[2] + 0.05, overlay); d.userData.sel = { type: "thing", i: ti, key: j }; });
    }
    const ck = sortKeys(sc.camera.keys);
    if (ck.length) {
      const pts = []; for (let t = 0; t <= motion.duration + 1e-6; t += 0.1) pts.push(motion.camera(t).at);
      overlay.add(line(pts, 0xff9d3c, true));
      ck.forEach(k => { const d = ballM(ui.sel.type === "camera" ? 0.25 : 0.18, "#ff9d3c", ...xyz(k.at), overlay); d.userData.sel = { type: "camera" }; });
    }
    camGizmo = new THREE.Group(); camGizmo.rotation.order = "ZYX";
    const body = boxM(0.5, 0.35, 0.3, "#ff9d3c", 0, 0, 0, camGizmo);
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.3, 0.5, 4, 1, true), new THREE.MeshBasicMaterial({ color: 0xff9d3c, wireframe: true }));
    cone.rotation.z = Math.PI / 2; cone.position.x = 0.45; camGizmo.add(cone);
    tag(camGizmo, { type: "camera" }); overlay.add(camGizmo);
    aimGizmo = ballM(0.18, "#ff9d3c", 0, 0, 0, overlay); aimGizmo.material = new THREE.MeshBasicMaterial({ color: 0xff9d3c, wireframe: true }); aimGizmo.userData.sel = { type: "aim" };
    void body;
    pose(ui.t);
    drawTimeline();
  }
  function pose(t) {
    for (const f of figures) {
      const m = motion.things[f.userData.name]; if (!m) continue;
      const p = m.pos(t), rig = f.userData.rig;
      f.position.set(p[0], p[1], p[2]); f.rotation.set(0, 0, m.face(t));
      const [tilt, sit, look, raise, lean] = m.pose(t);
      const v = vlen(vsub(m.pos(t + 0.05), m.pos(t - 0.05))) / 0.1;
      const dist = m.dist(t), stride = (BO.STRIDE[sc.things[f.userData.sel.i].kind] || 1.5) * (+sc.things[f.userData.sel.i].scale || 1);
      const phase = dist / stride * 2 * Math.PI;
      for (const l of rig.legs) {
        if (l.amp === -3) l.hip.rotation.y = -60 * deg + 0.5 * Math.sin(phase * 0.6 + l.off);
        else l.hip.rotation.y = (v > 0.25 ? l.amp * Math.sin(phase + l.off) * Math.min(1, v / 0.8) : 0) - 80 * deg * sit;
      }
      rig.body.rotation.y = (lean - tilt) * deg;
      rig.body.position.z = -0.45 * sit * rig.height / 1.75 + (tilt > 45 ? 0.15 * rig.height / 1.75 : 0);
      if (rig.head) rig.head.rotation.y = -look * deg;
      if (rig.arm) rig.arm.rotation.x = -raise * deg;
    }
    const c = motion.camera(t);
    shot.position.set(...c.at); shot.up.set(0, 0, 1); shot.lookAt(...c.look);
    const aspect = W / H, hf = 2 * Math.atan(18 / c.lens);       // Blender: 36 mm sensor across the longer side
    shot.fov = (aspect >= 1 ? 2 * Math.atan(Math.tan(hf / 2) / aspect) : hf) / deg; shot.aspect = aspect; shot.updateProjectionMatrix();
    if (camGizmo) { camGizmo.position.set(...c.at); const d = vsub(c.look, c.at); camGizmo.rotation.set(0, -Math.atan2(d[2], Math.hypot(d[0], d[1])), Math.atan2(d[1], d[0])); camGizmo.visible = ui.view === "free"; }
    if (aimGizmo) { aimGizmo.position.set(...c.look); aimGizmo.visible = ui.view === "free"; }
    if (timeLabel) timeLabel.textContent = t.toFixed(1) + " s";
    if (slider && document.activeElement !== slider) slider.value = t;
  }

  // ---------------- drawing loop, sizing, view
  const viewBox = h("div", { class: "boview" }, canvas);
  const frameLabel = h("div", { class: "boframe-label" });
  viewBox.append(frameLabel);
  let alive = true, last = performance.now();
  function resize() {
    const r = viewBox.getBoundingClientRect();
    renderer.setSize(Math.max(50, r.width), Math.max(50, r.height), false);
    free.aspect = r.width / Math.max(1, r.height); free.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  function frame(now) {
    if (!alive) return;
    if (!document.body.contains(canvas)) { alive = false; ro.disconnect(); renderer.dispose(); return; }
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (ui.playing) { ui.t += dt; if (ui.t > motion.duration) ui.t = 0; pose(ui.t); }
    placeFree();
    const r = viewBox.getBoundingClientRect(), cw = r.width, chh = r.height;
    if (ui.view === "shot") {                                   // letterboxed to the video's shape
      const a = W / H; let vw = cw, vh = cw / a; if (vh > chh) { vh = chh; vw = chh * a; }
      renderer.setScissorTest(false); renderer.setViewport(0, 0, cw, chh); renderer.setClearColor(0x000000); renderer.clear();
      renderer.setScissorTest(true); renderer.setScissor((cw - vw) / 2, (chh - vh) / 2, vw, vh); renderer.setViewport((cw - vw) / 2, (chh - vh) / 2, vw, vh);
      overlay.visible = false; renderer.render(scene3, shot); overlay.visible = true; renderer.setScissorTest(false);
      frameLabel.textContent = `Through the camera · ${W}×${H} · lens ${Math.round(motion.camera(ui.t).lens)} mm`;
    } else {
      renderer.setViewport(0, 0, cw, chh); renderer.render(scene3, free);
      frameLabel.textContent = "";
    }
    requestAnimationFrame(frame);
  }

  // pointer: click selects, drag a selected thing / set piece / camera moves it on the ground, drag empty space orbits
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const hitAt = e => { const r = canvas.getBoundingClientRect(); ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1); ray.setFromCamera(ndc, free); };
  const groundPoint = (e, z = 0) => { hitAt(e); const p = new THREE.Vector3(); return ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), -z), p) ? p : null; };
  let drag = null;
  canvas.addEventListener("contextmenu", e => e.preventDefault());
  canvas.addEventListener("pointerdown", e => {
    canvas.focus();
    if (ui.view !== "free") { drag = { mode: "none" }; return; }
    if (e.button === 2 || e.shiftKey || e.button === 1) { drag = { mode: "pan", x: e.clientX, y: e.clientY, t0: orbit.target.clone() }; canvas.setPointerCapture(e.pointerId); return; }
    hitAt(e);
    const hit = ray.intersectObjects([...world.children, ...overlay.children], true).find(x => x.object.userData.sel);
    const sel = hit && hit.object.userData.sel;
    if (sel) {
      const same = ui.sel.type === sel.type && ui.sel.i === sel.i;
      if (!same || sel.key !== undefined) {
        ui.sel = { type: sel.type === "aim" ? "camera" : sel.type, i: sel.i };
        if (sel.key !== undefined) { const k = motion.things[sc.things[sel.i].name].keys[sel.key]; ui.t = k.t; pose(ui.t); }
        rebuild(); drawOutline(); drawInspector();
      }
      const z = sel.type === "camera" ? motion.camera(ui.t).at[2] : sel.type === "aim" ? motion.camera(ui.t).look[2] : 0;
      drag = { mode: "move", sel, z, start: groundPoint(e, z), moved: false, before: snap() };
    } else drag = { mode: "orbit", x: e.clientX, y: e.clientY, yaw: orbit.yaw, pitch: orbit.pitch, click: true };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", e => {
    if (!drag) return;
    if (drag.mode === "orbit") {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.click = false;
      orbit.yaw = drag.yaw - dx * 0.006; orbit.pitch = Math.max(-0.1, Math.min(1.5, drag.pitch + dy * 0.006));
    } else if (drag.mode === "pan") {
      const k = orbit.dist * 0.0016, dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      const right = new THREE.Vector3(-Math.sin(orbit.yaw), Math.cos(orbit.yaw), 0), fwd = new THREE.Vector3(Math.cos(orbit.yaw), Math.sin(orbit.yaw), 0);
      orbit.target.copy(drag.t0).addScaledVector(right, dx * k).addScaledVector(fwd, dy * k);
    } else if (drag.mode === "move" && drag.start) {
      const p = groundPoint(e, drag.z); if (!p) return;
      if (!drag.moved) { ui.undo.push(drag.before); ui.redo = []; drag.moved = true; }
      moveSelection(drag.sel, p.x, p.y);
      rebuild();
    }
  });
  const endDrag = () => {
    if (!drag) return;
    if (drag.mode === "orbit" && drag.click && ui.sel.type !== "scene") { ui.sel = { type: "scene" }; rebuild(); drawOutline(); drawInspector(); }
    if (drag.mode === "move" && drag.moved) { drawInspector(); save(); }
    drag = null;
  };
  canvas.addEventListener("pointerup", endDrag); canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("wheel", e => { e.preventDefault(); if (ui.view !== "free") return; orbit.dist = Math.max(1.5, Math.min(1500, orbit.dist * Math.exp(e.deltaY * 0.0012))); }, { passive: false });
  canvas.addEventListener("keydown", e => {
    if ((e.key === "Delete" || e.key === "Backspace") && (ui.sel.type === "set" || ui.sel.type === "thing")) { e.preventDefault(); removeSelected(); }
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
  });
  const onKey = e => {
    if (!document.body.contains(canvas)) return document.removeEventListener("keydown", onKey);
    if (e.target.closest && e.target.closest("input, textarea, select")) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? restore(ui.redo, ui.undo) : restore(ui.undo, ui.redo); }
  };
  document.addEventListener("keydown", onKey);

  // a key at the playhead: the one there (within 0.05 s), or a new one
  function keyAtNow(keys, make) {
    let k = keys.find(k => Math.abs((+k.t || 0) - ui.t) < 0.05);
    if (!k) { k = make(); k.t = Math.round(ui.t * 10) / 10; keys.push(k); keys.sort((a, b) => a.t - b.t); }
    return k;
  }
  const r2 = v => Math.round(v * 100) / 100;
  function moveSelection(sel, x, y) {
    if (sel.type === "set") { const it = sc.set[sel.i]; const at = xyz(it.at); it.at = [r2(x), r2(y), at[2]]; }
    else if (sel.type === "thing") {
      const th = sc.things[sel.i]; th.keys = th.keys || [];
      const m = motion.things[th.name];
      const k = sel.key !== undefined ? th.keys.find(kk => Math.abs((+kk.t || 0) - m.keys[sel.key].t) < 1e-6) || th.keys[0]
        : keyAtNow(th.keys, () => { const prev = sortKeys(th.keys).filter(kk => +kk.t <= ui.t).pop() || th.keys[0] || {}; return { at: [0, 0, 0], face: null, pose: prev.pose || "stand" }; });
      const z = xyz(k.at)[2]; k.at = [r2(x), r2(y), z];
    } else if (sel.type === "camera" || sel.type === "aim") {
      const c = motion.camera(ui.t);
      const k = keyAtNow(sc.camera.keys, () => ({ at: c.at.map(r2), look_at: c.look.map(r2), follow: "", lens: 0, cut: false }));
      if (sel.type === "camera") { const z = xyz(k.at, [0, 0, 1.6])[2]; k.at = [r2(x), r2(y), z]; }
      else { k.follow = ""; const z = xyz(k.look_at)[2]; k.look_at = [r2(x), r2(y), z]; }
    }
  }
  function removeSelected() {
    change(() => {
      if (ui.sel.type === "set") sc.set.splice(ui.sel.i, 1);
      if (ui.sel.type === "thing") { const n = sc.things[ui.sel.i].name; sc.things.splice(ui.sel.i, 1); sc.camera.keys.forEach(k => { if (k.follow === n) { k.follow = ""; k.look_at = motion.things[n] ? motion.things[n].pos(k.t || 0) : [0, 0, 1]; } }); }
      ui.sel = { type: "scene" };
    });
  }
  function frameAll() {
    const box = new THREE.Box3();
    world.children.forEach(o => { if (!o.userData.ground) box.expandByObject(o); });
    overlay.children.forEach(o => { if (o.userData.sel) box.expandByObject(o); });
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
    orbit.target.copy(c); orbit.dist = Math.min(400, Math.max(8, Math.max(s.x, s.y, s.z * 2) * 0.9));
  }
  function startView() {                     // from behind and above the camera's first position, looking where it looks
    const c = motion.camera(0), d = vsub(c.at, c.look), flat = Math.hypot(d[0], d[1]) || 1;
    orbit.target.set(...c.look); orbit.yaw = Math.atan2(d[1], d[0]); orbit.pitch = 0.5; orbit.dist = Math.max(10, Math.min(120, flat * 2.2 + 6));
  }
  function frameSelection() {
    let p = null;
    if (ui.sel.type === "thing") { const m = motion.things[(sc.things[ui.sel.i] || {}).name]; if (m) p = m.pos(ui.t); }
    if (ui.sel.type === "set") p = xyz(sc.set[ui.sel.i].at);
    if (ui.sel.type === "camera") p = motion.camera(ui.t).at;
    if (p) { orbit.target.set(p[0], p[1], p[2] + 1); orbit.dist = Math.min(orbit.dist, 18); }
  }

  // ---------------- timeline
  const slider = h("input", { type: "range", min: 0, max: 1, step: 0.01, value: 0, class: "boslider", "aria-label": "Time" });
  const timeLabel = h("span", { class: "botime" }, "0.0 s");
  const playBtn = h("button", { class: "small", onclick: () => togglePlay() }, "▶ Play");
  const ticks = h("div", { class: "boticks" });
  slider.addEventListener("input", () => { ui.t = +slider.value; ui.playing = false; playBtn.textContent = "▶ Play"; pose(ui.t); });
  slider.addEventListener("change", () => drawInspector());          // "key at …", the key rows that are now
  function togglePlay() { ui.playing = !ui.playing; if (ui.playing && ui.t >= motion.duration - 0.01) ui.t = 0; playBtn.textContent = ui.playing ? "❚❚ Pause" : "▶ Play"; if (!ui.playing) drawInspector(); }
  function drawTimeline() {
    slider.max = motion.duration;
    if (ui.t > motion.duration) ui.t = motion.duration;
    let keys = [], color = "";
    if (ui.sel.type === "thing") { const m = motion.things[(sc.things[ui.sel.i] || {}).name]; keys = m ? m.keys.map(k => k.t) : []; color = "lime"; }
    if (ui.sel.type === "camera") { keys = sortKeys(sc.camera.keys).map(k => +k.t || 0); color = "orange"; }
    ticks.replaceChildren(keys.map(t => h("button", { class: "botick " + color, style: { left: (100 * t / motion.duration) + "%" }, title: `key at ${t} s`, onclick: () => { ui.t = t; pose(t); } })));
  }
  const timeline = h("div", { class: "botimeline" }, playBtn, h("div", { class: "boslidewrap" }, slider, ticks), timeLabel);

  // ---------------- outline (left)
  const outline = h("div", { class: "bolist" });
  const pickMenu = (title, items, onpick) => {
    const box = h("div", { class: "popmenu bopop" }, h("div", { class: "muted small", style: { padding: "4px 10px" } }, title),
      items.map(([v, label, about]) => h("button", { onclick: () => { box.remove(); onpick(v); } }, h("b", {}, label), about ? h("span", { class: "muted small" }, " " + about) : null)));
    setTimeout(() => document.addEventListener("pointerdown", function off(e) { if (!box.contains(e.target)) { box.remove(); document.removeEventListener("pointerdown", off); } }), 0);
    return box;
  };
  const uniqueName = base => { let n = base, i = 2; while (sc.things.some(t => t.name === n)) n = base + " " + i++; return n; };
  function addSet(type) {
    const at = [r2(orbit.target.x), r2(orbit.target.y), 0];
    change(() => { sc.set.push({ type, name: "", at: type === "street" ? [at[0] - 30, at[1], 0] : at, size: BO.SET_SIZE[type].slice(), turn: 0, color: "" }); ui.sel = { type: "set", i: sc.set.length - 1 }; });
  }
  function addThing(kind) {
    const at = [r2(orbit.target.x), r2(orbit.target.y), 0];
    const name = uniqueName(kind[0].toUpperCase() + kind.slice(1));
    change(() => { sc.things.push({ name, kind, color: "", scale: 1, keys: [{ t: Math.round(ui.t * 10) / 10, at, face: null, pose: "stand" }] }); ui.sel = { type: "thing", i: sc.things.length - 1 }; });
  }
  function drawOutline() {
    const row = (sel, label, sub, icon) => h("button", { class: "borow" + (ui.sel.type === sel.type && ui.sel.i === sel.i ? " on" : ""),
      onclick: () => { ui.sel = sel; rebuild(); drawOutline(); drawInspector(); frameSelection(); } }, h("span", { class: "boicon" }, icon), h("span", {}, label, sub ? h("small", {}, sub) : null));
    const addSetBtn = h("button", { class: "small ghost", onclick: e => e.currentTarget.parentElement.after(pickMenu("Add a set piece (it does not move)", BO.SET_TYPES.map(t => [t, t, BO.SET_ABOUT[t]]), addSet)) }, "+ Add");
    const addThingBtn = h("button", { class: "small ghost", onclick: e => e.currentTarget.parentElement.after(pickMenu("Add a thing (it can move)", BO.KINDS.map(k => [k, k]), addThing)) }, "+ Add");
    outline.replaceChildren(
      row({ type: "scene" }, "Scene", `${sc.sky}, ${sc.ground} · ${b.size}`, "◎"),
      row({ type: "camera" }, "Camera", `${sc.camera.keys.length} key(s) · ${sc.camera.lens || 35} mm`, "▣"),
      h("div", { class: "bohead" }, h("span", {}, "Things that move"), addThingBtn),
      sc.things.length ? sc.things.map((th, i) => row({ type: "thing", i }, th.name, `${th.kind}${th.color ? " · " + th.color : ""} · ${(th.keys || []).length} key(s)`, "●"))
        : h("div", { class: "faint small bonone" }, "People, cars, animals… Add one, then drag it in the view."),
      h("div", { class: "bohead" }, h("span", {}, "The set"), addSetBtn),
      sc.set.length ? sc.set.map((it, i) => row({ type: "set", i }, it.name || it.type, it.name ? it.type : "", "■"))
        : h("div", { class: "faint small bonone" }, "A street, a room, buildings, boxes, trees…"));
  }

  // ---------------- inspector (right)
  const inspector = h("div", { class: "boinspect" });
  const num = (obj, key, o = {}) => h("input", { type: "number", step: o.step || 0.1, value: obj[key] ?? "", placeholder: o.placeholder || "", class: "bonum",
    onchange: e => change(() => { const v = e.target.value === "" ? (o.blank !== undefined ? o.blank : 0) : +e.target.value; obj[key] = v; }) });
  const vec = (obj, key, labels, d) => { obj[key] = xyz(obj[key], d); return h("div", { class: "bovec" }, labels.map((l, i) => h("label", {}, h("span", {}, l),
    h("input", { type: "number", step: 0.1, value: obj[key][i], class: "bonum", onchange: e => change(() => { obj[key] = xyz(obj[key], d); obj[key][i] = +e.target.value || 0; }) })))); };
  const choose = (obj, key, opts, o = {}) => h("select", { onchange: e => change(() => { obj[key] = e.target.value; if (o.after) o.after(e.target.value); }) },
    opts.map(v => { const [val, label] = Array.isArray(v) ? v : [v, v]; return h("option", { value: val, selected: (obj[key] ?? "") === val }, label); }));
  const colorPick = obj => h("div", { class: "bocolor" },
    choose(obj, "color", [["", "(default)"], ...Object.keys(BO.COLORS).filter(c => !["skin", "snow", "grass", "asphalt", "sand", "floor", "water", "tinted glass", "headlight", "taillight"].includes(c)), ...(obj.color && obj.color.startsWith("#") ? [obj.color] : [])]),
    h("input", { type: "color", value: /^#[0-9a-f]{6}$/i.test(obj.color || "") ? obj.color : "#" + mat(obj.color || "grey").color.getHexString(), title: "Any colour", onchange: e => change(() => { obj.color = e.target.value; }) }));
  const fieldRow = (label, control, hint) => h("div", { class: "field" }, h("label", {}, label), control, hint ? h("div", { class: "hint" }, hint) : null);
  function drawInspector() {
    const s = ui.sel;
    if (s.type === "scene") {
      inspector.replaceChildren(h("h3", {}, "Scene"),
        fieldRow("Name", h("input", { value: b.name, onchange: e => { b.name = e.target.value.trim() || b.name; save(); } })),
        fieldRow("Video size", h("select", { onchange: async e => { b.size = e.target.value; await saveNow(); route(); } }, ["1152x640", "640x1152", "1024x1024", "1280x704", "832x480", "480x832"].map(v => h("option", { value: v, selected: v === b.size }, v))), "Use the size of the clip you will make from it."),
        h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Sky"), choose(sc, "sky", BO.SKIES)), h("div", { class: "field" }, h("label", {}, "Ground"), choose(sc, "ground", BO.GROUNDS))),
        h("p", { class: "hint" }, "Click a thing in the view or in the list to change it. Drag in the view to look around (right-drag or Shift-drag to slide, wheel to zoom)."),
        h("div", { class: "field" }, h("label", {}, "Earlier versions"),
          h("button", { class: "small", onclick: showVersions }, "Show earlier versions"),
          h("div", { class: "hint" }, "The studio keeps the scene from before each change in words or from Blender, and every few minutes while you edit."), versionsBox));
    } else if (s.type === "set") {
      const it = sc.set[s.i];
      inspector.replaceChildren(h("h3", {}, "Set piece: " + (it.name || it.type)),
        h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Type"), choose(it, "type", BO.SET_TYPES, { after: t => { it.size = BO.SET_SIZE[t].slice(); } })),
          h("div", { class: "field" }, h("label", {}, "Name"), h("input", { value: it.name || "", placeholder: it.type, onchange: e => change(() => { it.name = e.target.value; }) }))),
        h("div", { class: "hint", style: { marginTop: "-6px", marginBottom: "10px" } }, BO.SET_ABOUT[it.type] || ""),
        fieldRow("Where", vec(it, "at", ["x", "y", "z"]), it.type === "street" ? "The start of the road; it runs along +x." : "The middle of its base. Or drag it in the view."),
        fieldRow(it.type === "street" ? "Length, road width, house height" : "Size x, y, height (m)", vec(it, "size", ["x", "y", "h"], BO.SET_SIZE[it.type])),
        ["street", "room", "city"].includes(it.type) ? null : fieldRow("Turn (degrees)", num(it, "turn", { step: 5 })),
        fieldRow("Colour", colorPick(it)),
        h("div", { class: "row", style: { gap: "6px" } }, h("button", { class: "small", onclick: () => change(() => { sc.set.push(JSON.parse(JSON.stringify({ ...it, at: xyz(it.at).map((v, i) => i < 2 ? v + 2 : v) }))); ui.sel = { type: "set", i: sc.set.length - 1 }; }) }, "Duplicate"),
          h("button", { class: "small danger", onclick: removeSelected }, "Delete")));
    } else if (s.type === "thing") {
      const th = sc.things[s.i]; th.keys = th.keys || [];
      const keys = sortKeys(th.keys);
      inspector.replaceChildren(h("h3", {}, th.name),
        h("div", { class: "row" },
          h("div", { class: "field" }, h("label", {}, "Name"), h("input", { value: th.name, onchange: e => { const n = e.target.value.trim(); if (!n || n === th.name) return; if (sc.things.some(t => t !== th && t.name === n)) { toast("Another thing has that name", true); e.target.value = th.name; return; }
            change(() => { sc.camera.keys.forEach(k => { if (k.follow === th.name) k.follow = n; }); th.name = n; }); } })),
          h("div", { class: "field" }, h("label", {}, "What it is"), choose(th, "kind", BO.KINDS))),
        BO.KIND_ABOUT[th.kind] ? h("div", { class: "hint", style: { marginTop: "-6px", marginBottom: "8px" } }, BO.KIND_ABOUT[th.kind] + ", with see-through windows.") : null,
        h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Colour"), colorPick(th)), h("div", { class: "field fit" }, h("label", {}, "Size ×"), num(th, "scale", { step: 0.1, blank: 1 }))),
        BO.CARS.includes(th.kind) ? fieldRow("Driver", choose(th, "driver", [["", "nobody"], ...Object.keys(BO.COLORS).filter(c => !["skin", "snow", "grass", "asphalt", "sand", "floor", "water", "tinted glass", "headlight", "taillight", "glass"].includes(c)).map(c => [c, "in " + c + " clothes"])]),
          "Someone at the wheel, seen through the windows; moves with the car.") : null,
        h("h4", {}, "Where it is when"),
        h("div", { class: "hint", style: { marginBottom: "6px" } }, "Each key says where it is at a moment. Move the timeline, then drag it in the view: a key is added at that moment. Between keys it moves smoothly; to stop, give two keys at the same place."),
        h("table", { class: "bokeys" }, h("colgroup", {}, [42, 46, 46, 48, null, 44].map(w => h("col", w ? { style: { width: w + "px" } } : {}))),
          h("tr", {}, ["at s", "x", "y", "faces", "pose", ""].map(x => h("th", {}, x))),
          keys.map(k => { k.at = xyz(k.at); return h("tr", { class: Math.abs((+k.t || 0) - ui.t) < 0.05 ? "now" : "" },
            h("td", {}, num(k, "t", { step: 0.5 })), h("td", {}, h("input", { type: "number", step: 0.5, value: k.at[0], class: "bonum", onchange: e => change(() => { k.at[0] = +e.target.value || 0; }) })),
            h("td", {}, h("input", { type: "number", step: 0.5, value: k.at[1], class: "bonum", onchange: e => change(() => { k.at[1] = +e.target.value || 0; }) })),
            h("td", {}, h("input", { type: "number", step: 15, value: k.face ?? "", placeholder: "auto", class: "bonum", title: "Degrees: 0 = +x, 90 = +y. Empty: the way it moves.", onchange: e => change(() => { k.face = e.target.value === "" ? null : +e.target.value; }) })),
            h("td", {}, choose(k, "pose", BO.POSES)),
            h("td", {}, h("button", { class: "small ghost", title: "Go to this moment", onclick: () => { ui.t = +k.t || 0; pose(ui.t); drawInspector(); } }, "◷"),
              keys.length > 1 ? h("button", { class: "small ghost danger", title: "Remove this key", onclick: () => change(() => { th.keys.splice(th.keys.indexOf(k), 1); }) }, "×") : null)); })),
        h("div", { class: "row", style: { gap: "6px", marginTop: "8px" } },
          h("button", { class: "small", onclick: () => change(() => { const p = motion.things[th.name] ? motion.things[th.name].pos(ui.t).map(r2) : [0, 0, 0]; keyAtNow(th.keys, () => ({ at: p, face: null, pose: "walk" })); }) }, `+ Key at ${ui.t.toFixed(1)} s`),
          h("button", { class: "small", onclick: () => change(() => { sc.camera.keys.forEach(k => { k.follow = th.name; }); if (!sc.camera.keys.length) sc.camera.keys.push({ t: 0, at: [xyz(th.keys[0].at)[0] - 6, xyz(th.keys[0].at)[1], 1.6], look_at: [0, 0, 0], follow: th.name, lens: 0, cut: false }); }) }, "Camera follows it"),
          h("button", { class: "small danger", onclick: removeSelected }, "Delete")));
    } else if (s.type === "camera") {
      const cam = sc.camera, keys = sortKeys(cam.keys);
      inspector.replaceChildren(h("h3", {}, "Camera"),
        h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Lens (mm)"), num(cam, "lens", { step: 1, blank: 35 }), h("div", { class: "hint" }, "18 very wide · 35 normal · 85 tight")),
          h("div", { class: "field" }, h("label", {}, "Shake (m)"), num(cam, "shake", { step: 0.01 }), h("div", { class: "hint" }, "0 steady · 0.03 handheld"))),
        h("button", { class: "primary small", style: { width: "100%", margin: "4px 0 12px" }, onclick: () => {
          if (ui.view !== "free") return toast("Switch to the free view, frame the shot there, then press this", true);
          change(() => { const k = keyAtNow(cam.keys, () => ({ at: [0, 0, 0], look_at: [0, 0, 0], follow: "", lens: 0, cut: false })); k.at = [free.position.x, free.position.y, free.position.z].map(r2); k.look_at = [orbit.target.x, orbit.target.y, orbit.target.z].map(r2); k.follow = ""; });
          ui.view = "shot"; drawViewBtns(); } }, `Set the camera to my view (at ${ui.t.toFixed(1)} s)`),
        h("div", { class: "hint", style: { marginBottom: "8px" } }, "Look around in the free view until it shows the shot you want, then press the button above: the camera gets a key there at the time on the timeline. Or drag the orange camera (and its aim, the orange ball) in the view."),
        keys.map((k, n) => { k.at = xyz(k.at, [0, -10, 1.6]); k.look_at = xyz(k.look_at); return h("div", { class: "bocamkey" + (Math.abs((+k.t || 0) - ui.t) < 0.05 ? " now" : "") },
          h("div", { class: "spread" }, h("b", {}, `Key ${n + 1}`), h("span", {},
            h("button", { class: "small ghost", onclick: () => { ui.t = +k.t || 0; pose(ui.t); drawInspector(); } }, "Go to it"),
            keys.length > 1 ? h("button", { class: "small ghost danger", onclick: () => change(() => { cam.keys.splice(cam.keys.indexOf(k), 1); }) }, "×") : null)),
          h("div", { class: "row" }, h("div", { class: "field fit" }, h("label", {}, "At (s)"), num(k, "t", { step: 0.5 })), h("div", { class: "field fit" }, h("label", {}, "Lens"), num(k, "lens", { step: 1, placeholder: "same" })),
            h("div", { class: "field fit", style: { alignSelf: "end" } }, h("label", { class: "check", title: "Jump here (a cut to a new angle) instead of moving here" }, h("input", { type: "checkbox", checked: !!k.cut, onchange: e => change(() => { k.cut = e.target.checked; }) }), " Cut here"))),
          fieldRow("Stands at (z = height; 1.6 is eye level)", vec(k, "at", ["x", "y", "z"], [0, -10, 1.6])),
          fieldRow("Looks at", h("div", {}, choose(k, "follow", [["", "a point"], ...sc.things.map(t => [t.name, "follows " + t.name])]), k.follow ? null : vec(k, "look_at", ["x", "y", "z"])))); }));
    }
  }

  // ---------------- describe it (Claude), render it (Blender), use it
  const ideaBox = h("textarea", { rows: 3, placeholder: "Make the camera circle her slowly / add a tram that crosses at 4 s / it is night and snowing", value: "" });
  const sayBox = h("div", { class: "hint" });
  const askProg = h("div", { hidden: true });
  const askBtn = h("button", { style: { width: "100%", marginTop: "6px" }, onclick: () => ask() }, "Change the scene");
  let asking = false;
  async function ask(running) {
    const joining = running && running.task;
    if (!joining && !ideaBox.value.trim()) return toast("Say what to change", true);
    if (asking) return;
    asking = true; sayBox.className = "hint"; sayBox.textContent = "";
    askBtn.disabled = true;
    if (joining) ideaBox.value = running.idea || "";
    try {
      // the studio saves the new scene itself (also when this page is closed meanwhile); here it is only picked up
      const r = await writeSceneWithProgress({ idea: ideaBox.value, scene: sc, size: b.size, blockout: id }, askProg, joining ? running : null);
      if (!r || !r.scene || typeof r.scene !== "object") throw new Error("Claude sent no scene; the scene is unchanged");
      const nb = await api("/api/blockouts/" + id);
      replaceScene(nb); b.idea = nb.idea; ideaBox.value = "";
      sayBox.textContent = r.say + (r.problem ? " (Problem: " + r.problem + ")" : "") + " Ctrl+Z, or an earlier version under Scene, brings the scene before back.";
      frameAll();
    } catch (e) { sayBox.className = "hint bad"; sayBox.textContent = e.message + " Your words are still in the box."; }
    finally { asking = false; askBtn.disabled = false; }
  }
  const renderBox = h("div", { class: "card borender" });
  function drawRender() {
    const st = ui.state || {}, job = ui.job;
    const running = job && (job.status === "queued" || job.status === "running");
    renderBox.replaceChildren(
      h("h3", { style: { marginTop: 0 } }, "Render it in Blender"),
      st.error ? h("div", { class: "note bad" }, "Fix this first: " + st.error) : h("div", { class: "muted small" }, `${st.seconds || 0} s at ${b.size}. Blender renders it on this computer; about a minute or two.`),
      st.blender === false ? h("div", { class: "note warn" }, "Blender was not found: set its path in ☰ → Machine → Settings.") : null,
      running ? h("div", { class: "note" }, (job.progress && job.progress.text) || "Waiting in the queue…") : null,
      job && job.status === "failed" ? h("div", { class: "note bad" }, job.error) : null,
      h("button", { class: "primary", style: { width: "100%", marginTop: "8px" }, disabled: !!st.error || running || st.blender === false, onclick: async () => {
        await saveNow(); const j = await tryApi(`/api/blockouts/${id}/make`, {}); if (j) { ui.job = j; drawRender(); poll(); } } },
        running ? "Rendering…" : b.video ? (st.current ? "Render again" : "Render the changes") : "Render the blockout"),
      b.video && !st.current && !running ? h("div", { class: "hint" }, "The scene changed since the video below was made.") : null,
      (st.small || []).length ? h("div", { class: "note warn" }, "Too small in the picture: " + st.small.map(([n, w]) => n + " " + w).join("; ") + ". The clip then stops following the blockout; bring the camera closer or use a longer lens.") : null,
      b.video ? [h("video", { src: "/media/" + encodeURI(b.video.replace(/ \[output\]$/, "")) + "?t=" + (b.updated || 0), controls: true, muted: true, loop: true, style: { width: "100%", marginTop: "10px", borderRadius: "8px", background: "#000" } }),
        // only a video of the scene as it is now: an older one has other shapes, cuts and camera than the 3D view shows
        st.current ? h("button", { style: { width: "100%", marginTop: "8px" }, onclick: () => go("video", "form", { start: "blockout", blockout: b.video, blockout_shapes: b.shapes || shapesText(), size: b.size, frames: nearestFrames(st.frames) }) }, "Use in a video →")
          : h("div", { class: "note warn", style: { marginTop: "8px" } }, "This video is older than the scene. Render the changes first: a clip follows the video, not the 3D view."),
        h("div", { class: "hint" }, "Opens the Video form with this blockout. Say there what the shapes really are and what happens.")] : null);
  }
  const shapesText = () => sc.things.map(t => `the ${t.color ? t.color + " " : ""}${t.kind} is ${t.name}`).join("; ");
  const nearestFrames = n => { const opts = [124, 158, 209, 243, 260, 294, 345]; return opts.filter(c => c <= n).pop() || 124; };   // a clip no longer than the blockout
  onJobEnd(async j => { if (ui.job && j.id === ui.job.id) {
    try { const nb = await api("/api/blockouts/" + id); b.video = nb.video; b.asset = nb.asset; b.updated = nb.updated; ui.state = nb.state; ui.job = { ...j }; } catch (e) { /* gone */ }
    if (j.status === "done") toast("The blockout is rendered");
    drawRender(); } });
  const watchJob = setInterval(() => {
    if (!document.body.contains(canvas)) return clearInterval(watchJob);
    if (!ui.job) return;
    const j = (S.state.jobs || []).find(x => x.id === ui.job.id);
    if (j && (j.status !== ui.job.status || JSON.stringify(j.progress) !== JSON.stringify(ui.job.progress))) { ui.job = j; drawRender(); }
  }, 1000);

  // ---------------- Blender: open the scene in its own window; what is sent back from there replaces the scene here
  const blenderNote = h("div", { class: "boblender", hidden: true },
    h("b", {}, "Open in Blender. "),
    "Move, turn and scale things there; insert keys (I) at other frames for new ones. Press ", h("b", {}, "Send to H3 Studio"),
    " in Blender's sidebar (N → H3 Studio) or save with Ctrl+S, and the scene here follows. Poses, kinds and colours stay here. What you change here meanwhile is replaced by what Blender sends (Ctrl+Z brings it back).",
    h("button", { class: "small ghost", onclick: () => { blenderNote.hidden = true; } }, "Hide"));
  async function openBlender() {
    await saveNow();
    if (ui.state && ui.state.error) return toast("Fix the scene first: " + ui.state.error, true);
    const r = await tryApi(`/api/blockouts/${id}/blender`, {});
    if (!r) return;
    ui.blender = true; blenderNote.hidden = false;
    toast("Blender is opening; it takes a few seconds");
  }
  // Changes saved elsewhere (Blender, a change in words that finished, another tab) come in here, so this page never
  // saves an old scene over them. Every 2 s while Blender is open, else every 4 s; not while an edit here waits to be saved.
  let polls = 0;
  const watchBlender = setInterval(async () => {
    if (!document.body.contains(canvas)) return clearInterval(watchBlender);
    if (!ui.blender && ++polls % 2) return;
    if (ui.saving || asking) return;
    let nb; try { nb = await api("/api/blockouts/" + id); } catch (e) { return; }
    if (ui.saving || asking || !(nb.updated > (b.updated || 0) + 0.001)) return;
    const fromBlender = nb.blender_at && nb.blender_at > ui.blenderSeen;
    if (fromBlender) ui.blenderSeen = nb.blender_at;
    b.updated = nb.updated;
    if (JSON.stringify(nb.scene) === snap()) return;
    replaceScene(nb); b.idea = nb.idea; b.name = nb.name;
    toast(fromBlender ? "The scene came back from Blender" : "The scene was changed elsewhere and is shown here now (Ctrl+Z brings back what you had)");
  }, 2000);

  // a scene saved by the studio (from Blender, or an earlier version) replaces the one here; Ctrl+Z brings this one back
  function replaceScene(nb) {
    if (!nb || !nb.scene || typeof nb.scene !== "object") return;
    ui.undo.push(snap()); ui.redo = [];
    for (const k of Object.keys(sc)) delete sc[k];
    Object.assign(sc, nb.scene); sc.set = sc.set || []; sc.things = sc.things || []; sc.camera = sc.camera || { lens: 35, shake: 0, keys: [] }; sc.camera.keys = sc.camera.keys || [];
    if (ui.sel.i !== undefined && !(ui.sel.type === "set" ? sc.set[ui.sel.i] : sc.things[ui.sel.i])) ui.sel = { type: "scene" };
    ui.state = nb.state; b.updated = nb.updated;
    rebuild(); drawOutline(); drawInspector(); drawRender();
  }
  const versionsBox = h("div", {});
  async function showVersions() {
    const vs = await tryApi(`/api/blockouts/${id}/versions`);
    if (!vs) return;
    const when = t => new Date(t * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
    const why = { words: "before a change in words", Blender: "before Blender sent a scene", restore: "before going back", edits: "your edits" };
    versionsBox.replaceChildren(vs.length ? h("div", { class: "boversions" }, vs.map(v => h("div", { class: "spread" },
      h("span", { class: "small" }, h("b", {}, when(v.at)), " · " + (why[v.why] || v.why) + ` · ${v.things} moving, ${v.set} set`),
      h("button", { class: "small", onclick: async () => {
        await saveNow();
        const nb = await tryApi(`/api/blockouts/${id}/versions/${v.id}`, {});
        if (nb) { replaceScene(nb); toast("Back to the version of " + when(v.at) + ". The scene before is kept as a version too."); }
      } }, "Go back to it")))) : h("div", { class: "hint" }, "No earlier versions yet. They are kept as you change the scene."));
  }

  // ---------------- layout
  const viewBtns = h("div", { class: "segs small" });
  function drawViewBtns() {
    viewBtns.replaceChildren(h("button", { class: ui.view === "free" ? "on" : "", onclick: () => { ui.view = "free"; drawViewBtns(); pose(ui.t); } }, "Free view"),
      h("button", { class: ui.view === "shot" ? "on" : "", onclick: () => { ui.view = "shot"; drawViewBtns(); pose(ui.t); } }, "Through the camera"));
  }
  drawViewBtns();
  const nameIn = h("input", { class: "name", value: b.name, "aria-label": "Blockout name", onchange: e => { b.name = e.target.value.trim() || b.name; save(); } });
  root.append(
    h("div", { class: "cvbar" }, h("button", { class: "ghost small", onclick: () => go("blockout") }, "← Blockouts"), nameIn, viewBtns,
      h("button", { class: "ghost small", onclick: frameAll, title: "Show everything" }, "Fit"),
      h("button", { class: "small", onclick: openBlender, title: "Open this scene in Blender's own window to edit it there" }, "Edit in Blender"),
      h("button", { class: "ghost small", onclick: () => restore(ui.undo, ui.redo), title: "Undo (Ctrl+Z)" }, "↶ Undo"),
      h("button", { class: "ghost small", onclick: () => restore(ui.redo, ui.undo), title: "Redo (Ctrl+Shift+Z)" }, "↷ Redo"),
      h("span", { class: "muted small", style: { marginLeft: "auto" } }, "Drag: look around · right-drag: slide · wheel: zoom · drag a thing to move it · Space: play")),
    h("div", { class: "bo" },
      h("aside", { class: "boleft" }, outline),
      h("div", { class: "bocenter" }, blenderNote, viewBox, timeline),
      h("aside", { class: "boright" }, inspector,
        h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Change it in words"),
          h("div", { class: "hint", style: { marginBottom: "6px" } }, "Claude Code on this computer changes the scene; only the words and the scene are sent."),
          ideaBox, askBtn, askProg, sayBox),
        renderBox)));
  rebuild(); drawOutline(); drawInspector(); drawRender();
  resize(); ro.observe(viewBox); startView();
  requestAnimationFrame(frame);
  if (b.write && !b.write.done) ask(b.write);            // a change in words still running (the page was reloaded)
}
