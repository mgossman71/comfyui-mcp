"""Named model presets for image and audio generation.

Maps friendly preset names (``flux1-dev``, ``acestep-turbo``, ...) to the exact
ComfyUI model files + settings, so callers select a model by a stable name
instead of a raw file path. Edit these dictionaries to add or remove models.

Image presets carry: checkpoint, model_type ('flux'/'sdxl'), description.
Audio presets carry: engine, and (for acestep15) unet_name/clip_name/vae_name.
"""
from __future__ import annotations

DEFAULT_IMAGE_MODEL = "flux1-dev"
DEFAULT_AUDIO_MODEL = "acestep-turbo"

IMAGE_PRESETS: dict[str, dict] = {
    "flux1-dev": {
        "checkpoint": "FLUX1/flux1-dev-fp8.safetensors",
        "model_type": "flux",
        "description": "FLUX.1 dev (fp8): highest quality, ~20 steps",
    },
    "flux1-schnell": {
        "checkpoint": "FLUX1/flux1-schnell-fp8.safetensors",
        "model_type": "flux",
        "description": "FLUX.1 schnell (fp8): fast, ~4 steps",
    },
    "sdxl-juggernaut": {
        "checkpoint": "juggernautXL.safetensors",
        "model_type": "sdxl",
        "description": "SDXL Juggernaut XL: classic SDXL checkpoint",
    },
}

AUDIO_PRESETS: dict[str, dict] = {
    "acestep-turbo": {
        "engine": "acestep15",
        "unet_name": "acestep_v1.5_turbo.safetensors",
        "clip_name": "qwen_0.6b_ace15.safetensors",
        "vae_name": "ace_1.5_vae.safetensors",
        "description": "ACE-Step 1.5 turbo: music from tags/lyrics",
    },
    "sonilo": {
        "engine": "sonilo",
        "description": "Sonilo: self-contained text-to-music (no model files)",
    },
}


def format_presets(category: str | None = None) -> str:
    """Render the available presets as text. ``category`` is 'image', 'audio',
    or None/both."""
    lines: list[str] = []
    if category in (None, "image", "images"):
        lines.append("Image presets (pass to comfyui_generate_image as model=):")
        for name, p in IMAGE_PRESETS.items():
            marker = "  [default]" if name == DEFAULT_IMAGE_MODEL else ""
            lines.append(f"  - {name}: {p['description']}{marker}")
    if category in (None, "audio", "music"):
        lines.append("Audio presets (pass to comfyui_generate_music as model=):")
        for name, p in AUDIO_PRESETS.items():
            marker = "  [default]" if name == DEFAULT_AUDIO_MODEL else ""
            lines.append(f"  - {name}: {p['description']}{marker}")
    if not lines:
        return f"Unknown category '{category}'. Use 'image', 'audio', or omit for both."
    return "\n".join(lines)