"""Builders that produce ComfyUI API-format workflow dicts.

An API-format workflow maps node id -> {"class_type": ..., "inputs": {...}}.
Wiring between nodes uses a two-item list: ["node_id", output_slot_index].
"""

from __future__ import annotations

import random
from typing import Any


def resolve_seed(seed: int | None) -> int:
    """Return the given seed, or a fresh random one if None."""
    return seed if seed is not None else random.randint(0, 2**31 - 1)


def build_txt2img(
    *,
    checkpoint: str,
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    batch_size: int = 1,
    steps: int = 20,
    cfg: float = 7.0,
    sampler_name: str = "dpmpp_2m",
    scheduler: str = "karras",
    denoise: float = 1.0,
    seed: int | None = None,
    filename_prefix: str = "ComfyUI",
    is_flux: bool = False,
) -> dict[str, Any]:
    """Standard CheckpointLoader -> KSampler -> VAEDecode -> SaveImage graph.

    Works for SD1.5/SDXL. For FLUX, pass is_flux=True and (typically)
    sampler_name='euler', scheduler='simple', and a low cfg.
    """
    sd = resolve_seed(seed)
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": batch_size}},
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": sd,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": denoise,
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": filename_prefix}},
    }


def build_acestep_music(
    *,
    tags: str,
    lyrics: str = "",
    seconds: float = 30.0,
    unet_name: str = "acestep_v1.5_turbo.safetensors",
    clip_name: str = "qwen_4b_ace15.safetensors",
    vae_name: str = "ace_1.5_vae.safetensors",
    bpm: int = 120,
    timesignature: str = "4",
    language: str = "en",
    keyscale: str = "C major",
    seed: int | None = None,
    steps: int = 8,
    cfg: float = 1.0,
    sampler_name: str = "euler",
    scheduler: str = "simple",
    denoise: float = 1.0,
    filename_prefix: str = "music/ComfyUI",
    quality: str = "128k",
) -> dict[str, Any]:
    """ACE-Step 1.5 song generation: UNet + Qwen text encoder + ACE VAE.

    `tags` = genre/style (e.g. "pop, female vocal, upbeat"); `lyrics` = song text.
    """
    sd = resolve_seed(seed)
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet_name, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip_name, "type": "ace"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
        "4": {
            "class_type": "TextEncodeAceStepAudio1.5",
            "inputs": {
                "clip": ["2", 0],
                "tags": tags,
                "lyrics": lyrics,
                "seed": sd,
                "bpm": bpm,
                "duration": seconds,
                "timesignature": timesignature,
                "language": language,
                "keyscale": keyscale,
                "generate_audio_codes": True,
                "cfg_scale": 2.0,
                "temperature": 0.85,
                "top_p": 0.9,
                "top_k": 0,
                "min_p": 0.0,
            },
        },
        "5": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": seconds, "batch_size": 1}},
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": sd,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": denoise,
                "positive": ["4", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["7", 0], "filename_prefix": filename_prefix, "quality": quality}},
    }


def build_sonilo_music(
    *,
    prompt: str,
    duration: int = 30,
    seed: int | None = None,
    filename_prefix: str = "music/ComfyUI",
    quality: str = "128k",
) -> dict[str, Any]:
    """Sonilo all-in-one text -> music (self-contained, no model file needed)."""
    sd = resolve_seed(seed)
    return {
        "1": {"class_type": "SoniloTextToMusic", "inputs": {"prompt": prompt, "duration": duration, "seed": sd}},
        "2": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["1", 0], "filename_prefix": filename_prefix, "quality": quality}},
    }


def build_stable_audio(
    *,
    prompt: str,
    duration: int = 30,
    seed: int | None = None,
    steps: int = 8,
    model: str = "stable-audio-2.5",
    filename_prefix: str = "music/ComfyUI",
    quality: str = "128k",
) -> dict[str, Any]:
    """Stable Audio text -> audio. Best-effort (model pairing may need tuning)."""
    sd = resolve_seed(seed)
    return {
        "1": {
            "class_type": "StabilityTextToAudio",
            "inputs": {"model": model, "prompt": prompt, "duration": duration, "seed": sd, "steps": steps},
        },
        "2": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["1", 0], "filename_prefix": filename_prefix, "quality": quality}},
    }