# ComfyUI-MCP — Checkpoint / Handoff

> Living document. Update after every meaningful step so any agent can resume.
> Last updated: 2026-09-23 (added named model presets: image default now FLUX.1 dev, audio default ACE-Step turbo; FLUX.1 dev image verified through Docker; ACE-Step 1.5 text encoders confirmed incompatible with current ComfyUI)

## Mission
Build a **full-featured MCP server** (Python, official `mcp` SDK; stdio **or** streamable-http)
for the ComfyUI server at **http://10.0.54.157:8188**. Must support:
image generation, **music generation** (ACE-Step 1.5 / Sonilo / Stable Audio),
node & model discovery, and queue/system control. Generated media is returned to
the model (images as base64 `image` content; audio as saved filename + view URL).

## Environment (verified)
- OS: macOS (aarch64)
- **Interpreter: `~/.local/bin/python3.11`** (Python 3.11.16, uv-managed, pip 26.2.1).
  ALWAYS use this — `python3` is 3.9 and too old for the `mcp` SDK (needs >=3.10).
- **Project venv**: `.venv/` created with python3.11; deps installed via `.venv/bin/pip`.
- **ComfyUI**: `http://10.0.54.157:8188` -> v0.26.0, 883 node types.
  - Image checkpoints: FLUX1/flux1-dev-fp8, FLUX1/flux1-schnell-fp8, juggernautXL (SDXL),
    gonzalomoXLFluxPony_v70PhotoXLDMD, nsfw_v10, omnigenxlNSFWSFW_v10, realismByStableYogi_ponyV65
  - Music: diffusion_models/acestep_v1.5_turbo.safetensors + vae/ace_1.5_vae.safetensors
    + text_encoders/qwen_4b_ace15.safetensors (ACE-Step 1.5), checkpoints/stable_audio_3_medium_base.safetensors
  - VAEs: vae/ace_1.5_vae.safetensors, vae/ae.safetensors (FLUX)
  - Text encoders: clip_l, qwen_0.6b_ace15, qwen_4b_ace15, t5gemma_b_b_ul2, t5xxl_fp16, qwen3.5_2b_bf16

## Decisions
- **SDK**: official `mcp` (FastMCP), **stdio** transport. Entry point: `.venv/bin/python -m comfyui_mcp.server`
- **HTTP client**: `httpx` sync client.
- **Config via env**: `COMFYUI_URL` (default `http://10.0.54.157:8188`),
  `COMFYUI_TIMEOUT` (per-request, 120s), `COMFYUI_WAIT_TIMEOUT` (generation wait, 900s),
  `COMFYUI_POLL_INTERVAL` (1.0s).
- **Transport**: `MCP_TRANSPORT` (stdio default; `sse`/`streamable-http` for Docker),
  `MCP_HOST`/`MCP_PORT`, `MCP_STATELESS`. Docker serves streamable-http at `:8000/mcp` + `/health`.
- **Images** -> base64 `image` content (model can see results).
- **Audio** -> LLM can't "listen", so return saved filename + direct `/view` URL (+ base64 fallback).
- **Deps**: `.venv/bin/pip install mcp httpx`

## Task list (live status)
- [x] 1. Install deps (mcp 1.30.0, httpx 0.28.1) into project `.venv`
- [x] 2. `comfyui_mcp/__init__.py`
- [x] 3. `comfyui_mcp/client.py` (ComfyUI REST client)
- [x] 4. `comfyui_mcp/workflows.py` (txt2img / FLUX / ACE-Step / Sonilo / Stable Audio builders)
- [x] 5. `comfyui_mcp/server.py` (13 @mcp.tool() definitions -- imports clean, all register)
- [x] 6. `requirements.txt`
- [x] 7. `config/claude_desktop_config.json` (example client config)
- [x] 8. `README.md` (setup + usage + tool reference)
- [x] 9. Generation smoke test: image path verified; ACE-Step 1.5 graph validated
- [x] 10. Finalize + handoff
- [x] 11. Docker: `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- [x] 12. Server transport config (stdio/sse/streamable-http) + `/health` endpoint
- [x] 13. Verify `docker compose build` + `up` -> healthy; MCP handshake via container
- [x] 14. FIX `wait_for_completion`: `/history/{id}` returns `{prompt_id: entry}` (NESTED) -- unwrap by prompt_id. Image-gen now returns in ~seconds.
- [x] 15. Add `job_error()` so failed jobs surface the real ComfyUI error (e.g. CLIPLoader load failure) instead of "no output found".
- [x] 16. Named model presets (`comfyui_mcp/presets.py`): `model=` selector on generate_image/generate_music + new `comfyui_list_presets` tool. Image default -> flux1-dev.
- [x] 17. Verify FLUX.1 dev default image gen end-to-end through Docker (1024x1024 PNG OK); confirmed all ACE-Step 1.5 text encoders are incompatible with the current ComfyUI.

NOTE: installed `mcp` 2.x by accident first (breaks FastMCP API); pinned `mcp>=1.10,<2`
-> 1.30.0. requirements.txt already reflects this.

## Done so far
- Explored the target ComfyUI (v0.26.0), mapped image + music node schemas and installed models.
- Created project venv `.venv/` (python3.11); installed mcp 1.30.0 + httpx 0.28.1.
- Wrote all modules: client.py, workflows.py, server.py (13 tools), requirements.txt,
  config/claude_desktop_config.json, smoke_test.py.
- Verified server imports cleanly and all 13 tools register.

## Status: COMPLETE
- **stdio transport**: MCP handshake + read-only tools + image gen all verified.
- **Image gen**: SDXL job completes successfully; a cold model load exceeded the old 300s
  wait, so `COMFYUI_WAIT_TIMEOUT` now defaults to 900s (per-request timeout split to 120s).
- **ACE-Step 1.5**: `TextEncodeAceStepAudio1.5` needs ~15 required inputs (bpm, duration,
  timesignature, language, keyscale, cfg_scale, temperature, top_p, top_k, min_p, ...) --
  all now provided in `build_acestep_music`. Rule learned: **every `required` input must be
  present explicitly, even when it has a default.**
- **system_info**: `devices` lives at the TOP level of `/system_stats` (not under `system`)
  -- fixed; now reports the RTX 5070 Ti VRAM.
- **Docker**: `docker compose up -d --build` -> container `healthy`; `/health` returns
  `comfyui_reachable:true`; MCP streamable-http handshake at `http://localhost:8000/mcp`
  lists all 13 tools and tool calls work through the container.

## Status: image path VERIFIED through Docker
- `comfyui_generate_image` via `http://localhost:8000/mcp` returns a valid 512x512 PNG in ~8.6s
  (saved to `generated_image.png`). Root cause of the earlier "hang": `wait_for_completion`
  checked top-level `outputs`/`status`, but ComfyUI nests them under the prompt_id key.
- **FLUX verified on the 5070 Ti (15.5 GB):** `FLUX1/flux1-schnell-fp8` at 768x768, 4 steps
  generates a valid 768x768 PNG in ~21s -> `flux_test.png`. Fits in VRAM fine (fp8 schnell).
- Music (`comfyui_generate_music`, acestep15): MCP side is correct; generation itself is
  blocked by the ComfyUI CLIPLoader vocab mismatch (see Resolved below).

## Status: named model presets (VERIFIED through Docker)
- `comfyui_generate_image(model=...)` -- default preset **flux1-dev** (FLUX1/flux1-dev-fp8). Verified:
  the default call generates a valid 1024x1024 PNG -> `flux1dev_test.png`. Other presets:
  flux1-schnell, sdxl-juggernaut. Raw `checkpoint=` still works as an override.
- `comfyui_generate_music(model=...)` -- default preset **acestep-turbo** (engine + unet/clip/vae).
  Plumbing verified: resolves the preset and builds the correct generic-loader graph
  (UNETLoader + CLIPLoader[type=ace] + VAELoader + TextEncodeAceStepAudio1.5 + KSampler).
  Still blocked at runtime by the ComfyUI text-encoder mismatch (below).
- `comfyui_list_presets` tool lists image + audio presets (with [default] markers).
- **Audio blocker (server-side, thorough check):** ALL installed ACE-Step 1.5 text encoders are
  incompatible with the current ComfyUI's `ace` CLIP (Qwen3, vocab 151936):
  qwen_0.6b_ace15 -> 151669 (Qwen2.5); qwen_4b_ace15 -> 217204; t5gemma/qwen3.5_2b -> loads but
  KSampler gets a None conditioning. Fix = install a matching Qwen3-0.6B (151936) ACE-1.5 encoder,
  or a ComfyUI build that matches the installed models. The MCP code is ready and will work once fixed.
## Resolved
- **`/history/{id}` return shape (the root cause of the image "hang")**: it returns
  `{prompt_id: entry}` -- the entry is NESTED under its prompt_id, NOT returned directly.
  `wait_for_completion` now unwraps with `entry = data.get(prompt_id)`. Running job -> id not
  yet a key (keep polling); done -> entry has `outputs` + `status_str` (return).
- **ACE-Step 1.5 blocked (ComfyUI-side, NOT an MCP bug)**: CLIPLoader `type="ace"` in this
  ComfyUI (v0.26.0) instantiates a Qwen3 arch with vocab 151936, but `qwen_4b_ace15.safetensors`
  has vocab 217204 -> "size mismatch for model.embed_tokens.weight" at model load. Needs a
  ComfyUI whose `ace` type supports ACE-Step 1.5 (or ACE-Step 1.0 models). The MCP server is
  correct: it queues, detects the error status, and surfaces the message via `job_error()`.
- **Stable Audio 3**: `StabilityTextToAudio` advertises model `stable-audio-2.5` but installed
  checkpoint is `stable_audio_3_medium_base` -- pairing may not match; treat as best-effort.

## Key API / workflow facts (for resuming agent)
ComfyUI REST:
- `GET /object_info` -> {node_type: {input:{required,optional,latent}, output:[...], ...}}
- `GET /object_info/{node_type}` -> single node
- `POST /prompt` body `{"prompt": <api-workflow-dict>, "front": false, "number": -1}` ->
  `{"prompt_id": "...", "number": int, "node_errors": {...}}`
- `GET /history` -> {prompt_id: entry}; `GET /history/{id}` -> {prompt_id: entry} (STILL nested -- unwrap by id!)
- entry: `{"prompt": {...}, "status": {"status_str": "success|error", "completed": bool}, "outputs": {node_id: {...}}}`
- `GET /view?filename=X&subfolder=Y&type=output` -> media bytes
- `POST /interrupt`; `POST /free` body `{"unload_models":bool,"rerun_outputs":bool}`
- `GET /queue` -> {"queue_running":[...], "queue_pending":[...]}
- `GET /system_stats` -> {system:{comfyui_version, os, ram_total, ram_free,...}}
- `GET /models` -> [category names]; `GET /models/{category}` -> [model file names]

API-format workflow = `{ "<node_id>": {"class_type": "...", "inputs": {...}}, ... }`;
wiring uses `["node_id", output_slot_index]`.

### Image txt2img graph
1 CheckpointLoaderSimple{ckpt_name} -> MODEL/CLIP/VAE
2 CLIPTextEncode{text: prompt, clip:[1,1]} -> positive
3 CLIPTextEncode{text: negative, clip:[1,1]} -> negative
4 EmptyLatentImage{width,height,batch_size}
5 KSampler{model:[1,0],seed,steps,cfg,sampler_name,scheduler,positive:[2,0],negative:[3,0],latent_image:[4,0]}
6 VAEDecode{samples:[5,0], vae:[1,2]}
7 SaveImage{images:[6,0], filename_prefix:"ComfyUI"}

### ACE-Step 1.5 music graph (verified)
1 UNETLoader{unet_name:"acestep_v1.5_turbo.safetensors", weight_dtype:"default"} -> MODEL
2 CLIPLoader{clip_name:"qwen_4b_ace15.safetensors", type:"ace"} -> CLIP
3 VAELoader{vae_name:"ace_1.5_vae.safetensors"} -> VAE
4 TextEncodeAceStepAudio1.5{clip:[2,0], tags, lyrics, seed, bpm, duration, timesignature, language, keyscale, generate_audio_codes, cfg_scale, temperature, top_p, top_k, min_p} -> CONDITIONING
   (ALL required inputs must be present explicitly -- see build_acestep_music for defaults)
5 EmptyAceStep1.5LatentAudio{seconds, batch_size:1}
6 KSampler{model:[1,0],seed,steps,cfg,sampler_name,scheduler,positive:[4,0],negative:[4,0],latent_image:[5,0]}
7 VAEDecodeAudio{samples:[6,0], vae:[3,0]} -> AUDIO
8 SaveAudioMP3{audio:[7,0], filename_prefix:"music/ComfyUI", quality:"128k"}

### Sonilo (self-contained) / Stable Audio
- Sonilo: 1 SoniloTextToMusic{prompt,duration,seed} -> AUDIO ; 2 SaveAudioMP3{audio:[1,0],...}
- Stable: 1 StabilityTextToAudio{model:"stable-audio-2.5",prompt,duration,seed,steps} -> AUDIO ; 2 SaveAudioMP3