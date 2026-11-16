"""What H3 Studio Next adds on top of H3 Studio: favourites and folders, Recreate, canvas boards, the agent chat and
Shorts. Claude is replaced by a stand-in (writer.run_claude), so nothing is sent anywhere."""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse

from tests import env  # noqa: F401
from tests.test_api import Api as _Base
from studio import agent, blockouts, config, films, library, writer


class Next(_Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.answers = []
        self.asked = []

        async def fake_claude(system, schema, text, timeout=0, progress=None):
            self.asked.append((system, text))
            if progress is not None:
                progress.update(phase="writing", chars=120)
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

    async def test_a_blockout_is_built_written_rendered_and_used(self):
        b = await self.call("POST", "/api/blockouts", {"name": "Walk"})
        self.assertEqual((b["state"]["error"], b["state"]["seconds"]), ("", 8.0))           # the starter scene is valid
        bad = await self.call("PUT", f"/api/blockouts/{b['id']}", {"scene": {**b["scene"], "camera": {"keys": [{"t": 0, "follow": "Nobody"}]}}})
        self.assertIn("Nobody", bad["state"]["error"])                                      # kept as edited, with what is wrong
        await self.call("POST", f"/api/blockouts/{b['id']}/make", {}, expect=400)
        scene = {"sky": "night", "ground": "snow", "set": [], "things": [{"name": "Car", "kind": "car", "color": "red", "scale": 1,
                 "keys": [{"t": 0, "at": [0, 0, 0], "face": None, "pose": "stand"}, {"t": 3, "at": [20, 0, 0], "face": None, "pose": "stand"}]}],
                 "camera": {"lens": 35, "shake": 0, "keys": [{"t": 0, "at": [10, -8, 1.6], "look_at": [0, 0, 0], "follow": "Car", "lens": 0, "cut": False}]}}
        self.answers.append({"say": "A red car drives past.", "scene": scene})
        self.answers.append({"say": "A red car drives past.", "scene": scene})
        old = await self.call("POST", "/api/blockouts/write", {"idea": "a red car drives past", "scene": bad["scene"]})
        self.assertEqual(old["scene"]["things"][0]["name"], "Car")                         # an older page gets the scene itself
        t = await self.call("POST", "/api/blockouts/write", {"idea": "a red car drives past", "scene": bad["scene"], "size": "1152x640", "progress": True})
        self.assertGreater(t["expect"], 200)                                                # about as long as the scene it changes
        for _ in range(100):
            t = await self.call("GET", f"/api/blockouts/write/{t['task']}")
            if t["done"]:
                break
            await asyncio.sleep(0.02)
        self.assertEqual((t["error"], t["phase"], t["chars"]), ("", "writing", 120))
        r = t["result"]
        self.assertFalse(t["saved"])                                                        # no blockout given: nothing saved
        self.answers.append({"say": "A red car drives past.", "scene": scene})
        t = await self.call("POST", "/api/blockouts/write", {"idea": "a red car", "scene": bad["scene"], "blockout": b["id"], "progress": True})
        for _ in range(100):
            t = await self.call("GET", f"/api/blockouts/write/{t['task']}")
            if t["done"]:
                break
            await asyncio.sleep(0.02)
        saved = await self.call("GET", f"/api/blockouts/{b['id']}")                       # the studio saved it itself
        self.assertEqual((t["saved"], saved["scene"]["sky"], saved["write"]), (True, "night", None))
        self.assertTrue(saved["idea"].endswith("a red car"))
        self.assertEqual((await self.call("GET", f"/api/blockouts/{b['id']}/versions"))[0]["why"], "words")
        self.assertEqual((r["problem"], r["scene"]["things"][0]["name"]), ("", "Car"))
        self.assertIn("The current scene", self.asked[-1][1])                               # it changes the scene it is given
        await self.call("POST", "/api/blockouts/write", {"idea": " "}, expect=400)
        b = await self.call("PUT", f"/api/blockouts/{b['id']}", {"scene": r["scene"], "size": "640x1152", "name": "Car"})
        self.assertEqual((b["state"]["error"], b["state"]["frames"], b["size"]), ("", 73, "640x1152"))
        # a stand-in Blender: writes the frames the studio asks for and the stats file
        fake = os.path.join(config.home(), "fake_blender.py")
        with open(fake, "w") as fh:
            fh.write("#!/usr/bin/env python3\nimport sys, json, os, subprocess\na = sys.argv[sys.argv.index('--') + 1:]\nout, n, w, h = a[1], int(a[2]), a[3], a[4]\n"
                     "subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=gray:s={w}x{h}:d=1', '-frames:v', str(n), '-vf', 'loop=-1:1', os.path.join(out, 'f_%04d.png')], check=True)\n"
                     "json.dump({'Car': {'followed': True, 'in_view': 1.0, 'median': 0.1, 'max': 0.2, 'side': 'middle'}}, open(os.path.join(out, 'stats.json'), 'w'))\n")
        os.chmod(fake, 0o755)
        config.update({"blender": fake})
        try:
            j = await self.job((await self.call("POST", f"/api/blockouts/{b['id']}/make", {}))["id"])
        finally:
            config.update({"blender": ""})
        self.assertEqual(j["status"], "done", j.get("error"))
        a = library.get(j["result"]["assets"][0])
        self.assertEqual((a["kind"], a["surface"], a["form"]["blockout_shapes"]), ("clip", "blockout", ""))                 # "the car stands for Car" says nothing
        self.assertTrue(j["result"]["small"])                                               # the car is too small in the picture
        got = await self.call("GET", f"/api/blockouts/{b['id']}")
        self.assertTrue(got["state"]["current"])
        self.assertTrue(got["video"].endswith("blockout.mp4 [output]"))
        listed = await self.call("GET", "/api/blockouts")
        self.assertEqual(listed["items"][0]["asset"], a["id"])
        await self.call("DELETE", f"/api/blockouts/{b['id']}")
        await self.call("GET", f"/api/blockouts/{b['id']}", expect=404)
        await self.call("GET", "/api/blockouts/..%2Fsettings", expect=404)

    def test_cars_come_in_shapes_with_a_driver(self):
        keys = [{"t": 0, "at": [0, 0, 0], "face": None, "pose": "stand"}]
        sc = blockouts.normalize({"things": [{"name": "A", "kind": "sports car", "color": "orange", "driver": "red", "keys": keys},
                                             {"name": "B", "kind": "van", "driver": "red", "keys": keys},
                                             {"name": "C", "kind": "suv", "keys": keys}],
                                  "camera": {"keys": [{"t": 0, "at": [5, 5, 2], "look_at": [0, 0, 1]}]}})
        self.assertEqual([t["driver"] for t in sc["things"]], ["red", "", ""])                   # only cars have a driver
        shapes = json.load(open(os.path.join(os.path.dirname(blockouts.__file__), "static", "car_shapes.json")))
        self.assertEqual(sorted(shapes), sorted(blockouts.CARS))                                 # Blender and the 3D view share them
        for k, shp in shapes.items():
            self.assertTrue(any(p["c"] == "tinted glass" for p in shp["parts"]), k)              # the driver can be seen
            self.assertEqual(sum(p["p"] == "wheel" for p in shp["parts"]), 4, k)

    async def test_the_writer_list_skips_files_that_are_not_conversations(self):
        config.write_json(os.path.join(config.home("writer"), "blockout_write_stats.json"), {"runs": [1, 2]})
        r = await self.call("GET", "/api/writer")
        self.assertIsInstance(r["conversations"], list)

    async def test_a_clip_follows_a_whole_blockout_in_parts(self):
        d = config.home("blockouts", "free_bo0123456789_abcdef")
        os.makedirs(d, exist_ok=True)
        keys = [{"t": 0, "at": [0, 0, 0], "face": None, "pose": "stand"}, {"t": 57, "at": [200, 0, 0], "face": None, "pose": "stand"}]
        cam = [{"t": t, "at": [5, -8, 1.6], "look_at": [0, 0, 1], "follow": "", "lens": 0, "cut": t > 0} for t in (0, 6, 10, 13, 16, 25, 29.4, 34.5, 44.4, 48.6)]
        config.write_json(os.path.join(d, "scene.json"), blockouts.normalize({"things": [{"name": "Car", "kind": "coupe", "keys": keys}], "camera": {"keys": cam}}))
        ref = config.out_ref(os.path.join(d, "blockout.mp4"))
        plan = await self.call("GET", "/api/blockout_parts?ref=" + urllib.parse.quote(ref))
        self.assertEqual((plan["total"], len(plan["parts"])), (1369, 5))
        self.answers.append({"parts": [{"action": f"Step {i + 1}."} for i in range(5)]})
        r = await self.call("POST", "/api/clips", {"action": "They race.", "width": 384, "height": 256, "frames": 345,
                                                   "blockout": ref, "whole_blockout": True})
        f = await self.call("GET", f"/api/films/{r['film']}")
        self.assertEqual([s["action"] for s in f["shots"]], [f"Step {i + 1}." for i in range(5)])   # each its own stretch
        self.assertIn("part 2: 13.0 to 24.5 s", self.asked[-1][1])
        self.assertEqual([(s["frames"], s["blockout_start"], s["new_shot"]) for s in f["shots"]],
                         [(p["frames"], p["start"] if p["new_shot"] else 0, p["new_shot"]) for p in plan["parts"]])
        self.assertTrue(all(s["blockout"] == ref for s in f["shots"]))
        await self.call("POST", f"/api/films/{r['film']}/stop", {})
        one = await self.call("POST", "/api/clips", {"action": "x", "width": 384, "height": 256, "frames": 345, "blockout": ref})
        self.assertIn("job", one)                                                       # without it: one part
        await self.call("POST", f"/api/clips/{one['film']}/cover_blockout", {})        # no answer: the parts keep the words
        self.assertEqual(len((await self.call("GET", f"/api/films/{one['film']}"))["shots"]), 5)

    async def test_earlier_blockout_versions_are_kept_and_restored(self):
        b = await self.call("POST", "/api/blockouts", {"name": "Keep"})
        full = b["scene"]
        moved = json.loads(json.dumps(full))
        moved["things"][0]["keys"][0]["at"] = [30, 1, 0]
        await self.call("PUT", f"/api/blockouts/{b['id']}", {"scene": moved})                 # an edit: the starter is kept
        moved2 = json.loads(json.dumps(moved))
        moved2["things"][0]["keys"][0]["at"] = [31, 1, 0]
        await self.call("PUT", f"/api/blockouts/{b['id']}", {"scene": moved2})                # soon after: one version for both
        self.assertEqual(len(await self.call("GET", f"/api/blockouts/{b['id']}/versions")), 1)
        empty = {"set": [], "things": [], "camera": {"lens": 35, "shake": 0, "keys": []}}
        await self.call("PUT", f"/api/blockouts/{b['id']}", {"scene": empty})                 # most of it goes: always kept
        vs = await self.call("GET", f"/api/blockouts/{b['id']}/versions")
        self.assertEqual([(v["why"], v["things"], v["set"]) for v in vs], [("edits", 1, 1), ("edits", 1, 1)])
        back = await self.call("POST", f"/api/blockouts/{b['id']}/versions/{vs[0]['id']}", {})
        self.assertEqual(back["scene"], moved2)
        await self.call("POST", f"/api/blockouts/{b['id']}/versions/123", {}, expect=404)
        await self.call("PUT", f"/api/blockouts/{b['id']}", {"scene": moved, "why": "words"})  # a change in words: kept
        self.assertEqual((await self.call("GET", f"/api/blockouts/{b['id']}/versions"))[0]["why"], "words")
        await self.call("DELETE", f"/api/blockouts/{b['id']}")
        self.assertFalse(os.path.exists(os.path.join(config.home("blockout_scenes"), "versions", b["id"])))

    async def test_every_answer_says_which_build_of_the_page_is_current(self):
        async with self.http.get(self.url + "/api/blockouts") as r:
            self.assertRegex(r.headers.get("X-Studio-Build") or "", r"^[0-9a-f]{12}$")

    async def test_a_blockout_goes_to_blender_and_comes_back(self):
        b = await self.call("POST", "/api/blockouts", {"name": "Walk"})
        fake = os.path.join(config.home(), "fake_blender_gui.sh")
        with open(fake, "w") as fh:
            fh.write("#!/bin/sh\necho \"$@\" > \"$(dirname \"$0\")/blender_args.txt\"\n")
        os.chmod(fake, 0o755)
        config.update({"blender": fake})
        try:
            r = await self.call("POST", f"/api/blockouts/{b['id']}/blender", {})
        finally:
            config.update({"blender": ""})
        self.assertTrue(r["opened"])
        for _ in range(100):
            if os.path.exists(os.path.join(config.home(), "blender_args.txt")):
                break
            await asyncio.sleep(0.05)
        args = open(os.path.join(config.home(), "blender_args.txt")).read().split()
        self.assertEqual(args[0], "-P")
        self.assertTrue(args[1].endswith("blockout_edit.py"))
        self.assertEqual(args[4:7], ["193", "1152", "640"])                                  # frames, width, height
        self.assertEqual(args[8], b["id"])
        self.assertEqual(json.load(open(args[3]))["things"][0]["name"], "Walker")           # the scene, normalized
        scene = json.loads(json.dumps(b["scene"]))
        scene["things"][0]["keys"][0]["at"] = [20, 1, 0]
        back = await self.call("POST", f"/api/blockouts/{b['id']}/from_blender", {"scene": scene})
        self.assertGreater(back["blender_at"], 0)
        self.assertEqual(back["scene"]["things"][0]["keys"][0]["at"], [20, 1, 0])
        await self.call("POST", f"/api/blockouts/{b['id']}/from_blender", {"scene": "x"}, expect=400)
        bad = await self.call("PUT", f"/api/blockouts/{b['id']}", {"scene": {"camera": {"keys": []}}})
        await self.call("POST", f"/api/blockouts/{b['id']}/blender", {}, expect=400)          # a broken scene does not open
        self.assertTrue(bad["state"]["error"])

    @unittest.skipUnless(shutil.which("blender"), "Blender is not installed")
    def test_the_blender_edit_script_reads_back_what_it_built(self):
        scene = blockouts.normalize({"sky": "dusk", "ground": "asphalt",
            "set": [{"type": "street", "name": "main", "at": [-40, 0, 0], "size": [80, 12, 10], "turn": 0, "color": "brick"},
                    {"type": "box", "name": "crate", "at": [3, 2, 0], "size": [1, 2, 1.5], "turn": 30, "color": "wood"}],
            "things": [{"name": "Car", "kind": "car", "color": "red", "scale": 1, "keys": [
                {"t": 0, "at": [-20, -2, 0], "face": None, "pose": "stand"}, {"t": 4, "at": [10, -2, 0], "face": None, "pose": "stand"},
                {"t": 6, "at": [10, 8, 0], "face": 90, "pose": "stand"}]},
                       {"name": "Ann", "kind": "person", "color": "blue", "scale": 1, "keys": [{"t": 0, "at": [2, 4, 0], "face": None, "pose": "wave"}]}],
            "camera": {"lens": 35, "shake": 0, "keys": [{"t": 0, "at": [0, -10, 1.6], "look_at": [0, 0, 1], "follow": "Car", "lens": 0, "cut": False},
                                                        {"t": 3, "at": [5, -10, 2], "look_at": [4, 0, 1], "follow": "", "lens": 50, "cut": True}]}})
        d = tempfile.mkdtemp(dir=config.home())
        src, out, edits = (os.path.join(d, n) for n in ("in.json", "out.json", "edits.py"))
        json.dump(scene, open(src, "w"))
        with open(edits, "w") as fh:
            fh.write('car = bpy.data.objects["Car"]\nsc.frame_set(49)\ncar.location = (0, 0, 0)\ncar.keyframe_insert("location", frame=49)\n'
                     'bpy.data.objects["Ann"].name = "Anna"\n')
        script = os.path.join(os.path.dirname(blockouts.SCRIPT), "blockout_edit.py")
        r = subprocess.run(["blender", "-b", "--factory-startup", "-P", script, "--", src, "145", "640", "352", "http://127.0.0.1:9", "x", os.path.join(d, "x.blend")],
                           env={**os.environ, "H3_BLOCKOUT_DUMP": out, "H3_BLOCKOUT_EDITS": edits}, capture_output=True, text=True, timeout=180)
        self.assertTrue(os.path.exists(out), r.stdout[-2000:] + r.stderr[-2000:])
        got = blockouts.normalize(json.load(open(out)))
        car = next(t for t in got["things"] if t["name"] == "Car")
        self.assertEqual([k["t"] for k in car["keys"]], [0, 2.0, 4, 6])                     # the key added at frame 49
        self.assertEqual(car["keys"][1]["at"], [0, 0, 0])
        self.assertEqual([k["face"] for k in car["keys"]][::2], [None, None])                # untouched facings stay automatic
        self.assertEqual(car["keys"][3]["face"], 90)
        self.assertEqual(next(t for t in got["things"] if t["name"] == "Anna")["keys"][0]["pose"], "wave")
        crate = next(i for i in got["set"] if i["name"] == "crate")
        self.assertEqual((crate["at"], crate["size"], round(crate["turn"])), ([3, 2, 0], [1, 2, 1.5], 30))
        cam = got["camera"]["keys"]
        self.assertEqual([(k["t"], k["follow"], k["lens"], k["cut"]) for k in cam], [(0, "Car", 0, False), (3, "", 50, True)])
        self.assertEqual(cam[1]["look_at"], [4, 0, 1])

    async def test_the_new_pages_are_served(self):
        for name in ("explore.js", "composer.js", "remix.js", "agent.js", "canvas.js", "library.js", "blockout.js", "vendor/three-0.170.0.module.min.js"):
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
