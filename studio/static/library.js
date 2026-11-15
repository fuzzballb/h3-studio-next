"use strict";
// The Library: everything made here or brought in. Kinds, favourites, uploads and folders on the left; search, sort
// and a selection bar for many files at once. Deleting moves a file to the trash; only emptying the trash erases.

ROOMS.library = { title: "Library", draw(root) {
  const pend = S.pending || {}; S.pending = null;
  const st = Object.assign({ q: "", view: "all", sort: "newest", sel: new Map() }, ROOMS.library.keep || {}, { sel: new Map() });
  ROOMS.library.keep = st;
  const side = h("div", { class: "libside" }), grid = h("div", { class: "tiles" }), bar = h("div", {}), title = h("h2", { style: { margin: 0 } });
  let sum = null, items = [];
  const VIEWS = [["all", "Everything", s => s.all], ["k:image", "Pictures", s => s.kinds.image], ["k:clip", "Clips", s => s.kinds.clip], ["k:film", "Films", s => s.kinds.film],
    ["k:sheet", "Sheets", s => s.kinds.sheet], ["k:audio", "Sound", s => s.kinds.audio], ["k:export", "Exports", s => s.kinds.export],
    ["fav", "Favourites", s => s.favorites], ["up", "Uploads", s => s.uploads]];
  const viewName = () => { const v = VIEWS.find(x => x[0] === st.view); if (v) return v[1]; if (st.view === "trash") return "Trash";
    const f = sum && sum.folders.find(x => "f:" + x.id === st.view); return f ? f.name : "Library"; };
  function query() {
    const p = new URLSearchParams({ q: st.q, sort: st.sort, limit: "600" });
    if (st.view.startsWith("k:")) p.set("kind", st.view.slice(2));
    if (st.view === "fav") p.set("favorite", "1");
    if (st.view === "up") p.set("source", "upload");
    if (st.view === "trash") p.set("trashed", "1");
    if (st.view.startsWith("f:")) p.set("folder", st.view.slice(2));
    return p.toString();
  }
  async function loadSum() { sum = await tryApi("/api/library/summary"); drawSide(); }
  function drawSide() {
    if (!sum) return;
    const item = (id, label, n, extra) => h("button", { class: "item" + (st.view === id ? " on" : ""), onclick: () => { st.view = id; st.sel.clear(); drawSide(); load(); } },
      h("span", {}, label), extra || h("span", { class: "n" }, n ?? ""));
    side.replaceChildren(
      VIEWS.map(([id, label, n]) => item(id, label, n(sum))),
      h("div", { class: "lbl" }, "Folders", h("button", { class: "ghost small", "aria-label": "New folder", title: "New folder", onclick: newFolder }, "+")),
      sum.folders.length ? sum.folders.map(f => h("div", { style: { display: "flex", alignItems: "center" } }, item("f:" + f.id, "▸ " + f.name, f.count),
        st.view === "f:" + f.id ? h("button", { class: "ghost small", title: "Rename or delete", "aria-label": "Folder options", onclick: () => folderMenu(f) }, "⋯") : null))
        : h("div", { class: "faint small", style: { padding: "2px 10px" } }, "No folders yet."),
      h("div", { class: "lbl" }, "Bin"),
      item("trash", "Trash", sum.trash),
      h("div", { class: "meter" }, `${sum.all} files · ${(sum.bytes / 2 ** 30).toFixed(1)} GB`, h("div", { class: "faint", style: { marginTop: "3px" } }, "Files live in ComfyUI's output folder.")));
  }
  async function newFolder() {
    const o = { name: "" };
    modal(h("div", {}, h("h2", {}, "New folder"), field("Name", text(o, "name", { placeholder: "Mood board for the jetty" })),
      h("div", { class: "row", style: { gap: "6px" } }, h("button", { class: "primary", onclick: async () => { const f = await tryApi("/api/folders", { name: o.name }); if (f) { closeModal(); toast("Folder made"); await loadSum(); } } }, "Make it"),
        h("button", { onclick: closeModal }, "Cancel"))), true);
  }
  function folderMenu(f) {
    const o = { name: f.name };
    modal(h("div", {}, h("h2", {}, "Folder"), field("Name", text(o, "name")),
      h("div", { class: "row", style: { gap: "6px" } },
        h("button", { class: "primary", onclick: async () => { if (await tryApi("/api/folders/" + f.id, { name: o.name }, "PATCH")) { closeModal(); loadSum(); } } }, "Rename"),
        h("button", { class: "danger", onclick: async () => { if (await tryApi("/api/folders/" + f.id, undefined, "DELETE")) { closeModal(); toast("Folder deleted; its files are still in the Library"); st.view = "all"; loadSum(); load(); } } }, "Delete the folder"),
        h("button", { onclick: closeModal }, "Cancel")), h("p", { class: "muted small", style: { marginTop: "10px" } }, "Deleting a folder keeps its files.")), true);
  }
  async function bulk(action, folder) {
    const ids = [...st.sel.keys()];
    const r = await tryApi("/api/library/bulk", { ids, action, folder: folder || "" });
    if (r) { toast(action === "move" ? (folder ? "Moved to the folder" : "Taken out of the folder") : action === "favorite" ? "Added to favourites" : "Taken out of favourites"); st.sel.clear(); load(); loadSum(); }
  }
  function drawBar() {
    const n = st.sel.size, its = [...st.sel.values()];
    const clipsSel = its.filter(a => ["clip", "film", "export"].includes(a.kind));
    const trash = st.view === "trash";
    bar.replaceChildren(n ? h("div", { class: "selbar" }, h("b", {}, n + " selected"),
      trash ? h("button", { class: "small", onclick: async () => { if (await tryApi("/api/library/restore", { ids: its.map(a => a.id) })) { toast("Put back"); st.sel.clear(); load(); loadSum(); } } }, "Put back")
        : [h("button", { class: "small", onclick: () => bulk("favorite") }, "★ Favourite"), h("button", { class: "small", onclick: () => bulk("unfavorite") }, "☆ Unfavourite"),
           sum && (sum.folders.length || st.view.startsWith("f:")) ? chipMenu("Move to", "", [...sum.folders.map(f => [f.id, f.name]), ["", "(no folder)"]], v => bulk("move", v), { title: "Folder" }) : null,
           clipsSel.length ? h("button", { class: "small", onclick: () => addToTimeline(clipsSel.map(a => a.id)) }, "+ Timeline") : null,
           clipsSel.length > 1 ? h("button", { class: "small", onclick: () => go("timeline", "", { roughcut: clipsSel.map(a => a.id) }) }, "Cut to a song") : null,
           its.length && its.every(isPic) ? h("button", { class: "small", onclick: async () => { const bd = await tryApi("/api/canvas", { name: "From the Library" }); if (!bd) return;
             await tryApi("/api/canvas/" + bd.id, { items: its.map((a, i) => ({ type: "asset", asset: a.id, x: (i % 4) * 300, y: Math.floor(i / 4) * 220, w: 280, h: a.width && a.height ? Math.round(280 * a.height / a.width) : 158 })) }, "PUT"); go("canvas", bd.id); } }, "To a board") : null,
           h("button", { class: "small danger", onclick: async () => { const r = await tryApi("/api/library/trash", { ids: its.map(a => a.id) }); if (!r) return;
             toast(`${r.moved.length} moved to the trash` + (r.kept.length ? `, ${r.kept.length} kept (${r.kept[0][1]})` : ""), r.kept.length > 0 && !r.moved.length); st.sel.clear(); load(); loadSum(); } }, "Delete")],
      h("button", { class: "small ghost", style: { marginLeft: "auto" }, onclick: () => { st.sel.clear(); drawBar(); draw(); } }, "Clear")) : null);
  }
  function tile(a) {
    const trash = st.view === "trash";
    const t = assetTile(a, { selected: st.sel.has(a.id), onselect: x => { st.sel.has(x.id) ? st.sel.delete(x.id) : st.sel.set(x.id, x); drawBar(); draw(); },
      actions: trash ? () => [h("button", { class: "small", onclick: async () => { if (await tryApi("/api/library/restore", { ids: [a.id] })) { toast("Put back"); load(); loadSum(); } } }, "Put back")]
        : x => [canRecreate(x) ? h("button", { class: "small", onclick: e => { e.stopPropagation(); recreate(x); } }, "↻ Recreate") : null, ...assetActions(x)] });
    if (!trash) {
      const fav = h("button", { class: "fav" + (a.favorite ? " on" : ""), "aria-label": "Favourite", "aria-pressed": a.favorite ? "true" : "false", onclick: async e => { e.stopPropagation(); await toggleFav(a, fav); fav.classList.toggle("on", !!a.favorite); fav.textContent = a.favorite ? "★" : "☆"; loadSum(); } }, a.favorite ? "★" : "☆");
      t.append(fav);
    }
    return t;
  }
  function draw() {
    title.textContent = viewName();
    grid.replaceChildren(items.length ? items.map(tile) : h("div", { class: "empty", style: { gridColumn: "1 / -1" } },
      st.view === "trash" ? "The trash is empty." : st.q ? "Nothing matches." : st.view === "fav" ? "No favourites yet: press ☆ on a file." : st.view.startsWith("f:") ? "This folder is empty: select files and use Move to." : "Nothing here yet."));
  }
  async function load() {
    const r = await tryApi("/api/library?" + query());
    if (!r) return;
    items = r.items;
    drawBar(); draw();
    trashNote.replaceChildren(st.view === "trash" && r.trash.files ? h("button", { class: "small danger", onclick: async () => {
      if (!confirm(`Erase ${r.trash.files} file(s) for good? This cannot be undone.`)) return;
      if (await tryApi("/api/library/empty-trash", { confirm: "erase" })) { toast("The trash is empty"); load(); loadSum(); } } }, `Empty the trash (${(r.trash.bytes / 2 ** 20).toFixed(0)} MB)`) : null);
    if (pend.action && items.length) { toast({ extend: "Open a clip, then Extend.", upscale: "Open a clip or film, then Upscale.", captions: "Open a clip, then Captions.", location: "Open a clip, then Location sound." }[pend.action] || ""); pend.action = ""; }
  }
  const trashNote = h("span", {});
  onJobEnd(() => { load(); loadSum(); });
  const imp = { path: "" };
  const search = h("input", { type: "search", placeholder: "Search names and prompts…", "aria-label": "Search the Library", value: st.q, style: { width: "280px" } });
  search.addEventListener("input", debounce(() => { st.q = search.value; load(); }, 250));
  const sortSel = select(st, "sort", [["newest", "Newest"], ["oldest", "Oldest"], ["largest", "Largest"], ["smallest", "Smallest"], ["name", "Name A→Z"]], { onchange: () => load() });
  sortSel.style.width = "auto";
  root.append(h("div", { class: "section-head" }, h("div", {}, h("h1", { class: "display", style: { fontSize: "34px" } }, "Library"),
      h("p", { class: "muted", style: { margin: "6px 0 0" } }, "Everything made here or brought in. Search looks in names and in the prompts the files were made from.")),
    h("div", { class: "row", style: { alignItems: "center", gap: "8px" } },
      h("button", { onclick: async () => { const files = await chooseFiles(ACCEPT.image + "," + ACCEPT.audio + "," + ACCEPT.clip, true); if (!files.length) return; try { await upload(files); toast("Uploaded"); load(); loadSum(); } catch (e) { toast(e.message, true); } } }, "Upload…"),
      h("button", { onclick: () => modal(h("div", {}, h("h2", {}, "Bring in a file that is already on this computer"),
        field("A path under ComfyUI's output or input folder", text(imp, "path", { placeholder: "long_video/my_project/my_project_full.mp4" }), "The file stays where it is (a file from input/ is copied to the studio's uploads)."),
        h("div", { class: "row", style: { gap: "6px" } }, h("button", { class: "primary", onclick: async () => { if (await tryApi("/api/library/import", { path: imp.path })) { closeModal(); toast("In the Library"); load(); loadSum(); } } }, "Bring it in"), h("button", { onclick: closeModal }, "Cancel"))), true) }, "From disk…"))),
    h("div", { class: "libwrap" }, side, h("div", {},
      h("div", { class: "spread", style: { marginBottom: "12px" } }, title, h("div", { class: "row", style: { alignItems: "center", gap: "8px" } }, trashNote, search, sortSel)),
      bar, grid)));
  loadSum(); load();
} };
