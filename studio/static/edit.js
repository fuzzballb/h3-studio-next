"use strict";
// Edit: the timeline (order, trim, level, music, captions, export, files for an editor) and Sound.

ROOMS.timeline = { title: "Timeline", async draw(root, arg) {
  const pend = S.pending || {}; S.pending = null;
  let list = (await tryApi("/api/timelines")) || [];
  let tl = null;
  const body = h("div", {}), results = h("div", {}), note = h("span", { class: "muted small" });
  const mine = new Set();
  const save = debounce(async () => { if (!tl) return; note.textContent = "saving…"; const r = await tryApi("/api/timelines/" + tl.id, tl, "PUT"); note.textContent = r ? "saved" : "not saved"; }, 500);
  const flush = () => new Promise(res => { const w = () => note.textContent === "saving…" || note.textContent === "…" ? setTimeout(w, 100) : res(); w(); });
  const edited = () => { note.textContent = "…"; save(); };
  async function open(id) { tl = id ? await tryApi("/api/timelines/" + id) : null; if (tl) history.replaceState(null, "", "#timeline/" + tl.id); draw(); }
  const total = () => tl.clips.reduce((s, c) => s + Math.max(0, c.out - c.in), 0) + ((tl.title.text || "").trim() ? Number(tl.title.seconds || 0) : 0);

  onJobEnd(async j => {
    if (!mine.has(j.id) || j.status !== "done") return;
    const r = j.result || {};
    if (j.kind === "export") {
      results.prepend(h("div", { class: "card" }, h("div", { class: "spread" }, h("h3", { style: { margin: 0 } }, "Export · " + secs(r.seconds)), h("span", { class: "muted small" }, "output/" + r.file)),
        h("video", { src: media(r.file), controls: true, style: { width: "100%", background: "#000", borderRadius: "4px", margin: "8px 0" } }),
        r.note ? h("div", { class: "note warn" }, r.note) : null,
        h("div", { class: "row", style: { gap: "6px" } }, h("a", { class: "btn small", href: media(r.file), download: "" }, "Download MP4"), h("a", { class: "btn small", href: media(r.fcpxml), download: "" }, "FCPXML"),
          h("a", { class: "btn small", href: media(r.edl), download: "" }, "EDL"), r.srt ? h("a", { class: "btn small", href: media(r.srt), download: "" }, "Captions (.srt)") : null,
          h("button", { class: "small", onclick: () => runJob("resolve", { asset: r.asset }, "ProRes · " + tl.name) }, "This cut as ProRes")),
        r.gains && r.gains.some(g => g) ? h("div", { class: "small muted", style: { marginTop: "8px" } }, "Levels matched: " + r.gains.map((g, i) => g ? `clip ${i + 1} ${g > 0 ? "+" : ""}${g} dB` : "").filter(Boolean).join(", ")) : null));
    } else if (j.kind === "resolve") {
      results.prepend(h("div", { class: "card" }, h("h3", {}, "For DaVinci Resolve"), r.folder ? h("p", {}, "The package is in ", h("code", {}, "output/" + r.folder), `: ${r.clips} clip(s) as ProRes 422 with PCM sound, timeline.fcpxml and timeline.edl. In Resolve: File → Import → Timeline.`)
        : h("p", {}, "ProRes copy: ", h("code", {}, "output/" + r.file))));
    } else if (j.kind === "conform") {
      results.prepend(h("div", { class: "card" }, h("h3", {}, "Brought back to size"), h("video", { src: media(r.file), controls: true, style: { width: "100%", background: "#000", borderRadius: "4px" } }),
        h("div", { class: "muted small" }, (r.bars_removed ? "Black bars removed. " : "No black bars found. ") + "output/" + r.file)));
    }
  });

  function clipRow(c, i) {
    const thumb = "/refthumb?name=" + encodeURIComponent(c.path + " [output]");
    return h("div", { class: "cliprow" },
      h("img", { src: thumb, alt: "", loading: "lazy" }),
      h("div", { style: { minWidth: 0 } }, h("div", { class: "name", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, (i + 1) + ". " + c.title), h("div", { class: "muted small" }, secs(c.out - c.in) + " of " + secs(c.duration))),
      h("div", {}, h("label", {}, "In"), number(c, "in", { min: 0, max: c.duration, step: 0.04, oninput: edited })),
      h("div", {}, h("label", {}, "Out"), number(c, "out", { min: 0, max: c.duration, step: 0.04, oninput: edited })),
      h("div", {}, h("label", {}, "dB"), number(c, "gain", { min: -24, max: 24, step: 0.5, oninput: edited })),
      h("div", { style: { display: "flex", gap: "2px" } },
        h("button", { class: "ghost small", "aria-label": "Earlier", disabled: i === 0, onclick: () => { tl.clips.splice(i - 1, 0, tl.clips.splice(i, 1)[0]); edited(); draw(); } }, "↑"),
        h("button", { class: "ghost small", "aria-label": "Later", disabled: i === tl.clips.length - 1, onclick: () => { tl.clips.splice(i + 1, 0, tl.clips.splice(i, 1)[0]); edited(); draw(); } }, "↓"),
        h("button", { class: "ghost small", "aria-label": "Preview", onclick: () => modal(h("div", {}, h("div", { class: "spread" }, h("h2", {}, c.title), h("button", { class: "ghost", onclick: closeModal }, "Close")),
          h("video", { src: media(c.path) + `#t=${c.in},${c.out}`, controls: true, autoplay: true }))) }, "▶"),
        h("button", { class: "ghost small danger", "aria-label": "Remove", onclick: () => { tl.clips.splice(i, 1); edited(); draw(); } }, "✕")));
  }
  function draw() {
    if (!tl) { body.replaceChildren(h("div", { class: "empty" }, "No timeline yet. Start one, send clips here from the Library, or send a film here from its Deliver tab.")); return; }
    const m = { ref: tl.music.path ? tl.music.path + " [output]" : "" };
    const sz = { v: tl.width && tl.height ? tl.width + "x" + tl.height : "" };
    body.replaceChildren(
      h("div", { class: "grid2" },
        h("div", { class: "card" },
          h("div", { class: "spread" }, h("div", { class: "field", style: { flex: 1, marginBottom: 0 } }, text(tl, "name", { oninput: edited })), h("span", { class: "muted" }, secs(total()))),
          h("div", { style: { marginTop: "10px" } }, tl.clips.length ? tl.clips.map(clipRow) : h("div", { class: "empty" }, "No clips yet.")),
          h("div", { class: "row", style: { marginTop: "10px", gap: "6px" } },
            h("button", { onclick: async () => { const got = await pickAsset("clip", { multiple: true, title: "Clips for the timeline" }); if (got && got.length) { await flush(); const r = await tryApi(`/api/timelines/${tl.id}/clips`, { assets: got.map(a => a.id) }); if (r) { tl = r; draw(); } } } }, "+ Clips from the Library"))),
        h("div", {},
          h("div", { class: "card" }, h("h3", {}, "Sound"),
            check(tl, "match", "Bring the clips with speech to the same level", { onchange: edited }),
            h("div", { class: "hint", style: { margin: "-6px 0 10px" } }, "One part of a film can come out a few dB hotter than its neighbours. Quiet clips (ambience only) are left alone."),
            field("A song under the cut", refPicker(m, "ref", { kind: "audio", empty: "none", onchange: v => { tl.music.path = v.replace(/ \[output\]$/, ""); edited(); } }), "It is lowered while a clip has sound."),
            h("div", { class: "row" }, h("div", { class: "field fit" }, h("label", {}, "Song level (dB)"), number(tl.music, "gain", { min: -40, max: 0, step: 1, oninput: edited })),
              h("div", { class: "field fit" }, h("label", {}, "Lowered by (dB)"), number(tl.music, "duck", { min: 0, max: 24, step: 1, oninput: edited })),
              h("div", { class: "field fit" }, h("label", {}, "Loudness (LUFS)"), number(tl, "loudness", { min: -30, max: -9, step: 1, oninput: edited })))),
          h("div", { class: "card" }, h("h3", {}, "Picture"),
            h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Title card"), text(tl.title, "text", { oninput: edited, placeholder: "none" })),
              h("div", { class: "field" }, h("label", {}, "Line under it"), text(tl.title, "subtitle", { oninput: edited }))),
            check(tl, "captions", "Burn in captions (what Whisper hears in each clip)", { onchange: edited }),
            h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Size"), select(sz, "v", [["", "The first clip's own"], ["1920x1080", "1920x1080"], ["1280x720", "1280x720"], ["1080x1920", "1080x1920 (vertical)"], ["1080x1080", "1080x1080 (square)"], ...sizeOptions()],
              { onchange: v => { [tl.width, tl.height] = v ? v.split("x").map(Number) : [0, 0]; edited(); } })),
              h("div", { class: "field fit" }, h("label", {}, "Frames a second (0 = the clip's)"), number(tl, "fps", { min: 0, max: 60, oninput: edited })))),
          h("div", { class: "row", style: { gap: "6px" } },
            h("button", { class: "primary", disabled: !tl.clips.length, onclick: async () => { await flush(); const j = await tryApi(`/api/timelines/${tl.id}/export`, {}); if (j) { mine.add(j.id); S.seen[j.id] = j.status; toast("Export queued"); poll(); } } }, "Export"),
            h("button", { disabled: !tl.clips.length, onclick: async () => { await flush(); const j = await tryApi(`/api/timelines/${tl.id}/export`, { resolve: true }); if (j) { mine.add(j.id); S.seen[j.id] = j.status; toast("Queued"); poll(); } } }, "Package for DaVinci Resolve"),
            h("button", { class: "ghost danger", onclick: async () => { if (!confirm("Remove this timeline? The clips stay.")) return; if (await tryApi("/api/timelines/" + tl.id, undefined, "DELETE")) { list = (await tryApi("/api/timelines")) || []; open((list[0] || {}).id); drawHead(); } } }, "Remove the timeline")))));
  }

  // ---- cut to a song, and bring an editor's export back
  const rc = { song: "", mode: "own", order: "as_filmed", film: "", name: "Rough cut", assets: pend.roughcut || [] };
  const cf = { clip: "", size: "1152x640", fps: 0 };
  const films = (await tryApi("/api/films")) || [];
  const tools = h("div", { class: "grid2", style: { marginTop: "8px" } },
    h("div", { class: "card" }, h("h3", {}, "Cut to a song"),
      h("p", { class: "muted small" }, "The studio finds the song's beats on this computer and lays the clips end to end so each cut lands on the music. A clip is trimmed around its middle to fill its slot."),
      field("The song", refPicker(rc, "song", { kind: "audio", empty: "pick a song from the Library" })),
      h("div", { class: "row" },
        h("div", { class: "field" }, h("label", {}, "Clips"), rc.assets.length ? h("div", { class: "chip accent" }, rc.assets.length + " picked in the Library") : select(rc, "film", [["", tl ? "This timeline's clips" : "(pick a film)"], ...films.map(f => [f.id, "Film: " + f.name])])),
        h("div", { class: "field" }, h("label", {}, "Cuts fall"), select(rc, "mode", [["own", "Near each clip's own length"], ["bar", "One bar each"], ["two_bars", "Two bars each"], ["beat", "One beat each"]])),
        h("div", { class: "field" }, h("label", {}, "Order"), select(rc, "order", [["as_filmed", "As filmed"], ["shuffled", "Shuffled"]]))),
      h("button", { onclick: async () => {
        if (!rc.song) return toast("Pick the song", true);
        let d = { song_path: rc.song.replace(/ \[output\]$/, ""), mode: rc.mode, order: rc.order, name: rc.name };
        if (rc.assets.length) d.assets = rc.assets; else if (rc.film) d.film = rc.film; else if (tl && tl.clips.length) d.assets = tl.clips.map(c => c.asset).filter(Boolean); else return toast("Pick a film, or put clips on the timeline first", true);
        if (d.assets && !d.assets.length) return toast("These clips are not in the Library; pick a film instead", true);
        const t = await tryApi("/api/roughcut", d);
        if (t) { toast(`Cut on the beat: ${t.beats.bpm} BPM, ${t.beats.slots} clips` + (t.beats.clips_left_out ? `, ${t.beats.clips_left_out} left out (the song ended)` : "")); list = (await tryApi("/api/timelines")) || []; drawHead(); open(t.id); }
      } }, "Make the cut")),
    h("div", { class: "card" }, h("h3", {}, "Bring an editor's export back"),
      h("p", { class: "muted small" }, "An export from DaVinci Resolve often comes back larger, with black bars, as ProRes. This cuts the bars off, scales it to the film's own size and writes H.264 with AAC."),
      field("The export", refPicker(cf, "clip", { kind: "clip", empty: "upload it, or bring it in from disk in the Library" })),
      h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Back to"), select(cf, "size", [...sizeOptions(), ["1728x960", "1728x960 (1152x640 upscaled)"], ["1920x1056", "1920x1056 (1280x704 upscaled)"]])),
        h("div", { class: "field fit" }, h("label", {}, "Frames a second (0 = keep)"), number(cf, "fps", { min: 0, max: 60 })),
        h("div", { class: "field fit" }, h("button", { onclick: async () => { if (!cf.clip) return toast("Pick the export", true); const [w, hh] = cf.size.split("x").map(Number);
          const j = await tryApi("/api/jobs", { kind: "conform", params: { path: cf.clip.replace(/ \[output\]$/, ""), width: w, height: hh, fps: cf.fps || 0 }, title: "Back to " + cf.size }); if (j) { mine.add(j.id); S.seen[j.id] = j.status; toast("Queued"); poll(); } } }, "Bring it back")))));

  const headBox = h("div", {});
  function drawHead() {
    const pick = { id: tl ? tl.id : "" };
    headBox.replaceChildren(h("div", { class: "row" },
      list.length ? h("div", { class: "field" }, h("label", {}, "Timeline"), select(pick, "id", list.map(t => [t.id, `${t.name} · ${t.clips} clips · ${secs(t.seconds)}`]), { onchange: async v => { await flush(); open(v); } })) : null,
      h("div", { class: "field fit" }, h("button", { onclick: async () => { const t = await tryApi("/api/timelines", { name: "Timeline " + (list.length + 1) }); if (t) { list = (await tryApi("/api/timelines")) || []; await open(t.id); drawHead(); } } }, "+ New timeline")),
      h("div", { class: "field fit" }, note)));
  }
  root.append(head("Timeline", "One video track: order the clips, trim them, level them, lay a song under them, export. For anything more, send the cut to an editor."), headBox, body, results, tools);
  const first = (arg && list.find(t => t.id === arg)) ? arg : (list[0] || {}).id;
  await open(first);
  drawHead();
} };

// ---------------------------------------------------------------- Sound
ROOMS.sound = { title: "Sound", draw(root, arg) {
  const pend = S.pending || {}; S.pending = null;
  const st = { tab: arg || pend.tab || "voices" };
  const body = h("div", {}), tabBar = h("div", {});
  const t = { text: "", voice: "", name: "", seed: 1 };
  const res = h("div", { class: "tiles", style: { marginTop: "14px" } });
  const mine = new Set();
  onJobEnd(async j => { if (j.kind === "tts" && mine.has(j.id) && j.status === "done") for (const id of j.result.assets || []) { const a = await tryApi("/api/library/" + id); if (a) res.prepend(assetTile(a)); } if (st.tab === "voices") draw(); });
  async function draw() {
    tabBar.replaceChildren(tabs([["voices", "Voice samples"], ["tts", "Voice-over"], ["beats", "Beats"]], st.tab, x => { st.tab = x; draw(); }));
    if (st.tab === "voices") {
      const v = (await tryApi("/api/voices")) || { samples: [], tts: [] };
      body.replaceChildren(
        h("div", { class: "note" }, "A voice sample is 10 to 20 seconds of clean speech of one person. Give it to a character (in a film's Cast, or under People in Video) and the video model speaks that character's lines in that voice, with the lips: “says in the voice from Audio 1”. Clean samples sound like a studio; Location sound in the Library fixes that afterwards."),
        h("button", { class: "primary", onclick: async () => { const files = await chooseFiles(ACCEPT.audio, true); if (!files.length) return; try { await upload(files); toast("Uploaded"); draw(); } catch (e) { toast(e.message, true); } } }, "Upload a sample…"),
        h("div", { class: "tiles", style: { marginTop: "14px" } }, v.samples.length ? v.samples.map(a => assetTile(a)) : h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, "No sound files yet.")));
    } else if (st.tab === "tts") {
      const v = (await tryApi("/api/voices")) || { tts: [] };
      if (!t.voice && v.tts.length) t.voice = v.tts[0];
      body.replaceChildren(h("div", { class: "card" },
        h("p", { class: "muted small" }, "A line spoken by ChatterBox in a voice from the TTS Audio Suite's list: for narration, or as a voice sample for a character. A voice you add to ComfyUI's models/voices appears here after ComfyUI restarts."),
        field("The words", text(t, "text", { rows: 3, placeholder: "It was a quiet morning on the lake, until the duck arrived." })),
        h("div", { class: "row" },
          h("div", { class: "field" }, h("label", {}, "Voice"), v.tts.length ? select(t, "voice", v.tts.map(x => [x, x])) : h("div", { class: "note warn" }, "No voices found: the TTS Audio Suite is not installed, or ComfyUI is down.")),
          h("div", { class: "field" }, h("label", {}, "Name (optional)"), text(t, "name", {})),
          h("div", { class: "field fit" }, h("label", {}, "Seed"), number(t, "seed", { min: 1 })),
          h("div", { class: "field fit" }, h("button", { class: "primary", disabled: !v.tts.length, onclick: async () => { const j = await tryApi("/api/tts", t); if (j) { mine.add(j.id); S.seen[j.id] = j.status; toast("Queued"); poll(); } } }, "Speak it")))), res);
    } else {
      const b = { song: "" }, out = h("div", {});
      body.replaceChildren(h("div", { class: "card" },
        h("p", { class: "muted small" }, "The tempo and every beat of a song, found on this computer. The Timeline uses them to cut clips on the music."),
        field("The song", refPicker(b, "song", { kind: "audio", empty: "pick or upload a song" })),
        h("button", { onclick: async () => { if (!b.song) return toast("Pick a song", true); out.replaceChildren(h("div", { class: "muted" }, "Listening…")); const r = await tryApi("/api/beats", { path: b.song.replace(/ \[output\]$/, "") });
          out.replaceChildren(r ? h("div", {}, h("div", { style: { fontSize: "22px", fontWeight: 650 } }, r.bpm + " BPM"), h("div", { class: "muted" }, `${r.beats.length} beats · ${r.bars} bars · ${secs(r.duration)} · first bar at ${r.downbeats[0] ?? "?"} s`),
            h("div", { class: "hint" }, "4/4 is assumed. Very fast songs may read at half tempo, which still cuts on the beat.")) : ""); } }, "Find the beats"), h("div", { style: { marginTop: "12px" } }, out)));
    }
  }
  root.append(head("Sound", "Voices for characters, narration, and the beats of a song. Speech in a clip is made by the video model together with the picture; that is why the lips fit."), tabBar, body);
  draw();
} };
