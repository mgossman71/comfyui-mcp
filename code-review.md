# Code Review — `ComfyUI-MCP`

- **Date:** 2026-09-23
- **Branch / commit:** `main` @ `0fcc4ff` — *"Make the MCP self-describing for LLM/harness clients"* (clean working tree)
- **Files reviewed:** `comfyui_mcp/server.py` (540), `client.py` (150), `presets.py` (63), `workflows.py` (170), `__init__.py` (7); `config/claude_desktop_config.json`; `requirements.txt`; `smoke_test.py`; `Dockerfile`; `docker-compose.yml`; `README.md`

## Overall assessment

A clean, well-structured, genuinely useful MCP server with good separation of concerns:

- `client.py` — thin synchronous `httpx` wrapper over the ComfyUI REST API
- `workflows.py` — pure builders that emit API-format workflow dicts
- `presets.py` — friendly-name → model-file mapping
- `server.py` — 15 `@mcp.tool()` definitions + `/health`

The latest commit's goal (make the MCP self-describing for LLM/harness clients) is **well
achieved**: every tool has a self-sufficient docstring, a top-level `INSTRUCTIONS` block is
delivered at `initialize`, and `comfyui_help` returns the same guide on demand. Error surfacing
via `job_error()` is a real quality win (actual ComfyUI errors, e.g. the CLIPLoader mismatch,
bubble up instead of "no output found"). Config is env-driven, there is a Docker healthcheck,
and the `/history/{id}` nested-unwrap case is correctly handled.

The findings below are mostly correctness / robustness / polish — not architectural rework.

## Findings summary

Severity legend: 🔴 High (correctness) · 🟠 Medium (robustness / security / deploy) · 🟡 Low (polish)

| ID | Sev | Location | Finding | Status |
|----|-----|----------|---------|--------|
| H1 | 🔴 | `presets.py:37` vs `workflows.py:72` | ACE-Step preset selects a different (wrong) text encoder than the builder default | Open |
| M1 | 🟠 | `client.py:112` | Each generation holds a worker thread for the whole wait (bounded concurrency) | Open |
| M2 | 🟠 | `docker-compose.yml:8-9` | No authentication on the HTTP endpoint, bound to `0.0.0.0` | Open |
| M3 | 🟠 | `docker-compose.yml` | `MCP_STATELESS=true` recommended by README but not set in compose | Open |
| M4 | 🟠 | `client.py:123-134` | `wait_for_completion` relies on `/history/{id}` returning `200 {}` for in-flight jobs | Open |
| M5 | 🟠 | `client.py:13` | Hardcoded personal LAN IP baked into the default `COMFYUI_URL` | Open |
| L1 | 🟡 | `server.py:22` | Unused `import random` | Open |
| L2 | 🟡 | `workflows.py:33` | Dead `is_flux` parameter in `build_txt2img` | Open |
| L3 | 🟡 | `server.py:414-417` | FLUX defaults detected via equality-with-defaults (brittle) | Open |
| L4 | 🟡 | `README.md` (tool table) | `comfyui_interrupt` doc claims an optional prompt id the tool does not accept | Open |
| L5 | 🟡 | `server.py` | Several tools annotated `-> list` instead of a precise content type | Open |
| L6 | 🟡 | `server.py:164` | `ram_free / 1e9` raises `TypeError` if the value is `None` | Open |
| L7 | 🟡 | `requirements.txt` | Loose version pins, no lockfile | Open |
| L8 | 🟡 | `checkpoint.md:43` | Handoff doc says "13 `@mcp.tool()`"; there are actually 15 | Open |
| L9 | 🟡 | `client.py:137` | `extract_media` handles `images` + `audio` only (drops `gifs`/`videos`) | Open |

---

## 🔴 High — correctness

### H1. ACE-Step preset selects a different (wrong) text encoder than the builder default

The same engine produces **different models** depending on whether it is reached via the preset
name or the raw `engine` argument:

| Source | `unet_name` | `clip_name` | `vae_name` |
|---|---|---|---|
| `presets.py:34` `acestep-turbo` | `acestep_v1.5_turbo.safetensors` | **`qwen_0.6b_ace15.safetensors`** | `ace_1.5_vae.safetensors` |
| `workflows.py:71` `build_acestep_music` default | `acestep_v1.5_turbo.safetensors` | **`qwen_4b_ace15.safetensors`** | `ace_1.5_vae.safetensors` |

In `server.py:487-498`, the preset's `clip_name` is passed via `**extra` and **overrides** the
builder default. Per `checkpoint.md`, the installed/verified ACE-Step 1.5 text encoder is
`qwen_4b_ace15.safetensors` (the 0.6B file is the ACE-Step **1.0** encoder). Consequently:

- `comfyui_generate_music()` with the **default** `model="acestep-turbo"` → uses `qwen_0.6b`
  → the "size mismatch for model.embed_tokens.weight" failure.
- `comfyui_generate_music(engine="acestep15")` → skips the preset (`if engine is None`), uses the
  builder's `qwen_4b` default → the verified-correct encoder.

Two entry points, two different text encoders for "the same thing." The preset is the outlier.

**Fix:** make `presets.py:37` use `qwen_4b_ace15.safetensors` (matching the builder + installed
model), *or* — cleaner — drop the `unet_name`/`clip_name`/`vae_name` overrides from the preset
entirely and let the builder defaults be the single source of truth.

---

## 🟠 Medium — robustness / security / deploy

### M1. Concurrency ceiling: each generation holds a worker thread for the whole wait
`wait_for_completion` (`client.py:112`) blocks with `time.sleep` for up to
`COMFYUI_WAIT_TIMEOUT` (default 900 s). FastMCP runs sync tool functions in the anyio
worker-thread pool (default capacity **40**), so a single in-flight 15-minute job holds one thread
for its entire duration. Fine for the intended single-user / stdio use, but the streamable-http
Docker deployment has a hard, undocumented ceiling on concurrent generations. **Fix:** either
raise the thread limiter or document the cap.

### M2. No authentication on the HTTP endpoint, bound to `0.0.0.0`
The Docker deployment (`docker-compose.yml`) exposes `:8000` (and `/health`) with no auth and
binds `0.0.0.0`. Anyone on the LAN can hit `/mcp` and drive the ComfyUI GPU (generate, free VRAM,
interrupt, and submit arbitrary workflows via `comfyui_queue_prompt`). Acceptable on a trusted
private LAN, but worth a security note + optional shared-secret/auth or a reverse proxy.

### M3. `docker-compose.yml` does not set `MCP_STATELESS=true`
`README.md` explicitly recommends `MCP_STATELESS=true` for "a Docker service that may be
restarted behind a proxy… (no stale-session errors)," but the compose file does not set it — so
the default deployment is **stateful** and will drop sessions on container restart, the exact
failure the README warns about. **Fix:** add `MCP_STATELESS: "true"` to the compose
`environment:` block (or document the tradeoff).

### M4. `wait_for_completion` relies on `/history/{id}` returning `200 {}` for in-flight jobs
`client.py:123-134` keeps polling while the entry is empty; that works because ComfyUI v0.26
returns `200 {}` for a not-yet-completed id. But `_request` (`client.py:52`) raises `ComfyUIError`
on any status ≥ 400 — if a future ComfyUI returns `404` for an in-flight id, the wait loop
**raises immediately** instead of continuing to poll. **Fix:** treat "not found yet" as
*keep polling* rather than a hard error (version-robustness).

### M5. Hardcoded personal LAN IP as the default `COMFYUI_URL`
`client.py:13` `DEFAULT_BASE_URL = "http://10.0.54.157:8188"` — and the same IP is baked into
`config/claude_desktop_config.json`, `docker-compose.yml`, and `README.md`. Baking a specific
machine's LAN IP into the library default means anyone who clones this without setting
`COMFYUI_URL` points at the author's machine. **Fix:** default to `http://127.0.0.1:8188` and
document `COMFYUI_URL` as the required override.

---

## 🟡 Low — polish / hygiene

- **L1. Unused import.** `server.py:22` `import random` is never used (seed randomness lives in
  `workflows.resolve_seed`). Remove it.
- **L2. Dead parameter.** `workflows.py:33` `build_txt2img(..., is_flux: bool = False)` — `is_flux`
  appears only in the signature + docstring, never in the body (FLUX sampler/scheduler/cfg/steps
  are already applied in `server.py` before the call). Remove the param.
- **L3. Brittle FLUX default logic.** `server.py:414-417` detects "user didn't override" via
  `if steps == 20` / `if cfg == 7.0`. That conflation means a user who *explicitly* wants 20 steps
  on `flux1-schnell` can't get it (it's forced to 4). **Fix:** `steps: Optional[int] = None`,
  `cfg: Optional[float] = None`; apply FLUX-appropriate defaults only when `None`.
- **L4. Doc mismatch.** The `README.md` tool table claims `comfyui_interrupt` works "optionally by
  prompt id," but `comfyui_interrupt()` takes no arguments. Fix the doc.
- **L5. Return-type precision.** Several tools are annotated `-> list`; `list[TextContent]` /
  `list[ContentBlock]` would be more precise for tooling.
- **L6. Defensive null-safety.** `server.py:164` `sysd.get('ram_free', 0) / 1e9` raises `TypeError`
  if the key is present but `None` (vs. missing). `(sysd.get('ram_free') or 0) / 1e9` is safer.
- **L7. Reproducibility.** `requirements.txt` uses loose pins (`mcp>=1.10,<2`, `httpx>=0.27`) with
  no lockfile. Consider `pip-tools` / `uv` lock for the Docker build.
- **L8. Stale handoff.** `checkpoint.md:43` says "13 `@mcp.tool()`" but there are now **15**.
  Minor, since it is a living doc.
- **L9. Feature gap (not a bug).** `extract_media` (`client.py:137`) handles `images` + `audio`
  only — ComfyUI `gifs`/`videos` outputs are silently dropped. Fine for now; worth a comment.

---

## Prioritized fix plan

1. **H1** — reconcile the ACE-Step `clip_name` (preset vs. builder). Highest value: a genuine
   wrong-model-selection bug on the default path.
2. **M3** — add `MCP_STATELESS: "true"` to `docker-compose.yml` (one line, matches the README).
3. **M5** — change the default `COMFYUI_URL` to `127.0.0.1` (across the 4 places).
4. **M4** — make `wait_for_completion` treat a missing in-flight id as "keep polling."
5. **L1 + L2** — remove the unused `import random` and the dead `is_flux` param.
6. **M2** — add a short security note on the HTTP endpoint (auth / reverse proxy).
7. **L3–L9** — the remaining polish.

## Suggested verification

- Run the read-only smoke checks: `.venv/bin/python smoke_test.py` (handshake, `tools/list`,
  read-only tools).
- After the H1 fix: run `.venv/bin/python smoke_test.py --gen` and confirm the ACE-Step path
  selects `qwen_4b` (and that `job_error()` surfaces any encoder mismatch clearly).
- Rebuild the Docker image and confirm `/health` + the stateless behavior.