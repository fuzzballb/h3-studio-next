"""Which models and nodes this ComfyUI has, and what the studio can do with them.

Nothing is hard-wired to one machine: every model file is picked by its role from what ComfyUI lists, in an order of
preference, and can be set by hand in Settings. A feature that misses a node or a model is shown as unavailable with
the reason, never hidden.
"""
import re

from . import config
from .comfy import combo_options

# role -> (node, field) that lists the files, and regexes in order of preference
ROLES = {
    "video_unet": (("UNETLoader", "unet_name"), [
        r"minimax_h3.*hybrid.*ref2va.*int8", r"minimax_h3.*ref2va.*int8_convrot", r"minimax_h3.*ref2va",
        r"minimax_h3.*fl2va.*int8_convrot", r"minimax_h3.*fl2va", r"minimax_h3"]),
    "video_clip": (("CLIPLoader", "clip_name"), [
        r"qwen3vl_32b.*minimax_h3.*int8", r"qwen3vl_32b.*minimax_h3", r"qwen3vl_32b"]),
    "video_vae": (("VAELoader", "vae_name"), [r"minimax_h3_video_vae.*int8", r"minimax_h3_video_vae"]),
    "audio_vae": (("VAELoader", "vae_name"), [r"minimax_h3_audio_vae"]),
    # quantized "int8convrot" LoRAs give pure noise through LoraLoaderModelOnly: never pick those
    "turbo_lora": (("LoraLoaderModelOnly", "lora_name"), [
        r"minimax_h3_fl2v_turbo_8step.*bf16", r"minimax_h3.*turbo.*8step(?!.*int8)", r"minimax_h3_turbo(?!.*int8)"]),
    # following a blockout (V2V) was tested with the fl2va model (2026-11-14); the others are untested fallbacks
    "blockout_unet": (("UNETLoader", "unet_name"), [
        r"minimax_h3_fl2va.*int8_convrot", r"minimax_h3_fl2va", r"minimax_h3.*fl2va", r"minimax_h3"]),
    "tiny_vae": (("ModelPreviewOverrideKJ", "tiny_vae"), [r"taeh3"]),
    "upscaler": (("MMH3LatentUpscaleWithModelParams", "model_name"), [r"minimax_h3_latent_upscaler"]),
    "film": (("FrameInterpolationModelLoader", "model_name"), [r"film_net"]),
    "image_unet": (("UNETLoader", "unet_name"), [r"qwen_image_2\.1.*int8", r"qwen_image_2\.1", r"qwen_image"]),
    "image_clip": (("CLIPLoader", "clip_name"), [r"qwen3vl_8b.*int8", r"qwen3vl_8b"]),
    "image_vae": (("VAELoader", "vae_name"), [r"qwen_image.*vae"]),
}
ROLE_TITLES = {
    "video_unet": "Video model (MiniMax H3)", "video_clip": "Video text encoder (Qwen3-VL 32B)",
    "video_vae": "Video VAE", "audio_vae": "Audio VAE", "turbo_lora": "Turbo LoRA (8 steps)",
    "tiny_vae": "Preview VAE (optional)", "upscaler": "H3 latent upscaler", "film": "Frame interpolation (FILM)",
    "image_unet": "Picture model (Qwen-Image 2.1)", "image_clip": "Picture text encoder (Qwen3-VL 8B)",
    "image_vae": "Picture VAE", "blockout_unet": "Video model for blockouts (MiniMax H3 fl2va)",
}
LORA_BAD = re.compile(r"int8_?convrot", re.I)
FILE_NODES = ("LoadImage", "LoadAudio", "VHS_LoadVideo", "LoadVideo")

# feature -> nodes and model roles it needs. The pack names tell the user what to install.
PACKS = {
    "PK_MiniMaxH3Combined": "ComfyUI-PlagueKind-Nodes", "H3AdaLNLoRAFix": "ComfyUI-PlagueKind-Nodes",
    "MMH3UltimateUpscale": "ComfyUI-PlagueKind-Nodes", "MMH3LatentUpscaleWithModelParams": "ComfyUI-PlagueKind-Nodes",
    "MMH3TemporalSplitParams": "ComfyUI-PlagueKind-Nodes", "MMH3SpatialSplitParams": "ComfyUI-PlagueKind-Nodes",
    "MiniMaxLowVRAMAttention": "comfyui-kjnodes", "MiniMaxChunkFeedForward": "comfyui-kjnodes",
    "ModelPreviewOverrideKJ": "comfyui-kjnodes", "ImageSharpenKJ": "comfyui-kjnodes",
    "MiniMaxH3GeneratedAVMaskedContext": "ComfyUI-H3-Motion-Context-MultiRef",
    "MiniMaxH3MotionContextTrim": "ComfyUI-H3-Motion-Context-MultiRef",
    "H3LongVideoContinue": "this repo (restart ComfyUI)", "H3LongVideoAppend": "this repo (restart ComfyUI)",
    "H3LongVideoLoadPart": "this repo (restart ComfyUI)", "H3LongVideoUpscaleAppend": "this repo (restart ComfyUI)",
    "H3LongVideoReferenceAudios": "this repo (restart ComfyUI)",
    "H3V2VGranularFractionalDenoise": "ComfyUI-H3-Motion-Context-MultiRef",
    "MiniMaxH3Validate24FPSVideo": "ComfyUI-H3-Motion-Context-MultiRef",
    "MiniMaxH3AudioVAECompatibility": "ComfyUI-H3-Motion-Context-MultiRef",
    "VHS_LoadVideoPath": "ComfyUI-VideoHelperSuite", "MiniMaxH3ReferenceToVideo": "ComfyUI (update it)",
    "ChatterBoxEngineNode": "TTS Audio Suite", "UnifiedTTSTextNode": "TTS Audio Suite",
    "TextEncodeQwenImage21": "ComfyUI (update it)", "MiniMaxH3SigmaShift": "ComfyUI (update it)",
    "ComfySwitchNode": "ComfyUI (update it)", "FrameInterpolate": "ComfyUI (update it)",
}
FEATURES = {
    "image": {"title": "Pictures (Qwen-Image 2.1)",
              "nodes": ["UNETLoader", "CLIPLoader", "VAELoader", "TextEncodeQwenImage21", "KSampler", "EmptyLatentImage",
                        "VAEDecode", "SaveImage"],
              "roles": ["image_unet", "image_clip", "image_vae"]},
    "edit": {"title": "Edit a picture, turnaround, storyboard",
             "nodes": ["TextEncodeQwenImage21", "LoadImage", "KSampler", "VAEDecode", "SaveImage"],
             "roles": ["image_unet", "image_clip", "image_vae"]},
    "video": {"title": "Video with sound (MiniMax H3), in parts that continue each other",
              "nodes": ["PK_MiniMaxH3Combined", "MiniMaxLowVRAMAttention", "MiniMaxChunkFeedForward", "H3AdaLNLoRAFix",
                        "H3LongVideoContinue", "H3LongVideoAppend", "H3LongVideoSaveConditioning",
                        "MiniMaxH3GeneratedAVMaskedContext", "MiniMaxH3MotionContextTrim", "RandomNoise", "BasicGuider",
                        "KSamplerSelect", "BasicScheduler", "SamplerCustomAdvanced", "VAEDecode", "VAEDecodeAudio"],
              "roles": ["video_unet", "video_clip", "video_vae", "audio_vae"]},
    "blockout": {"title": "Shots that follow a blockout video (H3 V2V)",
                 "nodes": ["VHS_LoadVideoPath", "MiniMaxH3Validate24FPSVideo", "MiniMaxH3AudioVAECompatibility",
                           "MiniMaxH3ReferenceToVideo", "H3V2VGranularFractionalDenoise", "ImageScale",
                           "H3LongVideoContinue", "H3LongVideoAppend", "VAEDecodeAudio"],
                 "inputs": [("H3LongVideoContinue", "keep_latent_mask")],
                 "roles": ["blockout_unet", "video_clip", "video_vae", "audio_vae"]},
    "turbo": {"title": "Turbo (8 steps)", "nodes": ["LoraLoaderModelOnly", "MiniMaxH3SigmaShift"], "roles": ["turbo_lora"]},
    "voices": {"title": "Voices from samples (H3 speaks in a given voice)",
               "nodes": ["H3LongVideoReferenceAudios", "LoadAudio"], "roles": []},
    "upscale": {"title": "Upscale x1.5 + 48 fps",
                "nodes": ["MMH3UltimateUpscale", "MMH3LatentUpscaleWithModelParams", "MMH3TemporalSplitParams",
                          "MMH3SpatialSplitParams", "H3LongVideoLoadPart", "H3LongVideoLoadConditioning",
                          "H3LongVideoUpscaleAppend", "ManualSigmas", "ComfyMathExpression"],
                "roles": ["video_unet", "video_vae", "upscaler"]},
    "interpolate": {"title": "Frame interpolation to 48 fps", "nodes": ["FrameInterpolate", "FrameInterpolationModelLoader"],
                    "roles": ["film"]},
    "tts": {"title": "Voice-over (ChatterBox)", "nodes": ["ChatterBoxEngineNode", "UnifiedTTSTextNode", "SaveAudio"],
            "roles": []},
    "face": {"title": "Face pass for small faces", "nodes": ["H3LongVideoFaceCrop", "H3LongVideoFacePaste"], "roles": []},
}


def options_for(info, role):
    (node, field), _ = ROLES[role]
    opts = combo_options(info, node, field)
    if role == "turbo_lora":
        opts = [o for o in opts if not LORA_BAD.search(o)]
    return opts


def pick(info, role):
    """The best installed file for a role, or ''."""
    opts = options_for(info, role)
    for rx in ROLES[role][1]:
        for o in opts:
            if re.search(rx, o, re.I):
                return o
    return ""


def resolve(info, settings=None):
    """role -> file: the user's choice when it is still installed, else the best match, else ''."""
    chosen = (settings or config.settings())["models"]
    out = {}
    for role in ROLES:
        want = chosen.get(role) or ""
        out[role] = want if want and want in options_for(info, role) else pick(info, role)
    return out


def loras(info):
    """Installed LoRAs, split into usable and quantized (which give noise through the plain loader)."""
    all_ = combo_options(info, "LoraLoaderModelOnly", "lora_name")
    return [o for o in all_ if not LORA_BAD.search(o)], [o for o in all_ if LORA_BAD.search(o)]


def find_lora(info, pattern):
    """The first usable LoRA whose name matches a regex ('' when none): presets name LoRAs by pattern, not by file."""
    usable, _ = loras(info)
    for o in usable:
        if re.search(pattern, o, re.I):
            return o
    return ""


def features(info, settings=None):
    """feature -> {title, ok, missing_nodes: [(node, pack)], missing_models: [role title]}."""
    roles = resolve(info, settings)
    out = {}
    for key, f in FEATURES.items():
        miss_n = [(n, PACKS.get(n, "")) for n in f["nodes"] if n not in info]
        for n, field in f.get("inputs", []):          # a node that is there but too old for an input this needs
            spec = (info.get(n) or {}).get("input") or {}
            if n in info and not any(field in (spec.get(k) or {}) for k in ("required", "optional")):
                miss_n.append((f"{n}.{field}", f"{PACKS.get(n) or n}: {n} is too old, it has no input {field}"))
        miss_m = [ROLE_TITLES[r] for r in f["roles"] if not roles.get(r)]
        out[key] = {"title": f["title"], "ok": not miss_n and not miss_m,
                    "missing_nodes": miss_n, "missing_models": miss_m}
    return out


def why_not(feature_state):
    """One sentence for a feature that cannot run."""
    parts = []
    if feature_state["missing_nodes"]:
        packs = sorted({p or n for n, p in feature_state["missing_nodes"]})
        parts.append("missing nodes from " + ", ".join(packs))
    if feature_state["missing_models"]:
        parts.append("no model for: " + ", ".join(feature_state["missing_models"]))
    return "; ".join(parts)


def voices(info):
    """Voice names the TTS suite lists (its own dropdown; a voice must be in it)."""
    return [v for v in combo_options(info, "UnifiedTTSTextNode", "narrator_voice") if v != "none"]


def validate(graph, info):
    """Problems ComfyUI would refuse a graph for, found before it is queued: unknown nodes, missing required
    inputs, links to nodes that are not there, combo values that are not installed. [] = fine."""
    problems = []
    for nid, node in graph.items():
        ct = node.get("class_type")
        spec = info.get(ct)
        if spec is None:
            pack = PACKS.get(ct, "")
            problems.append(f"node {nid}: {ct} is not installed" + (f" (from {pack})" if pack else ""))
            continue
        inputs = node.get("inputs", {})
        for name, s in (spec.get("input", {}).get("required", {}) or {}).items():
            if name not in inputs and not any(k == name or k.startswith(name + ".") for k in inputs):
                kind = s[0] if isinstance(s, list) and s else None
                if isinstance(kind, str) and kind.startswith("COMFY_AUTOGROW"):
                    continue                                  # growing lists may be empty
                if isinstance(s, list) and len(s) > 1 and isinstance(s[1], dict) and "default" in s[1] and not isinstance(kind, list) \
                        and kind in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"):
                    continue                                  # ComfyUI fills in a default for plain widgets
                problems.append(f"node {nid} ({ct}): required input '{name}' is missing")
        for name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                if value[0] not in graph:
                    problems.append(f"node {nid} ({ct}): input '{name}' links to node {value[0]}, which is not in the graph")
            elif isinstance(value, str) and ct not in FILE_NODES:
                # (file pickers are left out: their lists are as old as the cached node info; graphs.py checks the files)
                opts = combo_options(info, ct, name)
                if opts and value not in opts and len(opts) < 5000:
                    near = [o for o in opts if value.lower()[:12] in o.lower()][:3]
                    problems.append(f"node {nid} ({ct}): '{value}' is not available for '{name}'"
                                    + (f" (installed: {', '.join(near)})" if near else ""))
    return problems
