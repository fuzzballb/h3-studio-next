"use strict";
// The Library: everything made here or brought in, searchable by its name and prompt.

ROOMS.library = { title: "Library", draw(root) {
  const pend = S.pending || {}; S.pending = null;
  const st = { q: "", kind: "", trashed: false, sel: new Map() };
  const grid = h("div", { class: "tiles" }), bar = h("div", {}), trashNote = h("span", { class: "muted small" });
  const kinds = [["", "Everything"], ["clip", "Clips"], ["film", "Films"], ["image", "Pictures"], ["sheet", "Sheets"], ["audio", "Sound"], ["export", "Exports"]];
  const chips = h("div", { class: "choice" });
  function drawChips() {
    chips.replaceChildren(kinds.map(([k, label]) => h("button", { class: "small" + (st.kind === k && !st.trashed ? " on" : ""), onclick: () => { st.kind = k; st.trashed = false; drawChips(); load(); } }, label)),
      h("button", { class: "small" + (st.trashed ? " on" : ""), onclick: () => { st.trashed = !st.trashed; drawChips(); load(); } }, "Trash"));
  }
  function drawBar() {
    const n = st.sel.size, items = [...st.sel.values()];
    const clipsSel = items.filter(a => ["clip", "film", "export"].includes(a.kind));
    bar.replaceChildren(n ? h("div", { class: "card", style: { position: "sticky", top: 0, zIndex: 3 } }, h("div", { class: "row", style: { gap: "6px", alignItems: "center" } },
      h("b", { class: "fit" }, n + " selected"),
      st.trashed ? h("button", { class: "small", onclick: async () => { if (await tryApi("/api/library/restore", { ids: items.map(a => a.id) })) { toast("Put back"); st.sel.clear(); load(); } } }, "Put back")
        : [clipsSel.length ? h("button", { class: "small", onclick: () => addToTimeline(clipsSel.map(a => a.id)) }, "+ Timeline") : null,
           clipsSel.length > 1 ? h("button", { class: "small", onclick: () => go("timeline", "", { roughcut: clipsSel.map(a => a.id) }) }, "Cut these to a song") : null,
           h("button", { class: "small danger", onclick: async () => { const r = await tryApi("/api/library/trash", { ids: items.map(a => a.id) }); if (!r) return;
             toast(`${r.moved.length} moved to the trash` + (r.kept.length ? `, ${r.kept.length} kept (${r.kept[0][1]})` : ""), r.kept.length > 0 && !r.moved.length); st.sel.clear(); load(); } }, "Delete")],
      h("button", { class: "small ghost", onclick: () => { st.sel.clear(); drawBar(); draw(); } }, "Clear the selection"))) : null);
  }
  let items = [];
  function draw() {
    grid.replaceChildren(items.length ? items.map(a => assetTile(a, { selected: st.sel.has(a.id), onselect: x => { st.sel.has(x.id) ? st.sel.delete(x.id) : st.sel.set(x.id, x); drawBar(); draw(); },
      actions: st.trashed ? () => [h("button", { class: "small", onclick: async () => { if (await tryApi("/api/library/restore", { ids: [a.id] })) { toast("Put back"); load(); } } }, "Put back")] : x => assetActions(x) }))
      : h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, st.trashed ? "The trash is empty." : st.q ? "Nothing matches." : "Nothing here yet."));
  }
  async function load() {
    const r = await tryApi(`/api/library?q=${encodeURIComponent(st.q)}&kind=${st.kind}&trashed=${st.trashed ? 1 : 0}`);
    if (!r) return;
    items = r.items;
    trashNote.replaceChildren(r.trash.files ? h("span", {}, `Trash: ${r.trash.files} file(s), ${(r.trash.bytes / 2 ** 20).toFixed(0)} MB `,
      h("button", { class: "small ghost danger", onclick: async () => { if (!confirm(`Erase ${r.trash.files} file(s) for good? This cannot be undone.`)) return; if (await tryApi("/api/library/empty-trash", { confirm: "erase" })) { toast("The trash is empty"); load(); } } }, "Empty it")) : "");
    drawBar(); draw();
    if (pend.action && items.length) { toast({ extend: "Open a clip, then Extend.", upscale: "Open a clip or film, then Upscale.", captions: "Open a clip, then Captions.", location: "Open a clip, then Location sound." }[pend.action] || ""); pend.action = ""; }
  }
  onJobEnd(() => load());
  const imp = { path: "" };
  root.append(head("Library", "Everything made here or brought in. Search looks in names and in the prompts the files were made from. Deleting moves a file to the trash; only emptying the trash erases."),
    h("div", { class: "row" },
      h("div", { class: "field" }, (() => { const i = h("input", { type: "search", placeholder: "Search: a name, or words of the prompt…", "aria-label": "Search the Library" }); i.addEventListener("input", debounce(() => { st.q = i.value; load(); }, 250)); return i; })()),
      h("div", { class: "field fit" }, h("button", { onclick: async () => { const files = await chooseFiles(ACCEPT.image + "," + ACCEPT.audio + "," + ACCEPT.clip, true); if (!files.length) return; try { await upload(files); toast("Uploaded"); load(); } catch (e) { toast(e.message, true); } } }, "Upload…")),
      h("div", { class: "field fit" }, h("button", { onclick: () => modal(h("div", {}, h("h2", {}, "Bring in a file that is already on this computer"),
        field("A path under ComfyUI's output or input folder", text(imp, "path", { placeholder: "long_video/my_project/my_project_full.mp4" }), "The file stays where it is (a file from input/ is copied to the studio's uploads)."),
        h("div", { class: "row", style: { gap: "6px" } }, h("button", { class: "primary", onclick: async () => { if (await tryApi("/api/library/import", { path: imp.path })) { closeModal(); toast("In the Library"); load(); } } }, "Bring it in"), h("button", { onclick: closeModal }, "Cancel"))), true) }, "From disk…"))),
    h("div", { class: "spread" }, chips, trashNote), bar, grid);
  drawChips(); load();
} };
