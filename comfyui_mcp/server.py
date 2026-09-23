"""ComfyUI MCP server.

Run with:
    .venv/bin/python -m comfyui_mcp.server       # stdio transport (local MCP client)
    MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 \
        .venv/bin/python -m comfyui_mcp.server   # network transport (e.g. Docker)

Configuration is via environment variables:
    COMFYUI_URL           base URL of the ComfyUI server
    COMFYUI_TIMEOUT       per-request HTTP timeout (default 120s)
    COMFYUI_WAIT_TIMEOUT  max time to wait for a generation (default 900s)
    COMFYUI_POLL_INTERVAL history poll interval (default 1.0s)
    MCP_TRANSPORT         stdio | sse | streamable-http (default: stdio)
    MCP_HOST              bind address for HTTP transports (default 127.0.0.1)
    MCP_PORT              port for HTTP transports (default 8000)
    MCP_STATELESS         "true" for stateless HTTP sessions (default false)
"""

from __future__ import annotations

import os
import random
from typing import Any, Optional

import anyio

from mcp.server.fastmcp import FastMCP
from mcp.types import AudioContent, ImageContent, TextContent

from . import workflows
from . import presets
from .client import ComfyUIError, ComfyUIClient, extract_media

# --- Server / transport configuration (from environment) -------------------- #
TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8000"))
STATELESS = os.environ.get("MCP_STATELESS", "false").lower() in ("1", "true", "yes")

mcp = FastMCP("comfyui", host=HOST, port=PORT, stateless_http=STATELESS)

_client: Optional[ComfyUIClient] = None


def client() -> ComfyUIClient:
    """Lazily create (and cache) the shared ComfyUI client."""
    global _client
    if _client is None:
        _client = ComfyUIClient()
    return _client


@mcp.custom_route("/health", methods=["GET"])
async def _health(request):
    """Container health check: confirms this MCP server is up and whether the
    configured ComfyUI server is reachable. Always returns HTTP 200 (liveness);
    ComfyUI reachability is reported as a flag."""
    from starlette.responses import JSONResponse

    try:
        await anyio.to_thread.run_sync(lambda: client().system_stats())
        reachable = True
    except Exception:
        reachable = False
    return JSONResponse({"ok": True, "comfyui_reachable": reachable})


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _err(e: ComfyUIError) -> list[TextContent]:
    return [TextContent(type="text", text=f"ComfyUI error: {e}")]


def _mime(filename: str, default: str) -> str:
    name = (filename or "").lower()
    table = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
        ".opus": "audio/ogg", ".flac": "audio/flac", ".m4a": "audio/mp4",
    }
    for ext, mime in table.items():
        if name.endswith(ext):
            return mime
    return default


def _image_block(c: ComfyUIClient, item: dict[str, str]) -> list:
    b64 = c.view_base64(item["filename"], item["subfolder"], item["type"])
    return [ImageContent(type="image", data=b64, mimeType=_mime(item["filename"], "image/png"))]


def _audio_block(c: ComfyUIClient, item: dict[str, str]) -> list:
    b64 = c.view_base64(item["filename"], item["subfolder"], item["type"])
    url = c.view_url(item["filename"], item["subfolder"], item["type"])
    return [
        TextContent(type="text", text=f"Audio file: {item['filename']}\nURL: {url}"),
        AudioContent(type="audio", data=b64, mimeType=_mime(item["filename"], "audio/mpeg")),
    ]


def job_error(entry: Any) -> Optional[str]:
    """Return a readable error message if a completed history entry reports a
    failed/interrupted execution (e.g. a model-load failure); else None."""
    status = (entry or {}).get("status") or {}
    if status.get("status_str") not in ("error", "interrupted"):
        return None
    for msg in status.get("messages", []):
        if isinstance(msg, list) and len(msg) >= 2 and msg[0] == "execution_error":
            payload = msg[1] if isinstance(msg[1], dict) else {}
            node = payload.get("node_type") or payload.get("node_id") or "node"
            detail = payload.get("exception_message") or payload.get("exception_type") or ""
            return f"[{node}] {detail}".strip()[:800]
    return f"status: {status.get('status_str')}"


# --------------------------------------------------------------------------- #
# System & discovery
# --------------------------------------------------------------------------- #
@mcp.tool()
def comfyui_system_info() -> str:
    """Report the ComfyUI server status: version, OS, RAM, and GPU/VRAM devices."""
    c = client()
    try:
        stats = c.system_stats() or {}
        sysd = stats.get("system", {}) if isinstance(stats, dict) else {}
        devices = stats.get("devices", []) if isinstance(stats, dict) else []
        lines = [
            f"ComfyUI {sysd.get('comfyui_version', '?')} on {sysd.get('os', '?')}",
            f"RAM: {sysd.get('ram_free', 0) / 1e9:.1f} GB free / {sysd.get('ram_total', 0) / 1e9:.1f} GB total",
        ]
        for d in devices:
            vf, vt = d.get("vram_free"), d.get("vram_total")
            vram = f"{vf / 1e9:.1f}/{vt / 1e9:.1f} GB free/total" if vt else "n/a"
            lines.append(f"  - {d.get('name')} ({d.get('type')}): VRAM {vram}")
        return "\n".join(lines)
    except ComfyUIError as e:
        return f"ComfyUI error: {e}"


@mcp.tool()
def comfyui_queue() -> str:
    """Show the current running and pending jobs in the queue."""
    c = client()
    try:
        q = c.queue() or {}
        running = q.get("queue_running", []) or []
        pending = q.get("queue_pending", []) or []

        def brief(items):
            return [f"  - {x[0]}" for x in items[:10]]

        return "\n".join(
            [f"Running: {len(running)}", *brief(running), f"Pending: {len(pending)}", *brief(pending)]
        )
    except ComfyUIError as e:
        return f"ComfyUI error: {e}"


@mcp.tool()
def comfyui_list_models(category: Optional[str] = None) -> str:
    """List available models. Without a category, returns all model categories
    (checkpoints, loras, vae, diffusion_models, text_encoders, ...). Pass a
    category to list the model file names in that folder -- use these exact
    names with the generate tools."""
    c = client()
    try:
        if category is None:
            cats = c.models() or []
            return "Model categories:\n" + "\n".join(f"  - {x}" for x in cats)
        models = c.models_for(category) or []
        return f"{len(models)} model(s) in '{category}':\n" + "\n".join(f"  - {x}" for x in models)
    except ComfyUIError as e:
        return f"ComfyUI error: {e}"


@mcp.tool()
def comfyui_list_presets(category: Optional[str] = None) -> str:
    """List the named model presets for the generate tools. Pass 'image' or
    'audio' to filter, or omit for both. Pick a name and pass it as `model` to
    comfyui_generate_image / comfyui_generate_music."""
    return presets.format_presets(category)


@mcp.tool()
def comfyui_list_nodes(search: Optional[str] = None) -> str:
    """List ComfyUI node class types. Pass `search` to filter by a
    case-insensitive substring (e.g. 'sampler', 'audio', 'KSampler')."""
    c = client()
    try:
        info = c.object_info() or {}
        keys = list(info.keys())
        if search:
            low = search.lower()
            keys = [k for k in keys if low in k.lower()]
        shown = keys[:100]
        head = f"{len(keys)} node type(s)" + (" (first 100 shown)" if len(keys) > 100 else "") + ":\n"
        return head + "\n".join(f"  - {k}" for k in shown)
    except ComfyUIError as e:
        return f"ComfyUI error: {e}"


@mcp.tool()
def comfyui_node_info(node_type: str) -> str:
    """Show the full input/output schema for a node type: input names, types,
    defaults, and output slots. Use this to build a raw workflow for
    comfyui_queue_prompt."""
    c = client()
    try:
        info = c.object_info(node_type) or {}
        if not info:
            return f"No node type named '{node_type}'."
        node = list(info.values())[0]
        lines = [node_type, f"  outputs: {node.get('output')}"]
        for section in ("required", "optional"):
            vals = (node.get("input") or {}).get(section, {})
            if not vals:
                continue
            lines.append(f"  {section}:")
            for k, v in vals.items():
                typ = v[0] if isinstance(v, list) and v else v
                opts = v[1] if isinstance(v, list) and len(v) > 1 else {}
                default = opts.get("default") if isinstance(opts, dict) else None
                extra = f"  default={default}" if default is not None else ""
                lines.append(f"    - {k} ({typ}){extra}")
        return "\n".join(lines)
    except ComfyUIError as e:
        return f"ComfyUI error: {e}"


# --------------------------------------------------------------------------- #
# Queue control
# --------------------------------------------------------------------------- #
@mcp.tool()
def comfyui_interrupt() -> str:
    """Interrupt the currently running prompt (cancels the in-progress job)."""
    c = client()
    try:
        res = c.interrupt()
        return f"Interrupt requested. {res}" if res else "Interrupt requested."
    except ComfyUIError as e:
        return f"ComfyUI error: {e}"


@mcp.tool()
def comfyui_free(unload_models: bool = False, rerun_outputs: bool = False) -> str:
    """Free VRAM on the server (optionally unload models and rerun outputs)."""
    c = client()
    try:
        res = c.free(unload_models, rerun_outputs)
        return f"Free requested. {res}" if res else "Free requested."
    except ComfyUIError as e:
        return f"ComfyUI error: {e}"


# --------------------------------------------------------------------------- #
# Raw prompt / fetch
# --------------------------------------------------------------------------- #
@mcp.tool()
def comfyui_queue_prompt(workflow: dict, front: bool = False) -> str:
    """Queue a raw ComfyUI API-format workflow. `workflow` maps node id ->
    {'class_type':..., 'inputs':{...}} with wiring like ['node_id', slot].
    Returns the prompt_id to pass to comfyui_wait_for_completion."""
    c = client()
    try:
        res = c.prompt(workflow, front=front) or {}
        errors = res.get("node_errors") or {}
        msg = f"Queued prompt {res.get('prompt_id')} (queue number {res.get('number')})."
        if errors:
            msg += "  node_errors: " + str(errors)[:500]
        return msg
    except ComfyUIError as e:
        return f"ComfyUI error: {e}"


@mcp.tool()
def comfyui_wait_for_completion(prompt_id: str, timeout_seconds: Optional[float] = None) -> list:
    """Block until a queued prompt finishes, then return its outputs. Images are
    returned as viewable image content; audio as a base64 audio block plus URL."""
    c = client()
    try:
        entry = c.wait_for_completion(prompt_id, timeout=timeout_seconds)
    except ComfyUIError as e:
        return _err(e)
    status = (entry.get("status") or {}).get("status_str")
    err = job_error(entry)
    if err:
        return [TextContent(type="text", text=f"Prompt {prompt_id} finished (status: {status}): {err}")]
    media = extract_media(entry)
    out: list = [
        TextContent(
            type="text",
            text=f"Prompt {prompt_id} finished (status: {status}). "
            f"{len(media['images'])} image(s), {len(media['audio'])} audio file(s).",
        )
    ]
    for img in media["images"]:
        try:
            out.extend(_image_block(c, img))
        except ComfyUIError as e:
            out.append(TextContent(type="text", text=f"  image {img['filename']}: {e}"))
    for a in media["audio"]:
        try:
            out.extend(_audio_block(c, a))
        except ComfyUIError as e:
            out.append(TextContent(type="text", text=f"  audio {a['filename']}: {e}"))
    return out


@mcp.tool()
def comfyui_get_image(filename: str, subfolder: str = "", image_type: str = "output") -> list:
    """Fetch a specific image output from ComfyUI and return it as viewable
    image content."""
    c = client()
    try:
        block = _image_block(c, {"filename": filename, "subfolder": subfolder, "type": image_type})
        return [TextContent(type="text", text=f"Image: {filename}")] + block
    except ComfyUIError as e:
        return _err(e)


@mcp.tool()
def comfyui_get_audio(filename: str, subfolder: str = "", audio_type: str = "output") -> list:
    """Fetch a specific audio output; returns a base64 audio block plus its /view URL."""
    c = client()
    try:
        block = _audio_block(c, {"filename": filename, "subfolder": subfolder, "type": audio_type})
        return [TextContent(type="text", text=f"Audio: {filename}")] + block
    except ComfyUIError as e:
        return _err(e)


# --------------------------------------------------------------------------- #
# High-level generation
# --------------------------------------------------------------------------- #
@mcp.tool()
def comfyui_generate_image(
    prompt: str,
    model: str = presets.DEFAULT_IMAGE_MODEL,
    checkpoint: Optional[str] = None,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    sampler_name: Optional[str] = None,
    scheduler: Optional[str] = None,
    seed: Optional[int] = None,
    model_type: str = "auto",
) -> list:
    """Generate an image and return it.

    Pick a model by name via `model` (see comfyui_list_presets) -- defaults to
    FLUX.1 dev -- or pass a raw `checkpoint` file to override it.
    model_type: 'auto' (detect FLUX/SDXL from the name), 'sdxl', or 'flux'.
    """
    c = client()
    if checkpoint is None:
        preset = presets.IMAGE_PRESETS.get(model)
        if preset is None:
            return [TextContent(type="text", text=f"Unknown image model '{model}'. Available: {', '.join(presets.IMAGE_PRESETS)}")]
        checkpoint = preset["checkpoint"]
        if model_type == "auto":
            model_type = preset.get("model_type", "auto")
    low = checkpoint.lower()
    is_flux = ("flux" in low) if model_type == "auto" else (model_type == "flux")
    sd = workflows.resolve_seed(seed)
    if sampler_name is None:
        sampler_name = "euler" if is_flux else "dpmpp_2m"
    if scheduler is None:
        scheduler = "simple" if is_flux else "karras"
    if is_flux:
        if steps == 20:
            steps = 4 if "schnell" in low else 20
        if cfg == 7.0:
            cfg = 1.0
    workflow = workflows.build_txt2img(
        checkpoint=checkpoint,
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        sampler_name=sampler_name,
        scheduler=scheduler,
        seed=sd,
        is_flux=is_flux,
    )
    try:
        res = c.prompt(workflow) or {}
        if res.get("node_errors"):
            return [TextContent(type="text", text=f"Queued but with node_errors: {res['node_errors']}")]
        entry = c.wait_for_completion(res.get("prompt_id"))
    except ComfyUIError as e:
        return _err(e)
    err = job_error(entry)
    if err:
        return [TextContent(type="text", text=f"Image generation failed: {err}")]
    media = extract_media(entry)
    out: list = [
        TextContent(
            type="text",
            text=f"Generated image (seed={sd}, {'flux' if is_flux else 'sdxl'}, {steps} steps). "
            f"{len(media['images'])} image(s).",
        )
    ]
    for img in media["images"]:
        try:
            out.extend(_image_block(c, img))
        except ComfyUIError as e:
            out.append(TextContent(type="text", text=f"  image {img['filename']}: {e}"))
    return out


@mcp.tool()
def comfyui_generate_music(
    prompt: str = "",
    model: str = presets.DEFAULT_AUDIO_MODEL,
    engine: Optional[str] = None,
    tags: str = "",
    lyrics: str = "",
    duration_seconds: int = 30,
    bpm: int = 120,
    language: str = "en",
    keyscale: str = "C major",
    seed: Optional[int] = None,
    filename_prefix: str = "music/ComfyUI",
) -> list:
    """Generate music and return it.

    Pick an audio model by name via `model` (see comfyui_list_presets) -- defaults
    to ACE-Step 1.5 turbo -- or pass `engine` ('acestep15'/'sonilo'/'stable_audio')
    to choose a pipeline directly. For ACE-Step put genre/style in `tags` and song
    text in `lyrics`. Returns the audio as a base64 block plus its /view URL.
    """
    c = client()
    sd = workflows.resolve_seed(seed)
    unet_name = clip_name = vae_name = None
    if engine is None:
        preset = presets.AUDIO_PRESETS.get(model)
        if preset is None:
            return [TextContent(type="text", text=f"Unknown audio model '{model}'. Available: {', '.join(presets.AUDIO_PRESETS)}")]
        engine = preset["engine"]
        unet_name, clip_name, vae_name = preset.get("unet_name"), preset.get("clip_name"), preset.get("vae_name")
    if engine == "sonilo":
        workflow = workflows.build_sonilo_music(prompt=prompt or tags, duration=duration_seconds, seed=sd, filename_prefix=filename_prefix)
    elif engine == "stable_audio":
        workflow = workflows.build_stable_audio(prompt=prompt or tags, duration=min(duration_seconds, 190), seed=sd, filename_prefix=filename_prefix)
    else:  # acestep15
        extra = {k: v for k, v in (("unet_name", unet_name), ("clip_name", clip_name), ("vae_name", vae_name)) if v}
        workflow = workflows.build_acestep_music(
            tags=tags or prompt,
            lyrics=lyrics,
            seconds=duration_seconds,
            seed=sd,
            bpm=bpm,
            language=language,
            keyscale=keyscale,
            filename_prefix=filename_prefix,
            **extra,
        )
    try:
        res = c.prompt(workflow) or {}
        if res.get("node_errors"):
            return [TextContent(type="text", text=f"Queued but with node_errors: {res['node_errors']}")]
        entry = c.wait_for_completion(res.get("prompt_id"))
    except ComfyUIError as e:
        return _err(e)
    err = job_error(entry)
    if err:
        return [TextContent(type="text", text=f"Music generation failed: {err}")]
    media = extract_media(entry)
    out: list = [
        TextContent(type="text", text=f"Generated music via {engine} (seed={sd}, {duration_seconds}s). {len(media['audio'])} audio file(s).")
    ]
    for a in media["audio"]:
        try:
            out.extend(_audio_block(c, a))
        except ComfyUIError as e:
            out.append(TextContent(type="text", text=f"  audio {a['filename']}: {e}"))
    if not media["audio"]:
        out.append(TextContent(type="text", text="  (no audio output found in the completed job)"))
    return out


def main() -> None:
    # stdio by default; MCP_TRANSPORT selects sse or streamable-http (the
    # latter is what the Docker deployment serves -- endpoint: /mcp).
    mcp.run(transport=TRANSPORT)


if __name__ == "__main__":
    main()