"use strict";
// Canvas: open boards for laying out pictures, clips and notes. Drag to move, the corner to resize, drag the
// background to pan, the wheel to zoom. Boards are kept by the studio (canvas/<id>.json), not in the browser.

ROOMS.canvas = { title: "Canvas", full: arg => !!arg, async draw(root, arg) {
  if (!arg) return drawBoards(root);
  let b;
  try { b = await api("/api/canvas/" + arg); } catch (e) { toast(e.message, true); return go("canvas"); }
  const assets = b.assets || {};
  const view = Object.assign({ x: 0, y: 0, zoom: 1 }, b.view || {});
  let sel = null;
  const world = h("div", { class: "world" });
  const cv = h("div", { class: "cv", tabindex: "0", "aria-label": "The board" }, world);
  const zoomLabel = h("span", {}, "100%");
  const save = debounce(async () => { await tryApi("/api/canvas/" + b.id, { name: b.name, items: b.items, view }, "PUT"); }, 600);
  const nameIn = h("input", { class: "name", value: b.name, "aria-label": "Board name" });
  nameIn.addEventListener("input", () => { b.name = nameIn.value; save(); });

  function applyView() { world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`; zoomLabel.textContent = Math.round(view.zoom * 100) + "%";
    cv.style.backgroundSize = 24 * view.zoom + "px " + 24 * view.zoom + "px"; cv.style.backgroundPosition = view.x + "px " + view.y + "px"; }
  function center() { const r = cv.getBoundingClientRect(); return { x: (r.width / 2 - view.x) / view.zoom, y: (r.height / 2 - view.y) / view.zoom }; }
  function itemEl(it) {
    let inner;
    if (it.type === "note") {
      inner = null;
    } else {
      const a = assets[it.asset];
      inner = !a ? h("div", { class: "missing" }, "This file is gone") : isMov(a) ? h("video", { src: a.url, muted: true, loop: true, autoplay: true, playsinline: true, poster: a.thumb })
        : h("img", { src: a.kind === "image" || a.kind === "sheet" ? a.url : a.thumb, alt: a.name, draggable: "false" });
    }
    const el = h("div", { class: "it" + (it.type === "note" ? " note " + (it.color || "yellow") : "") + (sel === it.id ? " sel" : ""), "data-id": it.id,
      style: { left: it.x + "px", top: it.y + "px", width: it.w + "px", height: it.h + "px" } }, inner, h("div", { class: "rz", "data-rz": "1" }));
    if (it.type === "note") {
      const t = h("div", { style: { width: "100%", height: "100%", outline: "none" } });
      t.textContent = it.text || "";
      el.prepend(t);
      el.addEventListener("dblclick", () => { t.contentEditable = "true"; t.focus(); el.style.cursor = "text"; });
      t.addEventListener("input", () => { it.text = t.innerText; save(); });
      t.addEventListener("blur", () => { t.contentEditable = "false"; el.style.cursor = ""; });
    } else el.addEventListener("dblclick", () => { if (assets[it.asset]) openAsset(it.asset); });
    return el;
  }
  function draw() { world.replaceChildren(b.items.map(itemEl)); applyView(); }
  function add(it) { it.id = Math.random().toString(36).slice(2, 10); b.items.push(it); sel = it.id; draw(); save(); }
  async function addAsset(kind) {
    const got = await pickAsset(kind, { multiple: true, title: kind === "image" ? "Pictures for the board" : "Clips for the board" });
    if (!got || !got.length) return;
    const c = center();
    got.forEach((a, i) => {
      assets[a.id] = a;
      const w = 280, hh = a.width && a.height ? Math.round(w * a.height / a.width) : 158;
      add({ type: "asset", asset: a.id, x: c.x - w / 2 + i * 30, y: c.y - hh / 2 + i * 30, w, h: hh });
    });
  }
  function addNote(color) { const c = center(); add({ type: "note", text: "", color: color || "yellow", x: c.x - 110, y: c.y - 70, w: 220, h: 140 }); }
  function remove() { if (!sel) return; b.items = b.items.filter(i => i.id !== sel); sel = null; draw(); save(); }

  // pointer: move an item, resize it, or pan the board
  let drag = null;
  cv.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    const el = e.target.closest(".it");
    if (el && el.querySelector("[contenteditable=true]")) return;
    cv.focus();
    if (el) {
      const it = b.items.find(i => i.id === el.dataset.id);
      if (sel !== it.id) { sel = it.id; world.querySelectorAll(".it").forEach(x => x.classList.toggle("sel", x.dataset.id === sel)); }
      drag = { mode: e.target.dataset.rz ? "size" : "move", it, el, x: e.clientX, y: e.clientY, ox: it.x, oy: it.y, ow: it.w, oh: it.h, ratio: it.type === "asset" ? it.h / it.w : 0 };
    } else {
      sel = null; world.querySelectorAll(".it.sel").forEach(x => x.classList.remove("sel"));
      drag = { mode: "pan", x: e.clientX, y: e.clientY, ox: view.x, oy: view.y };
      cv.classList.add("panning");
    }
    cv.setPointerCapture(e.pointerId);
  });
  cv.addEventListener("pointermove", e => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (drag.mode === "pan") { view.x = drag.ox + dx; view.y = drag.oy + dy; applyView(); return; }
    const it = drag.it;
    if (drag.mode === "move") { it.x = Math.round(drag.ox + dx / view.zoom); it.y = Math.round(drag.oy + dy / view.zoom); }
    else { it.w = Math.max(60, Math.round(drag.ow + dx / view.zoom)); it.h = drag.ratio ? Math.round(it.w * drag.ratio) : Math.max(40, Math.round(drag.oh + dy / view.zoom)); }
    Object.assign(drag.el.style, { left: it.x + "px", top: it.y + "px", width: it.w + "px", height: it.h + "px" });
  });
  const end = () => { if (!drag) return; cv.classList.remove("panning"); drag = null; save(); };
  cv.addEventListener("pointerup", end); cv.addEventListener("pointercancel", end);
  cv.addEventListener("wheel", e => {
    e.preventDefault();
    const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    const z = Math.min(4, Math.max(0.1, view.zoom * Math.exp(-e.deltaY * 0.0015)));
    view.x = mx - (mx - view.x) * z / view.zoom; view.y = my - (my - view.y) * z / view.zoom; view.zoom = z;
    applyView(); save();
  }, { passive: false });
  cv.addEventListener("keydown", e => {
    if (e.target !== cv) return;
    if ((e.key === "Delete" || e.key === "Backspace") && sel) { e.preventDefault(); remove(); }
  });
  cv.addEventListener("dragover", e => e.preventDefault());
  cv.addEventListener("drop", async e => {
    e.preventDefault();
    const files = [...(e.dataTransfer.files || [])];
    if (!files.length) return;
    try {
      const up = await upload(files);
      const r = cv.getBoundingClientRect();
      up.forEach((a, i) => { assets[a.id] = a; const w = 280, hh = a.width && a.height ? Math.round(w * a.height / a.width) : 158;
        add({ type: "asset", asset: a.id, x: (e.clientX - r.left - view.x) / view.zoom + i * 30, y: (e.clientY - r.top - view.y) / view.zoom + i * 30, w, h: hh }); });
    } catch (err) { toast(err.message, true); }
  });
  const zoomBy = f => { const r = cv.getBoundingClientRect(); const mx = r.width / 2, my = r.height / 2; const z = Math.min(4, Math.max(0.1, view.zoom * f));
    view.x = mx - (mx - view.x) * z / view.zoom; view.y = my - (my - view.y) * z / view.zoom; view.zoom = z; applyView(); save(); };
  const fit = () => {
    if (!b.items.length) { Object.assign(view, { x: 0, y: 0, zoom: 1 }); applyView(); return; }
    const r = cv.getBoundingClientRect();
    const x0 = Math.min(...b.items.map(i => i.x)), y0 = Math.min(...b.items.map(i => i.y)), x1 = Math.max(...b.items.map(i => i.x + i.w)), y1 = Math.max(...b.items.map(i => i.y + i.h));
    const z = Math.min(2, Math.max(0.1, Math.min((r.width - 80) / (x1 - x0), (r.height - 140) / (y1 - y0))));
    Object.assign(view, { zoom: z, x: (r.width - (x1 - x0) * z) / 2 - x0 * z, y: (r.height - 60 - (y1 - y0) * z) / 2 - y0 * z }); applyView(); save();
  };
  root.append(
    h("div", { class: "cvbar" }, h("button", { class: "ghost small", onclick: () => go("canvas") }, "← Boards"), nameIn,
      h("span", { class: "muted small", style: { marginLeft: "auto" } }, "Drag to move · corner to resize · wheel to zoom · double-click a note to write · Delete removes")),
    h("div", { style: { position: "relative", flex: 1, minHeight: 0, display: "flex" } }, cv,
      h("div", { class: "cvtools" },
        h("button", { class: "small", onclick: () => addAsset("image") }, "+ Picture"), h("button", { class: "small", onclick: () => addAsset("clip") }, "+ Clip"),
        h("button", { class: "small", onclick: () => addNote("yellow") }, "+ Note"), h("button", { class: "small", onclick: () => addNote("lime") }, "+ Lime note"),
        h("button", { class: "small danger", onclick: remove, title: "Remove the selected item from the board (the file stays in the Library)" }, "Remove")),
      h("div", { class: "cvzoom" }, h("button", { class: "ghost small", "aria-label": "Zoom out", onclick: () => zoomBy(1 / 1.25) }, "−"), zoomLabel,
        h("button", { class: "ghost small", "aria-label": "Zoom in", onclick: () => zoomBy(1.25) }, "+"), h("button", { class: "ghost small", onclick: fit }, "Fit"))));
  draw();
  if (b.items.length && !b.view) setTimeout(fit, 0);          // a board made elsewhere (the Library's "To a board"): show it all
  cv.focus();
} };

async function drawBoards(root) {
  const grid = h("div", { class: "boards" });
  root.append(h("div", { class: "section-head" }, h("div", {}, h("h1", { class: "display", style: { fontSize: "34px" } }, "Canvas"),
    h("p", { class: "muted", style: { margin: "6px 0 0" } }, "Open boards for laying out pictures, clips and notes: a mood board, a storyboard wall, a cast line-up.")),
    h("button", { class: "primary", onclick: async () => { const c = await tryApi("/api/canvas", { name: "" }); if (c) go("canvas", c.id); } }, "+ New board")), grid);
  const list = (await tryApi("/api/canvas")) || [];
  const thumbs = {};
  await Promise.all([...new Set(list.flatMap(b => b.preview))].map(id => api("/api/library/" + id).then(a => { thumbs[id] = a.thumb; }).catch(() => {})));
  grid.replaceChildren(
    h("button", { class: "boardcard new", onclick: async () => { const c = await tryApi("/api/canvas", { name: "" }); if (c) go("canvas", c.id); } }, "+ New board"),
    list.map(bd => h("div", { style: { position: "relative" } }, h("button", { class: "boardcard", style: { width: "100%" }, onclick: () => go("canvas", bd.id) },
      h("div", { class: "prev" }, [0, 1, 2, 3].map(i => h("div", { style: bd.preview[i] && thumbs[bd.preview[i]] ? { backgroundImage: `url("${thumbs[bd.preview[i]]}")` } : {} }))),
      h("div", { class: "info" }, h("b", {}, bd.name), h("span", {}, `${bd.items} item(s) · ${ago(bd.updated)}`))),
      h("button", { class: "small ghost danger", style: { position: "absolute", bottom: "10px", right: "10px" }, onclick: async () => {
        if (!confirm(`Delete the board “${bd.name}”? The files on it stay in the Library.`)) return;
        if (await tryApi("/api/canvas/" + bd.id, undefined, "DELETE")) route(); } }, "Delete"))));
}
