// Open every room of the studio in headless Chrome, fail on any script error, and save a screenshot of each.
//   node tests/ui/smoke.mjs [http://127.0.0.1:8190] [output folder] [#room ...]
// Needs the studio running and google-chrome-stable (or CHROME=/path/to/chrome). Node 22 or newer (built-in WebSocket).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

const base = process.argv[2] || "http://127.0.0.1:8190";
const outDir = process.argv[3] || path.join(os.tmpdir(), "h3-studio-ui");
const rooms = process.argv.slice(4).length ? process.argv.slice(4)
  : ["#home", "#apps", "#picture", "#edit", "#video", "#films", "#cast", "#nightshift", "#library", "#timeline", "#sound", "#machine", "#learn", "#learn/check"];
fs.mkdirSync(outDir, { recursive: true });
const port = 9400 + Math.floor(Math.random() * 400);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "h3-studio-chrome-"));
const chrome = spawn(process.env.CHROME || "google-chrome-stable", ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
  "--window-size=1680,1050", `--user-data-dir=${profile}`, `--remote-debugging-port=${port}`, "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let target;
for (let i = 0; i < 40 && !target; i++) {
  await sleep(300);
  target = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" }).then(r => r.json()).catch(() => null);
}
if (!target) { console.error("Chrome did not start"); chrome.kill(); process.exit(2); }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0;
const pending = new Map(), errors = [];
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") errors.push("exception: " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).split("\n").slice(0, 3).join(" | "));
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push("console.error: " + m.params.args.map(a => a.value || a.description || "").join(" ").slice(0, 300));
  if (m.method === "Log.entryAdded" && m.params.entry.level === "error") errors.push("log: " + m.params.entry.text.slice(0, 200) + " " + (m.params.entry.url || ""));
};
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
export const evaluate = async expr => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 500));
  return r.result.result.value;
};
await send("Runtime.enable"); await send("Log.enable"); await send("Page.enable");
let failed = 0;
for (const room of rooms) {
  const before = errors.length;
  await send("Page.navigate", { url: base + "/" + room });
  await sleep(1800);
  const text = await evaluate(`document.querySelector("#room").innerText.slice(0, 90).replace(/\\n/g, " / ")`);
  const drew = await evaluate(`document.querySelector("#room").children.length`);
  const bad = await evaluate(`[...document.querySelectorAll("#room .note.bad")].map(e => e.innerText).join(" | ")`);
  const shot = await send("Page.captureScreenshot", { format: "png" });
  const file = path.join(outDir, room.replace(/[#/]/g, "_").replace(/^_/, "") + ".png");
  fs.writeFileSync(file, Buffer.from(shot.result.data, "base64"));
  const errs = errors.slice(before);
  const ok = !errs.length && drew > 0 && !bad;
  if (!ok) failed++;
  console.log(`${ok ? "ok  " : "FAIL"} ${room.padEnd(14)} ${text}` + (bad ? `\n     page says: ${bad}` : "") + errs.map(e => "\n     " + e).join(""));
}
{ // the switch in the menu: ComfyUI's output takes the bottom of the window, its top edge drags, and it gives the room back
  const before = errors.length;
  const look = () => evaluate(`(() => { const t = document.querySelector("#term"), r = t.getBoundingClientRect(), b = document.querySelector("#side .nav[aria-pressed]").getBoundingClientRect();
    const shell = document.querySelector("#shell").getBoundingClientRect().height;
    return { hidden: t.hidden, top: Math.round(r.top), bottom: Math.round(r.bottom), shell: Math.round(shell), win: innerHeight, text: t.innerText.length,
      // the switch itself: in the window and above the pane, whatever the pane's height
      inView: b.height > 20 && b.top >= 0 && b.bottom <= shell + 1 }; })()`);
  const mouse = (type, y, buttons) => send("Input.dispatchMouseEvent", { type, x: 700, y, button: "left", buttons, clickCount: 1 });
  const dragTo = async y => { const from = (await look()).top; await mouse("mousePressed", from, 1); for (const s of [0.3, 0.7, 1]) await mouse("mouseMoved", Math.round(from + (y - from) * s), 1); await mouse("mouseReleased", y, 0); await sleep(150); };
  const shut = await look();
  await evaluate(`document.querySelector("#side .nav[aria-pressed]").click()`);
  await sleep(1800);
  const open = await look();
  const shot = async name => { const s = await send("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(path.join(outDir, name + ".png"), Buffer.from(s.result.data, "base64")); };
  await shot("comfyui_output");
  await dragTo(240);                                  // a tall pane
  const tall = await look();
  await dragTo(5);                                    // as far up as it goes: the menu's switch must still be there
  const most = await look();
  await shot("comfyui_output_tall");
  await dragTo(open.win - 10);                        // as far down as it goes: a strip, not nothing
  const least = await look();
  await dragTo(600);
  const set = await look();
  await send("Page.reload"); await sleep(2500);       // the height and the switch are remembered
  const again = await look();
  await evaluate(`document.querySelector("#side .nav[aria-pressed]").click()`);
  const closed = await look();
  const near = (a, b) => Math.abs(a - b) <= 2;
  const checks = {
    "the switch is in view with the pane shut": shut.hidden && shut.inView,
    "half the window at first": !open.hidden && near(open.top, open.win / 2) && near(open.bottom, open.win) && near(open.shell, open.win / 2) && open.inView,
    "shows ComfyUI's text": open.text > 40,
    "the top edge drags": near(tall.top, 240) && near(tall.shell, 240) && tall.inView,
    "the switch stays in view at the tallest": most.top > 100 && most.top < 200 && most.inView,
    "a strip is left at the smallest": least.win - least.top >= 80 && least.win - least.top <= 100 && least.inView,
    "height and switch are remembered": near(set.top, 600) && !again.hidden && near(again.top, 600) && again.inView,
    "shut gives the room back": closed.hidden && closed.shell === closed.win && closed.inView,
    "no script errors": errors.length === before,
  };
  const bad = Object.keys(checks).filter(k => !checks[k]);
  if (bad.length) failed++;
  console.log(`${bad.length ? "FAIL" : "ok  "} ComfyUI output  opens at half the window, drags from ${least.win - least.top} to ${most.win - most.top} px of ${open.win}, the switch stays in view`
    + (bad.length ? "\n     failed: " + bad.join("; ") + "\n     " + JSON.stringify({ shut, open, tall, most, least, set, again, closed }) : "") + errors.slice(before).map(e => "\n     " + e).join(""));
}
if (process.env.UI_SCRIPT) {      // extra steps for a deeper test: a file that exports run({evaluate, send, sleep, shot})
  const mod = await import(path.resolve(process.env.UI_SCRIPT));
  const shot = async name => { const s = await send("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(path.join(outDir, name + ".png"), Buffer.from(s.result.data, "base64")); };
  try { await mod.run({ evaluate, send, sleep, shot, base, errors }); } catch (e) { console.log("FAIL script: " + e.message); failed++; }
  if (errors.length) { console.log("script errors:\n  " + errors.slice(-8).join("\n  ")); }
}
ws.close(); chrome.kill();
await sleep(500);
try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }); } catch { /* Chrome still writing; the OS cleans /tmp */ }
console.log(failed ? `${failed} check(s) failed; screenshots in ${outDir}` : `${rooms.length} room(s) and ComfyUI's output drew without errors; screenshots in ${outDir}`);
process.exit(failed ? 1 : 0);
