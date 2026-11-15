"""What H3 Studio Next adds on top of H3 Studio: favourites and folders, Recreate, canvas boards, the agent chat and
Shorts. Claude is replaced by a stand-in (writer.run_claude), so nothing is sent anywhere."""
import os
import unittest

from tests import env  # noqa: F401
from tests.test_api import Api as _Base
from studio import agent, films, library, writer


class Next(_Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.answers = []
        self.asked = []

        async def fake_claude(system, schema, text, timeout=0):
            self.asked.append((system, text))
            return self.answers.pop(0), {"seconds": 0.1, "model": "stand-in", "text": ""}
        self._real = writer.run_claude
        writer.run_claude = fake_claude

    async def asyncTearDown(self):
        writer.run_claude = self._real
        await super().asyncTearDown()

    async def pictures(self, n=2, prompt="A red bicycle."):
        j = await self.job((await self.call("POST", "/api/images", {"prompt": prompt, "takes": n, "width": 512, "height": 384, "seed": 7}))["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        return j["result"]["assets"]

    async def test_favourites_folders_and_the_summary(self):
        ids = await self.pictures(3, "A green tandem.")                 # the Library is shared with the other tests: count by search
        async def count(query):
            return len([a for a in (await self.call("GET", "/api/library?q=tandem&" + query))["items"] if a["id"] in ids])
        a = await self.call("PATCH", f"/api/library/{ids[0]}", {"favorite": True})
        self.assertTrue(a["favorite"])
        s0 = await self.call("GET", "/api/library/summary")
        f = await self.call("POST", "/api/folders", {"name": "Bikes"})
        await self.call("POST", "/api/folders", {"name": "bikes"}, expect=400)              # names are unique, any case
        await self.call("POST", "/api/library/bulk", {"ids": ids[:2], "action": "move", "folder": f["id"]})
        await self.call("POST", "/api/library/bulk", {"ids": [ids[1], "nope"], "action": "favorite"}, expect=404)   # all or nothing
        self.assertEqual(await count(f"folder={f['id']}"), 2)
        self.assertEqual(await count("folder=none&kind=image"), 1)
        self.assertEqual(await count("favorite=1"), 1)
        self.assertEqual(await count("kind=image,sheet"), 3)
        self.assertEqual(await count("kind=clip,audio"), 0)
        s = await self.call("GET", "/api/library/summary")
        self.assertEqual(s["favorites"], s0["favorites"])
        self.assertEqual(next(x for x in s["folders"] if x["id"] == f["id"])["count"], 2)
        await self.call("PATCH", f"/api/folders/{f['id']}", {"name": "Bicycles"})
        await self.call("DELETE", f"/api/folders/{f['id']}")
        self.assertFalse(any(library.get(i).get("folder") for i in ids))                   # the files stay, in no folder
        order = [a["id"] for a in (await self.call("GET", "/api/library?q=tandem&sort=oldest"))["items"] if a["id"] in ids]
        self.assertEqual(order, ids)

    async def test_a_picture_and_a_clip_keep_what_recreate_needs(self):
        ids = await self.pictures(1, "A lighthouse at dusk.")
        a = library.get(ids[0])
        self.assertEqual((a["form"]["prompt"], a["form"]["seed"], a["form"]["width"]), ("A lighthouse at dusk.", 7, 512))
        r = await self.call("POST", "/api/clips", {"action": "Waves roll in.", "width": 384, "height": 256, "frames": 124, "surface": "remix", "look": "cinematic"})
        j = await self.job(r["job"]["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        clip = library.get(films.load(r["film"])["asset"])
        self.assertEqual((clip["surface"], clip["form"]["action"], clip["form"]["frames"]), ("remix", "Waves roll in.", 124))
        self.assertEqual(len((await self.call("GET", "/api/library?surface=remix"))["items"]), 1)

    async def test_a_board_keeps_its_items_and_shows_missing_files(self):
        ids = await self.pictures(1)
        b = await self.call("POST", "/api/canvas", {"name": "Mood"})
        b = await self.call("PUT", f"/api/canvas/{b['id']}", {"name": "Mood board", "view": {"x": 10, "y": 20, "zoom": 9},
                            "items": [{"type": "asset", "asset": ids[0], "x": 1, "y": 2, "w": 300, "h": 200},
                                      {"type": "asset", "asset": "gone", "x": 0, "y": 0}, {"type": "note", "text": "hi", "color": "red"},
                                      {"type": "video"}, {"type": "asset"}]})
        self.assertEqual(len(b["items"]), 3)
        self.assertEqual(b["view"]["zoom"], 4)                                               # clamped
        self.assertEqual(b["items"][2]["color"], "yellow")                                   # an unknown colour falls back
        got = await self.call("GET", f"/api/canvas/{b['id']}")
        self.assertEqual(got["assets"][ids[0]]["id"], ids[0])
        self.assertIsNone(got["assets"]["gone"])
        listed = await self.call("GET", "/api/canvas")
        self.assertEqual((listed[0]["name"], listed[0]["items"], listed[0]["preview"]), ("Mood board", 3, [ids[0], "gone"]))
        await self.call("DELETE", f"/api/canvas/{b['id']}")
        await self.call("GET", f"/api/canvas/{b['id']}", expect=404)
        await self.call("GET", "/api/canvas/..%2Fsettings", expect=404)

    async def test_the_agent_asks_first_then_makes_and_shows_the_result(self):
        ids = await self.pictures(1, "A fox in the snow.")
        self.answers.append({"say": "Two takes coming up.", "actions": [
            {"tool": "make_picture", "why": "", "prompt": "A red fox at night.", "asset": "", "shape": "square", "count": 9,
             "seconds": 0, "sound": "", "lines": [], "story": ""},
            {"tool": "edit_picture", "why": "", "prompt": "At dawn.", "asset": "not-there", "shape": "landscape", "count": 1,
             "seconds": 0, "sound": "", "lines": [], "story": ""},
            {"tool": "animate_picture", "why": "", "prompt": "The fox looks up.", "asset": ids[0], "shape": "landscape", "count": 1,
             "seconds": 5, "sound": "Wind.", "lines": [{"speaker": "Narrator", "text": "Look."}], "story": ""}]})
        c = await self.call("POST", "/api/agent", {})
        c = await self.call("POST", f"/api/agent/{c['id']}/say", {"text": "make a fox"})
        self.assertIn(ids[0], self.asked[0][1])                                               # Claude sees the Library's ids
        acts = c["turns"][-1]["actions"]
        self.assertEqual([a["status"] for a in acts], ["proposed", "failed", "proposed"])     # nothing runs before Allow
        self.assertEqual(acts[0]["count"], 4)                                                 # at most 4 takes
        self.assertEqual(acts[2]["source"]["id"], ids[0])
        before = len(self.studio.queue.jobs)
        c = await self.call("POST", f"/api/agent/{c['id']}/act", {"action": acts[0]["id"], "allow": True})
        self.assertEqual(len(self.studio.queue.jobs), before + 1)
        c = await self.call("POST", f"/api/agent/{c['id']}/act", {"action": acts[2]["id"], "allow": False})
        self.assertEqual(c["turns"][-1]["actions"][2]["status"], "denied")
        await self.idle()
        c = await self.call("GET", f"/api/agent/{c['id']}")
        a0 = c["turns"][-1]["actions"][0]
        self.assertEqual((a0["status"], len(a0["assets"])), ("done", 4))
        self.assertEqual(library.get(a0["assets"][0]["id"])["surface"], "agent")
        await self.call("POST", f"/api/agent/{c['id']}/act", {"action": a0["id"], "allow": True}, expect=400)   # it already ran
        c = await self.call("POST", f"/api/agent/{c['id']}/act", {"action": acts[2]["id"], "allow": True})     # allowed after all
        await self.idle()
        c = await self.call("GET", f"/api/agent/{c['id']}")
        a2 = c["turns"][-1]["actions"][2]
        self.assertEqual(a2["status"], "done", a2.get("error"))
        f = films.load(a2["film"])
        self.assertTrue(f["shots"][0]["first_frame"].endswith(" [output]"))
        self.assertEqual(f["cast"][0]["name"], "Narrator")
        # with "ask first" off, the next answer's actions start straight away
        await self.call("PATCH", f"/api/agent/{c['id']}", {"ask_first": False})
        self.answers.append({"say": "On it.", "actions": [{"tool": "make_picture", "why": "", "prompt": "A hare.", "asset": "", "shape": "portrait",
                                                           "count": 1, "seconds": 0, "sound": "", "lines": [], "story": ""}]})
        c = await self.call("POST", f"/api/agent/{c['id']}/say", {"text": "and a hare"})
        self.assertIn(c["turns"][-1]["actions"][0]["status"], ("queued", "running", "done"))
        self.assertIn("make_picture", self.asked[-1][1])                                      # the earlier actions are in what Claude reads
        await self.idle()
        chats = await self.call("GET", "/api/agent")
        self.assertEqual(chats["chats"][0]["title"], "make a fox")
        await self.call("DELETE", f"/api/agent/{c['id']}")

    async def test_a_short_is_planned_then_rendered_as_one_take(self):
        self.answers.append({"title": "Last Light", "look": "cinematic", "place": "A lighthouse lantern room at dusk.",
                             "people": [{"name": "Elias", "description": "An old keeper."}],
                             "beats": [{"action": "Elias climbs in.", "sound": "Wind.", "lines": [{"speaker": "Elias", "text": "One more night."}]},
                                       {"action": "He pulls the lever.", "sound": "A hum.", "lines": []},
                                       {"action": "Too many.", "sound": "", "lines": []}]})
        r = await self.call("POST", "/api/shorts/plan", {"idea": "A keeper's last night.", "parts": 2})
        self.assertEqual(len(r["plan"]["beats"]), 2)
        await self.call("POST", "/api/shorts/plan", {"idea": " "}, expect=400)
        r = await self.call("POST", "/api/shorts", {"plan": r["plan"], "size": "384x640"})
        await self.idle()
        f = films.load(r["film"])
        self.assertEqual((f["surface"], len(f["shots"]), f["bible"]["width"], f["bible"]["height"]), ("shorts", 2, 384, 640))
        self.assertFalse(f["shots"][1]["new_shot"])                                           # the parts continue each other
        self.assertEqual(f["shots"][0]["lines"][0]["speaker"], f["cast"][0]["id"])
        self.assertEqual(f["form"]["short"]["title"], "Last Light")
        self.assertTrue(all(s["status"] in ("approved", "review") for s in f["shots"]), [s["status"] for s in f["shots"]])
        self.assertEqual(library.get(f["asset"])["surface"], "shorts")

    async def test_the_new_pages_are_served(self):
        for name in ("explore.js", "composer.js", "remix.js", "agent.js", "canvas.js", "library.js"):
            async with self.http.get(self.url + "/static/" + name) as r:
                self.assertEqual(r.status, 200, name)
        async with self.http.get(self.url + "/") as r:
            page = await r.text()
        self.assertIn('id="top"', page)
        self.assertIn("/static/agent.js", page)


for _name in dir(_Base):     # its own tests run in test_api.py; only these run here
    if _name.startswith("test_") and _name not in Next.__dict__:
        setattr(Next, _name, None)
del _Base

if __name__ == "__main__":
    unittest.main()
