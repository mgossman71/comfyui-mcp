# ComfyUI MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that lets an
LLM client (Claude, Cursor, etc.) drive a running [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
instance: generate images and music, discover nodes/models, manage the queue, and
retrieve the media that jobs produce.

Media is returned to the model in a way it can act on:
- **Images** come back as base64 `ImageContent` blocks (the model can see them).
- **Audio** comes back as an `AudioContent` block **plus** a `/view` URL (the model can't
  "listen", but it can hand the URL to the user).

---

## Supported generation engines

| Tool | How you pick the model |
| --- | --- |
| `comfyui_generate_image` | Pass `model` = a preset name (default **`flux1-dev`**). A raw `checkpoint` file also works. |
| `comfyui_generate_music` | Pass `model` = a preset name (default **`acestep-turbo`**), or `engine` = `acestep15` / `sonilo` / `stable_audio`. |

### Model presets

Models are selected by a friendly preset name (not a raw file path). Run
`comfyui_list_presets` to see the current presets:

- **Image:** `flux1-dev` (default), `flux1-schnell`, `sdxl-juggernaut`
- **Audio:** `acestep-turbo` (default), `sonilo`

To add or change a model, edit the `IMAGE_PRESETS` / `AUDIO_PRESETS` dictionaries
in [`comfyui_mcp/presets.py`](comfyui_mcp/presets.py) (then rebuild the container).
Power users can still pass a raw `checkpoint` (image) or `engine` (music) to bypass presets.

---

## How to run it

There are two ways to run this server. **Docker (recommended)** runs it as a long-lived
service over HTTP; **local stdio** runs it in-process for a client that spawns the server.

### Option A — Docker with docker compose (recommended)

Prerequisites: Docker + the Docker Compose plugin.

```bash
# 1. Point the server at your ComfyUI instance (edit docker-compose.yml)
#    -> COMFYUI_URL: http://<your-comfyui-host>:8188

# 2. Build and start the container
docker compose up -d --build

# 3. Verify it is healthy and can reach ComfyUI
curl http://localhost:8000/health
#    -> {"ok":true,"comfyui_reachable":true}
```

The MCP endpoint is **`http://localhost:8000/mcp`** (Streamable HTTP transport).

Stop / manage:
```bash
docker compose logs -f     # follow logs
docker compose ps          # status / health
docker compose down        # stop and remove the container
```

> **Reaching ComfyUI from the container**
> - ComfyUI is on the **LAN** (your case): keep `COMFYUI_URL: http://10.0.54.157:8188`.
> - ComfyUI runs on the **Docker host**: use `COMFYUI_URL: http://host.docker.internal:8188`
>   (the compose file already adds the `host.docker.internal` host entry for Linux).

### Option B — Local, in-process (stdio)

For clients that launch the server as a subprocess. Uses the project's virtualenv:

```bash
cd ComfyUI-MCP
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
COMFYUI_URL=http://10.0.54.157:8188 .venv/bin/python -m comfyui_mcp.server
```

> ⚠️ The `.venv/bin/python` interpreter is required — system Python won't have the
> `mcp` package installed.

---

## Configuring your MCP client

### For the Docker deployment (Streamable HTTP)

Point any client that supports remote / HTTP MCP servers at the endpoint:

```
http://localhost:8000/mcp      (transport: streamable-http)
```

Example (Claude Desktop / any client with a "remote MCP server" setting):
```json
{
  "mcpServers": {
    "comfyui": {
      "url": "http://localhost:8000/mcp",
      "transport": "streamable-http"
    }
  }
}
```
> The exact schema differs slightly between clients — some use `url`, others
> `type`+`url`. The endpoint and transport above are the important parts.

### For the local stdio deployment

Use `config/claude_desktop_config.json` (merge it into your client's MCP config):
```json
{
  "mcpServers": {
    "comfyui": {
      "command": "/Users/markgossman/Documents/GITHUB/ComfyUI-MCP/.venv/bin/python",
      "args": ["-m", "comfyui_mcp.server"],
      "cwd": "/Users/markgossman/Documents/GITHUB/ComfyUI-MCP",
      "env": { "COMFYUI_URL": "http://10.0.54.157:8188" }
    }
  }
}
```

---

## Tools

| Tool | Purpose |
| --- | --- |
| `comfyui_system_info` | Version, OS, RAM, GPU/VRAM devices |
| `comfyui_queue` | Currently running + pending jobs |
| `comfyui_list_models` | Installed models, optionally filtered by type |
| `comfyui_list_presets` | Named model presets for the generate tools (image + audio) |
| `comfyui_list_nodes` | Installed node types, optionally searched |
| `comfyui_node_info` | Full input schema (required/optional) for one node |
| `comfyui_interrupt` | Interrupt the front-of-queue job (optionally by prompt id) |
| `comfyui_free` | Free model memory (weights + VRAM) to make room |
| `comfyui_queue_prompt` | Queue an arbitrary workflow (API-format graph), no waiting |
| `comfyui_wait_for_completion` | Block until a queued prompt finishes |
| `comfyui_get_image` | Fetch a produced image from `/view` as image content |
| `comfyui_get_audio` | Fetch a produced audio file as audio content + URL |
| `comfyui_generate_image` | One-shot image generation (FLUX or SDXL) → returns the image |
| `comfyui_generate_music` | One-shot music generation (ACE-Step 1.5 / Sonilo / Stable Audio) → returns audio |

### Music generation tips
- **ACE-Step 1.5** (default): put genre/style in `tags` (e.g. `"pop, female vocal, upbeat"`)
  and song text in `lyrics`. Tune `bpm`, `language`, `keyscale`. `prompt` may be empty.
- **Sonilo**: a plain natural-language `prompt`.
- **Stable Audio**: a plain natural-language `prompt` (treated as best-effort).

---

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `COMFYUI_URL` | `http://10.0.54.157:8188` | Base URL of the ComfyUI server |
| `COMFYUI_TIMEOUT` | `120` | Per-request HTTP timeout (seconds) |
| `COMFYUI_WAIT_TIMEOUT` | `900` | Max time to wait for a single generation to finish |
| `COMFYUI_POLL_INTERVAL` | `1.0` | How often to poll `/history` while waiting |
| `MCP_TRANSPORT` | `stdio` | `stdio` \| `sse` \| `streamable-http` |
| `MCP_HOST` | `127.0.0.1` | Bind address for the HTTP transports (`0.0.0.0` in Docker) |
| `MCP_PORT` | `8000` | Port for the HTTP transports |
| `MCP_STATELESS` | `false` | `true` = stateless HTTP sessions (resilient to container restarts) |

---

## Notes & troubleshooting

- **Slow GPUs / cold model loads:** the first generation of a session can take a long
  time while models load into VRAM. If a generation times out, raise `COMFYUI_WAIT_TIMEOUT`
  (e.g. `1800`) — the job may have finished right after the default window.
- **Image generation is verified** end-to-end through the Docker container: `comfyui_generate_image`
  defaults to **FLUX.1 dev** and returns a valid PNG (e.g. 1024×1024) over
  `http://localhost:8000/mcp`.
- **ACE-Step 1.5 needs a matching ComfyUI:** the `CLIPLoader` `type="ace"` in your ComfyUI must
  match the installed text encoder's vocabulary. If a music job fails at `CLIPLoader` with
  "size mismatch for model.embed_tokens.weight", your ComfyUI's `ace` type (base Qwen3, vocab
  151936) predates ACE-Step 1.5 (vocab 217204) — update ComfyUI or install matching models.
  Failed jobs now surface the exact ComfyUI error in the tool response.
- **The `/health` endpoint** reports whether the MCP server is up *and* whether it can
  reach ComfyUI. If `comfyui_reachable` is `false`, check `COMFYUI_URL` and Docker networking.
- **Stateless mode:** for a Docker service that may be restarted behind a proxy/load
  balancer, set `MCP_STATELESS=true` so each request is independent (no stale-session errors).