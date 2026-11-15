"""The ComfyUI graphs the studio queues, built in code.

`clip()` and `upscale()` make the same graphs as example workflows 1 and 2 (story_kit/templates), with the switches
resolved here: a LoRA that is off is not in the graph at all, so nothing loads a file it does not use and a missing
optional model cannot make ComfyUI refuse the job. Settings that matter are copied from those workflows and are
explained in docs/long-video.md ("Settings that matter"): no H3 MiniMax Cache in the generate chain (continuations
ignore their context with it), SLA attention off (backgrounds warp), sizes in multiples of 32.

`roles` is models.resolve(): role -> installed file.
"""
import os

from . import config, lengths

MAX_REFS = 9          # PK_MiniMaxH3Combined takes reference_image_0 .. 8
MAX_VOICES = 4        # H3LongVideoReferenceAudios takes audio_1 .. 4
MAX_PICTURES = 9      # further pictures of a Qwen edit


def _need(roles, *names):
    missing = [n for n in names if not roles.get(n)]
    if missing:
        from .models import ROLE_TITLES
        raise ValueError("no model installed for: " + ", ".join(ROLE_TITLES[m] for m in missing))


def _lora_chain(g, start, loras, first_id=90):
    prev = start
    for i, (name, strength) in enumerate(loras or []):
        nid = str(first_id + i)
        g[nid] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"lora_name": name, "strength_model": float(strength), "model": prev}}
        prev = [nid, 0]
    return prev


def clip(roles, *, project, part, prompt, new_shot=True, width=1152, height=640, frames=243, seed=0, turbo=True,
         refs=(), first_frame=None, last_frame=None, voices=(), loras=(), unet=None, steps=None, sla=False,
         preview=True, crf=14, video=None):
    """One part of a long-video project: part 1 or a new shot starts fresh, any other part continues the one before
    in latent space (its last 39 frames and their sound stay frozen at the start).

    refs         reference pictures, in order: <Picture 1>, <Picture 2>... (after a first/last frame, which come first)
    first_frame  a picture the part opens on (new shots only); last_frame = a picture it ends on
    voices       voice samples, in order: <Audio 1>, <Audio 2>...
    loras        [(file, strength)], applied after the turbo LoRA
    """
    v = (video or config.settings()["video"])
    lengths.check_size(width, height)
    lengths.check_fit(frames, continuation=not (new_shot or part == 1))
    _need(roles, "video_unet", "video_clip", "video_vae", "audio_vae")
    if turbo:
        _need(roles, "turbo_lora")
    if len(refs) > MAX_REFS:
        raise ValueError(f"{len(refs)} reference pictures: the model takes {MAX_REFS}")
    if len(voices) > MAX_VOICES:
        raise ValueError(f"{len(voices)} voice samples: a part takes {MAX_VOICES}")
    cont = not (new_shot or part == 1)
    if cont and first_frame:
        raise ValueError("a part that continues the one before opens on its frames; a first frame needs a new shot")

    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet or roles["video_unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": roles["video_clip"], "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": roles["video_vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": roles["audio_vae"]}},
    }
    model = ["1", 0]
    if sla:      # off by default: it makes straight background lines warp; ~2.8x faster per step
        g["5"] = {"class_type": "H3SLAAttention", "inputs": {
            "sparsity_ratio": 0.7, "block_size": "32", "min_seq_len": 12288, "dense_last_steps": 0, "protect_audio": False,
            "enabled": True, "dense_steps": "1", "dense_backend": "comfy_kitchen", "disable_fp16_accum": True,
            "stabilize_motion": False, "reference_protection": "Off", "tail_correction": False, "use_int8_qk": True,
            "engine": "comfy_kitchen", "model": model}}
        model = ["5", 0]
    g["6"] = {"class_type": "MiniMaxLowVRAMAttention", "inputs": {"head_chunks": 4, "model": model}}
    g["7"] = {"class_type": "MiniMaxChunkFeedForward", "inputs": {"chunks": 2, "seq_threshold": 4096, "model": ["6", 0]}}
    model = ["7", 0]
    if turbo:
        g["71"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": roles["turbo_lora"], "strength_model": float(v["turbo_strength"]), "model": model}}
        g["72"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "shift_video": float(v["shift_video"]), "shift_audio": float(v["shift_audio"]), "model": ["71", 0]}}
        model = ["72", 0]
    model = _lora_chain(g, model, loras)
    if preview and roles.get("tiny_vae"):
        g["9"] = {"class_type": "ModelPreviewOverrideKJ", "inputs": {
            "max_resolution": 512, "jpeg_quality": 80, "suppress_default_preview": True, "preview_frames": frames,
            "preview_fps": 8, "tiny_vae": roles["tiny_vae"], "model": model}}
        model = ["9", 0]
    g["10"] = {"class_type": "H3AdaLNLoRAFix", "inputs": {"mode": "port", "model": model}}

    enc = {"prompt": prompt, "width": width, "height": height, "length": frames, "ref_image_size": "match",
           "vlm_resolution": 384, "vlm_video_resolution": 384, "reference_fps": 24, "max_total_tokens": 0,
           "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0]}
    if first_frame and not cont:
        g["15"] = {"class_type": "LoadImage", "inputs": {"image": first_frame}}
        enc["first_frame"] = ["15", 0]
    if last_frame:
        g["16"] = {"class_type": "LoadImage", "inputs": {"image": last_frame}}
        enc["last_frame"] = ["16", 0]
    for i, name in enumerate(refs):
        nid = str(100 + i)
        g[nid] = {"class_type": "LoadImage", "inputs": {"image": name}}
        enc[f"reference_images.reference_image_{i}"] = [nid, 0]
    if voices:
        bundle = {"max_seconds": 10.0}
        for i, name in enumerate(voices):
            nid = str(36 + i)
            g[nid] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
            bundle[f"audio_{i + 1}"] = [nid, 0]
        g["40a"] = {"class_type": "H3LongVideoReferenceAudios", "inputs": bundle}
        enc["references"] = ["40a", 0]
    g["23"] = {"class_type": "PK_MiniMaxH3Combined", "inputs": enc}

    g["32"] = {"class_type": "H3LongVideoContinue", "inputs": {
        "project": project, "part": int(part), "context_length": lengths.CONTEXT, "audio_feather_ticks": 8,
        "new_shot": not cont, "latent": ["23", 1]}}
    n_steps = int(steps or (v["turbo_steps"] if turbo else v["steps"]))
    g["40"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}}
    g["41"] = {"class_type": "BasicGuider", "inputs": {"model": ["10", 0], "conditioning": ["23", 0]}}
    g["42"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    g["43"] = {"class_type": "BasicScheduler", "inputs": {"scheduler": "simple", "steps": n_steps, "denoise": 1, "model": ["10", 0]}}
    g["44"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["40", 0], "guider": ["41", 0], "sampler": ["42", 0], "sigmas": ["43", 0], "latent_image": ["32", 0]}}
    g["50"] = {"class_type": "VAEDecode", "inputs": {"samples": ["44", 0], "vae": ["3", 0]}}
    g["51"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["44", 0], "vae": ["4", 0]}}
    g["52"] = {"class_type": "H3LongVideoAppend", "inputs": {
        "project": project, "part": int(part), "crf": int(crf), "latent": ["44", 0], "images": ["50", 0],
        "audio": ["51", 0], "trim_frames": ["32", 1]}}
    g["80"] = {"class_type": "H3LongVideoSaveConditioning", "inputs": {
        "project": project, "part": int(part), "conditioning": ["23", 0]}}
    return g


def blockout_clip(roles, *, project, part, prompt, blockout, start=0, strength=0.997, new_shot=True, width=1152,
                  height=640, frames=243, seed=0, turbo=True, refs=(), voices=(), loras=(), unet=None, steps=None,
                  preview=True, crf=14, video=None, sampler="er_sde", scheduler="beta", ref_scale=0.5):
    """One part that follows a blockout: a rough 3D render (or any video) whose camera, framing, positions and timing
    the part keeps, with real pictures in place of its shapes. H3 V2V: the blockout's frames from `start` are encoded and
    noised to `strength` (H3V2VGranularFractionalDenoise) and are also shown to the model as <Video 1>.

    Part 1 or a new shot starts fresh. A continuation takes over the last 39 frames of the part before and follows the
    blockout after them (H3LongVideoContinue with keep_latent_mask: without it everything after the context is generated
    at full strength and the blockout is lost). For that the blockout must run on under the context: the caller starts
    a continuation 39 frames before the end of the stretch the part before used.

    blockout  an absolute path to a 24 fps video with a sound track at least as long as its picture (work.py makes one)
    """
    v = (video or config.settings()["video"])
    lengths.check_size(width, height)
    cont = not (new_shot or part == 1)
    lengths.check_fit(frames, continuation=cont)
    _need(roles, "blockout_unet", "video_clip", "video_vae", "audio_vae")
    if turbo:
        _need(roles, "turbo_lora")
    if len(refs) > MAX_REFS:
        raise ValueError(f"{len(refs)} reference pictures: the model takes {MAX_REFS}")
    if len(voices) > MAX_VOICES:
        raise ValueError(f"{len(voices)} voice samples: a part takes {MAX_VOICES}")
    if not 0 < float(strength) <= 1:
        raise ValueError("the blockout strength is between 0 and 1 (1 = only the blockout's motion, nothing of its look)")

    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet or roles["blockout_unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": roles["video_clip"], "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": roles["video_vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": roles["audio_vae"]}},
        "4a": {"class_type": "MiniMaxH3AudioVAECompatibility", "inputs": {"audio_vae": ["4", 0]}},
    }
    g["6"] = {"class_type": "MiniMaxLowVRAMAttention", "inputs": {"head_chunks": 4, "model": ["1", 0]}}
    g["7"] = {"class_type": "MiniMaxChunkFeedForward", "inputs": {"chunks": 8, "seq_threshold": 4096, "model": ["6", 0]}}
    model = ["7", 0]
    if turbo:
        g["71"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": roles["turbo_lora"], "strength_model": float(v["turbo_strength"]), "model": model}}
        model = ["71", 0]
    model = _lora_chain(g, model, loras)
    g["72"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {
        "shift_video": float(v["shift_video"]), "shift_audio": float(v["shift_audio"]), "model": model}}
    model = ["72", 0]
    sample_model = model
    if preview and roles.get("tiny_vae"):
        g["9"] = {"class_type": "ModelPreviewOverrideKJ", "inputs": {
            "max_resolution": 512, "jpeg_quality": 80, "suppress_default_preview": True, "preview_frames": frames,
            "preview_fps": 8, "tiny_vae": roles["tiny_vae"], "model": model}}
        sample_model = ["9", 0]

    # the blockout: its stretch for this part, 24 fps, at the part's size; the model sees it at half size as <Video 1>
    g["60"] = {"class_type": "VHS_LoadVideoPath", "inputs": {
        "video": blockout, "force_rate": 24, "custom_width": width, "custom_height": height, "frame_load_cap": frames,
        "skip_first_frames": int(start), "select_every_nth": 1, "format": "AnimateDiff"}}
    g["61"] = {"class_type": "MiniMaxH3Validate24FPSVideo", "inputs": {"images": ["60", 0], "video_info": ["60", 3]}}
    g["62"] = {"class_type": "ImageScale", "inputs": {"image": ["61", 0], "upscale_method": "bilinear",
                                                      "width": int(width * ref_scale), "height": int(height * ref_scale),
                                                      "crop": "disabled"}}
    enc = {"prompt": prompt, "width": width, "height": height, "length": frames, "ref_image_size": "match",
           "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4a", 0], "ref_videos.ref_video_0": ["62", 0]}
    for i, name in enumerate(refs):
        nid = str(100 + i)
        g[nid] = {"class_type": "LoadImage", "inputs": {"image": name}}
        enc[f"ref_images.ref_image_{i}"] = [nid, 0]
    for i, name in enumerate(voices):
        nid = str(36 + i)
        g[nid] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
        enc[f"ref_audios.ref_audio_{i}"] = [nid, 0]
    g["23"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": enc}
    g["24"] = {"class_type": "H3V2VGranularFractionalDenoise", "inputs": {
        "source_fps": 24, "mode": "global", "global_strength": float(strength), "inside_strength": 1, "outside_strength": 0,
        "audio_strength": 1.0, "source_fit": "start", "crop": "center", "mask_temporal_reduce": "max", "invert_mask": False,
        "latent": ["23", 1], "model": model, "vae": ["3", 0], "audio_vae": ["4a", 0], "source_frames": ["61", 0],
        "source_audio": ["60", 2]}}

    g["32"] = {"class_type": "H3LongVideoContinue", "inputs": {
        "project": project, "part": int(part), "context_length": lengths.CONTEXT, "audio_feather_ticks": 8,
        "new_shot": not cont, "keep_latent_mask": True, "latent": ["24", 0]}}
    n_steps = int(steps or (v["turbo_steps"] if turbo else v["steps"]))
    g["40"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}}
    g["41"] = {"class_type": "BasicGuider", "inputs": {"model": sample_model, "conditioning": ["23", 0]}}
    g["42"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler}}
    g["43"] = {"class_type": "BasicScheduler", "inputs": {"scheduler": scheduler, "steps": n_steps, "denoise": 1, "model": model}}
    g["44"] = {"class_type": "SamplerCustomAdvanced", "inputs": {
        "noise": ["40", 0], "guider": ["41", 0], "sampler": ["42", 0], "sigmas": ["43", 0], "latent_image": ["32", 0]}}
    g["50"] = {"class_type": "VAEDecode", "inputs": {"samples": ["44", 1], "vae": ["3", 0]}}
    g["51"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["44", 1], "vae": ["4a", 0]}}
    g["52"] = {"class_type": "H3LongVideoAppend", "inputs": {
        "project": project, "part": int(part), "crf": int(crf), "latent": ["44", 1], "images": ["50", 0],
        "audio": ["51", 0], "trim_frames": ["32", 1]}}
    g["80"] = {"class_type": "H3LongVideoSaveConditioning", "inputs": {
        "project": project, "part": int(part), "conditioning": ["23", 0]}}
    return g


BLOCKOUT_STAGES = {"1": "loading the video model", "2": "loading the text encoder", "60": "reading the blockout",
                   "23": "reading the prompt, the blockout and the references", "24": "laying the blockout into the latent",
                   "32": "taking over the end of the part before", "44": "sampling", "50": "decoding the picture",
                   "51": "decoding the sound", "52": "writing the part"}


# node id -> what the user sees while it runs
CLIP_STAGES = {"1": "loading the video model", "2": "loading the text encoder", "23": "reading the prompt and references",
               "32": "taking over the end of the part before", "44": "sampling", "50": "decoding the picture",
               "51": "decoding the sound", "52": "writing the part"}


def upscale(roles, *, project, part, loras=(), scale=1.5, interpolate=True, sharpen=True, seed=0,
            sigmas="0.6316, 0.3158, 0.0000", crf=14, unet=None):
    """Upscale one stored part from its latent (H3 latent upscaler, tiled), optionally to 48 fps and sharpened.

    Start sigma 0.6316 keeps small props; 0.9 re-drew them from the prompt (a parcel turned see-through).
    A person LoRA used in generation should be passed here too, or the face drifts at this sigma.
    """
    _need(roles, "video_unet", "video_vae", "upscaler")
    if interpolate:
        _need(roles, "film")
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet or roles["video_unet"], "weight_dtype": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": roles["video_vae"]}},
        "6": {"class_type": "MiniMaxLowVRAMAttention", "inputs": {"head_chunks": 4, "model": ["1", 0]}},
        "7": {"class_type": "MiniMaxChunkFeedForward", "inputs": {"chunks": 2, "seq_threshold": 4096, "model": ["6", 0]}},
    }
    model = _lora_chain(g, ["7", 0], loras)
    g["10"] = {"class_type": "H3AdaLNLoRAFix", "inputs": {"mode": "port", "model": model}}
    g["502"] = {"class_type": "H3LongVideoLoadPart", "inputs": {"project": project, "part": int(part)}}
    g["503"] = {"class_type": "H3LongVideoLoadConditioning", "inputs": {"project": project, "part": int(part)}}
    s = float(scale)
    g["504"] = {"class_type": "ComfyMathExpression", "inputs": {"expression": f"round(a * {s} / 32) * 32", "values.a": ["502", 3]}}
    g["505"] = {"class_type": "ComfyMathExpression", "inputs": {"expression": f"round(a * {s} / 32) * 32", "values.a": ["502", 4]}}
    g["507"] = {"class_type": "ComfyMathExpression", "inputs": {"expression": f"floor(floor(a / 32) * 32 * {s})", "values.a": ["502", 3]}}
    g["508"] = {"class_type": "ComfyMathExpression", "inputs": {"expression": f"floor(floor(a / 32) * 32 * {s})", "values.a": ["502", 4]}}
    g["301"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed)}}
    g["302"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    g["303"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": sigmas}}
    g["304"] = {"class_type": "MMH3TemporalSplitParams", "inputs": {"chunk_length": 102, "temporal_overlap": 17, "anchor_strength": 0.999}}
    g["305"] = {"class_type": "MMH3LatentUpscaleWithModelParams", "inputs": {
        "model_name": roles["upscaler"], "width": ["504", 1], "height": ["505", 1], "device": "cuda", "precision": "bf16"}}
    g["306"] = {"class_type": "MMH3SpatialSplitParams", "inputs": {
        "upscale_width": 2560, "upscale_height": 1920, "tile_size_mode": "auto", "tile_width": 736, "tile_height": 736,
        "grid_rows": 3, "grid_cols": 1, "spatial_w_overlap": 128, "spatial_h_overlap": 128, "fade_width": 32,
        "fade_height": 32, "min_tile_size": 256, "overlap_mode": "earlier", "overlap_blend": "linear", "joint_steps": True,
        "token_budget": 70000}}
    g["307"] = {"class_type": "MMH3UltimateUpscale", "inputs": {
        "cfg": 1, "model": ["10", 0], "conditioning": ["503", 0], "latent": ["502", 0], "noise": ["301", 0],
        "sampler": ["302", 0], "sigmas": ["303", 0], "latent_upscale_param": ["305", 0],
        "temporal_split_param": ["304", 0], "spatial_split_param": ["306", 0]}}
    g["308"] = {"class_type": "VAEDecode", "inputs": {"samples": ["307", 0], "vae": ["3", 0]}}
    images = ["308", 0]
    if interpolate:
        g["510"] = {"class_type": "FrameInterpolationModelLoader", "inputs": {"model_name": roles["film"]}}
        g["511"] = {"class_type": "FrameInterpolate", "inputs": {"multiplier": 2, "interp_model": ["510", 0], "images": images}}
        images = ["511", 0]
    if sharpen:
        g["512"] = {"class_type": "ImageSharpenKJ", "inputs": {"method": "rcas", "method.strength": 0.3, "image": images}}
        images = ["512", 0]
    g["513"] = {"class_type": "H3LongVideoUpscaleAppend", "inputs": {
        "project": project, "part": int(part), "fps_multiplier": 2 if interpolate else 1,
        "crop_width": ["507", 1], "crop_height": ["508", 1], "crf": int(crf), "images": images,
        "context_frames": ["502", 1], "source_frames": ["502", 2]}}
    return g


UPSCALE_STAGES = {"1": "loading the video model", "307": "upscaling", "308": "decoding", "511": "interpolating to 48 fps",
                  "512": "sharpening", "513": "writing the upscaled part"}


def image(roles, *, prompt, prefix, width=1344, height=768, seed=0, steps=25, pictures=(), keep_size=False,
          resolution=1024, sampler="euler", scheduler="simple", cache=True, has_cache_node=True):
    """A picture with Qwen-Image 2.1, from words, or from words and pictures (an edit).

    pictures     files in ComfyUI/input: image 1 is the one that is edited, the others are image 2, image 3...
    keep_size    the result takes image 1's own shape (an edit in place); otherwise width x height is a new canvas
    """
    _need(roles, "image_unet", "image_clip", "image_vae")
    if len(pictures) > MAX_PICTURES + 1:
        raise ValueError(f"{len(pictures)} pictures: the model takes {MAX_PICTURES + 1}")
    if keep_size and not pictures:
        raise ValueError("keep_size needs a picture")
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": roles["image_unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": roles["image_clip"], "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": roles["image_vae"]}},
    }
    model = ["1", 0]
    if cache and has_cache_node:
        g["9"] = {"class_type": "QwenImage21Cache", "inputs": {"device": "auto", "dtype": "default", "model": model}}
        model = ["9", 0]
    enc = {"clip": ["2", 0], "prompt": prompt, "negative_prompt": "", "resolution": int(resolution)}
    if pictures:
        enc["vae"] = ["3", 0]
        for i, name in enumerate(pictures, 1):
            nid = str(60 + i)
            g[nid] = {"class_type": "LoadImage", "inputs": {"image": name}}
            enc[f"images.image_{i}"] = [nid, 0]
    g["4"] = {"class_type": "TextEncodeQwenImage21", "inputs": enc}
    if keep_size:
        latent = ["4", 2]
    else:
        lengths.check_size(width, height)
        g["5"] = {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}}
        latent = ["5", 0]
    g["6"] = {"class_type": "KSampler", "inputs": {
        "model": model, "positive": ["4", 0], "negative": ["4", 1], "latent_image": latent, "seed": int(seed),
        "steps": int(steps), "cfg": 1, "sampler_name": sampler, "scheduler": scheduler, "denoise": 1}}
    g["7"] = {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}}
    g["8"] = {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}}
    return g


IMAGE_STAGES = {"1": "loading the picture model", "2": "loading the text encoder", "4": "reading the prompt",
                "6": "drawing", "7": "decoding", "8": "saving"}


def tts(*, text, voice, prefix, seed=1, language="local:English", exaggeration=0.5, temperature=0.8, cfg_weight=0.5):
    """One line spoken by ChatterBox (TTS Audio Suite) in a voice from the suite's own list."""
    return {
        "1": {"class_type": "ChatterBoxEngineNode", "inputs": {
            "language": language, "device": "auto", "exaggeration": float(exaggeration), "temperature": float(temperature),
            "cfg_weight": float(cfg_weight), "crash_protection_template": "hmm ,, {seg} hmm ,,"}},
        "2": {"class_type": "UnifiedTTSTextNode", "inputs": {
            "TTS_engine": ["1", 0], "text": text, "narrator_voice": voice, "seed": int(seed)}},
        "3": {"class_type": "SaveAudio", "inputs": {"audio": ["2", 0], "filename_prefix": prefix}},
    }


def input_files(graph):
    """Files a graph loads: [(node id, class, name)]."""
    out = []
    for nid, node in graph.items():
        if node["class_type"] == "LoadImage":
            out.append((nid, "LoadImage", node["inputs"]["image"]))
        elif node["class_type"] == "LoadAudio":
            out.append((nid, "LoadAudio", node["inputs"]["audio"]))
    return out


def missing_inputs(graph):
    """Files a graph loads that are not there (names as ComfyUI's loaders take them, see config.ref_path)."""
    return [name for _, _, name in input_files(graph) if not os.path.isfile(config.ref_path(name))]
