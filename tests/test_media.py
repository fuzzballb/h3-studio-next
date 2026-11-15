"""Checks, the Library and the export, on small synthetic clips (ffmpeg only; no ComfyUI, no Whisper)."""
import os
import unittest
import xml.dom.minidom

from tests import env, media  # noqa: F401
from studio import checks, config, finish, library


def tmp(name):
    return os.path.join(config.home("tmp"), name)


class Checks(unittest.TestCase):
    def test_probe(self):
        p = checks.probe(media.clip(tmp("a.mkv"), 2.0))
        self.assertEqual((p["width"], p["height"], p["fps"], p["has_audio"]), (320, 192, 24.0, True))
        self.assertAlmostEqual(p["duration"], 2.0, delta=0.1)
        self.assertEqual(checks.probe(tmp("nope.mkv")), {})

    def test_a_hard_cut_is_found_and_the_longest_stretch_without_one(self):
        clean = checks.frame_diffs(media.clip(tmp("clean.mkv"), 2.0))
        self.assertEqual(checks.cuts_from(clean), [])
        self.assertTrue(checks.window_from(clean)["whole"])
        d = checks.frame_diffs(media.clip(tmp("cut.mkv"), 3.0, cut_at=1.0))
        cuts = checks.cuts_from(d)
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0][0], 1.0, delta=0.06)
        w = checks.window_from(d)
        self.assertAlmostEqual(w["in"], 1.0, delta=0.06)
        self.assertAlmostEqual(w["out"], 3.0, delta=0.06)
        self.assertFalse(w["whole"])

    def test_join_and_keyframe(self):
        a, b, c = media.clip(tmp("j1.mkv"), 1.0, "blue"), media.clip(tmp("j2.mkv"), 1.0, "blue"), media.clip(tmp("j3.mkv"), 1.0, "yellow")
        self.assertLess(checks.join_diff(a, b), 10)           # the same place carries on
        self.assertGreater(checks.join_diff(a, c), 25)        # the background was swapped
        pic = media.picture(tmp("blue.png"), "blue")
        self.assertLess(checks.keyframe_diff(a, pic), 12)
        self.assertGreater(checks.keyframe_diff(c, pic), 12)

    def test_loudness_only_counts_while_someone_speaks(self):
        quiet = checks.loudness(media.clip(tmp("quiet.mkv"), 3.0, volume=0.02))
        loud = checks.loudness(media.clip(tmp("loud.mkv"), 3.0, volume=6.0))     # ffmpeg's sine is 1/8 of full scale
        self.assertLess(quiet["max_momentary"], -30)
        self.assertGreater(loud["max_momentary"], -15)
        tl = [[0.5, -30.0], [1.0, -24.0], [1.5, -25.0], [2.5, -12.0], [3.0, -12.0]]     # a roar after the last word
        self.assertEqual(checks.loudest_during(tl, [(0.8, 1.4)]), -24.0)
        self.assertEqual(checks.loudest_during(tl, [(2.4, 2.8)]), -12.0)
        self.assertIsNone(checks.loudest_during(tl, []))

    def test_review_fails_on_a_cut_and_on_a_bad_join_and_skips_what_it_cannot_run(self):
        good = checks.review(media.clip(tmp("r1.mkv"), 2.0, "blue"), do_speech=False)
        self.assertTrue(good["ok"])
        self.assertIn(("speech", "skip"), [(c["name"], c["status"]) for c in good["checks"]])
        bad = checks.review(media.clip(tmp("r2.mkv"), 3.0, cut_at=1.5), do_speech=False)
        self.assertFalse(bad["ok"])
        self.assertIn("1 cut(s)", bad["summary"])
        asked = checks.review(tmp("r2.mkv"), do_speech=False, asks_for_cut=True)
        self.assertTrue(asked["ok"])                           # a prompt with [Shot 2] asked for the cut
        jump = checks.review(media.clip(tmp("r3.mkv"), 2.0, "yellow"), continuation=True, prev_path=tmp("r1.mkv"), do_speech=False)
        self.assertFalse(jump["ok"])
        self.assertIn("the picture jumps at the join with the part before (difference", jump["summary"])
        silent = checks.review(media.clip(tmp("r4.mkv"), 1.0, audio=False), do_speech=True)
        self.assertTrue(silent["ok"])
        self.assertIn("the clip has no sound", [c["text"] for c in silent["checks"]])

    def test_a_hot_line_is_judged_against_its_own_film(self):
        from unittest import mock
        clip = media.clip(tmp("hot.mkv"), 3.0, volume=6.0)               # speech "peaks" near -6 LUFS
        lines = [{"speaker": "A", "text": "hello there"}]
        heard = {"text": "hello there", "segments": [{"start": 0.5, "end": 2.5, "text": "hello there", "no_speech_prob": 0.0,
                                                       "words": [{"start": 0.5, "end": 1.4, "word": "hello"}, {"start": 1.5, "end": 2.5, "word": "there"}]}]}
        with mock.patch.object(checks, "transcribe", lambda *a, **k: heard):
            alone = checks.review(clip, lines=lines)
            item = next(c for c in alone["checks"] if c["name"] == "loudness")
            self.assertEqual((alone["ok"], item["status"], item["speech"]), (True, "note", True))      # nothing to compare with: a note
            same = checks.review(clip, lines=lines, loud_reference=[item["value"] - 1, item["value"], item["value"] + 1])
            self.assertTrue(same["ok"])                                                              # the whole film is this loud
            hot = checks.review(clip, lines=lines, loud_reference=[-24.0, -23.0, -25.0, -22.0])
            self.assertFalse(hot["ok"])
            self.assertIn("above this film's other parts", hot["summary"])
            two = checks.review(clip, lines=lines, loud_reference=[-24.0, -23.0])
            self.assertTrue(two["ok"])                                                               # two parts are not enough to judge by

    def test_speech_helpers(self):
        self.assertEqual(checks.words("3, 2, 1, go!"), ["three", "two", "one", "go"])
        self.assertEqual(checks.speech_match([{"text": "Best seat in the house."}], "best seat in the house"), 1.0)
        self.assertLess(checks.speech_match([{"text": "the coffee"}], "the cocky"), 0.8)
        heard = {"segments": [{"start": 0, "end": 1, "text": " Thank you for watching.", "no_speech_prob": 0.1, "words": []},
                              {"start": 1, "end": 2, "text": " Get in the car.", "no_speech_prob": 0.2, "words": [{"start": 1.1, "end": 1.3, "word": " Get"}]},
                              {"start": 2, "end": 3, "text": " mumble", "no_speech_prob": 0.9, "words": []}]}
        self.assertEqual(checks.sure_speech(heard), "Get in the car.")
        self.assertEqual(checks.word_spans(heard), [(0, 1), (1.1, 1.3), (2, 3)])
        self.assertIn("00:00:01,000 --> 00:00:02,000\nGet in the car.", checks.srt(heard))
        self.assertEqual(checks.language_code("Dutch"), "nl")

    def test_sheets_and_thumbnails(self):
        c = media.clip(tmp("s.mkv"), 2.0)
        self.assertTrue(checks.contact_sheet(c, tmp("sheet.jpg"), fps=2, cols=4, width=160))
        self.assertTrue(checks.identity_sheet(c, tmp("ident.jpg")))
        self.assertTrue(checks.thumbnail(c, tmp("t.jpg")))
        self.assertTrue(checks.thumbnail(media.picture(tmp("p.png")), tmp("tp.jpg")))
        self.assertTrue(checks.last_frame(c, tmp("last.png")))


class Library(unittest.TestCase):
    def test_add_search_trash_restore(self):
        a = library.add(media.picture(config.home("images", "lib_boat.png")), prompt="a small wooden boat at dawn", seed=5)
        b = library.add(media.clip(config.home("exports", "lib_cut.mp4"), 1.0), "export", name="my cut")
        self.assertEqual((a["kind"], a["width"], a["height"]), ("image", 320, 192))
        self.assertAlmostEqual(b["duration"], 1.0, delta=0.1)
        self.assertEqual(library.add(config.home("images", "lib_boat.png"))["id"], a["id"])       # the same file keeps its id
        self.assertEqual([x["id"] for x in library.search("wooden dawn")], [a["id"]])            # every word, in the prompt
        self.assertEqual(library.search("wooden submarine"), [])
        self.assertEqual([x["id"] for x in library.search("my cut", kind="export")], [b["id"]])
        self.assertEqual(library.search("my cut", kind="image"), [])
        self.assertTrue(os.path.isfile(library.thumb(a)))
        r = library.trash([a["id"]])
        self.assertEqual(r["moved"], [a["id"]])
        self.assertFalse(os.path.exists(config.home("images", "lib_boat.png")))
        self.assertEqual(library.search("wooden"), [])
        self.assertEqual(len(library.search("wooden", trashed=True)), 1)
        self.assertEqual(library.restore(), [a["id"]])
        self.assertTrue(os.path.isfile(config.home("images", "lib_boat.png")))

    def test_only_the_studios_own_files_can_be_moved(self):
        outside = media.clip(os.path.join(config.LONG_DIR, "someones_project", "segments", "part_001.mkv"), 1.0)
        a = library.add(outside)
        r = library.trash([a["id"]])
        self.assertEqual(r["moved"], [])
        self.assertTrue(os.path.isfile(outside))
        with self.assertRaises(ValueError):
            library.add("/etc/hostname")


class Finish(unittest.TestCase):
    def test_levels_are_matched_between_clips_with_speech_only(self):
        self.assertEqual(finish.match_gains([-24.0, -21.0, -24.5, -50.0, None]), [0.0, -3.0, 0.5, 0.0, 0.0])   # the hot part comes down 3 dB
        self.assertEqual(finish.match_gains([-24.0, -60.0]), [0.0, 0.0])                                  # one clip with speech: nothing to match
        self.assertEqual(finish.match_gains([-10.0, -30.0, -30.0]), [-15.0, 0.0, 0.0])                     # a hot clip comes down as far as 15 dB
        self.assertEqual(finish.match_gains([-34.0, -20.0, -20.0]), [6.0, 0.0, 0.0])                       # a quiet one is raised 6 dB at most
        self.assertEqual(finish.match_gains([-20.0, -26.0]), [-3.0, 3.0])                                  # two clips meet in the middle

    def test_export_trims_levels_joins_and_writes_editor_files(self):
        a = library.add(media.clip(config.home("exports", "fx_a.mp4"), 3.0, "blue", volume=1.0))
        b = library.add(media.clip(config.home("exports", "fx_b.mp4"), 3.0, "green", volume=4.0, tone=660))
        song = media.click_track(config.home("audio", "fx_song.wav"), 120, 12)
        tl = finish.blank("Test cut")
        finish.add_clip(tl, asset=a["id"], start=0.5, end=2.5)
        finish.add_clip(tl, asset=b["id"])
        tl["title"] = {"text": "A Title", "subtitle": "under it", "seconds": 1.0}
        tl["music"] = {"path": os.path.relpath(song, config.OUTPUT_DIR), "gain": -20, "duck": 12}
        clips = finish.resolve_clips(tl)
        levels = [finish.measure(p, c["in"], c["out"]) for c, p, _ in clips]
        self.assertGreater(levels[1] - levels[0], 8)                    # the second clip is much louder
        gains = finish.match_gains(levels)
        self.assertLess(gains[1], gains[0])
        out = config.home("exports", "fx_out.mp4")
        cmd, total, (w, h, fps) = finish.build_export(tl, out, clips, gains)
        self.assertAlmostEqual(total, 1.0 + 2.0 + 3.0, places=2)
        finish.run_progress(cmd, total, lambda x, y: None)
        info = checks.probe(out)
        self.assertAlmostEqual(info["duration"], 6.0, delta=0.15)
        self.assertEqual((info["width"], info["height"], info["has_audio"]), (320, 192, True))
        self.assertAlmostEqual(checks.loudness(out)["integrated"], -16.0, delta=2.5)     # normalised
        self.assertEqual(checks.cuts_from(checks.frame_diffs(out))[-1][0] > 2.9, True)   # the cut between the two clips is there

        e = finish.edl(tl, clips, 24)
        self.assertIn("001  AX       AA/V  C        00:00:00:12 00:00:02:12 00:00:00:00 00:00:02:00", e)
        self.assertIn("002  AX       AA/V  C        00:00:00:00 00:00:03:00 00:00:02:00 00:00:05:00", e)
        x = xml.dom.minidom.parseString(finish.fcpxml(tl, clips, w, h, fps))
        spine = x.getElementsByTagName("asset-clip")
        self.assertEqual([(c.getAttribute("offset"), c.getAttribute("start"), c.getAttribute("duration")) for c in spine],
                         [("0/24s", "12/24s", "48/24s"), ("48/24s", "0/24s", "72/24s")])
        self.assertEqual(x.getElementsByTagName("sequence")[0].getAttribute("duration"), "120/24s")
        self.assertEqual(len(x.getElementsByTagName("asset")), 2)

    def test_prores_copy_and_conform_back(self):
        src = media.clip(config.home("exports", "pr_src.mp4"), 1.0, "red")
        mov = config.home("exports", "pr.mov")
        finish.run_progress(finish.prores_cmd(src, mov), 1.0, lambda x, y: None)
        import subprocess
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", mov], capture_output=True, text=True)
        self.assertEqual(sorted(r.stdout.split()), ["pcm_s16le", "prores"])
        # an editor's export: larger, with black bars above and below
        barred = config.home("exports", "pr_barred.mp4")
        media.run("-i", src, "-vf", "scale=640:384,pad=640:480:0:48:black", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", barred)
        self.assertEqual(finish.detect_bars(barred), (640, 384, 0, 48))
        self.assertIsNone(finish.detect_bars(src))

    def test_rough_cut_lands_on_the_beat(self):
        song = media.click_track(config.home("audio", "rc_song.wav"), 120, 20)
        paths = [media.clip(config.home("exports", f"rc_{i}.mp4"), 3.0, c) for i, c in enumerate(["blue", "green", "red"])]
        tl = finish.rough_cut(paths, song, mode="bar")
        self.assertEqual(len(tl["clips"]), 3)
        for c in tl["clips"]:
            self.assertAlmostEqual(c["out"] - c["in"], 2.0, delta=0.06)          # one bar at 120 BPM
            self.assertAlmostEqual(c["in"], 0.5, delta=0.06)                      # trimmed around the middle of 3 s
        self.assertAlmostEqual(tl["beats"]["bpm"], 120, delta=0.5)
        self.assertAlmostEqual(tl["music"]["offset"], 0.35, delta=0.04)


if __name__ == "__main__":
    unittest.main()
