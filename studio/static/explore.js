"use strict";
// Explore: the home page. The studios as big cards, the newer tools as tiles, the films in progress, and a feed of
// everything made here. Every post keeps the settings it was made with, so Recreate opens them again.

// ---------------------------------------------------------------- shared by the feed, the composers and the Library
const isPic = a => a.kind === "image" || a.kind === "sheet";
const isMov = a => a.kind === "clip" || a.kind === "film" || a.kind === "export";

// Open the page a file was made on, with its settings filled in.
function recreate(a) {
  const form = a.form || {};
  if (isPic(a)) return go("picture", "", { recreate: Object.keys(form).length ? form : { prompt: a.prompt || "" } });
  if (a.surface === "shorts" && form.short) return go("shorts", "", { plan: form.short, size: form.size });
  if (a.surface === "remix") return go("remix", "", { form });
  if (Object.keys(form).length) return go("video", "", { recreate: form });
  if (a.film && !a.quick) return go("films", a.film);
  toast("This file has no saved settings to make it again", true);
}
const canRecreate = a => isPic(a) ? !!(a.form || a.prompt) : !!(a.form && Object.keys(a.form).length) || (a.film && !a.quick);

async function toggleFav(a, btn) {
  const r = await tryApi("/api/library/" + a.id, { favorite: !a.favorite }, "PATCH");
  if (!r) return;
  a.favorite = r.favorite;
  if (btn) { btn.classList.toggle("on", !!r.favorite); btn.textContent = r.favorite ? "★" : "☆"; btn.setAttribute("aria-pressed", r.favorite ? "true" : "false"); }
}

// One post: the picture (a clip plays while the pointer is on it), and on hover its prompt and what to do with it.
function post(a, o = {}) {
  const el = h("div", { class: "post", tabindex: "0", role: "button", "aria-label": a.name, onclick: () => (o.onopen || openAsset)(a.id),
    onkeydown: e => { if (e.key === "Enter") (o.onopen || openAsset)(a.id); } });
  const img = h("img", { src: a.thumb, alt: "", loading: "lazy", style: a.width && a.height ? { aspectRatio: a.width + " / " + a.height } : {} });
  el.append(img);
  if (isMov(a)) {
    let v = null;
    el.addEventListener("mouseenter", () => { if (v) return; v = h("video", { src: a.url, muted: true, loop: true, playsinline: true, preload: "auto",
      style: { position: "absolute", inset: "0", width: "100%", height: "100%", objectFit: "cover" } }); v.muted = true; el.insertBefore(v, img.nextSibling); v.play().catch(() => {}); });
    el.addEventListener("mouseleave", () => { if (v) { v.remove(); v = null; } });
    el.append(h("span", { class: "badge2" }, "▶ " + (a.duration ? secs(a.duration) : a.kind)));
  } else if (a.kind === "sheet") el.append(h("span", { class: "badge2" }, "sheet"));
  const stop = fn => e => { e.stopPropagation(); fn(e); };
  const fav = h("button", { class: "favbtn" + (a.favorite ? " on" : ""), "aria-label": "Favourite", "aria-pressed": a.favorite ? "true" : "false", title: "Favourite",
    onclick: stop(() => toggleFav(a, fav)) }, a.favorite ? "★" : "☆");
  const acts = [];
  if (canRecreate(a)) acts.push(h("button", { class: "small white", onclick: stop(() => recreate(a)) }, "↻ Recreate"));
  if (isPic(a)) {
    acts.push(h("button", { class: "small", onclick: stop(() => go("remix", "", { asset: a })) }, "Remix"));
    acts.push(h("button", { class: "small", onclick: stop(() => go("picture", "", { attach: [{ ref: a.ref, thumb: a.thumb }] })) }, "Edit"));
  } else if (a.quick && a.film) acts.push(h("button", { class: "small", onclick: stop(() => go("video", "clip/" + a.film)) }, "Extend"));
  if (o.extra) acts.push(...o.extra(a));
  el.append(fav, h("div", { class: "ov" }, a.prompt ? h("div", { class: "p" }, a.prompt) : h("div", { class: "p" }, a.name), h("div", { class: "acts" }, acts)));
  return el;
}

// ---------------------------------------------------------------- Explore
ROOMS.home = { title: "Explore", draw(root) {
  const st = { filter: "all" };
  const heroes = h("div", { class: "heroes" });
  const filmsBox = h("div", {});
  const feed = h("div", { class: "feed" });
  const status = h("div", { class: "pill" });
  const filters = h("div", { class: "filters" });
  const HERO = [["picture", "H3 Image", "Stills with Qwen-Image: scouts, faces, places, products.", "image,sheet"],
    ["video", "H3 Video", "Picture and sound together with MiniMax H3, up to 15 s a part.", "clip"],
    ["films", "H3 Films", "A story in shots: write, block out, render, approve, deliver.", "film"]];
  const FEATURES = [["writer", "✎", "Writer", "Tell it a small story; it writes the film.", ""],
    ["remix", "⟳", "Remix", "One picture in, as many moving takes as you like.", "New"],
    ["shorts", "▯", "Shorts", "One idea becomes a vertical video in one take.", "New"],
    ["agent", "✦", "Agent", "A chat that plans and makes things for you.", "New"],
    ["blockout", "⬚", "Blockout", "Sketch a shot in 3D: the set, who moves where, the camera.", "New"],
    ["canvas", "▦", "Canvas", "A board for pictures, clips and notes.", "New"],
    ["audio", "♪", "Audio", "Voice-overs and voice samples for your cast.", ""],
    ["nightshift", "☾", "Night shift", "Leave a film rendering while you sleep.", ""],
    ["apps", "▤", "Apps", "One-click starts for every tool.", ""]];
  function drawFilters() {
    filters.replaceChildren([["all", "All"], ["image,sheet", "Pictures"], ["clip", "Clips"], ["film", "Films"], ["fav", "Favourites"]].map(([k, label]) =>
      h("button", { class: st.filter === k ? "on" : "", "aria-pressed": st.filter === k ? "true" : "false", onclick: () => { st.filter = k; drawFilters(); loadFeed(); } }, label)));
  }
  async function loadFeed() {
    const q = st.filter === "fav" ? "kind=image,sheet,clip,film&favorite=1" : "kind=" + (st.filter === "all" ? "image,sheet,clip,film" : st.filter);
    const r = await tryApi("/api/library?limit=160&" + q);
    if (!r) return;
    feed.replaceChildren(r.items.length ? r.items.map(a => post(a)) : h("div", { class: "empty", style: { columnSpan: "all" } },
      st.filter === "fav" ? "No favourites yet: press ☆ on a post." : "Nothing made yet. Start with a picture or a clip."));
  }
  root.append(
    heroes,
    h("div", { class: "features" }, FEATURES.map(([r, ico, b, s, tag]) => h("button", { class: "feature", onclick: () => go(r) },
      h("span", { class: "ico", "aria-hidden": "true" }, ico), h("b", {}, b, tag ? h("span", { class: "tag" }, tag) : null), h("span", {}, s)))),
    filmsBox,
    h("div", { class: "section-head" }, h("div", {}, h("h2", {}, "Made here"), h("div", { class: "muted small", style: { marginTop: "4px" } }, "Everything rendered on this computer. Recreate opens a post's settings again.")),
      h("div", { class: "row", style: { alignItems: "center" } }, status, filters)),
    feed);
  heroes.replaceChildren(HERO.map(([r, t, s]) => h("button", { class: "hero", onclick: () => go(r) },
    h("div", { class: "art" }, h("div", { class: "ph" }, t.split(" ")[1])), h("div", { class: "t" }, t), h("div", { class: "s" }, s))));
  HERO.forEach(([r, , , kind], i) => api("/api/library?limit=1&kind=" + kind).then(x => {
    const a = x.items[0]; if (!a) return;
    const art = heroes.children[i].querySelector(".art");
    art.style.backgroundImage = `url("${a.thumb}")`; art.replaceChildren();
  }).catch(() => {}));
  getMachine().then(m => { const g = m.gpus[0];
    status.replaceChildren(h("span", { class: "dot " + (m.comfy.up ? "good" : "bad") }), m.comfy.up ? "ComfyUI up" + (g ? " · " + gb(g.total - g.used) + " GPU free" : "") : "ComfyUI is not running"); }).catch(() => {});
  api("/api/films").then(list => {
    const open = list.filter(f => f.next || f.review).slice(0, 4);
    filmsBox.replaceChildren(open.length ? [h("div", { class: "section-head" }, h("h2", {}, "Your films"), h("button", { class: "ghost small", onclick: () => go("films") }, "All films →")),
      h("div", { class: "filmstrip" }, open.map(f => h("button", { class: "app card", style: { margin: 0 }, onclick: () => go("films", f.id + (f.next ? "/" + f.next.id : "")) },
        h("b", {}, f.name), h("span", {}, `${f.shots} shots · ${f.approved} approved · ${secs(f.seconds)}`),
        f.review ? h("span", { class: "chip warn" }, f.review + " at the gate") : f.next ? h("span", { style: { color: "var(--accent)", marginTop: "6px" } }, `Next: ${f.next.n} · ${f.next.label}`) : null)))] : null);
  }).catch(() => {});
  onJobEnd(j => { if (j.status === "done") loadFeed(); });
  drawFilters(); loadFeed();
} };
