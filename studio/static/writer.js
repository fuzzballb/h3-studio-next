// The Writer: a conversation with Claude (the Claude Code program signed in on this computer) that writes a film from
// a small story, and changes a film when something about it is wrong. Nothing changes until "Apply" is pressed.
ROOMS.writer = { title: "Writer", async draw(root, arg) {
  // #writer/film/<id>: start a conversation about that film
  if (arg && arg.startsWith("film/")) {
    const c = await tryApi("/api/writer", { film: arg.slice(5) });
    if (c) go("writer", c.id);
    return;
  }
  const data = await tryApi("/api/writer");
  if (!data) return;
  const filmsList = (await tryApi("/api/films")) || [];
  const filmName = id => (filmsList.find(f => f.id === id) || {}).name || id;
  const cid = arg || "";
  let conv = cid ? await tryApi("/api/writer/" + cid) : null;
  // the film's shots by id, so a proposal can say "Shot 3 · The blessing" and not an id
  let shotNames = {}, theFilm = null;
  const loadFilm = async () => { const f = conv && conv.film ? await api("/api/films/" + conv.film).catch(() => null) : null;
    theFilm = f;
    shotNames = f ? Object.fromEntries(f.shots.map((s, i) => [s.id, `shot ${i + 1} · ${s.title || "untitled"}`])) : {}; };
  await loadFilm();
  const shotName = id => shotNames[id] || id;
  const answers = {};
  let busy = false;

  const side = h("div", { class: "card", style: { margin: 0 } },
    h("button", { class: "primary", style: { width: "100%" }, onclick: async () => { const c = await tryApi("/api/writer", {}); if (c) go("writer", c.id); } }, "+ A new film from a story"),
    filmsList.length ? h("div", { class: "field", style: { marginTop: "10px" } }, h("label", {}, "Or talk about a film"),
      (() => { const pick = { f: "" }; return select(pick, "f", [["", "(choose a film)"], ...filmsList.filter(f => !f.quick).map(f => [f.id, f.name])], { onchange: v => v && go("writer", "film/" + v) }); })()) : null,
    h("h3", { style: { marginTop: "14px" } }, "Conversations"),
    data.conversations.length ? data.conversations.map(c => h("button", { class: "nav" + (c.id === cid ? " on" : ""), style: { width: "100%", textAlign: "left", overflow: "hidden" }, title: (c.title || "(empty)") + (c.film ? " · " + filmName(c.film) : ""), onclick: () => go("writer", c.id) },
      h("span", { class: "label", style: { display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 } }, (c.title || "(empty)") + (c.film ? " · " + filmName(c.film) : "")))) : h("div", { class: "faint small" }, "None yet."));

  const main = h("div", { class: "chat" });
  const page = h("div", {}, head("Writer", "The start of a film. Tell a small story; Claude asks a few questions and writes the film: the bible (step 1), the shots in scenes (step 3) and a blockout for a scene where the camera matters (step 4). \u201cMake this film\u201d makes it. Talk about a film later to change it."),
    data.state.ok ? null : h("div", { class: "note bad" }, "The Writer needs Claude Code on this computer: " + data.state.why),
    h("div", { class: "split" }, side, main));
  root.append(page);

  const shotLine = s => h("li", {}, h("b", {}, s.title || "Shot"), " ", s.new_shot === false ? h("span", { class: "chip" }, "continues") : null,

    h("div", { class: "muted small" }, [s.location ? "at " + s.location : null, (s.cast || []).join(", "), s.seconds ? s.seconds + " s" : null].filter(Boolean).join(" · ")),
    h("div", { class: "small" }, s.action || (s.prompt || "").slice(0, 200)),
    (s.lines || []).map(l => h("div", { class: "small" }, h("i", {}, l.speaker + (l.how ? " (" + l.how + ")" : "") + ": "), "“" + l.text + "”")));

  function proposal(t, n) {
    const a = t.answer;
    if (!a.film && !a.edits) return null;
    const applied = t.applied;
    const btn = applied ? h("button", { class: "small", onclick: () => go("films", applied) }, "Go on with the film →")
      : h("button", { class: "primary", onclick: async e => {
          e.target.disabled = true;
          const r = await tryApi(`/api/writer/${cid}/apply`, { turn: n });
          e.target.disabled = false;
          if (!r) return;
          const rep = r.report;
          toast(rep.made ? `The film “${r.film.name}” is made: ${rep.added.length} shots.`
            : `${rep.updated.length} shot(s) changed, ${rep.added.length} added, ${rep.removed.length} removed.` + (rep.rerender.length ? ` ${rep.rerender.length} rendered shot(s) must be rendered again.` : ""));
          conv = r.conversation; await loadFilm(); draw();
        } }, a.film ? "Make this film" : "Apply these changes");
    if (a.film) {
      const scenes = [];
      for (const s of a.film.shots) { const k = s.scene || ""; let sc = scenes.find(x => x.k === k); if (!sc) scenes.push(sc = { k, shots: [] }); sc.shots.push(s); }
      return h("div", { class: "card", style: { marginTop: "8px" } },
        h("div", { class: "spread" }, h("h3", { style: { margin: 0 } }, a.film.name), btn),
        h("p", { class: "muted" }, a.film.logline),
        h("div", { class: "small" }, h("b", {}, "Cast: "), a.film.cast.map(c => c.name + " (" + c.description + ")").join("; ")),
        h("div", { class: "small", style: { marginBottom: "8px" } }, h("b", {}, "Places: "), a.film.locations.map(l => l.name).join(", ")),
        scenes.map(sc => h("div", {}, sc.k ? h("h4", { style: { margin: "10px 0 4px" } }, (/^scene\b/i.test(sc.k) ? "" : "Scene ") + sc.k,
          (a.film.blockouts || []).some(b => (b.scene || "").trim() === sc.k.trim() && b.blockout) ? h("span", { class: "chip accent", style: { marginLeft: "8px" }, title: "Blender makes it when the film is made" }, "blockout") : null) : null,
          h("ol", {}, sc.shots.map(shotLine)))));
    }
    const e = a.edits;
    return h("div", { class: "card", style: { marginTop: "8px" } },
      h("div", { class: "spread" }, h("h3", { style: { margin: 0 } }, "Proposed changes"), btn),
      (e.update || []).map(u => h("div", { style: { marginTop: "6px" } }, h("b", {}, "Change " + shotName(u.id) + ": "), u.why,
        h("div", { class: "muted small" }, Object.keys(u.changes || {}).join(", ")))),
      (e.add || []).map(x => h("div", { style: { marginTop: "6px" } }, h("b", {}, "Add after " + (x.after ? shotName(x.after) : "the start") + ": "), x.why, h("ul", {}, shotLine(x.shot)))),
      (e.remove || []).length ? h("div", { style: { marginTop: "6px" } }, h("b", {}, "Remove: "), e.remove.map(shotName).join(", ")) : null,
      blockoutEdits(e),
      (e.cast || []).length ? h("div", { class: "small" }, h("b", {}, "Cast: "), e.cast.map(c => c.name).join(", ")) : null,
      (e.locations || []).length ? h("div", { class: "small" }, h("b", {}, "Places: "), e.locations.map(l => l.name).join(", ")) : null);
  }

  // the blockouts of the conversation's film: made ones play here, the others say where they are
  function blockoutsCard() {
    if (!theFilm) return null;
    const bos = theFilm.blockouts || [];
    if (!bos.length) return null;
    const jobs = ((S.state || {}).jobs || []).filter(j => j.status === "queued" || j.status === "running");
    return h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Blockouts"),
      bos.map(b => {
        const making = jobs.find(j => j.kind === "blockout" && j.film === theFilm.id && (j.params || {}).blockout === b.id) || jobs.find(j => j.kind === "blockout" && j.film === theFilm.id);
        return h("div", { style: { marginBottom: "12px" } },
          h("div", { class: "spread" }, h("b", {}, "Scene " + (b.scene_name || "(no name)") + ` · ${(b.stretches || []).length} shot(s)`),
            h("button", { class: "small ghost", onclick: () => go("films", theFilm.id + "/blockout") }, "Refine and cut it →")),
          b.video ? rangeVideo(refUrl(b.video) + "?m=" + (b.made || ""), 0, 0, { style: { maxHeight: "300px", marginTop: "6px" } })
            : h("div", { class: "muted small" }, making ? "Blender is making it…" + (making.progress && making.progress.max ? ` ${making.progress.value} of ${making.progress.max} frames` : "") : "Not made yet."));
      }));
  }
  onJobEnd(async j => { if (j.kind === "blockout" && conv && j.film === conv.film) { await loadFilm(); draw(); } });
  const blockoutEdits = e => (e.blockouts || []).map(b => h("div", { style: { marginTop: "6px" } }, h("b", {}, (b.blockout ? "Blockout of scene " : "Remove the blockout of scene ") + (b.scene || "(no name)") + ": "), b.why));

  function draw() {
    if (!conv) { main.replaceChildren(h("div", { class: "empty" }, "Start a new film from a story, or choose a film to talk about.")); return; }
    const last = conv.turns[conv.turns.length - 1];
    const open = last && last.role === "writer" ? last.answer.questions : [];
    const box = { text: "" };
    const input = text(box, "text", { rows: 4, placeholder: conv.turns.length ? "Answer, or say what should change…" : (conv.film ? "What is wrong with the film, or what should change?" : "A small story: who, where, what happens…") });
    const send = async () => {
      const parts = open.filter(q => answers[q.id]).map(q => `- ${q.question} ${answers[q.id]}`);
      const msg = (parts.length ? "My answers:\n" + parts.join("\n") + "\n" : "") + box.text;
      if (!msg.trim() || busy) return;
      busy = true; draw();
      const r = await tryApi(`/api/writer/${cid}/say`, { text: msg });
      busy = false;
      if (r) { conv = r; for (const k in answers) delete answers[k]; }
      draw();
    };
    input.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(); });
    main.replaceChildren(
      conv.film ? h("div", { class: "note" }, "About the film ", h("a", { href: "#films/" + conv.film + "/shots" }, filmName(conv.film)), ". Claude sees its shots, their words and what the checks said about each take.") : null,
      conv.turns.map((t, n) => t.role === "user"
        ? h("div", { class: "card mine", style: { marginLeft: "15%" } }, h("div", { style: { whiteSpace: "pre-wrap" } }, t.text))
        : h("div", { class: "card", style: { marginRight: "5%" } },
            h("div", { style: { whiteSpace: "pre-wrap" } }, t.answer.say),
            n === conv.turns.length - 1 && t.answer.questions.length ? t.answer.questions.map(q => h("div", { class: "field", style: { marginTop: "10px" } },
              h("label", {}, q.question),
              h("div", { class: "choice" }, q.options.map(o => h("button", { class: "small" + (answers[q.id] === o ? " on" : ""), onclick: () => { answers[q.id] = answers[q.id] === o ? "" : o; draw(); } }, o))),
              text(answers, q.id, { placeholder: "or your own answer" }))) : null,
            proposal(t, n),
            h("div", { class: "faint small", style: { marginTop: "6px" } }, [t.meta && t.meta.seconds ? t.meta.seconds + " s" : "", t.meta && t.meta.model].filter(Boolean).join(" · ")))),
      blockoutsCard(),
      busy ? h("div", { class: "note" }, "Claude is writing… this takes from a few seconds to a few minutes for a whole film.") : null,
      h("div", { class: "card" }, input,
        h("div", { class: "spread", style: { marginTop: "8px" } }, h("span", { class: "faint small" }, "Ctrl+Enter sends. Only text goes to Claude; pictures and clips stay here."),
          h("button", { class: "primary", disabled: busy || !data.state.ok, onclick: send }, busy ? "Writing…" : "Send"))));
    if (!busy) input.focus();
  }
  draw();
} };
