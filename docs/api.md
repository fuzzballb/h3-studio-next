# Agents and the API

Everything the page does, it does through a JSON API on the same address (`http://127.0.0.1:8191` by default). A script
or an agent can do the same. There is no sign-in: the server listens on this computer only, and refuses requests from
other sites' pages.

Send JSON with `Content-Type: application/json`. An error is `{"error": "..."}` with status 400 (it cannot be done,
and why), 404, or 503 (ComfyUI does not answer).

## For an agent

**Render only through the studio.** Its queue runs one render at a time, checks every take, keeps the takes and knows
which part continues which. A graph queued into ComfyUI beside it is none of that, and a second big model next to a
render is how the machine runs out of memory.

**With MCP** (Claude Code and other MCP clients):

```bash
claude mcp add h3-studio -- python3 /path/to/this/repo/mcp/studio_mcp.py
```

The server is one file with no dependencies. Its tools: `studio_status`, `presets`, `prompt_check`, `make_picture`,
`edit_picture`, `make_clip`, `extend_clip`, `job_status`, `cancel_job`, `library_search`, `import_file`, `film_list`,
`film_get`, `film_create`, `film_update`, `film_add_shots`, `shot_preflight`, `shot_render`, `gate_list`,
`gate_approve`, `take_put_back`, `film_run`, `film_stop`, `storyboard`, `film_upscale`, `night_shift`, `film_export`.
Tools that render wait for the job by default and return the files as absolute paths, with each file's `use_as` name
(what to pass as a picture or voice to another tool).

**How to work at the gate.** After `make_clip` or `shot_render`, open the `contact_sheet` and look at it before you
report or approve. The automatic checks see cuts, a jump at a join, wrong or unwanted speech and shouted lines. They do
not see a wrong prop, an empty place or a person on the wrong side. A flaw you notice is a fail: change the prompt and
render again; do not approve it with a note.

**Without MCP**, the same over HTTP:

```bash
# a picture, then a clip that opens on it
curl -s -X POST 127.0.0.1:8191/api/images -H 'Content-Type: application/json' \
     -d '{"prompt": "A rowing boat at a jetty at dawn, mist over the lake, photo.", "width": 1024, "height": 576}'
curl -s 127.0.0.1:8191/api/jobs/<job id>          # until "status": "done"; result.assets holds the Library ids
curl -s 127.0.0.1:8191/api/library/<asset id>     # "ref" is the name to use as a picture
curl -s -X POST 127.0.0.1:8191/api/clips -H 'Content-Type: application/json' \
     -d '{"first_frame": "<ref>", "action": "The boat rocks gently. A duck swims past.", "frames": 124, "width": 864, "height": 480}'
```

`tests/live/smoke.py` is a complete example in Python.

## Routes

### State

| | | |
|---|---|---|
| GET | `/api/state` | Is ComfyUI up (or `starting`: started by the studio and still loading), the recent jobs with their progress, the takes at the gate. The page polls this. |
| GET | `/api/machine` | Memory, GPU, disks, the model picked for each role, which features can run and what they miss, LoRAs, voices. `?refresh=1` asks ComfyUI again. |
| POST | `/api/machine/comfy` | `{"action": "start" \| "stop" \| "free"}`. Stop only works on a ComfyUI the studio started, with an empty queue. Start answers when ComfyUI does; asked again while it loads, it waits for the same one instead of starting a second. |
| GET | `/api/machine/comfy/output` | What ComfyUI printed last, as text with its colour codes and carriage returns: `live` from ComfyUI when it answers, otherwise the end of its newest log file on this computer (`source`, `written`), so a ComfyUI that is loading or died can be read too. |
| GET, PUT | `/api/settings` | The settings; PUT merges a patch. |
| GET | `/api/presets` | Camera moves, framings, looks, apps, coverage plans, angle sets, and the lengths and sizes that work. |
| POST | `/api/prompt/check` | `{prompt, new_shot, lines, seconds}` → findings. |
| POST | `/api/fit` | `{width, height, frames, scale, fps_multiplier}` → will the frames fit in memory. |

### Jobs

| | | |
|---|---|---|
| GET | `/api/jobs`, `/api/jobs/{id}` | The queue; one job with its params and result. |
| POST | `/api/jobs` | `{kind, params, title}`. Kinds: `image`, `shot`, `upscale`, `tts`, `review`, `captions`, `location_sound`, `export`, `resolve`, `conform`, `dailies`. |
| DELETE | `/api/jobs/{id}` | Cancel a waiting or running job; forget a finished one. |
| POST | `/api/jobs/clear` | `{"statuses": ["failed", "cancelled"]}`. |

A job is `{id, kind, title, status, progress, result, error}` with status `queued`, `running`, `done`, `failed` or
`cancelled`.

### Pictures and clips

| | | |
|---|---|---|
| POST | `/api/images` | `{prompt, width, height, takes, seed, template, name}`; with `pictures: [names]` an edit (`keep_size`), with `angles: [views] \| "sheet"` one picture a view. |
| POST | `/api/clips` | One clip: `{place, action, lines, sound, framing, camera, look, people, refs, first_frame, last_frame, width, height, frames, seed, turbo}` or `{mode: "free", prompt}`. With `beats: [...]` a long take. |
| POST | `/api/clips/{film}/extend` | `{action, lines, sound, frames}`: a part that continues the clip. |
| POST | `/api/clips/variants` | The same clip in several `looks`. |
| POST | `/api/compose` | The prompt a clip form would send, with its findings and a time estimate; makes nothing. |

### The Library

| | | |
|---|---|---|
| GET | `/api/library` | `?q=&kind=&film=&trashed=1`. `q` looks in names and prompts. |
| GET | `/api/library/{id}` | One file: `url`, `thumb`, `ref` (its name as a picture or voice), prompt, seed, checks. |
| POST | `/api/upload` | Multipart, field `file`. Kept under `output/studio_next/uploads`. |
| POST | `/api/library/import` | `{path}`: a file already under ComfyUI's output or input folder. |
| POST | `/api/frame` | `{asset, at: seconds \| "first" \| "last"}`: a frame of a clip as a picture. |
| POST | `/api/library/trash`, `/restore`, `/empty-trash` | `{ids}`; restore without ids undoes the last deletion; emptying needs `{"confirm": "erase"}`. |
| GET | `/media/{path}`, `/input/{path}`, `/thumb/{id}.jpg` | Files under output/, under input/, and thumbnails. |

### Writer

A conversation with Claude through the Claude Code program on this computer (`claude -p`, no tools, no saved session). Only for requests from this computer.

| | | |
|---|---|---|
| GET, POST | `/api/writer` | `{state, conversations}`; POST `{film}` starts a conversation (about that film, or a new one). |
| GET, DELETE | `/api/writer/{id}` | One conversation: `{id, film, turns: [{role: user, text} \| {role: writer, answer: {say, questions, film, edits}, meta, applied}]}`. DELETE moves it to the trash. |
| POST | `/api/writer/{id}/say` | `{text}`: a turn. Waits for the answer (a whole film took 39 s). |
| POST | `/api/writer/{id}/apply` | `{turn}`: make the proposed film, or apply the proposed edits to the film. Returns `{film, report: {made, updated, added, removed, rerender}, conversation}`. |

### Films

| | | |
|---|---|---|
| GET, POST | `/api/films` | The list (`?quick=1` for clips), each with `next`: the first step that is not done (see `steps`), or null when the film is finished; a new film `{name, bible}`. |
| GET, PUT, DELETE | `/api/films/{id}` | A film comes with `steps`: the seven steps of making it in order (`films.STEPS`: bible, cast, shots, blockout, storyboard, roll, deliver), each `{id, n, label, what, done, optional, todo}`; once every shot is approved the steps before count as done (`passed` when something there is still missing). PUT merges what a person edits (`name, bible, cast, locations, props, gate, shots, blockouts`); takes, status and part numbers stay the server's. The answer's `report` lists parts that moved and continuations that went stale. A film's `blockouts` are one per scene: `{id, scene_name (the shots' Scene), scene (the form in docs/prompting.md "Blockouts"), cuts ({shot id: start frame} for a new shot whose stretch should not start where the one before ends)}`; the server adds `video`, `made`, `stats`, `state` `{made, current, error, small, frames}` and `stretches` (each shot's `{index, id, start, frames, end, continuation, auto}`; a continuation starts 39 frames before the end of the shot it continues). A shot follows its scene's blockout on its own; with `blockout` (a loader name, e.g. an upload) it follows a video of its own instead, from `blockout_start` (0 = the start; for a continuation of a shot with the same video: 39 frames before where that one stopped). Both use `blockout_shapes` (what the shapes are; empty = said from the scene's things) and `blockout_strength` (0 = Settings → blockout, 0.997). |
| POST | `/api/films/{id}/compose/{shot}` | Preflight: prompt, pictures, voices, findings, `eligible` and `why`. A shot with a blockout also gets `blockout: {file, start, end, strength, shapes, frames}` (the frames it reads, and how many the video has). |
| POST | `/api/films/{id}/render/{shot}` | A new take: `{seed, force}`. |
| POST | `/api/films/{id}/preview/{shot}` | `{seed?, take?}`: a very small render of the shot (short side `preview.short_side`, 256 px) into a project of its own per take (`<film project>_preview_<opener>`), with the same prompt, pictures, voices and blockout. Nothing in the film changes: no part, no take, no gate. A continuation continues the preview of the shot before (refused until that one is there); `take: true` queues the take's shots up to this one in order. The result lands on the shot as `preview` `{file, seed, width, height, frames, time, seconds_taken, prompt, blockout}`; a new preview of a shot clears the previews after it in its take. |
| POST | `/api/films/{id}/blockouts/{bid}/make` | Render a scene's blockout in Blender (cpu lane), long enough for every shot's stretch and for the whole scene. Its shots then follow their stretches. |
| POST | `/api/films/{id}/blockout/{shot}` | The same for the scene this shot is in. |
| POST | `/api/blockout/check` | `{scene}`: the scene filled in and checked (`{scene, blender}`), or `{error, blender}`. |
| POST | `/api/films/{id}/approve/{shot}` | Approve the active take. |
| POST | `/api/films/{id}/take/{shot}` | `{n}`: put take n back. |
| POST | `/api/films/{id}/run`, `/stop` | Render every shot without a take: `{mode: hold \| auto \| keep_going, retries, upscale}`. |
| POST | `/api/films/{id}/storyboard` | `{shots, takes}`: stills, drawn by the picture model. A shot with its own prompt is drawn from those words without its spoken lines and sound; a continuation also gets the place and people of the shot that opened it. |
| GET | `/takeframe/{id}/{shot}.jpg` | A frame from the middle of the take the shot has in the film (the storyboard shows it for a rendered shot). |
| POST | `/api/films/{id}/upscale` | `{first, last, force}`. |
| POST | `/api/films/{id}/outline` | `{plan, a, b, place}` (a coverage plan) or `{logline, scenes, shots}` (the writing help). |
| POST | `/api/films/{id}/timeline` | The film's takes as a new timeline (`{upscaled}`). |
| GET | `/api/films/{id}/story` | The film as a story-kit file. |
| GET | `/api/projects` | Long-video projects on disk that no film owns (made with the story kit or the workflows). |
| POST | `/api/films/adopt` | `{project, name, story}`: open such a project as a film, one shot a part with its part as an approved take. The project folder is left where it is. `story` (optional) is the path of the story-kit file it was made from. |
| POST | `/api/films/{id}/story` | `{path}`: read that story file into a film that was brought in: prompts and lines per part, cast, places, props, the bible. Answers `{film, report}`; `report.same` counts the parts the studio composes exactly as the story kit sends them, `report.differ` lists the others, `report.missing` the story's pictures and voice samples that are not in ComfyUI's input folder. The file is a program and is run: only for a request from the studio's own computer. |
| GET, PUT | `/api/cast` | The cast library. |

### Timelines and sound

| | | |
|---|---|---|
| GET, POST | `/api/timelines` | The list; a new one. |
| GET, PUT, DELETE | `/api/timelines/{id}` | `{name, clips: [{path, in, out, gain}], music: {path, gain, duck}, title, captions, width, height, fps, loudness, match}`. |
| POST | `/api/timelines/{id}/clips` | `{assets: [ids]}`. |
| POST | `/api/timelines/{id}/export` | The export job; `{"resolve": true}` for the ProRes package. |
| POST | `/api/beats` | `{asset \| path}` → `{bpm, beats, downbeats, bars, duration}`. |
| POST | `/api/roughcut` | `{film \| assets, song \| song_path, mode: own \| bar \| two_bars \| beat, order}` → a timeline cut on the beat. |
| GET | `/api/voices` | The TTS suite's voices and the sound files of the Library. |
| POST | `/api/tts` | `{text, voice, seed, name}`. |

### Night shift

| | | |
|---|---|---|
| GET, POST | `/api/nightshift` | Plan one: `{film, start: now \| idle \| HH:MM, retries, upscale}`. |
| POST | `/api/nightshift/{id}/start`, `/cancel` | |
| POST | `/api/dailies` | `{film, since}`: a reel and notes of a film's takes. |

### What H3 Studio Next adds

| | | |
|---|---|---|
| GET | `/api/library` | Also takes `favorite=1`, `folder=<id> \| none`, `source=upload \| made`, `surface=<name>`, `sort=newest \| oldest \| name \| kind`, and `kind` as a comma list. |
| GET | `/api/library/summary` | Counts per kind, favourites, uploads, trash and folders, for the Library's side list. |
| PATCH | `/api/library/{id}` | `{favorite, name, folder}`. |
| POST | `/api/library/bulk` | `{ids, action: favorite \| unfavorite \| move, folder}`. All or nothing; at most 200 ids. |
| GET, POST | `/api/folders` | List, or `{name}` makes one (names are unique, any case). |
| PATCH, DELETE | `/api/folders/{id}` | Rename; delete (its files stay, in no folder). |
| POST | `/api/estimate` | `{kind: image, takes}` → about how many seconds, from this machine's past renders. |
| GET, POST | `/api/canvas` | The boards; `{name}` makes one. |
| GET, PUT, DELETE | `/api/canvas/{id}` | GET adds `assets` (the Library records on the board, `null` when gone). PUT replaces `{name, items, view}`. |
| GET, POST | `/api/agent` | The chats, and whether Claude Code is there; POST starts a chat. |
| GET, PATCH, DELETE | `/api/agent/{id}` | PATCH `{ask_first, title}`. GET fills in each action's job, progress and what it made. |
| POST | `/api/agent/{id}/say` | `{text}`: Claude Code answers with words and actions. With `ask_first` the actions wait as `proposed`. |
| POST | `/api/agent/{id}/act` | `{action, allow}`: run a proposed (or failed) action, or say no. |
| POST | `/api/shorts/plan` | `{idea, parts}` → a plan: title, look, place, people, beats with the action, sound and exact lines. |
| POST | `/api/shorts` | `{plan, size, face, voice}`: renders the plan as one film whose parts continue each other. |

Pictures and quick clips keep `form` (the request they were made with) and `surface` (the page they came from) on their
Library record; Recreate uses them.

## Where things are

Everything is under ComfyUI's output folder:

```
output/studio_next/            the studio's own data (STUDIO_HOME)
  settings.json  jobs.json  telemetry.json
  images/  uploads/  audio/  exports/  dailies/  trash/
  films/<id>/film.json         the plan
  films/<id>/takes/<shot>/     every take: frames, latent, conditioning, preview, contact sheet
  library/index.json           what is known about every file
  library/folders.json         the Library's folders
  canvas/<id>.json             a board
  agent/<id>.json              an agent chat
output/long_video/st_<id>/     the parts of a film, as the long-video nodes keep them
```
