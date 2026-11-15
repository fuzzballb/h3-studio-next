"""The whole studio through its HTTP API, against a stand-in ComfyUI that writes synthetic clips: the queue, the
checks, the gate, takes, the order of parts, runs, the night shift, timelines. No GPU, no models, no Whisper."""
import asyncio
import os
import signal
import types
import unittest

import aiohttp
from aiohttp import web

from tests import env, media  # noqa: F401
from tests.fake_comfy import FakeComfy
from studio import checks, config, films, machine, server

checks.whisper_available = lambda: False          # speech is "skip" here; the Whisper path is covered by tests/live


class Api(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = await FakeComfy().start()
        config.update({"comfy_url": self.fake.url, "gate": {"auto_approve": False, "retries": 0}})
        self.app = server.make_app()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:%d" % site._server.sockets[0].getsockname()[1]
        self.http = aiohttp.ClientSession()
        self.studio = self.app[server.STUDIO]

    async def asyncTearDown(self):
        await self.http.close()
        await self.runner.cleanup()
        await self.fake.stop()

    async def call(self, method, path, data=None, expect=200, headers=None):
        async with self.http.request(method, self.url + path, json=data, headers=headers) as r:
            body = await r.json()
            self.assertEqual(r.status, expect, f"{method} {path}: {body}")
            return body

    async def job(self, jid, timeout=60):
        for _ in range(int(timeout / 0.05)):
            j = await self.call("GET", f"/api/jobs/{jid}")
            if j["status"] in ("done", "failed", "cancelled"):
                return j
            await asyncio.sleep(0.05)
        self.fail("job did not finish")

    async def idle(self, timeout=90):
        """Wait until nothing is queued or running (a run queues its next shot from a callback)."""
        quiet = 0
        for _ in range(int(timeout / 0.05)):
            quiet = 0 if (self.studio.queue.busy("gpu") or self.studio.queue.busy("cpu")) else quiet + 1
            if quiet > 6:
                return
            await asyncio.sleep(0.05)
        self.fail("the queue did not go idle")

    async def new_film(self, name, shots, **bible):
        f = await self.call("POST", "/api/films", {"name": name, "bible": {"width": 384, "height": 256, "frames": 124, **bible}})
        r = await self.call("PUT", f"/api/films/{f['id']}", {"shots": [{"id": f"s{i + 1}", "title": f"shot {i + 1}", "action": "Something happens.", **s} for i, s in enumerate(shots)]})
        return r["film"]

    # ------------------------------------------------------------------ basics
    async def test_state_machine_presets_and_the_guard(self):
        st = await self.call("GET", "/api/state")
        self.assertTrue(st["comfy"]["up"])
        m = await self.call("GET", "/api/machine")
        self.assertTrue(all(f["ok"] for f in m["features"].values()))
        self.assertEqual(len(m["roles"]), 12)
        p = await self.call("GET", "/api/presets")
        self.assertIn("cameras", p)
        self.assertEqual(len(p["lengths"]), 21)
        await self.call("POST", "/api/jobs", {"kind": "image", "params": {"prompt": "x"}}, expect=403, headers={"Origin": "http://evil.example"})
        await self.call("GET", "/api/state", expect=403, headers={"Host": "evil.example"})

    async def test_a_changed_script_reaches_the_browser_on_reload(self):
        # each script's address carries the time the file changed, and nothing of the page is kept without asking
        async with self.http.get(self.url + "/") as r:
            html = await r.text()
            self.assertEqual(r.headers["Cache-Control"], "no-cache")
        app_js = os.path.join(config.STATIC, "app.js")
        self.assertIn(f'src="/static/app.js?v={int(os.path.getmtime(app_js))}"', html)
        self.assertNotRegex(html, r'"/static/[\w.-]+"')                       # no address without its stamp
        async with self.http.get(self.url + "/static/app.js?v=1") as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers["Cache-Control"], "no-cache")
            tag = r.headers["ETag"]
        async with self.http.get(self.url + "/static/app.js?v=1", headers={"If-None-Match": tag}) as r:
            self.assertEqual(r.status, 304)                                    # unchanged: an empty answer

    # ------------------------------------------------------------------ ComfyUI's terminal output, and starting it
    async def test_comfy_output_live_then_from_its_log_file(self):
        out = await self.call("GET", "/api/machine/comfy/output")
        self.assertTrue(out["up"] and out["live"])
        self.assertEqual(out["text"], "".join(self.fake.printed))            # colour codes and carriage returns as printed
        # ComfyUI is gone: the end of the log file its start left, from a whole line
        log = config.home("logs", "comfyui_stdout.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w") as f:
            f.write("x" * 70_000 + "\nTraceback (most recent call last):\nMemoryError\n")
        self.studio.comfy.url = "http://127.0.0.1:9"                          # nothing answers there
        out = await self.call("GET", "/api/machine/comfy/output")
        self.assertFalse(out["up"] or out["live"] or out["starting"])
        self.assertEqual(out["source"], os.path.join("output", "studio_next", "logs", "comfyui_stdout.log"))
        self.assertEqual(out["text"], "Traceback (most recent call last):\nMemoryError\n")
        self.assertGreater(out["written"], 0)
        # a ComfyUI on another machine left nothing on this one
        self.assertEqual(machine.Machine(types.SimpleNamespace(url="http://192.0.2.7:8188")).log_files(), [])

    async def test_comfyui_is_started_once_and_shows_as_starting(self):
        starts = os.path.join(env.ROOT, "starts.txt")
        self.studio.comfy.url = "http://127.0.0.1:9"
        config.update({"comfy_start": f"echo loading models; echo x >> '{starts}'; exec sleep 30"})
        m = self.studio.machine
        try:
            both = await asyncio.gather(m.start_comfy(wait=0.4), m.start_comfy(wait=0.4), return_exceptions=True)
            self.assertTrue(all(isinstance(r, ValueError) and "did not answer" in str(r) for r in both), both)
            with self.assertRaises(ValueError):
                await m.start_comfy(wait=0.1)                                 # asked again while it loads
            with open(starts) as f:
                self.assertEqual(f.read(), "x\n")                             # three requests, one ComfyUI
            st = await self.call("GET", "/api/state")
            self.assertTrue(st["comfy"]["starting"] and not st["comfy"]["up"])
            out = await self.call("GET", "/api/machine/comfy/output")
            self.assertTrue(out["starting"] and not out["live"])
            self.assertEqual(out["text"], "loading models\n")
        finally:
            config.update({"comfy_start": ""})
            if m.proc:
                os.killpg(os.getpgid(m.proc.pid), signal.SIGTERM)
                m.proc.wait()
        st = await self.call("GET", "/api/state")
        self.assertFalse(st["comfy"]["starting"])                             # it died: not "starting" any more
        async with self.http.get(self.url + "/media/../../etc/hostname") as r:
            self.assertEqual(r.status, 404)
        async with self.http.get(self.url + "/") as r:
            self.assertIn("H3 Studio", await r.text())
        c = await self.call("POST", "/api/prompt/check", {"prompt": "Static shot. The camera pans left. No photographs on the wall."})
        self.assertEqual(c["forbids"], ["No photographs"])
        await self.call("PUT", "/api/settings", {"no_such_setting": 1}, expect=400)

    async def test_pictures_edits_and_angles_land_in_the_library(self):
        j = await self.job((await self.call("POST", "/api/images", {"prompt": "A red bicycle.", "takes": 2, "name": "bike"}))["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(len(j["result"]["assets"]), 2)
        a = await self.call("GET", f"/api/library/{j['result']['assets'][0]}")
        self.assertEqual((a["kind"], a["prompt"]), ("image", "A red bicycle."))
        self.assertTrue(a["ref"].endswith(" [output]"))
        j = await self.job((await self.call("POST", "/api/images", {"pictures": [a["ref"]], "angles": ["left", "back"], "keep_size": True}))["id"])
        self.assertEqual(len(j["result"]["assets"]), 2)
        graph = self.fake.prompts[-1]
        self.assertEqual(graph["61"]["inputs"]["image"], a["ref"])                    # the edit loads the picture from output/
        self.assertEqual(graph["6"]["inputs"]["latent_image"], ["4", 2])              # and keeps its shape
        self.assertIn("seen straight from behind", graph["4"]["inputs"]["prompt"])
        j = await self.job((await self.call("POST", "/api/images", {"pictures": ["not_there.png"], "prompt": "x"}))["id"])
        self.assertEqual(j["status"], "failed")
        self.assertIn("missing file(s): not_there.png", j["error"])
        async with self.http.get(self.url + a["thumb"]) as r:
            self.assertEqual((r.status, r.content_type), (200, "image/jpeg"))
        got = await self.call("GET", "/api/library?q=bicycle")
        self.assertEqual(len(got["items"]), 2)

    async def test_upload(self):
        form = aiohttp.FormData()
        form.add_field("file", open(media.picture(os.path.join(env.ROOT, "face.png")), "rb"), filename="My Face.png")
        async with self.http.post(self.url + "/api/upload", data=form) as r:
            body = await r.json()
            self.assertEqual(r.status, 200, body)
        self.assertTrue(body["items"][0]["path"].startswith("studio_next/uploads/my_face_"), body["items"][0]["path"])
        bad = aiohttp.FormData()
        bad.add_field("file", b"#!/bin/sh", filename="x.sh")
        async with self.http.post(self.url + "/api/upload", data=bad) as r:
            self.assertEqual(r.status, 400)

    # ------------------------------------------------------------------ a quick clip, extended
    async def test_a_clip_is_checked_and_can_be_extended_and_a_jump_at_the_join_is_caught(self):
        r = await self.call("POST", "/api/clips", {"name": "duck", "action": "A duck swims past.", "width": 384, "height": 256, "frames": 73, "seed": 5})
        j = await self.job(r["job"]["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertTrue(j["result"]["ok"])
        f = await self.call("GET", f"/api/films/{r['film']}")
        t = f["shots"][0]["takes"][0]
        self.assertEqual((f["quick"], f["shots"][0]["status"], t["seed"], t["verdict"]), (True, "approved", 5, "auto"))
        self.assertEqual({c["name"]: c["status"] for c in t["checks"]["checks"]}, {"cuts": "pass", "speech": "skip", "loudness": "pass"})
        self.assertTrue(os.path.isfile(os.path.join(config.OUTPUT_DIR, t["preview"])))
        self.assertTrue(os.path.isfile(os.path.join(config.OUTPUT_DIR, t["sheet"])))
        self.assertIn("A duck swims past.", t["prompt"])

        j = await self.job((await self.call("POST", f"/api/clips/{r['film']}/extend", {"action": "The duck dives.", "frames": 124}))["job"]["id"])
        self.assertTrue(j["result"]["ok"], j["result"])
        f = await self.call("GET", f"/api/films/{r['film']}")
        t2 = f["shots"][1]["takes"][0]
        self.assertTrue(t2["continuation"])
        self.assertEqual([c["status"] for c in t2["checks"]["checks"] if c["name"] == "join"], ["pass"])
        self.assertAlmostEqual(t2["duration"], (124 - 39) / 24, delta=0.1)           # a continuation adds 39 frames less
        self.assertAlmostEqual(checks.probe(os.path.join(config.OUTPUT_DIR, f["full"]))["duration"], 73 / 24 + 85 / 24, delta=0.2)

        self.fake.jump_next = True                                                    # the model swaps the background
        j = await self.job((await self.call("POST", f"/api/films/{r['film']}/render/{f['shots'][1]['id']}", {"force": True}))["id"])
        self.assertFalse(j["result"]["ok"])
        self.assertIn("jumps at the join", j["result"]["summary"])
        lib = await self.call("GET", "/api/library?q=duck")
        self.assertEqual([(a["kind"], a["ok"]) for a in lib["items"]], [("clip", False)])          # one Library item for the whole clip

        out = await self.call("POST", "/api/library/trash", {"ids": [lib["items"][0]["id"]]})    # deleting it deletes the quick film
        self.assertEqual(len(out["moved"]), 1)
        await self.call("GET", f"/api/films/{r['film']}", expect=404)

    async def test_a_short_continuation_is_replaced_by_a_length_that_fits(self):
        r = await self.call("POST", "/api/clips", {"action": "x", "width": 384, "height": 256, "frames": 73})
        await self.job(r["job"]["id"])
        j = await self.job((await self.call("POST", f"/api/clips/{r['film']}/extend", {"action": "y", "frames": 73}))["job"]["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        f = await self.call("GET", f"/api/films/{r['film']}")
        self.assertEqual(f["shots"][1]["takes"][0]["frames"], 90)

    # ------------------------------------------------------------------ shots that follow a blockout
    async def test_a_blockout_shot_and_its_continuation_follow_one_stretch_of_it(self):
        src = media.clip(config.home("uploads", "blockout_api.mp4"), seconds=10.0, size="384x256", audio=False)
        blk = config.out_ref(src)
        f = await self.new_film("Blockout", [{"blockout": blk, "blockout_shapes": "the box is a car"},
                                             {"blockout": blk, "new_shot": False}, {"new_shot": True}])
        fid = f["id"]
        pre = await self.call("POST", f"/api/films/{fid}/compose/s2", {})
        self.assertEqual((pre["blockout"]["start"], pre["blockout"]["end"]), (124 - 39, 124 - 39 + 124))
        self.assertIn("<Video 1> is a rough 3D blockout", pre["prompt"])
        j = await self.job((await self.call("POST", f"/api/films/{fid}/render/s1", {}))["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        g = self.fake.prompts[-1]
        load = next(n for n in g.values() if n["class_type"] == "VHS_LoadVideoPath")["inputs"]
        self.assertEqual((load["skip_first_frames"], load["frame_load_cap"]), (0, 124))
        self.assertTrue(load["video"].endswith("_24fps.mkv") and os.path.isfile(load["video"]))
        await self.call("POST", f"/api/films/{fid}/approve/s1", {})
        j = await self.job((await self.call("POST", f"/api/films/{fid}/render/s2", {}))["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        g = self.fake.prompts[-1]
        self.assertEqual(next(n for n in g.values() if n["class_type"] == "VHS_LoadVideoPath")["inputs"]["skip_first_frames"], 85)
        cont = next(n for n in g.values() if n["class_type"] == "H3LongVideoContinue")["inputs"]
        self.assertEqual((cont["new_shot"], cont["keep_latent_mask"]), (False, True))
        await self.call("POST", f"/api/films/{fid}/approve/s2", {})
        await self.job((await self.call("POST", f"/api/films/{fid}/render/s3", {}))["id"])
        self.assertIn("PK_MiniMaxH3Combined", [n["class_type"] for n in self.fake.prompts[-1].values()])   # no blockout: as before
        # the Video room: a clip on a blockout, as a long take that reads on in it
        pre = await self.call("POST", "/api/compose", {"action": "A car drives.", "blockout": blk, "blockout_shapes": "the box is a car",
                                                       "width": 384, "height": 256, "frames": 124})
        self.assertEqual((pre["blockout"]["start"], pre["blockout"]["end"], pre["blockout"]["frames"]), (0, 124, 240))
        self.assertIn("placeholders: the box is a car", pre["prompt"])
        r = await self.call("POST", "/api/clips", {"action": "A car drives.", "blockout": blk, "width": 384, "height": 256, "frames": 124,
                                                   "beats": ["It stops."]})
        f = await self.call("GET", f"/api/films/{r['film']}")
        self.assertEqual([x["blockout"] for x in f["shots"]], [blk, blk])
        pre = await self.call("POST", f"/api/films/{r['film']}/compose/{f['shots'][1]['id']}", {})
        self.assertEqual(pre["blockout"]["start"], 85)
        await self.call("POST", f"/api/films/{r['film']}/stop", {})
        # a blockout too short for the part is refused before anything is queued
        short = config.out_ref(media.clip(config.home("uploads", "blockout_short.mp4"), seconds=1.0, size="384x256", audio=False))
        f = await self.new_film("Short", [{"blockout": short}])
        n = len(self.fake.prompts)
        j = await self.job((await self.call("POST", f"/api/films/{f['id']}/render/s1", {}))["id"])
        self.assertEqual(j["status"], "failed")
        self.assertIn("the blockout has 24 frames", j["error"])
        self.assertEqual(len(self.fake.prompts), n)

    @unittest.skipUnless(__import__("shutil").which("blender"), "Blender is not installed")
    async def test_a_scene_blockout_is_made_in_blender_and_cut_into_its_shots(self):
        from tests.test_units import SCENE
        f = await self.new_film("Made blockout", [{"scene": "1"}, {"scene": "1", "new_shot": False}], width=256, height=160, frames=73)
        fid = f["id"]
        r = await self.call("PUT", f"/api/films/{fid}", {"blockouts": [{"id": "bk1", "scene_name": "1", "scene": SCENE, "cuts": {}}]})
        self.assertEqual(r["film"]["blockouts"][0]["state"]["made"], False)
        self.assertEqual([c["start"] for c in r["film"]["blockouts"][0]["stretches"]], [0, 73 - 39])
        self.assertEqual(next(s for s in r["film"]["steps"] if s["id"] == "blockout")["optional"], False)   # started: not optional
        pre = await self.call("POST", f"/api/films/{fid}/compose/s1", {})
        self.assertIn("blockout-not-made", [x["code"] for x in pre["findings"]])
        j = await self.job((await self.call("POST", f"/api/films/{fid}/render/s1", {}))["id"])
        self.assertIn("not made yet", j["error"])
        bad = await self.call("POST", "/api/blockout/check", {"scene": {"sky": "noon"}})
        self.assertIn("sky", bad["error"])
        j = await self.job((await self.call("POST", f"/api/films/{fid}/blockouts/bk1/make", {}))["id"], timeout=300)
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(j["result"]["frames"], 8 * 24 + 1)       # the scene runs 8 s, longer than its shots (73 + 90 - 39)
        f = await self.call("GET", f"/api/films/{fid}")
        b = f["blockouts"][0]
        self.assertEqual(b["video"], j["result"]["blockout"])
        self.assertTrue(b["state"]["current"])
        self.assertEqual([s["blockout"] for s in f["shots"]], ["", ""])          # the shots follow the scene's, not a copy
        path = config.ref_path(j["result"]["blockout"])
        import subprocess
        n = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
                            "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
        self.assertEqual(int(n), 193)
        pre = await self.call("POST", f"/api/films/{fid}/compose/s2", {})
        self.assertEqual((pre["blockout"]["file"], pre["blockout"]["start"]), (b["video"], 73 - 39))
        # the old per-shot route makes the blockout of the shot's scene
        j = await self.job((await self.call("POST", f"/api/films/{fid}/blockout/s2", {}))["id"], timeout=300)
        self.assertEqual(j["result"]["blockout_id"], "bk1")

    async def test_a_preview_is_small_stays_out_of_the_film_and_continues_the_take(self):
        f = await self.new_film("Preview", [{"new_shot": True}, {"new_shot": False}, {"new_shot": True}], width=1152, height=640, frames=124)
        fid = f["id"]
        j = await self.job((await self.call("POST", f"/api/films/{fid}/preview/s2", {}))["jobs"][0]["id"])
        self.assertEqual(j["status"], "failed")
        self.assertIn("preview that one first", j["error"])
        r = await self.call("POST", f"/api/films/{fid}/preview/s2", {"take": True})
        self.assertEqual(len(r["jobs"]), 2)
        for x in r["jobs"]:
            j = await self.job(x["id"])
            self.assertEqual(j["status"], "done", j.get("error"))
        g = self.fake.prompts[-1]
        enc = next(n for n in g.values() if n["class_type"] == "PK_MiniMaxH3Combined")["inputs"]
        self.assertEqual((enc["width"], enc["height"]), (448, 256))
        cont = next(n for n in g.values() if n["class_type"] == "H3LongVideoContinue")["inputs"]
        self.assertEqual((cont["project"], cont["part"], cont["new_shot"]), (f"{f['long_project']}_preview_s1", 2, False))
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertEqual([s["part"] for s in f["shots"]], [0, 0, 0])               # the film itself is untouched
        self.assertEqual([len(s["takes"]) for s in f["shots"]], [0, 0, 0])
        self.assertEqual(f["shots"][1]["preview"]["width"], 448)
        self.assertTrue(os.path.isfile(os.path.join(config.OUTPUT_DIR, f["shots"][1]["preview"]["file"])))
        await self.job((await self.call("POST", f"/api/films/{fid}/preview/s1", {}))["jobs"][0]["id"])
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertIsNone(f["shots"][1]["preview"])                                 # it continued the preview that was replaced
        j = await self.job((await self.call("POST", f"/api/films/{fid}/preview/s3", {}))["jobs"][0]["id"])
        self.assertEqual(j["status"], "done", j.get("error"))                       # a new shot needs nothing before it

    # ------------------------------------------------------------------ a film, with the gate held
    async def test_the_gate_holds_and_parts_render_in_order(self):
        f = await self.new_film("Gate", [{"new_shot": True}, {"new_shot": False}, {"new_shot": True}])
        fid = f["id"]
        r = await self.call("POST", f"/api/films/{fid}/render/s2", {}, expect=400)
        self.assertIn("shot 1 has to be rendered first", r["error"])
        pre = await self.call("POST", f"/api/films/{fid}/compose/s2", {})
        self.assertEqual((pre["eligible"], pre["continuation"], pre["part"]), (False, True, 2))

        j = await self.job((await self.call("POST", f"/api/films/{fid}/render/s1", {}))["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertEqual(f["shots"][0]["status"], "review")                           # held: nothing approves it by itself
        self.assertEqual([g["shot"] for g in (await self.call("GET", "/api/state"))["gate"] if g["film"] == fid], ["s1"])
        r = await self.call("POST", f"/api/films/{fid}/render/s2", {}, expect=400)
        self.assertIn("not approved yet", r["error"])

        await self.call("POST", f"/api/films/{fid}/approve/s1", {})
        await self.job((await self.call("POST", f"/api/films/{fid}/render/s2", {}))["id"])
        await self.call("POST", f"/api/films/{fid}/approve/s2", {})
        await self.job((await self.call("POST", f"/api/films/{fid}/render/s3", {}))["id"])
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertEqual([s["status"] for s in f["shots"]], ["approved", "approved", "review"])
        self.assertEqual([s["part"] for s in f["shots"]], [1, 2, 3])

        # a new take of shot 1: its continuation no longer fits; the new shot after it is kept
        await self.job((await self.call("POST", f"/api/films/{fid}/render/s1", {}))["id"])
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertEqual([s["status"] for s in f["shots"]], ["review", "stale", "review"])
        self.assertEqual([s["part"] for s in f["shots"]], [1, 0, 3])
        self.assertEqual((len(f["shots"][0]["takes"]), f["shots"][0]["circled"]), (2, 2))
        self.assertEqual(f["shots"][0]["takes"][0]["verdict"], "approved")
        project = os.path.join(config.LONG_DIR, f["long_project"])
        self.assertFalse(os.path.isfile(os.path.join(project, "segments", "part_002.mkv")))
        self.assertTrue(os.path.isfile(os.path.join(project, "_superseded", "part_002.mkv")))
        self.assertTrue(os.path.isfile(os.path.join(project, "segments", "part_003.mkv")))

        # put take 1 back: the files of the earlier take return, and it was approved before
        size1 = os.path.getsize(os.path.join(config.OUTPUT_DIR, f["shots"][0]["takes"][0]["kept"]["segment"]))
        r = await self.call("POST", f"/api/films/{fid}/take/s1", {"n": 1})
        self.assertEqual((r["film"]["shots"][0]["circled"], r["film"]["shots"][0]["status"]), (1, "approved"))
        self.assertEqual(os.path.getsize(os.path.join(project, "segments", "part_001.mkv")), size1)
        await self.call("POST", f"/api/films/{fid}/take/s1", {"n": 9}, expect=400)

    async def test_moving_shots_renumbers_the_parts_and_marks_continuations_stale(self):
        f = await self.new_film("Order", [{"new_shot": True}, {"new_shot": False}, {"new_shot": True}], )
        fid = f["id"]
        await self.call("PUT", f"/api/films/{fid}", {"gate": {"mode": "auto", "retries": 0}})
        await self.call("POST", f"/api/films/{fid}/run", {})
        await self.idle()
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertEqual([s["status"] for s in f["shots"]], ["approved"] * 3)
        old_project = f["long_project"]
        seg3 = os.path.getsize(os.path.join(config.LONG_DIR, old_project, "segments", "part_003.mkv"))

        order = [f["shots"][2], f["shots"][0], f["shots"][1]]                          # the last shot goes first
        r = await self.call("PUT", f"/api/films/{fid}", {"shots": order})
        self.assertEqual(sorted(r["report"]["moved"]), ["s1", "s2", "s3"])
        self.assertEqual(r["report"]["stale"], [])                                     # s2 still follows s1: it stays valid
        f = r["film"]
        self.assertNotEqual(f["long_project"], old_project)
        self.assertEqual([(s["id"], s["part"]) for s in f["shots"]], [("s3", 1), ("s1", 2), ("s2", 3)])
        new = os.path.join(config.LONG_DIR, f["long_project"])
        self.assertEqual(os.path.getsize(os.path.join(new, "segments", "part_001.mkv")), seg3)
        self.assertEqual(config.read_json(os.path.join(new, "shots.json")), {"1": 0, "2": 0, "3": 39})
        self.assertFalse(os.path.isdir(os.path.join(config.LONG_DIR, old_project)))    # the old folder went to the trash
        self.assertTrue(os.path.isfile(os.path.join(config.OUTPUT_DIR, f["full"])))

        r = await self.call("PUT", f"/api/films/{fid}", {"shots": [f["shots"][0], f["shots"][2], f["shots"][1]]})   # s2 now follows s3
        self.assertEqual(r["report"]["stale"], ["s2"])
        self.assertEqual([(s["id"], s["part"], s["status"]) for s in r["film"]["shots"]], [("s3", 1, "approved"), ("s2", 0, "stale"), ("s1", 3, "approved")])

        r = await self.call("PUT", f"/api/films/{fid}", {"shots": [r["film"]["shots"][0], r["film"]["shots"][2]]})   # s2 removed
        self.assertEqual(r["report"]["removed"], ["s2"])
        self.assertEqual([(s["id"], s["part"]) for s in r["film"]["shots"]], [("s3", 1), ("s1", 2)])

    # ------------------------------------------------------------------ runs
    async def test_an_auto_run_retakes_a_failed_check_and_goes_on(self):
        f = await self.new_film("Auto", [{"new_shot": True}, {"new_shot": False}])
        fid = f["id"]
        self.fake.cut_next = True                                                      # the first render has a hard cut
        await self.call("POST", f"/api/films/{fid}/run", {"mode": "auto", "retries": 1})
        await self.idle()
        f = await self.call("GET", f"/api/films/{fid}")
        s1 = f["shots"][0]
        self.assertEqual([t["verdict"] for t in s1["takes"]], ["rejected", "auto"])
        self.assertIn("1 cut(s)", s1["takes"][0]["checks"]["summary"])
        self.assertEqual([s["status"] for s in f["shots"]], ["approved", "approved"])
        self.assertFalse(f["run"]["active"])
        self.assertIn("every shot has a take", f["run"]["log"][-1][1])

    async def test_an_auto_run_stops_at_a_take_that_keeps_failing_and_a_render_error_stops_it(self):
        f = await self.new_film("Stops", [{"new_shot": True}, {"new_shot": True}])
        fid = f["id"]
        self.fake.cut_next = True
        await self.call("POST", f"/api/films/{fid}/run", {"mode": "auto", "retries": 0})
        await self.idle()
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertEqual([s["status"] for s in f["shots"]], ["review", "todo"])        # it waits for a person at shot 1
        self.assertTrue(f["run"]["active"])
        self.fake.fail_next = "CUDA out of memory"
        await self.call("POST", f"/api/films/{fid}/approve/s1", {})                    # approving lets the run go on
        await self.idle()
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertEqual((f["shots"][1]["status"], f["run"]["active"]), ("failed", False))
        self.assertIn("CUDA out of memory", f["shots"][1]["error"])
        self.assertIn("a render failed", f["run"]["stopped"])

    async def test_the_night_shift_keeps_going_and_leaves_a_reel_and_notes(self):
        f = await self.new_film("Night", [{"new_shot": True}, {"new_shot": False}, {"new_shot": True}])
        fid = f["id"]
        self.fake.cut_next = True
        s = await self.call("POST", "/api/nightshift", {"film": fid, "start": "23:00", "retries": 0, "upscale": True})
        self.assertEqual((s["status"], s["shots"]), ("planned", 3))
        await self.call("POST", f"/api/nightshift/{s['id']}/start", {})
        await self.idle(120)
        f = await self.call("GET", f"/api/films/{fid}")
        self.assertEqual([x["part"] for x in f["shots"]], [1, 2, 3])                   # it went on past the take that failed
        self.assertEqual(f["shots"][0]["status"], "review")
        self.assertTrue(f["shots"][0]["takes"][0]["needs_look"])
        s = next(x for x in await self.call("GET", "/api/nightshift") if x["id"] == s["id"])
        self.assertEqual(s["status"], "done")
        self.assertEqual(s["dailies"]["takes"], 3)
        self.assertAlmostEqual(checks.probe(os.path.join(config.OUTPUT_DIR, s["dailies"]["reel"]))["duration"], 3 * 1.5 + (124 + 85 + 124) / 24, delta=0.5)
        with open(os.path.join(config.OUTPUT_DIR, s["dailies"]["notes"])) as fh:
            notes = fh.read()
        self.assertIn("## Look at these first", notes)
        self.assertIn("**Shot 1: shot 1**, take 1", notes)
        self.assertTrue(f["full_upscaled"] or (await self.call("GET", f"/api/films/{fid}"))["full_upscaled"])   # the upscale ran at the end
        await self.call("POST", "/api/nightshift", {"film": fid, "start": "now"}, expect=400)   # nothing left to render

    async def test_a_night_shift_carries_on_after_the_studio_restarts(self):
        f = await self.new_film("Resume", [{"new_shot": True}, {"new_shot": True}])
        s = self.studio.nightshift.plan(f["id"], start="23:00", retries=0)
        s.update(status="running", started=0)                       # as a studio that was stopped mid-shift left it
        config.write_json(self.studio.nightshift._file(s["id"]), s)
        await self.studio.nightshift.resume()
        await self.idle(120)
        self.assertEqual(self.studio.nightshift.get(s["id"])["status"], "done")
        self.assertEqual([x["part"] for x in (await self.call("GET", f"/api/films/{f['id']}"))["shots"]], [1, 2])

    # ------------------------------------------------------------------ outline, storyboard, timeline
    async def test_outline_storyboard_and_story_export(self):
        f = await self.call("POST", "/api/films", {"name": "Plan", "bible": {"width": 384, "height": 256}})
        fid = f["id"]
        pic = (await self.job((await self.call("POST", "/api/images", {"prompt": "a face"}))["id"]))["result"]["assets"][0]
        ref = (await self.call("GET", f"/api/library/{pic}"))["ref"]
        f = (await self.call("PUT", f"/api/films/{fid}", {"cast": [{"name": "Sam", "pronoun": "his", "description": "a courier", "face": ref}, {"name": "Lisa", "pronoun": "her"}],
                                                          "locations": [{"name": "the alley", "description": "A narrow alley at night"}]}))["film"]
        ids = [c["id"] for c in f["cast"]]
        self.assertTrue(all(ids))
        r = await self.call("POST", f"/api/films/{fid}/outline", {"plan": "chase", "a": ids[0], "b": ids[1], "place": f["locations"][0]["id"]})
        self.assertEqual(r["added"]["shots"], 5)
        shots = r["film"]["shots"]
        self.assertEqual(shots[1]["cast"], ids)
        self.assertIn("Sam runs on the left and Lisa on the right", shots[1]["action"])
        await self.call("POST", f"/api/films/{fid}/outline", {"logline": "x"}, expect=400)       # no writing help is set

        r = await self.call("POST", f"/api/films/{fid}/storyboard", {"shots": [shots[0]["id"]]})
        j = await self.job(r["jobs"][0]["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        f = await self.call("GET", f"/api/films/{fid}")
        still = f["shots"][0]["storyboard"][0]
        self.assertTrue(os.path.isfile(config.ref_path(still["file"])))
        self.assertIn("his face is exactly the face in Picture 1", self.fake.prompts[-1]["4"]["inputs"]["prompt"])
        async with self.http.get(self.url + f"/api/films/{fid}/story") as resp:
            story = await resp.text()
        self.assertIn("PARTS = {", story)
        compile(story, "story.py", "exec")                                                        # it is valid Python

    async def test_a_film_to_a_timeline_and_an_export(self):
        f = await self.new_film("Cut", [{"new_shot": True}, {"new_shot": True}])
        fid = f["id"]
        await self.call("POST", f"/api/films/{fid}/run", {"mode": "auto"})
        await self.idle()
        tl = await self.call("POST", f"/api/films/{fid}/timeline", {})
        self.assertEqual(len(tl["clips"]), 2)
        tl["clips"][0]["out"] = 2.0
        await self.call("PUT", f"/api/timelines/{tl['id']}", {"clips": tl["clips"], "captions": True})
        j = await self.job((await self.call("POST", f"/api/timelines/{tl['id']}/export", {}))["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertAlmostEqual(j["result"]["seconds"], 2.0 + 124 / 24, delta=0.1)
        self.assertIn("captions left out", j["result"]["note"])
        for key in ("file", "fcpxml", "edl"):
            self.assertTrue(os.path.isfile(os.path.join(config.OUTPUT_DIR, j["result"][key])), key)
        j = await self.job((await self.call("POST", f"/api/timelines/{tl['id']}/export", {"resolve": True}))["id"])
        folder = os.path.join(config.OUTPUT_DIR, j["result"]["folder"])
        self.assertEqual(sorted(os.listdir(folder)), ["README.txt", "media", "timeline.edl", "timeline.fcpxml"])
        self.assertEqual(len(os.listdir(os.path.join(folder, "media"))), 2)
        await self.call("DELETE", f"/api/films/{fid}")
        await self.call("GET", f"/api/films/{fid}", expect=404)
        self.assertFalse(os.path.isdir(os.path.join(config.LONG_DIR, f["long_project"])))

    async def test_the_mcp_server_drives_the_studio(self):
        import json
        import sys
        proc = await asyncio.create_subprocess_exec(sys.executable, os.path.join(config.REPO, "mcp", "studio_mcp.py"), stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, env={**os.environ, "STUDIO_URL": self.url})
        n = 0

        async def rpc(method, params=None, note=False):
            nonlocal n
            n += 1
            msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
            if not note:
                msg["id"] = n
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()
            if note:
                return None
            return json.loads(await asyncio.wait_for(proc.stdout.readline(), 60))

        async def tool(tool_name, /, **args):
            r = (await rpc("tools/call", {"name": tool_name, "arguments": args}))["result"]
            return json.loads(r["content"][0]["text"]), r["isError"]
        try:
            init = await rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
            self.assertEqual(init["result"]["serverInfo"]["name"], "h3-studio")
            await rpc("notifications/initialized", note=True)
            tools = (await rpc("tools/list"))["result"]["tools"]
            self.assertGreaterEqual(len(tools), 25)
            self.assertTrue(all(t["inputSchema"]["type"] == "object" and t["description"] for t in tools))
            st, bad = await tool("studio_status")
            self.assertTrue(st["comfyui_up"] and not bad)
            pic, _ = await tool("make_picture", prompt="A lighthouse.", name="mcp lighthouse")
            self.assertEqual(pic["status"], "done")
            self.assertTrue(os.path.isfile(pic["files"][0]["file"]))
            clip, _ = await tool("make_clip", action="The lamp of the lighthouse turns.", first_frame=pic["files"][0]["use_as"], width=384, height=256, frames=73)
            self.assertEqual((clip["status"], clip["ok"], clip["status_of_shot"]), ("done", True, "approved"))
            self.assertTrue(os.path.isfile(clip["contact_sheet"]) and os.path.isfile(clip["full_video"]))
            self.assertEqual(self.fake.prompts[-1]["15"]["inputs"]["image"], pic["files"][0]["use_as"])
            film, _ = await tool("film_create", name="MCP film", bible={"width": 384, "height": 256, "frames": 124}, cast=[{"name": "Sam", "pronoun": "his"}])
            upd, _ = await tool("film_update", film=film["film"], shots=[{"id": "a", "title": "one", "action": "Sam waves.", "cast": [film["cast"][0][0]]},
                                                                           {"id": "b", "title": "two", "action": "Sam leaves.", "new_shot": False}])
            self.assertEqual(upd["shots"], [["a", "todo"], ["b", "todo"]])
            pre, _ = await tool("shot_preflight", film=film["film"], shot="b")
            self.assertEqual((pre["can_render"], pre["continuation"]), (False, True))
            r, bad = await tool("shot_render", film=film["film"], shot="b")
            self.assertTrue(bad)
            self.assertIn("shot 1 has to be rendered first", r["error"])
            r, _ = await tool("shot_render", film=film["film"], shot="a")
            self.assertEqual(r["status_of_shot"], "review")
            gate, _ = await tool("gate_list")
            self.assertIn("a", [g["shot"] for g in gate if g["film"] == film["film"]])
            ok, _ = await tool("gate_approve", film=film["film"], shot="a")
            self.assertEqual(ok["shots"][0], ["a", "approved"])
            bad_call = await rpc("tools/call", {"name": "no_such_tool", "arguments": {}})
            self.assertIn("no such tool", bad_call["error"]["message"])
        finally:
            proc.stdin.close()
            await proc.wait()
        unknown = await asyncio.create_subprocess_exec(sys.executable, os.path.join(config.REPO, "mcp", "studio_mcp.py"), stdin=asyncio.subprocess.PIPE,
                                                       stdout=asyncio.subprocess.PIPE, env={**os.environ, "STUDIO_URL": "http://127.0.0.1:9"})
        out, _ = await unknown.communicate(b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"studio_status","arguments":{}}}\n')
        r = json.loads(out)["result"]
        self.assertTrue(r["isError"])
        self.assertIn("the studio does not answer", r["content"][0]["text"])

    async def test_a_project_made_outside_the_studio_opens_as_a_film_and_is_left_alone(self):
        root = os.path.join(config.LONG_DIR, "my_story")
        media.clip(os.path.join(root, "segments", "part_001.mkv"), 2.0, "blue", size="384x256")
        media.clip(os.path.join(root, "segments", "part_002.mkv"), 1.5, "blue", size="384x256")
        config.write_json(os.path.join(root, "shots.json"), {"1": 0, "2": 39})
        media.run("-i", os.path.join(root, "segments", "part_001.mkv"), "-c", "copy", os.path.join(root, "my_story_full.mp4"))
        self.assertIn({"project": "my_story", "parts": 2}, await self.call("GET", "/api/projects"))
        f = await self.call("POST", "/api/films/adopt", {"project": "my_story"})
        self.assertEqual([(s["part"], s["new_shot"], s["status"], s["takes"][0]["continuation"]) for s in f["shots"]], [(1, True, "approved", False), (2, False, "approved", True)])
        self.assertEqual((f["long_project"], f["bible"]["width"], f["bible"]["height"]), ("my_story", 384, 256))
        # the storyboard shows a rendered shot by a frame of its take
        async with self.http.get(f"{self.url}/takeframe/{f['id']}/{f['shots'][0]['id']}.jpg") as r:
            self.assertEqual((r.status, r.content_type), (200, "image/jpeg"))
            self.assertEqual((await r.read())[:2], b"\xff\xd8")
        self.assertTrue(os.path.isfile(os.path.join(config.OUTPUT_DIR, f["shots"][0]["takes"][0]["preview"])))
        self.assertNotIn("my_story", [p["project"] for p in await self.call("GET", "/api/projects")])
        await self.call("POST", "/api/films/adopt", {"project": "../etc"}, expect=400)
        # a new shot after the last part renders into the same project
        shots = f["shots"] + [{"id": "new3", "title": "more", "action": "It goes on.", "new_shot": True, "frames": 124}]
        await self.call("PUT", f"/api/films/{f['id']}", {"shots": shots})
        j = await self.job((await self.call("POST", f"/api/films/{f['id']}/render/new3", {}))["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertTrue(os.path.isfile(os.path.join(root, "segments", "part_003.mkv")))
        await self.call("DELETE", f"/api/films/{f['id']}")
        self.assertTrue(os.path.isfile(os.path.join(root, "segments", "part_001.mkv")))      # deleting the film leaves the project

    async def test_a_project_comes_in_with_its_story_file(self):
        # a story-kit story: two people, each with a picture; a place for each new shot; a prop; the lines in the prompt
        story = os.path.join(env.ROOT, "harbour_story.py")
        with open(story, "w") as f:
            f.write('''
WIDTH, HEIGHT, SECONDS, TURBO = 384, 256, 5.0, True
FACE, BODY = "sam_face.png", "lisa_face.png"
PROPS = {"<BOATREF>": "boat_sheet.png"}
UNET = "h3_test.safetensors"
LORA = [("people/sam_v1.safetensors", 0.9)]
VOICES = {"Sam": (None, "his"), "Lisa": ("lisa.wav", "her")}
STYLE = "The video is in a grey documentary style."
SAM = "Sam, his face is exactly the face in Picture 1, a tall man in a yellow raincoat"
LISA = "Lisa, her face is exactly the face in Picture 2: a woman with short red hair; she wears a blue coat"
def part(new, loc, text, lines):
    return (new, loc, LORA, f"{STYLE}\\n{text}\\n\\noverall_soundscape:\\nWind and gulls.", lines)
PARTS = {
    1: part(True, "quay_loc.png", f"[Shot 1] A grey harbour quay at dawn. Fishing nets lie in heaps. The place looks exactly like Picture 3. "
            f"{SAM}; he stands on the left. {LISA}; she stands on the right. Sam (S1) says, <d>[English] Is that our boat?</d> "
            f"Lisa (S2) answers, <d>[English] It was.</d>", [("Sam", "Is that our boat?"), ("Lisa", "It was.", "dryly")]),
    2: part(False, None, "Continue the same shot without a cut. They walk to the edge. Nobody speaks, there are no words at all.", None),
    3: part(True, "pier_loc.png", f"[Shot 1] A wooden pier in fog, the small boat from <BOATREF> tied to it. The place looks exactly like "
            f"Picture 3. {SAM}; he kneels. {LISA}; she waits. Nobody speaks, there are no words at all.", None),
}
''')
        root = os.path.join(config.LONG_DIR, "harbour")
        media.clip(os.path.join(root, "segments", "part_001.mkv"), 2.0, "blue", size="384x256")
        media.clip(os.path.join(root, "segments", "part_002.mkv"), 1.5, "blue", size="384x256")
        config.write_json(os.path.join(root, "shots.json"), {"1": 0, "2": 39})
        f = await self.call("POST", "/api/films/adopt", {"project": "harbour"})
        self.assertEqual([s["prompt"] for s in f["shots"]], ["", ""])                         # brought in bare: no prompts
        r = await self.call("POST", f"/api/films/{f['id']}/story", {"path": story})
        rep, film = r["report"], r["film"]
        self.assertEqual((rep["parts"], rep["filled"], rep["added"], rep["same"], rep["differ"]), (3, 2, 1, 3, []))
        self.assertEqual(rep["missing"], ["sam_face.png", "lisa_face.png", "quay_loc.png", "pier_loc.png", "boat_sheet.png", "lisa.wav"])   # none of them is in the input folder here
        # the cast with their pictures, voice and LoRA; the places; the prop
        sam, lisa = film["cast"]
        self.assertEqual((sam["name"], sam["face"], sam["pronoun"], sam["lora"]), ("Sam", "sam_face.png", "his", {"file": "people/sam_v1.safetensors", "strength": 0.9}))
        self.assertEqual((lisa["name"], lisa["face"], lisa["voice"], lisa["pronoun"]), ("Lisa", "lisa_face.png", "lisa.wav", "her"))
        self.assertEqual(sam["description"], "a tall man in a yellow raincoat")
        self.assertEqual(lisa["description"], "a woman with short red hair; she wears a blue coat")
        self.assertEqual([(p["name"], p["plate"]) for p in film["locations"]], [("Quay", "quay_loc.png"), ("Pier", "pier_loc.png")])
        self.assertEqual(film["locations"][0]["description"], "A grey harbour quay at dawn. Fishing nets lie in heaps.")
        self.assertEqual(film["locations"][1]["description"], "A wooden pier in fog.")
        self.assertEqual([(p["name"], p["token"], p["sheet"]) for p in film["props"]], [("Boat", "<BOATREF>", "boat_sheet.png")])
        self.assertEqual((film["bible"]["style"], film["bible"]["frames"], film["bible"]["unet"]), ("The video is in a grey documentary style.", 124, "h3_test.safetensors"))
        # the shots: the story's words without the film's opening line, its lines, and the takes that were there
        one, two, three = film["shots"]
        self.assertTrue(one["prompt"].startswith("[Shot 1] A grey harbour quay") and "overall_soundscape" in one["prompt"])
        self.assertEqual([(ln["speaker"], ln["text"], ln["how"]) for ln in one["lines"]], [(sam["id"], "Is that our boat?", ""), (lisa["id"], "It was.", "dryly")])
        self.assertEqual((one["status"], two["status"], three["status"], three["part"]), ("approved", "approved", "todo", 0))
        self.assertTrue(one["takes"][0]["prompt"].startswith("The video is in a grey documentary style.\n[Shot 1]"))
        self.assertEqual((two["new_shot"], two["location"], three["location"]), (False, "", film["locations"][1]["id"]))
        # composed the studio's way, a part is what the story kit sends: the same words, the same pictures in the same order
        pre = await self.call("POST", f"/api/films/{film['id']}/compose/{three['id']}", {})
        self.assertEqual(pre["refs"], ["sam_face.png", "lisa_face.png", "pier_loc.png", "boat_sheet.png"])
        self.assertIn("the small boat from Picture 4 tied to it", pre["prompt"])
        pre = await self.call("POST", f"/api/films/{film['id']}/compose/{one['id']}", {})
        self.assertEqual(pre["prompt"].count("Is that our boat?"), 1)                          # its own lines are not added twice
        # another project's story is refused, and nothing is left half made
        media.clip(os.path.join(config.LONG_DIR, "other", "segments", "part_001.mkv"), 1.0, "green", size="384x256")
        media.clip(os.path.join(config.LONG_DIR, "other", "segments", "part_002.mkv"), 1.0, "green", size="384x256")
        config.write_json(os.path.join(config.LONG_DIR, "other", "shots.json"), {"1": 0, "2": 0})
        before = len(await self.call("GET", "/api/films"))
        bad = await self.call("POST", "/api/films/adopt", {"project": "other", "story": story}, expect=400)
        self.assertIn("does not look like the story of this project", bad["error"])
        self.assertEqual(len(await self.call("GET", "/api/films")), before)
        self.assertIn("other", [p["project"] for p in await self.call("GET", "/api/projects")])
        await self.call("POST", f"/api/films/{film['id']}/story", {"path": os.path.join(env.ROOT, "nothing.py")}, expect=400)

    async def test_cancel_and_restart_recovery(self):
        self.fake.delay = 1.0
        f = await self.new_film("Cancel", [{"new_shot": True}])
        j = await self.call("POST", f"/api/films/{f['id']}/render/s1", {})
        await asyncio.sleep(0.2)
        await self.call("DELETE", f"/api/jobs/{j['id']}")
        self.assertEqual((await self.job(j["id"]))["status"], "cancelled")
        self.assertEqual((await self.call("GET", f"/api/films/{f['id']}"))["shots"][0]["status"], "todo")
        self.fake.delay = 0.0
        # a shot left "rendering" by a studio that was stopped goes back to what it was
        with films.LOCK:
            film = films.load(f["id"])
            film["shots"][0]["status"] = "rendering"
            films.save(film)
        self.studio._repair()
        self.assertEqual(films.load(f["id"])["shots"][0]["status"], "todo")


if __name__ == "__main__":
    unittest.main()
