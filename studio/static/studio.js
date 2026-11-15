"use strict";
// Studio: the Machine (what is installed, what can run, settings) and Learn (tutorial, prompting, prompt check, agents).

ROOMS.machine = { title: "Machine", async draw(root) {
  const box = h("div", {});
  root.append(head("Machine", "What this ComfyUI has, what the studio can do with it, and the settings. Everything renders on this computer."), box);
  async function load(refresh) {
    let m, s;
    try { [m, s] = await Promise.all([getMachine(refresh), api("/api/settings")]); } catch (e) { box.replaceChildren(h("div", { class: "note bad" }, e.message)); return; }
    const put = debounce(async patch => { const r = await tryApi("/api/settings", patch, "PUT"); if (r) { s = r; toast("Saved"); } }, 700);
    const g = m.gpus[0];
    const feat = Object.entries(m.features);
    box.replaceChildren(
      h("div", { class: "tiles big" },
        h("div", { class: "card", style: { margin: 0 } }, h("h3", {}, "ComfyUI"), h("div", { class: "pill" }, h("span", { class: "dot " + (m.comfy.up ? "good" : "bad") }), m.comfy.up ? `up at ${m.comfy.url} · ${m.nodes} node types` : "does not answer at " + m.comfy.url),
          h("div", { class: "row", style: { gap: "6px", marginTop: "10px" } },
            m.comfy.up ? null : h("button", { class: "primary small", disabled: !m.comfy.can_start, onclick: async () => { toast("Starting ComfyUI…"); if (await tryApi("/api/machine/comfy", { action: "start" })) load(true); } }, "Start"),
            m.comfy.up ? h("button", { class: "small", onclick: async () => { if (await tryApi("/api/machine/comfy", { action: "free" })) toast("Asked ComfyUI to unload its models"); } }, "Unload its models") : null,
            m.comfy.ours ? h("button", { class: "small", onclick: async () => { if (await tryApi("/api/machine/comfy", { action: "stop" })) load(true); } }, "Stop") : null,
            h("button", { class: "small", onclick: () => load(true) }, "Look again")),
          m.comfy.up && !m.comfy.ours ? h("div", { class: "hint" }, "This ComfyUI was started outside the studio, so the studio will not stop it.") : null),
        h("div", { class: "card", style: { margin: 0 } }, h("h3", {}, "Memory"), g ? h("div", {}, `GPU: ${gb(g.total - g.used)} free of ${gb(g.total)} · ${g.name}`) : h("div", { class: "muted" }, "No NVIDIA GPU seen."),
          h("div", {}, `RAM: ${gb(m.memory.available)} free of ${gb(m.memory.total)}`),
          h("div", { class: "hint" }, "A job that keeps more frames in RAM than fit is refused before it is queued: that is what killed ComfyUI on long, large renders.")),
        h("div", { class: "card", style: { margin: 0 } }, h("h3", {}, "Disks"), h("div", {}, `Renders: ${gb(m.disk.free)} free`), h("div", { class: "muted small" }, m.disk.path),
          h("div", { class: m.home_disk.free < 5 * 2 ** 30 ? "warn" : "" }, `Home: ${gb(m.home_disk.free)} free`), h("div", { class: "muted small" }, "The studio keeps its data in " + m.paths.studio)),
        h("div", { class: "card", style: { margin: 0 } }, h("h3", {}, "Tools"),
          h("div", { class: "pill" }, h("span", { class: "dot " + (m.tools.ffmpeg ? "good" : "bad") }), m.tools.ffmpeg ? "ffmpeg" : "ffmpeg is missing: no checks, no exports"),
          h("div", { class: "pill" }, h("span", { class: "dot " + (m.tools.whisper ? "good" : "warn") }), m.tools.whisper ? "Whisper (speech checks, captions)" : "openai-whisper is missing: speech is not checked"),
          h("div", { class: "pill" }, h("span", { class: "dot " + (m.brain.ok ? "good" : "") }), m.brain.ok ? "writing help: " + m.brain.kind : "no writing help set (not needed)"))),

      h("h2", { style: { marginTop: "22px" } }, "What can run"),
      m.comfy.up ? h("table", {}, h("tr", {}, h("th", {}, "Feature"), h("th", {}, ""), h("th", {}, "What is missing")),
        feat.map(([k, f]) => h("tr", {}, h("td", {}, f.title), h("td", {}, h("span", { class: "chip " + (f.ok ? "good" : "bad") }, f.ok ? "ready" : "not here")),
          h("td", { class: "muted" }, f.ok ? "" : [f.missing_nodes.length ? "nodes: " + f.missing_nodes.map(([n, p]) => n + (p ? " (" + p + ")" : "")).join(", ") : "", f.missing_models.length ? "models: " + f.missing_models.join(", ") : ""].filter(Boolean).join(" · ")))))
        : h("div", { class: "note warn" }, "Start ComfyUI to see what it has."),

      m.comfy.up ? [h("h2", {}, "Models"), h("p", { class: "sub" }, "Each file is picked by its role from what ComfyUI lists; choose another when you have several. Quantized “int8convrot” LoRAs are left out: through the plain loader they give pure noise."),
        h("table", {}, h("tr", {}, h("th", {}, "Role"), h("th", {}, "File")), m.roles.map(r => { const o = { v: r.chosen && r.options.includes(r.chosen) ? r.chosen : "" };
          return h("tr", {}, h("td", {}, r.title), h("td", {}, r.options.length ? select(o, "v", [["", r.file ? "Automatic: " + r.file : "Automatic (none found)"], ...r.options.map(x => [x, x])], { onchange: v => { put({ models: { [r.role]: v } }); machinePromise = null; } }) : h("span", { class: "bad" }, "nothing installed"))); })),
        h("p", { class: "muted small" }, `${m.loras.length} LoRAs usable` + (m.loras_quantized.length ? `, ${m.loras_quantized.length} quantized ones left out` : "") + ` · ${m.voices.length} TTS voices`)] : null,

      h("h2", { style: { marginTop: "22px" } }, "Settings"),
      h("div", { class: "grid2" },
        h("div", {},
          h("div", { class: "card" }, h("h3", {}, "ComfyUI"),
            field("Address", text(s, "comfy_url", { oninput: v => put({ comfy_url: v }) })),
            field("Command that starts it", text(s, "comfy_start", { oninput: v => put({ comfy_start: v }), placeholder: m.comfy.can_start ? "(run.sh in the ComfyUI folder)" : "e.g. ./run.sh" })),
            check(s, "auto_start_comfy", "Start ComfyUI when a job needs it and it does not answer", { onchange: v => put({ auto_start_comfy: v }) })),
          h("div", { class: "card" }, h("h3", {}, "The gate, by default"),
            check(s.gate, "auto_approve", "Approve a take by itself when every automatic check passes", { onchange: v => put({ gate: { auto_approve: v } }) }),
            h("div", { class: "row" }, h("div", { class: "field fit" }, h("label", {}, "Automatic retakes"), number(s.gate, "retries", { min: 0, max: 5, oninput: v => put({ gate: { retries: v } }) }))),
            check(s, "keep_takes", "Keep every take's files, so an earlier take can be put back (about 50 MB a take)", { onchange: v => put({ keep_takes: v }) })),
          h("div", { class: "card" }, h("h3", {}, "Checks"),
            h("div", { class: "row" },
              h("div", { class: "field" }, h("label", {}, "A hard cut is a jump above"), number(s.checks, "cut", { min: 5, max: 100, oninput: v => put({ checks: { cut: v } }) })),
              h("div", { class: "field" }, h("label", {}, "A bad join is above"), number(s.checks, "join", { min: 5, max: 100, oninput: v => put({ checks: { join: v } }) })),
              h("div", { class: "field" }, h("label", {}, "Speech too hot: dB over the film"), number(s.checks, "loud_over", { min: 1, max: 12, step: 0.5, oninput: v => put({ checks: { loud_over: v } }) })),
              h("div", { class: "field" }, h("label", {}, "Speech must match"), number(s.checks, "speech_min", { min: 0.3, max: 1, step: 0.05, oninput: v => put({ checks: { speech_min: v } }) }))),
            h("div", { class: "row" },
              h("div", { class: "field" }, h("label", {}, "Whisper model"), select(s.checks, "whisper_model", ["tiny", "base", "small", "medium", "large-v3", "turbo"].map(x => [x, x]), { onchange: v => put({ checks: { whisper_model: v } }) })),
              h("div", { class: "field" }, h("label", {}, "Runs on"), select(s.checks, "whisper_device", [["cpu", "the processor (the GPU stays with the render)"], ["cuda", "the GPU"]], { onchange: v => put({ checks: { whisper_device: v } }) }))),
            h("div", { class: "hint" }, "A part's speech is compared with the film's other approved parts (shouted lines came out about 3 dB above their median). Good joins measure 1 to 9, a swapped background 29 or more."))),
        h("div", {},
          h("div", { class: "card" }, h("h3", {}, "Video, by default"),
            field("What a part without lines is told", text(s.video, "silent_line", { oninput: v => put({ video: { silent_line: v } }) }), "Without it the model fills silence with mumbling."),
            h("div", { class: "row" }, h("div", { class: "field fit" }, h("label", {}, "Steps"), number(s.video, "steps", { min: 4, max: 40, oninput: v => put({ video: { steps: v } }) })),
              h("div", { class: "field fit" }, h("label", {}, "Turbo steps"), number(s.video, "turbo_steps", { min: 2, max: 16, oninput: v => put({ video: { turbo_steps: v } }) })),
              h("div", { class: "field fit" }, h("label", {}, "Turbo strength"), number(s.video, "turbo_strength", { min: 0.5, max: 1.2, step: 0.05, oninput: v => put({ video: { turbo_strength: v } }) })))),
          h("div", { class: "card" }, h("h3", {}, "Upscale"),
            h("div", { class: "row" }, h("div", { class: "field fit" }, h("label", {}, "Scale"), number(s.upscale, "scale", { min: 1, max: 2, step: 0.25, oninput: v => put({ upscale: { scale: v } }) })),
              h("div", { class: "field" }, h("label", {}, "Sigmas"), text(s.upscale, "sigmas", { oninput: v => put({ upscale: { sigmas: v } }) }))),
            h("div", { class: "row" }, h("div", { class: "fit" }, check(s.upscale, "interpolate", "To 48 frames a second", { onchange: v => put({ upscale: { interpolate: v } }) })),
              h("div", { class: "fit" }, check(s.upscale, "sharpen", "Sharpen", { onchange: v => put({ upscale: { sharpen: v } }) }))),
            h("div", { class: "hint" }, "Start sigma 0.63 keeps small props; 0.9 re-drew them from the prompt.")),
          h("div", { class: "card" }, h("h3", {}, "Writing help (optional)"),
            h("p", { class: "muted small" }, "A language model that turns a logline into shots. Rendering never uses it. Only text is sent to it."),
            field("Kind", select(s.brain, "kind", [["none", "None: coverage plans only"], ["openai", "A model server on this computer or network (OpenAI-style API: Ollama, LM Studio, llama.cpp)"], ["command", "A command that reads the request and prints the answer"]], { onchange: v => { put({ brain: { kind: v } }); setTimeout(() => load(), 900); } })),
            s.brain.kind === "openai" ? h("div", { class: "row" }, h("div", { class: "field" }, h("label", {}, "Address"), text(s.brain, "endpoint", { oninput: v => put({ brain: { endpoint: v } }) })),
              h("div", { class: "field" }, h("label", {}, "Model"), text(s.brain, "model", { oninput: v => put({ brain: { model: v } }) }))) : null,
            s.brain.kind === "command" ? field("Command", text(s.brain, "command", { oninput: v => put({ brain: { command: v } }), placeholder: "ollama run llama3", mono: true }), "What you send it goes wherever that program sends it.") : null))));
  }
  load(true);
} };

ROOMS.learn = { title: "Learn", draw(root, arg) {
  const pend = S.pending || {}; S.pending = null;
  const st = { tab: arg || pend.tab || "guide" };
  const body = h("div", {}), tabBar = h("div", {});
  const pc = { prompt: "", new_shot: true, lines: "" };
  async function draw() {
    tabBar.replaceChildren(tabs([["guide", "Guide with pictures"], ["tutorial", "Tutorial"], ["prompting", "Prompting"], ["check", "Prompt check"], ["agent", "Agents and the API"], ["long-video", "The long-video nodes"]], st.tab, x => { st.tab = x; history.replaceState(null, "", "#learn/" + x); draw(); }));
    if (st.tab === "check") {
      const out = h("div", {});
      body.replaceChildren(h("div", { class: "card" },
        h("p", { class: "muted small" }, "Paste any prompt. The check lists what tripped the model in real runs: contradicting camera words, speech without lines, things forbidden by name (the model has no negative prompt, so naming a thing can make it appear), too many words for the time."),
        field("Prompt", text(pc, "prompt", { rows: 8, mono: true })),
        field("Spoken lines, one a row (optional)", text(pc, "lines", { rows: 3, placeholder: "Sam: Good afternoon. Urgent delivery for you." })),
        h("div", { class: "row" }, h("div", { class: "fit" }, check(pc, "new_shot", "A new shot (not a continuation)")),
          h("div", { class: "field fit" }, h("button", { class: "primary", onclick: async () => {
            const lines = pc.lines.split("\n").map(l => l.trim()).filter(Boolean).map(l => { const i = l.indexOf(":"); return i > 0 ? { speaker: l.slice(0, i).trim(), text: l.slice(i + 1).trim() } : { speaker: "", text: l }; });
            const r = await tryApi("/api/prompt/check", { prompt: pc.prompt, new_shot: pc.new_shot, lines }); if (r) out.replaceChildren(h("h3", { style: { marginTop: "12px" } }, r.summary), findingsList(r.findings)); } }, "Check")))), out);
      return;
    }
    body.replaceChildren(h("div", { class: "muted" }, "Loading…"));
    const name = { guide: "guide", tutorial: "tutorial", prompting: "prompting", agent: "api", "long-video": "long-video" }[st.tab];
    try { const d = await api("/api/docs/" + name); body.replaceChildren(md(d.text)); } catch (e) { body.replaceChildren(h("div", { class: "note bad" }, e.message)); }
  }
  root.append(head("Learn", "How to get good clips out of the model, and how the studio works."), tabBar, body);
  draw();
} };
