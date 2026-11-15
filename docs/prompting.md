# Prompting MiniMax H3

What the studio writes into a prompt, why, and what to watch for when you write your own. Every rule here comes from a
render that went wrong and the change that fixed it. The studio's prompt check (Learn → Prompt check, and the preflight
of every shot) looks for the patterns marked **checked**.

## How a prompt is built

A new shot:

```
The video is in realistic photographic cinematic style: natural colours, soft contrast, ...        ← the film's look
[Shot 1] A small bar with a steel counter... Other guests sit at the counter; they stay in the background.
The place looks exactly like Picture 4; no readable text, letters, signs or logos anywhere.
Sam from Picture 1 and Picture 2, a man in his thirties..., wearing the outfit from Picture 2; he sits on the left side of the picture.
Lisa, her face is exactly the face in Picture 3: a woman in her thirties...; she sits on the right side of the picture.
Close medium two-shot from the chest up, the camera is close so both faces are large in the frame, static shot on a
locked, still camera, one continuous take, it never cuts and there are no close-ups.
They look at each other while they talk, like in a real conversation, ...; nobody looks into the camera. ...
Sam puts the parcel from Picture 5 on the table. Sam (S1) says, looking at Lisa, his face in three-quarter view and
clearly visible to the camera, his lips moving clearly and in sync with every word, speaking in the voice from <Audio 1>,
friendly, a bit out of breath, <d>[English] Urgent delivery for you.</d> Lisa (S2) answers, looking at Sam, ... relieved,
laughing softly, <d>[English] Finally. I have been waiting all week.</d> Those are the only words; after that nobody says
anything else.

overall_soundscape:
Quiet bar chatter far in the back, glasses clinking.
```

A part that continues the shot before:

```
The video is in realistic photographic cinematic style: ...
Continue the same shot without a cut: the same place, the same light and the same camera position.
Lisa opens the parcel and smiles. Nobody speaks, there are no words at all.

overall_soundscape:
Paper rustling.
```

**Pictures are numbered in the order the model labels them:** a first frame (Picture 1), a last frame, then the
reference pictures: each person's face and outfit sheet in cast order, the place's plate, the props the shot names,
further pictures. The preflight lists the numbers. Voices are `<Audio 1>`, `<Audio 2>`... in cast order.

**A continuation names no place and no pictures.** The last 39 frames of the part before, with their sound, are frozen
at its start: they carry the place, the people and the light. The reference pictures are still attached.

## People

| Rule | What went wrong without it |
|---|---|
| **Big faces.** Use "Close medium two-shot from the chest up, the camera is close so both faces are large in the frame" for dialogue. | In a wide two-shot (a face about 90 px high) the likeness of a trained person dropped a lot. |
| **A face picture, and say so:** "her face is exactly the face in Picture 2". | Without it a second person drifted toward the face of the person a LoRA was trained on. |
| **Describe only what should differ** from the picture or the LoRA (the outfit, the hair style). | A full face description fought the LoRA. |
| **An outfit sheet** (whole body, several views) for clothes that must stay the same. | Clothes described in words change from shot to shot. |
| **Name sides:** "sits on the left side of the picture". **checked** for cars | Two people swapped sides between parts; a person got into a car on the wrong side. |
| **No small facial actions** (winks, a raised eyebrow). **checked** | The model cut to a face close-up for them. |
| **One turn at most.** **checked** | Turning back and forth made the model redraw the background. |

## Speech

| Rule | What went wrong without it |
|---|---|
| **Every spoken word is a line with its exact words.** Never "he counts down" in the action. **checked** | The model spoke what the action described and garbled it. |
| **A part without lines says so:** "Nobody speaks, there are no words at all." The studio adds it. **checked** | The model filled the silence with mumbling. |
| **A busy place gets short lines, or "they make no words".** | Background people babbled. |
| **End the lines:** "Those are the only words; after that nobody says anything else." The studio adds it. | A part with one short line was filled with chatter. |
| **About 2.6 words a second**, and a continuation only adds 8.5 s. **checked** | Lines were cut off or rushed. |
| **How it is said** goes before the words: "relieved, laughing softly". | One acting cue per line made the acting much better. |
| **Volume in words:** "urgent but at a normal speaking volume". A full stop, not an exclamation mark, when laughing. **checked** | Shouted lines came out at −15 to −19 LUFS next to speech at −23 to −26. |
| **"His face in three-quarter view and clearly visible to the camera"**, not "facing the camera". **checked** | They talked into the lens instead of to each other. |
| **Never while eating or drinking.** | Lips went out of sync. |
| **No LoRA trigger words in a part with lines.** The studio leaves them out. **checked** | The model spoke the trigger word ("D.Y."). |
| **A hard word:** "saying the word coffee slowly and very clearly". | "coffee" was heard as "cocky". |
| **An accent you do not want:** "in his own normal voice and accent". | A trained voice turned British in a running part. |

After rendering, the studio transcribes every part with Whisper and compares it with the lines (a match under 0.8
fails; a part without lines must stay without words). It also measures how loud the speech peaks and compares that with
the film's other approved parts: more than 2.5 dB above their median fails. The level of the sound differs from clip
to clip for reasons that have nothing to do with shouting (a calm talking head came out 12 dB hotter than another), so
a fixed limit is not used, and the export brings the parts to one level.

## Places, things and the camera

| Rule | What went wrong without it |
|---|---|
| **Say what is there.** The model has no negative prompt: naming a thing can make it appear. **listed** by the check | "No photographs appear anywhere" hung the wall with photographs (reported by Imagination Studio); "run away from the fire" showed people walking toward it. Fixed by "the alley is empty". |
| **One plate per place,** made once and used in every new shot of that place. | The bar, the alley and the car looked different in every scene. |
| **A sheet for every prop** that must stay the same, named in the shot by its token. | A bike, a parcel and a car changed from part to part. |
| **Say where every object comes from** ("takes the helmet out of the top case"; "a waiter's hand brings two cups"). | Objects popped into existence. |
| **One camera instruction.** Static and moving in one prompt invites cuts. **checked** | The model cut. |
| **"one continuous take, it never cuts and there are no close-ups"** on new shots. The studio adds it. | Unasked insert shots and close-ups. It reduces them; it does not stop them, so every part is checked for cuts. |
| **Lettering:** "no readable text, letters, signs or logos anywhere", and name the surface ("the window is plain clear glass"). | Mirrored nonsense lettering on a window. |
| **In a car:** "the windshield glass is clean and clear"; accelerate instead of swerving. **checked** | A swerve and "light streaking over the windshield" drew neon signs sliding across the glass. |
| **Getting into a car:** name each person's door. **checked** | Both got in on the driver's side. |
| **Night:** name the light sources and "both faces clearly lit". | Dark scenes lost the likeness. |

## Continuations

| Rule | What went wrong without it |
|---|---|
| **Name only what is in view at the END of the part before.** Look at its contact sheet (the preflight shows it). **noted** by the check | "Looking back toward the orange glow" swapped the whole background at the join, without a visible cut. |
| **A new place starts where the last picture ended:** "It starts exactly where the last picture ended: the same narrow street... then the car drives out onto the highway." | A highway at dusk replaced a narrow street at the join. |
| **Order events in time; a line comes after its cause:** "During the first four seconds nobody speaks: the police car falls behind... Only after it is gone, he says..." | "We lost them" was said with the police still in the rear window. |
| **Few actions per part.** **checked** | Three actions in a row in a continuation brought cuts. |
| **A new size or angle is a new shot**, with the same plate and "from the first frame they already sit...". | A continuation that needed another camera position cut in every take. |
| **The part after a mid-action ending is a new shot.** | The part after a frozen jump cut every time. |

The studio measures every join: the last frame of the part before against the first frame of the continuation. Good
joins measured 1 to 9, swapped backgrounds 29 to 52; above 25 the take fails.

## Blockouts

A shot with a blockout is rendered with H3 V2V: the blockout is encoded, noised almost all the way (the strength) and
also shown to the model as `<Video 1>`. The prompt then starts with a paragraph that says the shapes are stand-ins and
the camera is the blockout's. Measured on a 10-part film (2026-11-14, a sled flight over a city and a man in a street,
1152×640, turbo, 8 steps, about 7 minutes a part on an RTX 3090):

| Rule | What went wrong without it |
|---|---|
| **Strength 0.997.** | At 0.9995 three of ten parts dropped the blocked camera: a high diagonal view came out at eye level down the middle of the street, a camera circling a man kept looking up the street. 0.994 followed too, but left the buildings as flat textured blocks; 0.99 and below show the blockout with textures. |
| **Leave Framing and Camera empty; describe the blocked camera in words if it is unusual.** **warned** | "Close to Santa" in the action gave a close-up over a wide blocked shot. Writing the blocked camera out ("high above the right-hand pavement, looking down at a steep angle, the street runs diagonally, no sky") fixed both failing parts. |
| **Say what each shape is** (What the shapes are). | Without it a red box stays a box. |
| **No picture of a place that shows another view.** | A photo of the street looking down its length pulled a shot that circles a man back to that view. |
| **A continuation reads on in the same blockout.** | Rendered from its own start, the frozen context (the end of the part before) and the blockout under it differ and the part jumps. With `keep_latent_mask` on the Continue node the part after the context keeps following the blockout; without it everything after the context is generated freely and the camera is lost. |

### When the render does not follow the blockout

Seen 2026-11-14 ("Last Stop", a cyclist racing a tram): the camera followed her 9 m ahead with a 28 mm lens, so she
filled about 15% of the picture height, and she was a bike with nobody on it. The prompt said "keeps her large in the
middle of the picture". The render drew her large, put the camera close in front of her and kept only the street: the
words won where they disagreed with the blockout. With the camera 5 m ahead at 35 mm, level with her at every key, she
filled about 60%, and the preview kept that size and the leading camera. But it put the tram on the left and the parked
cars on the right, as the words said, while the blockout had them the other way round; and in the continuation it drew
the glass shelter the words asked for, which the blockout had placed inside a house wall, from a side view of its own.
Left and right in the words are the picture's, and everything the words name has to be visible in the blockout. With the
scene mirrored and the shelter moved onto the pavement, both previews followed the blockout frame by frame: her size,
the leading camera, the tram on the left, the cars on the right, and the stop beside the shelter.

So the blockout and the words must agree. Blender measures every thing's share of the picture height and of the time it
is in view (`stats.json` next to the blockout, `stats` on the film's blockout); Preflight warns (`blockout-small`) when a
subject the camera follows stays under 25% of the height or is in the picture under 70% of the time.

### Making a blockout here

A blockout belongs to a scene: the shots that share a Scene name (step 4, Blockout, or written by the Writer). It is
the set, the moving things and the camera as data, which the studio renders in Blender with a script of its own (grey
Workbench shapes; 17.9 s for the 17.9 s of "Last Stop" at 576×320 on this machine). Its time runs through the scene's
shots in order, and it is cut into them: each shot reads its stretch, a continuation starts 39 frames before the end of
the shot it continues (those frames are its frozen context), and a new shot starts where the one before ends unless its
cut is moved. It renders as long as its shots need, or as its own last key, whichever is longer. A shot with a video of
its own (Shots → Blockout → Follow a video of its own) follows that instead. Nothing in a scene is run as code. The
form, in short (metres, seconds, z up, a facing of 0 looks along +x):

| Part | What it holds |
|---|---|
| `sky`, `ground` | day, dusk, night, indoor · grass, snow, asphalt, sand, floor, water, none |
| `set` | street (along +x from `at`; size = length, road width, house height), room (walls at the back and the sides), building, city (roofs to fly over), box, wall, cylinder, ball, cone, tree; `at`, `size`, `turn`, `color` |
| `things` | person, child, cyclist, car, van, truck, bus, tram, train, bike, horse, dog, animal, bird, box, ball, sled, boat, plane; `keys`: `t`, `at`, `face` (or null: the way it moves), `pose` (stand, walk, run, sit, lie, crouch, look_up, look_down, wave) |
| `camera` | `lens` (mm), `shake` (m), `keys`: `t`, `at`, `look_at` or `follow` (a thing's name), `lens`, `cut` (true: the camera jumps to this key instead of moving there, a cut to another angle; put it where a new shot starts) |

The names and colours of the things become "What the shapes are" in the prompt ("the blue figure is Sam") unless the
shot says it itself. A scene changed after it was made, or a shot whose length changed, shows as out of date: make it again.

Fine motion (wheels turning, fingers, small props) does not come through at these strengths; paths, staging, jumps,
camera moves and scale do. A blockout needs no sound: the studio gives it a silent track that runs past the picture
(the V2V node refuses a source whose sound is shorter) and makes it 24 fps.

## Storyboard stills

A still is drawn by the picture model, not by the video model: it resembles the clip and is never the same picture. A
shot that is rendered shows a frame of its take on the storyboard; that is the film itself.

- A shot with its own prompt is drawn from those words without what one picture cannot show: the sound section, the
  spoken lines, "one continuous take". Before that (2026-11-12, a 20-part story brought in from the story kit) the
  stills only got the cast and the place, and came out as two people posing for the camera in every shot. **fixed**
- A continuation's prompt names neither its place nor how the people look, so its still also gets the place and the
  people of the shot that opened it, without where they stood then: with "he walks on the left" in it the man was
  drawn twice, once walking in and once seated. **fixed**

## Lengths and sizes

- A clip is 17n + 5 frames at 24 frames a second: 73, 90, 107, 124 (about 5 s), 192 (8 s), 243 (10 s), 362 (15 s)...
- **Short parts do not always fit the sound.** H3's sound runs on a 40 Hz grid; a part whose decoded sound is more than
  0.5 % off its picture's length is refused by the nodes. That rules out 22 and 56 frames for a new shot, and 56, 73 and
  107 frames for a continuation (measured: a 73-frame continuation, 0.59 % off). The studio offers only lengths that fit.
- Width and height are multiples of 32. 1280×720 gets a garbage strip at the bottom; use 1280×704.
- A continuation adds 39 frames less than it renders: 243 frames add 8.5 s.

## LoRAs

- The studio lists LoRAs by what ComfyUI has. Quantized "int8convrot" LoRAs are left out: through the plain loader they
  give pure noise.
- Keep the extra LoRAs around 1.2 to 1.3 in total. Three at full strength on the 8-step turbo made moving objects
  ghost (a parcel turned see-through). **noted**
- A person LoRA goes on the person (Cast), at 1.0, and is used in the upscale too, or the face drifts there.
- A LoRA trained on one base model wants that model: set it in the film's Bible.

## What the checks do not see

A wrong prop, a popular bar with nobody in it, an old car in a futuristic city, a person on the wrong side, one person
visible in a car that holds two. That is what the gate is for: look at the contact sheet of every part before the next
one builds on it, and treat a flaw you notice as a fail, not a note.

More of the same, with the stories they came from: [the long-video manual](long-video.md#prompting-tips).
