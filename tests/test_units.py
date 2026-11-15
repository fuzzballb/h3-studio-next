"""The parts that need no server: lengths, the prompt check, the composer, the graphs, presets, beats."""
import os
import json
import unittest

from tests import env, media  # noqa: F401  (env first: it sets the folders)
from studio import beats, brain, compose, config, graphs, lengths, models, presets, promptcheck


class Lengths(unittest.TestCase):
    def test_counts_are_17n_plus_5(self):
        self.assertEqual(lengths.COUNTS[0], 22)
        self.assertEqual(lengths.COUNTS[-1], 362)
        self.assertTrue(all(c % 17 == 5 for c in lengths.COUNTS))
        self.assertEqual(lengths.from_seconds(10), 243)
        self.assertEqual(lengths.from_seconds(6), 141)
        self.assertEqual(lengths.covering(98), 107)

    def test_short_continuations_do_not_fit_the_sound_grid(self):
        # measured: a 73-frame continuation was refused (45600 samples for 45333, 0.59 %; the node allows 0.5 %)
        self.assertAlmostEqual(lengths.audio_mismatch(73, True), 0.00589, places=4)
        self.assertFalse(lengths.fits(73, True))
        self.assertTrue(lengths.fits(73, False))          # the same length worked as a new shot
        self.assertTrue(lengths.fits(124, True))          # and 124 frames worked as a continuation
        self.assertTrue(lengths.fits(243, True))
        self.assertFalse(lengths.fits(22, False))
        with self.assertRaises(ValueError) as e:
            lengths.check_fit(73, True)
        self.assertIn("90 frames", str(e.exception))

    def test_sizes(self):
        self.assertEqual(lengths.snap32(720), 704)
        with self.assertRaises(ValueError):
            lengths.check_size(1280, 720)
        for _, w, h in lengths.SIZES:
            lengths.check_size(w, h)


class PromptCheck(unittest.TestCase):
    def codes(self, text, **kw):
        return [f["code"] for f in promptcheck.check(text, **kw)]

    def test_camera_contradiction(self):
        self.assertIn("camera-contradiction", self.codes("Static shot. The camera pans left across the room. Nobody speaks, there are no words at all."))

    def test_talk_without_lines_and_silence(self):
        c = self.codes("He counts down: three, two, one.")
        self.assertIn("talk-without-lines", c)
        self.assertIn("silence-not-said", c)
        self.assertNotIn("silence-not-said", self.codes("A dog runs. Nobody speaks, there are no words at all."))

    def test_words_that_forbid_are_listed_but_stock_sentences_are_not(self):
        f = promptcheck.forbids("A hall. No photographs or portraits appear anywhere. one continuous take, it never cuts and there are no close-ups.")
        self.assertEqual(f, [("No photographs or portraits", "photographs or portraits")])
        self.assertEqual(promptcheck.forbids("A grey cat jumps. No dogs are in the yard, and the wall is without posters."), [("No dogs", "dogs"), ("without posters", "posters")])
        self.assertEqual(promptcheck.forbids("Nobody speaks, there are no words at all. no readable text, letters, signs or logos anywhere"), [])

    def test_lessons_from_gate_mode(self):
        self.assertIn("windshield", self.codes("She yanks the wheel and the car swerves. Nobody speaks, there are no words at all."))
        self.assertIn("run-away", self.codes("People run away from the fire. Nobody speaks, there are no words at all."))
        self.assertIn("car-doors", self.codes("They both get into the car. Nobody speaks, there are no words at all."))
        self.assertIn("continuation-offscreen", self.codes("He looks back toward the orange glow. Nobody speaks, there are no words at all.", new_shot=False))
        self.assertNotIn("continuation-offscreen", self.codes("He looks back toward the orange glow. Nobody speaks, there are no words at all.", new_shot=True))

    def test_word_count_against_time(self):
        many = [{"speaker": "A", "text": " ".join(["word"] * 40)}]
        self.assertIn("too-many-words", self.codes("They talk.", lines=many, seconds=10))
        self.assertNotIn("too-many-words", self.codes("They talk.", lines=[{"speaker": "A", "text": "Hello there, how are you today?"}], seconds=10))
        self.assertIn("exclamation", self.codes("x", lines=[{"speaker": "A", "text": "We lost them!", "how": "laughing with relief"}]))


FILM = {"bible": {"look": "cinematic", "language": "English"},
        "cast": [{"id": "a", "name": "Sam", "pronoun": "his", "description": "a man in his thirties", "face": "sam_face.png", "body": "sam_body.png", "voice": "sam.wav"},
                 {"id": "b", "name": "Lisa", "pronoun": "her", "description": "a woman with dark hair", "face": "lisa.png", "voice": ""}],
        "locations": [{"id": "L", "name": "Bar", "description": "A small bar with a steel counter", "plate": "bar.png"}],
        "props": [{"id": "p", "name": "the parcel", "token": "<PARCEL>", "sheet": "parcel.png"}]}


def shot(**kw):
    return {**compose.blank_shot(), **kw}


class Composer(unittest.TestCase):
    def test_new_shot_numbers_pictures_in_label_order(self):
        c = compose.compose(FILM, shot(location="L", cast=["a", "b"], action="Sam puts the parcel from <PARCEL> on the table.", framing="two-close",
                                       staging={"a": "sits on the left side of the picture"}), 0)
        self.assertEqual(c["refs"], ["sam_face.png", "sam_body.png", "lisa.png", "bar.png", "parcel.png"])
        self.assertIn("Sam from Picture 1 and Picture 2", c["prompt"])
        self.assertIn("her face is exactly the face in Picture 3", c["prompt"])
        self.assertIn("The place looks exactly like Picture 4", c["prompt"])
        self.assertIn("the parcel from Picture 5", c["prompt"])
        self.assertIn("; he sits on the left side of the picture", c["prompt"])
        self.assertIn("[Shot 1] A small bar", c["prompt"])
        self.assertIn("Nobody speaks, there are no words at all", c["prompt"])
        self.assertIn("overall_soundscape:", c["prompt"])
        self.assertFalse(c["continuation"])

    def test_a_first_frame_is_picture_one(self):
        c = compose.compose(FILM, shot(cast=["b"], first_frame="still.png", action="Lisa waves."), 0)
        self.assertEqual(c["first_frame"], "still.png")
        self.assertEqual(c["refs"], ["lisa.png"])
        self.assertIn("her face is exactly the face in Picture 2", c["prompt"])

    def test_dialogue_has_tags_voices_and_only_words(self):
        c = compose.compose(FILM, shot(cast=["a", "b"], action="They sit.", lines=[{"speaker": "a", "text": "Urgent delivery.", "how": "friendly"},
                                                                                   {"speaker": "b", "text": "Finally.", "how": ""}]), 0)
        p = c["prompt"]
        self.assertIn("Sam (S1) says, looking at Lisa,", p)
        self.assertIn("speaking in the voice from <Audio 1>, friendly, <d>[English] Urgent delivery.</d>", p)
        self.assertIn("Lisa (S2) answers, looking at Sam,", p)
        self.assertIn("Those are the only words; after that nobody says anything else", p)
        self.assertIn("They look at each other while they talk", p)
        self.assertNotIn("Nobody speaks", p)
        self.assertEqual(c["voices"], ["sam.wav"])
        self.assertEqual([l["speaker"] for l in c["lines"]], ["Sam", "Lisa"])

    def test_continuation_names_no_place_and_no_plate(self):
        c = compose.compose(FILM, shot(new_shot=False, location="L", cast=["a"], action="Sam opens the parcel.", frames=73), 1)
        self.assertTrue(c["continuation"])
        self.assertTrue(c["prompt"].split("\n")[1].startswith("Continue the same shot without a cut"))
        self.assertNotIn("bar.png", c["refs"])
        self.assertNotIn("Picture", c["prompt"])
        self.assertEqual(c["frames"], 90)                       # 73 does not fit a continuation: the nearest that does
        self.assertIn("length", [f["code"] for f in c["findings"]])
        first = compose.compose(FILM, shot(new_shot=False, cast=["a"], action="x"), 0)
        self.assertFalse(first["continuation"])                 # the first shot of a film is always a new shot

    def test_free_prompt_and_trigger_words(self):
        c = compose.compose(FILM, shot(mode="free", prompt="[Shot 1] A hall. {DIALOGUE}", cast=["a"], lines=[{"speaker": "a", "text": "Hello."}]), 0)
        self.assertIn("<d>[English] Hello.</d> After that nobody says anything else.", c["prompt"])
        info = env.object_info()
        c = compose.compose(FILM, shot(action="A man jumps.", camera="bullet-time"), 0, info)
        self.assertEqual(c["loras"], [("BulletTime-MMH3.safetensors", 0.8)])
        self.assertTrue(c["prompt"].split("\n")[1].startswith("bullet-time [Shot 1]"))
        c = compose.compose(FILM, shot(action="A man jumps.", camera="bullet-time", cast=["a"], lines=[{"speaker": "a", "text": "Now."}]), 0, info)
        self.assertNotIn("bullet-time [Shot", c["prompt"])        # H3 speaks trigger words in a part with dialogue

    def test_still_prompt(self):
        text, refs = compose.still_prompt(FILM, shot(location="L", cast=["a"], action="Sam waves. Then he leaves."), 0)
        self.assertIn("The moment shown: Sam waves.", text)
        self.assertNotIn("Then he leaves", text)
        self.assertEqual(refs, ["sam_face.png", "sam_body.png", "bar.png"])

    def test_still_of_a_shot_with_its_own_prompt_is_drawn_from_those_words(self):
        # a prompt written for the video model: place, people, action, camera, spoken lines, sound
        opens = shot(mode="free", location="L", cast=["a", "b"], prompt=(
            "[Shot 1] A small bar at night. The place looks exactly like Picture 4; no signs anywhere. Sam, his face is exactly the face "
            "in Picture 1, wears a yellow raincoat; he sits on the left. Lisa, her face is exactly the face in Picture 3, in a blue coat; "
            "she sits on the right. Medium shot, the camera pushes in slowly, one continuous take, it never cuts. They look at each other "
            "while they talk; nobody looks into the camera.\nSam (S1) says, his lips moving clearly, <d>[English] Is it here? I hope so.</d> "
            "Lisa puts the parcel from <PARCEL> on the counter. Those are the only words.\n\noverall_soundscape:\nRain on the window."))
        goes_on = shot(mode="free", new_shot=False, cast=["a", "b"], prompt=(
            "Continue the same shot without a cut: the same place. Sam opens the parcel from <PARCEL> and laughs. Nobody speaks, there are "
            "no words at all.\n\noverall_soundscape:\nPaper tearing."))
        film = {**FILM, "shots": [opens, goes_on]}
        text, refs = compose.still_prompt(film, opens, 0)
        self.assertEqual(refs, ["sam_face.png", "lisa.png", "bar.png", "parcel.png"])           # only the pictures its words name, renumbered
        self.assertIn("frozen at its first moment: A small bar at night. The place looks exactly like Picture 3; no signs anywhere.", text)
        self.assertIn("Sam, his face is exactly the face in Picture 1, wears a yellow raincoat; he sits on the left.", text)
        self.assertIn("Lisa, her face is exactly the face in Picture 2, in a blue coat", text)
        self.assertIn("Medium shot, the camera pushes in slowly.", text)                          # what happens over time is left out
        self.assertIn("They look at each other; nobody looks into the camera.", text)
        self.assertIn("Lisa puts the parcel from Picture 4 on the counter.", text)
        for gone in ("Is it here", "I hope so", "lips", "only words", "Rain on the window", "soundscape", "[Shot 1]", "never cuts", "<d>"):
            self.assertNotIn(gone, text)
        # a continuation says nothing about its place or how the people look: its still gets how its shot opened
        text, refs = compose.still_prompt(film, goes_on, 1)
        self.assertEqual(refs, ["parcel.png", "sam_face.png", "lisa.png", "bar.png"])    # its own first, then the opening shot's
        self.assertIn("each person in the picture only once: A small bar at night. The place looks exactly like Picture 4;", text)
        self.assertIn("Sam, his face is exactly the face in Picture 2, wears a yellow raincoat. Lisa,", text)
        self.assertIn("The moment shown: Sam opens the parcel from Picture 1 and laughs.", text)
        self.assertNotIn("Continue the same shot", text)
        self.assertNotIn("sits on the left", text)               # where someone was when the shot opened: the model drew him twice
        self.assertNotIn("Lisa puts the parcel", text)                                            # the opening shot's action is not shown again
        # in fields, a continuation is drawn in the place its shot opened in
        text, refs = compose.still_prompt({**FILM, "shots": [shot(location="L", cast=["a"], action="Sam waits."), shot(new_shot=False, cast=["a"], action="Sam leaves.")]},
                                          shot(new_shot=False, cast=["a"], action="Sam leaves."), 1)
        self.assertIn("A small bar with a steel counter", text)
        self.assertIn("bar.png", refs)


class Graphs(unittest.TestCase):
    def setUp(self):
        self.info = env.object_info()
        self.roles = models.resolve(self.info)

    def test_roles_pick_the_right_files_and_skip_quantized_loras(self):
        self.assertEqual(self.roles["turbo_lora"], "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors")
        self.assertIn("ref2va", self.roles["video_unet"])
        usable, quantized = models.loras(self.info)
        self.assertEqual(quantized, ["minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy_int8convrot.safetensors"])
        self.assertNotIn(quantized[0], usable)
        self.assertTrue(all(f["ok"] for f in models.features(self.info).values()))

    def test_every_graph_validates_against_the_node_catalogue(self):
        g = [graphs.clip(self.roles, project="p", part=1, prompt="x", refs=["a.png"], voices=["v.wav"], first_frame="f.png", loras=[("BulletTime-MMH3.safetensors", 0.8)]),
             graphs.clip(self.roles, project="p", part=2, prompt="x", new_shot=False, turbo=False),
             graphs.upscale(self.roles, project="p", part=1, loras=[("person/sam_h3_v1.safetensors", 1.0)]),
             graphs.upscale(self.roles, project="p", part=1, interpolate=False, sharpen=False),
             graphs.image(self.roles, prompt="x", prefix="studio/images/x"),
             graphs.image(self.roles, prompt="x", prefix="studio/images/x", pictures=["a.png", "b.png"], keep_size=True),
             graphs.tts(text="hello", voice="narrator.wav", prefix="studio/audio/x")]
        for graph in g:
            self.assertEqual(models.validate(graph, self.info), [])

    def test_clip_graph_shape(self):
        g = graphs.clip(self.roles, project="p", part=3, prompt="x", new_shot=False, refs=["a.png", "b.png"], loras=[("BulletTime-MMH3.safetensors", 0.8)], seed=7)
        self.assertEqual(g["32"]["inputs"]["new_shot"], False)
        self.assertEqual(g["32"]["inputs"]["context_length"], 39)
        self.assertEqual(g["23"]["inputs"]["reference_images.reference_image_1"], ["101", 0])
        self.assertEqual(g["90"]["inputs"]["model"], ["72", 0])            # extra LoRAs come after the turbo LoRA and its shift
        self.assertEqual(g["43"]["inputs"]["steps"], 8)
        self.assertNotIn("5", g)                                           # SLA attention is off: it warps backgrounds
        self.assertNotIn("H3MiniMaxCache", [n["class_type"] for n in g.values()])
        off = graphs.clip(self.roles, project="p", part=1, prompt="x", turbo=False)
        self.assertNotIn("71", off)                                        # no turbo: its LoRA is not even loaded
        self.assertEqual(off["43"]["inputs"]["steps"], 13)

    def test_graphs_refuse_what_cannot_render(self):
        with self.assertRaises(ValueError):
            graphs.clip(self.roles, project="p", part=2, prompt="x", new_shot=False, frames=73)
        with self.assertRaises(ValueError):
            graphs.clip(self.roles, project="p", part=1, prompt="x", width=1280, height=720)
        with self.assertRaises(ValueError):
            graphs.clip(self.roles, project="p", part=1, prompt="x", refs=["x.png"] * 10)
        with self.assertRaises(ValueError) as e:
            graphs.clip({**self.roles, "turbo_lora": ""}, project="p", part=1, prompt="x")
        self.assertIn("Turbo LoRA", str(e.exception))

    def test_validate_names_what_is_missing(self):
        g = graphs.clip(self.roles, project="p", part=1, prompt="x")
        info = {k: v for k, v in self.info.items() if k != "PK_MiniMaxH3Combined"}
        self.assertIn("PK_MiniMaxH3Combined is not installed (from ComfyUI-PlagueKind-Nodes)", models.validate(g, info)[0])
        g["1"]["inputs"]["unet_name"] = "not_there.safetensors"
        self.assertIn("'not_there.safetensors' is not available", models.validate(g, self.info)[0])
        self.assertEqual(graphs.missing_inputs(graphs.image(self.roles, prompt="x", prefix="p", pictures=["nope.png"])), ["nope.png"])

    def test_loader_names(self):
        p = media.picture(config.home("uploads", "face.png"))
        ref = config.out_ref(p)
        self.assertEqual(ref, "studio_next/uploads/face.png [output]")
        self.assertEqual(os.path.realpath(config.ref_path(ref)), os.path.realpath(p))
        self.assertEqual(config.ref_path("x.png"), os.path.join(config.INPUT_DIR, "x.png"))
        self.assertEqual(config.ref_url(ref), "/media/studio_next/uploads/face.png")


class Blockout(unittest.TestCase):
    """A shot that follows a blockout video (H3 V2V)."""
    def film(self, *shots):
        return {**FILM, "shots": [dict(shot(**kw), id=f"s{i}") for i, kw in enumerate(shots)]}

    def test_a_continuation_reads_on_from_where_the_shot_before_stopped(self):
        f = self.film(dict(blockout="b.mp4", frames=243, cast=["a"]), dict(blockout="b.mp4", new_shot=False, frames=192),
                      dict(blockout="b.mp4", new_shot=False, frames=192), dict(blockout="b.mp4", frames=192, blockout_start=500))
        starts = [compose.blockout_plan(f, i)["start"] for i in range(4)]
        # 243 frames read 0..242; the next part's 39 context frames are the last 39 of those: it starts at 204
        self.assertEqual(starts, [0, 243 - 39, 243 - 39 + 192 - 39, 500])
        self.assertIsNone(compose.blockout_plan(self.film(dict()), 0))
        self.assertEqual(compose.blockout_plan(f, 0)["strength"], config.settings()["blockout"]["strength"])

    def test_the_prompt_names_the_blockout_and_drops_keyframes(self):
        f = self.film(dict(blockout="b.mp4", cast=["a"], first_frame="still.png", framing="two-close", action="Sam walks.",
                           blockout_shapes="the brown figure is Sam."),
                      dict(blockout="b.mp4", new_shot=False, action="He stops."))
        c = compose.compose(f, f["shots"][0], 0)
        self.assertIn("<Video 1> is a rough 3D blockout", c["prompt"])
        self.assertIn("placeholders: the brown figure is Sam", c["prompt"])
        self.assertEqual(c["first_frame"], "")
        self.assertEqual(c["refs"], ["sam_face.png", "sam_body.png"])         # Picture 1 is his face, not the still
        codes = [x["code"] for x in c["findings"]]
        self.assertIn("blockout-keyframes", codes)
        self.assertIn("blockout-camera", codes)
        self.assertEqual(c["blockout"]["start"], 0)
        c2 = compose.compose(f, f["shots"][1], 1)
        self.assertIn("the camera keeps following <Video 1>", c2["prompt"])
        self.assertNotIn("the same camera position", c2["prompt"])
        self.assertEqual(c2["blockout"]["start"], c["frames"] - 39)
        self.assertIsNone(compose.compose(FILM, shot(action="x"), 0)["blockout"])

    def test_a_continuation_of_another_blockout_is_warned_about(self):
        f = self.film(dict(action="x"), dict(blockout="b.mp4", new_shot=False, action="y"))
        self.assertIn("blockout-start", [x["code"] for x in compose.compose(f, f["shots"][1], 1)["findings"]])

    def test_graph(self):
        info = env.object_info()
        roles = models.resolve(info)
        self.assertIn("fl2va", roles["blockout_unet"])
        g = graphs.blockout_clip(roles, project="p", part=2, prompt="x", blockout="/tmp/b.mkv", start=204, strength=0.997,
                                 new_shot=False, frames=192, refs=["a.png"], voices=["v.wav"], loras=[("BulletTime-MMH3.safetensors", 0.8)])
        self.assertEqual(models.validate(g, info), [])
        self.assertEqual(g["60"]["inputs"]["skip_first_frames"], 204)
        self.assertEqual(g["60"]["inputs"]["frame_load_cap"], 192)
        self.assertEqual(g["24"]["inputs"]["global_strength"], 0.997)
        self.assertTrue(g["32"]["inputs"]["keep_latent_mask"])        # without it the blockout is lost after the context
        self.assertFalse(g["32"]["inputs"]["new_shot"])
        self.assertEqual(g["32"]["inputs"]["latent"], ["24", 0])
        self.assertEqual(g["23"]["inputs"]["ref_videos.ref_video_0"], ["62", 0])
        self.assertEqual(g["23"]["inputs"]["ref_images.ref_image_0"], ["100", 0])
        self.assertEqual(g["62"]["inputs"]["width"], 576)              # <Video 1> at half size
        self.assertEqual(models.validate(graphs.blockout_clip(roles, project="p", part=1, prompt="x", blockout="/tmp/b.mkv", turbo=False), info), [])
        with self.assertRaises(ValueError):
            graphs.blockout_clip(roles, project="p", part=1, prompt="x", blockout="/tmp/b.mkv", strength=1.5)

    def test_the_feature_needs_the_newer_continue_node(self):
        info = env.object_info()
        self.assertTrue(models.features(info)["blockout"]["ok"])
        old = dict(info, H3LongVideoContinue={**info["H3LongVideoContinue"], "input": {
            "required": info["H3LongVideoContinue"]["input"]["required"], "optional": {"new_shot": ["BOOLEAN", {}]}}})
        f = models.features(old)["blockout"]
        self.assertFalse(f["ok"])
        self.assertIn("keep_latent_mask", models.why_not(f))

    def test_the_blockout_gets_a_sound_track_and_its_length_is_checked(self):
        from studio import work
        from studio.jobs import Refused
        src = media.clip(config.home("uploads", "blockout_test.mp4"), seconds=2.0, audio=False)
        out = work.blockout_source(config.out_ref(src), 48)
        import json
        import subprocess
        d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", out],
                                      capture_output=True, text=True).stdout)
        self.assertEqual(sorted(x["codec_type"] for x in d["streams"]), ["audio", "video"])
        self.assertGreater(float(d["format"]["duration"]), 2.5)       # the sound runs on past the picture
        with self.assertRaises(Refused):
            work.blockout_source(config.out_ref(src), 100)


SCENE = {"sky": "night", "ground": "snow",
         "set": [{"type": "street", "name": "", "at": [-40, 0, 0], "size": [200, 14, 13], "turn": 0, "color": "brick"}],
         "things": [{"name": "Sam", "kind": "person", "color": "blue", "scale": 1,
                     "keys": [{"t": 6, "at": [18, -2, 0], "face": None, "pose": "stand"}, {"t": 0, "at": [10, -2, 0], "face": None, "pose": "walk"}]},
                    {"name": "taxi", "kind": "car", "color": "yellow", "scale": 1, "keys": [{"t": 0, "at": [0, 2, 0], "face": None, "pose": "stand"}]}],
         "camera": {"lens": 35, "shake": 0, "keys": [{"t": 0, "at": [24, -6, 1.6], "look_at": [10, -2, 1.2], "follow": "", "lens": 0},
                                                    {"t": 8, "at": [23, -4.5, 0.5], "look_at": [0, 0, 0], "follow": "Sam", "lens": 0}]}}


class FilmSteps(unittest.TestCase):
    def film(self, **kw):
        from studio import compose
        f = {"id": "t", "name": "T", "long_project": "t_steps_none", "bible": {**compose.blank_bible(), "logline": ""},
             "cast": [], "locations": [], "props": [], "shots": []}
        f.update(kw)
        return f

    def shot(self, **kw):
        from studio import compose
        return {**compose.blank_shot(), "id": kw.pop("id", "s"), "status": "todo", "takes": [], **kw}

    def test_the_next_step_is_the_first_one_missing(self):
        from studio import films
        f = self.film()
        self.assertEqual(films.next_step(films.steps(f))["id"], "bible")
        f["bible"]["logline"] = "A race."
        nx = films.next_step(films.steps(f))
        self.assertEqual((nx["id"], nx["n"]), ("cast", 2))
        f["cast"] = [{"name": "Mara", "face": ""}]
        self.assertIn("no face picture for Mara", films.next_step(films.steps(f))["todo"])
        f["cast"][0]["face"] = "mara.png"
        self.assertEqual(films.next_step(films.steps(f))["id"], "shots")
        f["shots"] = [self.shot(action="")]
        self.assertIn("shot 1", films.next_step(films.steps(f))["todo"])
        f["shots"][0]["action"] = "She rides."
        nx = films.next_step(films.steps(f))
        self.assertEqual(nx["id"], "roll")                       # the storyboard is optional
        self.assertEqual(nx["todo"], "0 of 1 shots approved")

    def test_an_approved_film_has_its_earlier_steps_behind_it(self):
        from studio import films
        f = self.film(shots=[self.shot(action="x", status="approved")])       # no logline, nobody with a face
        st = {s["id"]: s for s in films.steps(f)}
        self.assertTrue(st["cast"]["done"])
        self.assertEqual(films.next_step(films.steps(f))["id"], "deliver")

class BlockoutScenes(unittest.TestCase):
    def test_a_followed_subject_that_stays_small_is_named(self):
        from studio import blockouts
        stats = {"Mara": {"followed": True, "in_view": 1.0, "median": 0.147, "max": 0.158},
                 "tram": {"followed": False, "in_view": 1.0, "median": 0.05, "max": 0.1},
                 "dog": {"followed": True, "in_view": 0.4, "median": 0.5, "max": 0.6},
                 "Henk": {"followed": True, "in_view": 0.95, "median": 0.61, "max": 0.7}}
        small = dict(blockouts.too_small(stats))
        self.assertEqual(set(small), {"Mara", "dog"})                  # the tram is not followed; Henk is big enough
        self.assertIn("15%", small["Mara"])
        self.assertIn("40%", small["dog"])
        self.assertEqual(blockouts.too_small(None), [])

    """Blockout scenes: data checked here, rendered by Blender with the studio's own script."""
    def test_a_scene_is_checked_and_filled_in(self):
        from studio import blockouts
        n = blockouts.normalize(SCENE)
        self.assertEqual([k["t"] for k in n["things"][0]["keys"]], [0, 6])           # keys in time order
        self.assertEqual(n["camera"]["keys"][1]["follow"], "Sam")
        self.assertEqual(blockouts.normalize('{"camera": {"keys": [{"at": [0, -5, 2], "look_at": [0, 0, 1]}]}}')["sky"], "day")
        bad = [({**SCENE, "sky": "noon"}, "sky"), ({**SCENE, "camera": {"keys": []}}, "camera"),
               ({**SCENE, "camera": {"keys": [{"t": 0, "at": [0, 0, 1], "look_at": [0, 0, 0], "follow": "Bob"}]}}, "Bob"),
               ({**SCENE, "things": [SCENE["things"][0], SCENE["things"][0]]}, "two things"),
               ({**SCENE, "set": [{"type": "castle"}]}, "castle"),
               ({**SCENE, "things": [{"name": "x", "kind": "car", "keys": [{"t": 0, "at": [1e9, 0, 0]}]}]}, "outside"),
               ("{not json", "JSON")]
        for scene, word in bad:
            with self.assertRaises(blockouts.BadScene) as e:
                blockouts.normalize(scene)
            self.assertIn(word, str(e.exception))

    def test_a_scene_blockout_is_cut_into_its_shots(self):
        from studio import blockouts
        self.assertEqual(compose.scene_shapes(SCENE), "the blue figure is Sam; the yellow car is taxi")
        f = {**FILM, "bible": {**FILM["bible"], "frames": 243, "width": 1152, "height": 640},
             "shots": [dict(shot(id="a", scene="S")), dict(shot(id="b", scene="S", new_shot=False, frames=192)),
                       dict(shot(id="c", scene="S")), dict(shot(id="d", scene="T"))],
             "blockouts": [{"id": "bx", "scene_name": "S", "scene": SCENE, "cuts": {}, "video": "", "made": "", "stats": None}]}
        b = f["blockouts"][0]
        # the first shot from 0, a continuation 39 frames before the end of the one it continues, a cut where it ends
        self.assertEqual([(c["id"], c["start"], c["end"], c["continuation"]) for c in blockouts.cuts(f, b)],
                         [("a", 0, 243, False), ("b", 204, 396, True), ("c", 396, 639, False)])
        self.assertIsNone(blockouts.state(f, 3))                                  # scene T has none
        self.assertEqual(blockouts.state(f, 1)["id"], "bx")
        c = compose.compose(f, f["shots"][0], 0)
        self.assertIn("blockout-not-made", [x["code"] for x in c["findings"]])
        self.assertIsNone(c["blockout"])
        # made: each shot follows its stretch; the scene's things say what the shapes are
        frames = blockouts.render_frames(f, b, blockouts.normalize(SCENE))
        self.assertEqual(frames, 639)                                             # the shots need more than the 8 s scene
        b.update(video="b.mp4", made=blockouts.signature(blockouts.normalize(SCENE), frames, 1152, 640))
        self.assertTrue(blockouts.state(f, 0)["current"])
        c = compose.compose(f, f["shots"][2], 2)
        self.assertEqual((c["blockout"]["file"], c["blockout"]["start"]), ("b.mp4", 396))
        self.assertNotIn("blockout-start", [x["code"] for x in compose.compose(f, f["shots"][1], 1)["findings"]])   # same blockout as the shot before
        self.assertIn("placeholders: the blue figure is Sam; the yellow car is taxi", c["prompt"])
        self.assertIsNone(compose.compose(f, f["shots"][3], 3)["blockout"])
        # a cut moved by hand moves the shots after it; a continuation always overlaps the shot before
        b["cuts"] = {"c": 420, "b": 5}
        self.assertEqual([x["start"] for x in blockouts.cuts(f, b)], [0, 204, 420])
        self.assertFalse(blockouts.state(f, 0)["current"])                        # longer now: make it again
        self.assertIn("blockout-old", [x["code"] for x in compose.compose(f, f["shots"][0], 0)["findings"]])
        # a shot with a video of its own follows that instead
        f["shots"][2]["blockout"] = "own.mp4"
        self.assertEqual(compose.compose(f, f["shots"][2], 2)["blockout"]["file"], "own.mp4")

    def test_camera_cuts_and_old_films(self):
        from studio import blockouts, films as F
        sc = json.loads(json.dumps(SCENE))
        sc["camera"]["keys"][1]["cut"] = True
        self.assertTrue(blockouts.normalize(sc)["camera"]["keys"][1]["cut"])
        # a scene without cuts signs as it did before cuts existed, so made blockouts stay current
        plain = blockouts.normalize(SCENE)
        old = {**plain, "camera": {**plain["camera"], "keys": [{k: v for k, v in key.items() if k != "cut"} for key in plain["camera"]["keys"]]}}
        self.assertEqual(blockouts.signature(plain, 100, 64, 64), blockouts.signature(old, 100, 64, 64))
        # a film from before: the scene on the shot that opened a take moves to its scene's blockout
        f = {**FILM, "shots": [dict(shot(id="a", scene="S", blockout="v.mp4", blockout_scene=SCENE, blockout_made="abc")),
                               dict(shot(id="b", scene="S", new_shot=False, blockout="v.mp4"))]}
        self.assertTrue(blockouts.migrate(f))
        b = f["blockouts"][0]
        self.assertEqual((b["scene_name"], b["video"], b["made"]), ("S", "v.mp4", "abc"))
        self.assertEqual([s["blockout"] for s in f["shots"]], ["", ""])
        self.assertNotIn("blockout_scene", f["shots"][0])
        self.assertFalse(blockouts.migrate(f))
        self.assertIn("blockout", [s["id"] for s in F.steps({**f, "bible": FILM["bible"], "long_project": "t_steps_none"})])

    def test_the_writer_blocks_a_scene(self):
        from studio import writer
        self.assertIn("blockouts", writer.SCHEMA["properties"]["film"]["anyOf"][0]["required"])
        self.assertIn("blockouts", writer.SCHEMA["properties"]["edits"]["anyOf"][0]["required"])
        self.assertIn("A blockout is a rough 3D sketch of a whole scene", writer.system_prompt())
        c = writer.new_conversation()
        sh = lambda **k: {"title": "", "scene": "S", "new_shot": True, "location": "", "cast": [], "framing": "wide", "camera": "dolly-in",
                          "action": "x", "lines": [], "sound": "", "seconds": 10, "prompt": "", **k}
        film = {"name": "Chase", "logline": "", "look": "cinematic", "cast": [{"name": "Sam", "pronoun": "his", "description": "a man"}],
                "locations": [], "shots": [sh(title="Run"), sh(title="On", new_shot=False), sh(title="Talk", scene="T")],
                "blockouts": [{"scene": "S", "why": "the chase", "blockout": SCENE}, {"scene": "T", "why": "", "blockout": {"sky": "noon"}}]}
        c["turns"] += [{"role": "user", "text": "a chase"}, {"role": "writer", "answer": writer.clean({"say": "", "questions": [], "film": film, "edits": None})}]
        writer.save(c)
        f, rep = writer.apply(c["id"], 1)
        one, two, three = f["shots"]
        self.assertEqual([(s["framing"], s["camera"]) for s in (one, two)], [("", ""), ("", "")])   # the blockout sets those
        bs = {b["scene_name"]: b for b in f["blockouts"]}
        self.assertEqual(bs["S"]["scene"]["things"][0]["name"], "Sam")
        self.assertEqual(rep["blockouts"], [bs["S"]["id"]])                    # made right away; the bad one is not
        self.assertEqual(bs["T"]["scene"], {"sky": "noon"})                     # kept, so the Blockout step can say what is wrong
        words = json.loads(writer.film_words(f))
        self.assertEqual([b["scene"] for b in words["blockouts"]], ["S", "T"])
        self.assertEqual(len(words["blockouts"][0]["stretches"]), 2)            # it sees which seconds each shot reads


class Presets(unittest.TestCase):
    def test_files_load_and_ids_are_unique(self):
        p = presets.everything()
        for name, key in (("cameras", "moves"), ("cameras", "framings"), ("looks", "styles"), ("apps", "apps"), ("coverage", "plans"), ("angles", "views")):
            ids = [e["id"] for e in p[name][key]]
            self.assertEqual(len(ids), len(set(ids)), f"{name}.{key} has a double id")
        self.assertGreaterEqual(len(p["cameras"]["moves"]), 25)

    def test_presets_point_at_things_that_exist(self):
        p = presets.everything()
        moves = {m["id"] for m in p["cameras"]["moves"]}
        framings = {f["id"] for f in p["cameras"]["framings"]}
        looks = {s["id"] for s in p["looks"]["styles"]}
        views = {v["id"] for v in p["angles"]["views"]}
        for plan in p["coverage"]["plans"]:
            for s in plan["shots"]:
                self.assertIn(s.get("camera", "static"), moves)
                self.assertIn(s.get("framing", "medium"), framings)
                if s.get("frames"):
                    self.assertTrue(lengths.fits(s["frames"], not s.get("new")))
        for a in p["apps"]["apps"]:
            f = a.get("form") or {}
            self.assertIn(a["group"], p["apps"]["groups"])
            for key, known in (("camera", moves), ("framing", framings), ("look", looks)):
                if f.get(key):
                    self.assertIn(f[key], known, a["id"])
            self.assertTrue(set(a.get("needs", [])) <= set(models.FEATURES), a["id"])
        for st in p["angles"]["sets"]:
            self.assertTrue(set(st["views"]) <= views)

    def test_preset_words_forbid_nothing(self):
        # the model has no negative prompt: the studio's own preset words must not name things to keep out
        p = presets.everything()
        texts = [m["text"] for m in p["cameras"]["moves"]] + [f["text"] for f in p["cameras"]["framings"]] + \
                [s["text"] for k in ("styles", "lenses", "lights") for s in p["looks"][k]]
        for t in texts:
            self.assertEqual(promptcheck.forbids(t), [], t)

    def test_coverage_plan_to_shots(self):
        rows = brain.from_plan("chase", "Sam", "Lisa", "the alley")
        self.assertEqual(len(rows), 5)
        self.assertIn("passenger door on the far side", rows[2]["action"])
        self.assertEqual(rows[0]["cast_names"], ["Sam", "Lisa"])


class Memory(unittest.TestCase):
    def test_a_job_that_will_not_fit_in_ram_is_refused(self):
        from unittest import mock
        from studio import machine
        with mock.patch.object(machine, "memory", lambda: {"total": 62 * 2 ** 30, "available": 50 * 2 ** 30}):
            self.assertEqual(machine.fit(1152, 640, 243)["level"], "ok")                       # a 10 s part
            self.assertEqual(machine.fit(1152, 640, 243, scale=1.5, fps_multiplier=2)["level"], "tight")   # its upscale: works, RAM nearly full
            killed = machine.fit(1440, 2560, 362)                                              # this one was killed by the kernel
            self.assertFalse(killed["ok"])
            self.assertIn("ComfyUI would be killed", killed["text"])
        with mock.patch.object(machine, "memory", lambda: {"total": 0, "available": 0}):
            self.assertTrue(machine.fit(4000, 4000, 362)["ok"])                                # RAM unknown: nothing is refused


class Estimates(unittest.TestCase):
    def test_a_part_takes_longer_than_its_size_and_the_machine_learns_its_own_rate(self):
        from studio import jobs, work
        q = jobs.Queue.__new__(jobs.Queue)
        q.times = {}
        big = {"width": 1152, "height": 640, "frames": 243}
        small = {"width": 864, "height": 480, "frames": 73}
        self.assertAlmostEqual(q.estimate("part", work.clip_units(big, 8), prior=work.CLIP_PRIOR), 60 + 8 * 58, delta=1)     # about 8.7 minutes
        self.assertLess(q.estimate("part", work.clip_units(small, 8), prior=work.CLIP_PRIOR), 100)
        q.times = {"part": [[work.clip_units(small, 8), 100.0], [work.clip_units({**small, "frames": 124}, 8), 115.0]]}       # two drafts, as measured
        self.assertTrue(350 < q.estimate("part", work.clip_units(big, 8), prior=work.CLIP_PRIOR) < 800)
        self.assertIsNone(q.estimate("upscale", 1))


class Brain(unittest.TestCase):
    def test_json_is_found_in_prose(self):
        self.assertEqual(brain.parse_json('Sure!\n```json\n{"shots": []}\n```'), {"shots": []})
        self.assertEqual(brain.parse_json('Here: {"a": {"b": 1}} done'), {"a": {"b": 1}})
        with self.assertRaises(ValueError):
            brain.parse_json("no json here")

    def test_outline_is_cleaned(self):
        out = brain.clean_outline({"cast": [{"name": "Sam", "pronoun": "x"}, {"nope": 1}], "locations": [{"name": "Bar", "description": "d"}],
                                   "shots": [{"title": "t", "camera": "warp-drive", "framing": "wide", "lines": [{"speaker": "Sam", "text": ""}, {"speaker": "Sam", "text": "Hi."}], "cast": ["Sam"]}, "junk"]})
        self.assertEqual(out["cast"], [{"name": "Sam", "description": "", "pronoun": "their"}])
        self.assertEqual(out["shots"][0]["camera"], "")
        self.assertEqual(out["shots"][0]["framing"], "wide")
        self.assertEqual(len(out["shots"][0]["lines"]), 1)


class Beats(unittest.TestCase):
    def test_tempo_and_beats_of_a_click_track(self):
        for bpm in (100, 128):
            r = beats.analyse(media.click_track(os.path.join(env.ROOT, f"click_{bpm}.wav"), bpm))
            self.assertAlmostEqual(r["bpm"], bpm, delta=0.5)
            self.assertAlmostEqual(r["beats"][0], 0.35, delta=0.03)
            self.assertAlmostEqual(r["beats"][5] - r["beats"][4], 60 / bpm, delta=0.03)
            self.assertAlmostEqual(r["downbeats"][0], 0.35, delta=0.03)       # the accented click is the first of the bar

    def test_slots(self):
        grid = [i * 0.5 for i in range(40)]
        self.assertEqual(beats.slots(grid, [2.1, 0.9], "own"), [(0.0, 2.0), (2.0, 3.0)])
        self.assertEqual(beats.slots(grid, [9, 9], "bar"), [(0.0, 2.0), (2.0, 4.0)])
        self.assertEqual(beats.slots(grid, [9], "beat"), [(0.0, 0.5)])


if __name__ == "__main__":
    unittest.main()


class Writer(unittest.TestCase):
    """The Writer's proposals into films, without Claude: an answer as it would come back."""
    def test_a_written_film_is_made_and_then_changed(self):
        from studio import writer
        c = writer.new_conversation()
        shot = lambda **k: {"title": "", "scene": "Door", "new_shot": True, "location": "Doorstep", "cast": ["Sam"], "framing": "medium",
                            "camera": "static", "action": "", "lines": [], "sound": "", "seconds": 10, "prompt": "", **k}
        film = {"name": "Wrong door", "logline": "A parcel at the wrong door.", "look": "documentary",
                "cast": [{"name": "Sam", "pronoun": "his", "description": "a courier"}, {"name": "Ada", "pronoun": "her", "description": "an old woman"}],
                "locations": [{"name": "Doorstep", "description": "A green front door"}],
                "shots": [shot(title="Knock", action="Sam knocks.", camera="nonsense"),
                          shot(title="Talk", new_shot=False, location="", cast=["Sam", "Ada"], seconds=8,
                               lines=[{"speaker": "Ada", "text": "Mine.", "how": "calm"}])]}
        c["turns"] += [{"role": "user", "text": "a story"}, {"role": "writer", "answer": writer.clean({"say": "Here.", "questions": [], "film": film, "edits": None})}]
        writer.save(c)
        f, rep = writer.apply(c["id"], 1)
        self.assertTrue(rep["made"])
        self.assertEqual((f["name"], f["bible"]["look"], [x["name"] for x in f["cast"]]), ("Wrong door", "documentary", ["Sam", "Ada"]))
        one, two = f["shots"]
        self.assertEqual((one["location"], one["camera"], one["frames"]), (f["locations"][0]["id"], "", 243))   # unknown moves are dropped
        self.assertEqual((two["new_shot"], two["location"], two["lines"][0]["speaker"]), (False, "", f["cast"][1]["id"]))
        self.assertIn(two["frames"], lengths.usable(True))
        with self.assertRaises(ValueError):
            writer.apply(c["id"], 1)                                                       # once only
        edits = {"cast": [{"name": "Sam", "pronoun": "his", "description": "a courier in his thirties"}], "locations": [],
                 "update": [{"id": one["id"], "why": "more", "changes": {"action": "Sam knocks twice."}}],
                 "add": [{"after": one["id"], "why": "a beat", "shot": shot(title="Wait", action="Sam waits.")}], "remove": [two["id"]]}
        c = writer.load(c["id"])
        c["turns"] += [{"role": "user", "text": "change it"}, {"role": "writer", "answer": writer.clean({"say": "Done.", "questions": [], "film": None, "edits": edits})}]
        writer.save(c)
        f, rep = writer.apply(c["id"], 3)
        self.assertEqual([s["title"] for s in f["shots"]], ["Knock", "Wait"])
        self.assertEqual((f["shots"][0]["action"], f["cast"][0]["description"]), ("Sam knocks twice.", "a courier in his thirties"))
        self.assertEqual((rep["updated"], rep["removed"]), ([one["id"]], [two["id"]]))
        self.assertIn(f["id"], writer.transcript(writer.load(c["id"])))                   # the film goes with the next turn
