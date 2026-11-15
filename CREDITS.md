# Credits

H3 Studio Next is H3 Studio with a new front end. H3 Studio is glue and judgement around other people's models and nodes. It ships no model weights.

## What it stands on

| | By | Used for |
|---|---|---|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | Comfy Org and contributors | Runs every model. The studio talks to its API. |
| MiniMax H3 | MiniMax | Video with sound. |
| Qwen-Image 2.1 | Alibaba / the Qwen team | Pictures and picture edits. |
| [ComfyUI-PlagueKind-Nodes](https://github.com/PlagueKind/Comfyui-PlagueKind-Nodes) | PlagueKind | The combined H3 encode node, the AdaLN LoRA fix, the tiled latent upscale. |
| [ComfyUI-H3-Motion-Context-MultiRef](https://github.com/seitanism/ComfyUI-H3-Motion-Context-MultiRef) | seitanism | Continuing a part from the latent of the one before, and trimming picture and sound together. |
| [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) | kijai | Low-VRAM attention, chunked feed-forward, previews, sharpening. |
| [TTS Audio Suite](https://github.com/diodiogod/TTS-Audio-Suite) with ChatterBox | diodiogod; Resemble AI | Voice-over. |
| [openai-whisper](https://github.com/openai/whisper) | OpenAI | Hearing what a clip says, for the speech check and captions. |
| FFmpeg | the FFmpeg developers | Every check, cut, export and sheet. |
| FILM | Google Research | Frame interpolation to 48 fps. |

Each model and node pack has its own licence. Read them before commercial use; some model weights are non-commercial
or limited by territory.

## Where ideas came from

- **[Parallax](https://github.com/nickvasilescu/parallax)** by Nick Vasilescu (MIT, Copyright (c) 2026 Nick Vasilescu)
  for the look of this front end and several of its features: the dark palette with a lime accent, the top bar, the
  floating composer with chips, studio cards and feature tiles, an Explore feed with Recreate, Remix, Shorts, an agent
  chat that asks before it spends, a canvas, and a Library with folders and favourites. Everything was written again in
  plain JavaScript on H3 Studio's API, for local models; no Parallax code, text, logos or pictures are used.
- **[H3 Studio](https://github.com/fuzzballb/comfyui-h3-studio)**, the repo this one is built on: the whole backend,
  the film rooms, the checks and the gate.
- **[Imagination Studio by keys+Wasserman](https://github.com/drowzeys/Imagination-Studio-by-keys-Wasserman)** (Apache-2.0)
  showed what a local film studio around these models can be. Ideas taken from its guides, written again here for
  ComfyUI on one GPU: one-click apps, the prompt check for words that forbid (the model has no negative prompt), the
  shot check with the longest stretch without a cut, three frames side by side as an identity sheet, the night shift
  with a dailies reel and notes, cutting to a song's beats found with numpy, a film bible with cast and place sheets,
  coverage plans, and saying how every number was measured. No code was copied.
- **Hosted video studios** (Higgsfield and others) for what people now expect to find: camera moves, lenses and looks
  by name, reusable characters, a storyboard before any clip, first and last frames, product sheets, one shot in
  several looks. Here they are words, pictures and LoRAs on your own machine.
- **[comfyui-h3-long-video](https://github.com/fuzzballb/comfyui-h3-long-video)**, the repo this one grew from: its
  nodes, workflows and story kit are bundled unchanged, and the gate, the checks and the prompting rules come from the
  films made with it.
