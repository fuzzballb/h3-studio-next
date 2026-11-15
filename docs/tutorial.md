# Tutorial

Each part takes a few minutes. The times are from an RTX 3090 with 24 GB.

## 1. A picture, then a clip that opens on it

1. **Picture**: describe a place or a thing, pick a size, make two takes. A picture takes 10 to 30 seconds.
2. Under the one you like, press **Animate**. Video opens with it as the first frame.
3. Write **what happens** in one or two sentences. Pick a camera move if you want one. Leave the lines empty.
4. The right side shows **what the model gets**: the whole prompt, the pictures by number, the length and a time estimate.
   Under it, the **prompt check** lists what tripped the model in real runs.
5. **Render**. The queue on the right shows the step. A 10 s clip at 1152×640 takes about 8 minutes; pick
   864×480 and 5 seconds for a draft in under 2 minutes.
6. When it is done, open the clip. Its checks are listed with the take: cuts, speech, loudness, and whether the first
   frame was held. The contact sheet shows two frames a second.

## 2. Carry a clip on

In the clip's page, **Carry it on**: say what happens next and press Extend. The new part starts from the last 39 frames
and their sound, in latent space, so the place and the light carry through. Describe only what is in view at the end of
the clip. Naming something off-screen makes the model cut to it; the join check then fails the take, and you render it
again with other words.

## 3. Two people talking

1. **Video**, start from **References**. Add two people. Give each a **face** (make one in Picture → "A face for a
   character", or upload a tight crop) and, when their clothes matter, an **outfit sheet** (Edit a picture → Reference
   sheet → Character sheet).
2. Write **where each one is**, with the side of the picture.
3. Framing: **Close two-shot**. Camera: **Locked-off**.
4. Add **lines**: who, the exact words, and how it is said ("warm, half whispering"). About 22 words fit in 10 seconds.
5. A **voice sample** (10 to 20 s of clean speech) on a person makes the model speak their lines in that voice.
6. Render. Whisper compares what is said with your lines; a match under 0.8 fails the take.

## 4. A film

A film is made in seven steps, the numbered tabs of the film. A tab gets a tick when its step is done, the line under
the tabs says what is still missing, and the bottom of each tab leads to the next step. The film list and Home say the
step every film is at. The **Writer** (in the sidebar, or **Films → Write it with the Writer**) does steps 1, 3 and 4
from a small story; the film then opens at step 2.

1. **Films → Start empty.** In the **Bible**, pick the look, the size and the length of a shot, and how the gate works.
2. **Cast & places**: characters with their pictures, places with a **plate** (an empty picture of the place; the same
   plate in every new shot keeps the place the same), props with a **sheet**.
3. **Shots**: add them from a **coverage plan** (Arrive, sit, talk; Walk and talk; Chase...) or one by one. A shot is
   either **a new shot** (a cut) or **continues the shot before**.
4. **Blockout** (optional): for a scene where the camera or the staging matters, a rough 3D version of the whole
   scene, rendered in Blender. Write its scene (or let the Writer), **Make the blockout**, play it, change the scene
   and make it again until it works. It is then cut into the scene's shots on the timeline under the player: each
   shot plays its own stretch (click one), a continuation overlaps the shot before by 39 frames, and a new shot's cut
   can be moved. A camera key with `"cut": true` jumps to another angle where a new shot starts.
5. **Storyboard**: a still for every shot from the cast's own pictures, in seconds. Fix the script here, where a
   mistake costs 15 seconds and not 8 minutes. A still can be the frame its shot opens on. A still is drawn by the
   picture model, so it resembles the clip and is never the same picture; a shot that is rendered shows a frame of
   its take above its stills.
6. **Roll camera**: **Preflight** shows the exact prompt, and for a continuation the contact sheet of the shot before.
   **Render this shot.** The take is checked and waits **at the gate**: look at the video and the contact sheet, then
   **Approve** or **Render again**. Nothing continues a part that was not approved.
   Not sure about the staging or the camera yet? **Preview (low res)** renders the shot at 448x256 into a project of
   its own in a fraction of the time; the film does not change. On a continuation, **with the shots before** previews
   the take up to it, so the joins show too. The player above the buttons switches between the preview, the stretch of
   the blockout the shot follows, and the two **side by side**.
   **Render every shot without a take** walks the film in order. *Hold it for me* stops at every take; *Approve what
   passes* only stops at takes that fail their checks after the retakes.
7. **Deliver**: the film so far, **Upscale** (×1.5 and 48 frames a second, about 6 minutes a part), and **To a
   timeline**.

Every take is kept. **Put this take back** makes an earlier take the shot's part again. When you move or remove shots,
the rendered parts are renumbered into a new project folder, and a continuation whose predecessor changed is marked
**stale**: it has to be rendered again.

## 5. The night shift

**Night shift → Plan it**: pick the film and when it starts (now, when the machine has been idle for two minutes, or at
a time). It renders every shot without a take, retakes what fails, and keeps going past a take that still fails. In
the morning there is a **reel** (every take after a title card with its shot, seed and verdict) and **notes** that list
the takes to look at first.

## 6. Cut and export

**Timeline**: order the clips, set In and Out, and **Export**. The clips with speech are brought to the same level
first (one part can come out a few dB hotter than its neighbours), then the cut is normalised to −16 LUFS. A song can
go under it; it is lowered while a clip has sound. **Cut to a song** finds the song's beats and lays the clips on them.

**Package for DaVinci Resolve** writes every clip as ProRes 422 with PCM sound, with an FCPXML and an EDL: the free
Resolve on Linux reads neither H.264 nor AAC. **Bring an editor's export back** cuts off black bars and scales an
export to the film's own size.

## 7. When something goes wrong

| What you see | What to do |
|---|---|
| "ComfyUI does not answer" | Start it (the queue panel has a button when a start command is known), or set its address in Machine. **ComfyUI output** in the menu shows what it printed last, also when it died. |
| A feature is greyed out | Machine → What can run says which node pack or model is missing. |
| "this cannot be rendered: missing file(s)..." | A picture or voice a shot names is gone: pick it again in Cast or in the shot. |
| "... keeps about N GB of frames in memory" | The size times the length does not fit in RAM. Use a smaller size or a shorter part. |
| A take fails "cuts" | The model cut inside the shot. Render again; with fewer actions; or make the cut a new shot. |
| A take fails "join" | The continuation's prompt named something that was not in view. Rewrite it from the contact sheet of the shot before. |
| A take fails "speech" | The words were garbled. Render again; shorten the lines; write a hard word "slowly and very clearly". |
| A take fails "loudness" | Its speech is much louder than the film's other parts. Listen: for a shouted line, "at a normal speaking volume" and a full stop instead of an exclamation mark; a part that is only recorded hot can be approved, the export levels it. |
| ComfyUI disappears during a long job | The job says so, with the kernel's out-of-memory line when there is one. |
