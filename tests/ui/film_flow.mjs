// A film planned through the page, without rendering: start it, add a cast and a place, lay out shots from a
// coverage plan, edit one, and read its preflight. Run with:
//   UI_SCRIPT=tests/ui/film_flow.mjs node tests/ui/smoke.mjs http://127.0.0.1:8190 /tmp/shots "#films"
export async function run({ evaluate, sleep, shot, base }) {
  const page = fn => evaluate(`(async () => {
    const click = (text, root) => { const t = x => x.textContent.trim().replace(/^[0-9✓]+(?=[^ ])/, "");   /* a film's tabs start with their step number or a tick */
      const b = [...(root || document).querySelectorAll("button, a.btn")].find(x => t(x) === text || t(x).startsWith(text)); if (!b) throw new Error("no button: " + text); b.click(); };
    const type = (el, value) => { if (!el) throw new Error("no field"); el.value = value; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); };
    const byLabel = (label, root, nth) => { const l = [...(root || document).querySelectorAll("label")].filter(x => x.textContent.trim() === label)[nth || 0]; if (!l) throw new Error("no label: " + label); return l.parentElement.querySelector("input, textarea, select"); };
    const wait = ms => new Promise(r => setTimeout(r, ms));
    return await (${fn})({ click, type, byLabel, wait });
  })()`);
  const expect = (cond, what) => { if (!cond) throw new Error("expected: " + what); console.log("   ok: " + what); };

  await page(async ({ type, byLabel, click }) => { type(byLabel("Or start one empty and fill in each step yourself"), "UI test film"); click("Start empty"); });
  await sleep(1200);
  const fid = await evaluate(`location.hash.split("/")[1]`);
  expect(/^ui_test_film_/.test(fid), "a new film opens on its Bible: " + fid);
  await page(async ({ type, byLabel }) => { type(byLabel("Logline"), "A courier brings a parcel to the wrong door."); });
  await shot("film_bible");

  await page(async ({ click, wait }) => { click("Cast & places"); await wait(700); click("+ Character"); await wait(200); click("+ Character"); await wait(200); click("+ Place"); });
  await sleep(300);
  await page(async ({ type, byLabel }) => {
    const people = [...document.querySelectorAll(".person")];
    type(byLabel("Name", people[0]), "Sam"); type(byLabel("Looks like", people[0]), "a courier in his thirties with short dark curly hair, wearing a yellow jacket");
    type(byLabel("Name", people[1]), "Lisa"); type(byLabel("Looks like", people[1]), "a woman in her thirties with shoulder-length dark hair, wearing a grey sweater");
    type(byLabel("Name", people[2]), "the doorstep"); type(byLabel("The place", people[2]), "The dark blue front door of a red brick house, seen from the pavement in daylight");
  });
  await sleep(1500);
  await shot("film_cast");
  let film = await evaluate(`fetch("/api/films/${fid}").then(r => r.json())`);
  expect(film.cast.length === 2 && film.cast[0].name === "Sam" && film.locations[0].name === "the doorstep" && film.bible.logline.startsWith("A courier"), "the cast, the place and the logline were saved");

  await page(async ({ click, wait }) => { click("Shots"); await wait(900); });
  await page(async ({ byLabel, type, click, wait }) => { type(byLabel("A coverage plan"), "master-singles"); await wait(100); click("Add these shots"); });
  await sleep(1500);
  expect(await evaluate(`document.querySelectorAll(".shotrow").length`) === 3, "the coverage plan added three shots");
  await page(async ({ type, byLabel }) => { type(byLabel("What happens"), "Sam holds out a small brown parcel. Lisa opens the door and looks at it."); });
  await page(async ({ click, wait }) => { click("+ Line"); await wait(150); const rows = document.querySelectorAll(".linerow"); const last = rows[rows.length - 1]; const t = last.querySelectorAll("input")[0]; t.value = "Urgent delivery for you."; t.dispatchEvent(new Event("input", { bubbles: true })); });
  await sleep(1500);
  await shot("film_shots");
  film = await evaluate(`fetch("/api/films/${fid}").then(r => r.json())`);
  expect(film.shots.length === 3 && film.shots[0].action.startsWith("Sam holds out") && film.shots[0].cast.length === 2, "the edited shot was saved with its cast");

  await page(async ({ click, wait }) => { click("Storyboard"); await wait(600); });
  await shot("film_storyboard");
  await page(async ({ click, wait }) => { click("Roll camera"); await wait(1800); });
  const prompt = await evaluate(`(document.querySelector(".prompt") || {}).textContent || ""`);
  expect(prompt.includes("[Shot 1]") && prompt.includes("Sam, a courier") && prompt.includes("<d>[English] Urgent delivery for you.</d>"), "the preflight shows the composed prompt");
  await shot("film_roll");
  await page(async ({ click, wait }) => { click("Deliver"); await wait(600); });
  await shot("film_deliver");

  // Create > Video: the preview follows the form
  await evaluate(`location.hash = "#video"`);
  await sleep(1500);
  await page(async ({ type, byLabel, wait }) => { type(byLabel("What happens"), "A grey cat jumps onto a red bicycle. No dogs are in the yard."); type(byLabel("Camera"), "push-in"); await wait(1400); });
  const pv = await evaluate(`document.querySelector(".prompt").textContent`);
  expect(pv.includes("A grey cat jumps onto a red bicycle") && pv.includes("The camera pushes in slowly"), "the Video preview follows the form");
  expect((await evaluate(`[...document.querySelectorAll(".finding")].map(e => e.textContent).join(" | ")`)).includes("No dogs"), "the prompt check lists the thing forbidden by name");
  await shot("video_filled");

  await evaluate(`fetch("/api/films/${fid}", { method: "DELETE" })`);
}
