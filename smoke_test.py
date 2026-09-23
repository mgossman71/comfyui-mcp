"""End-to-end smoke test for the ComfyUI MCP server.

Always runs the fast checks (MCP handshake, tools/list, read-only tools).
Pass --gen to also run a small image generation and a short ACE-Step music
generation end-to-end.

Run:  .venv/bin/python smoke_test.py [--gen]
"""
import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(PROJECT, ".venv", "bin", "python")
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://10.0.54.157:8188")


def _params() -> StdioServerParameters:
    env = dict(os.environ)
    env["COMFYUI_URL"] = COMFYUI_URL
    env["PYTHONPATH"] = PROJECT
    return StdioServerParameters(
        command=PYTHON,
        args=["-m", "comfyui_mcp.server"],
        env=env,
        cwd=PROJECT,
    )


def _print_result(name: str, r) -> None:
    print(f"\n=== {name} ===")
    for c in r.content:
        if getattr(c, "type", "") == "text" and hasattr(c, "text"):
            print(c.text)
        else:
            print(f"[{getattr(c, 'type', '?')}] mimeType={getattr(c, 'mimeType', '?')} data_len={len(getattr(c, 'data', '') or '')}")


async def main() -> None:
    do_gen = "--gen" in sys.argv
    async with stdio_client(_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("=== tools/list ===")
            print(", ".join(t.name for t in tools.tools))

            _print_result("system_info", await session.call_tool("comfyui_system_info", {}))
            _print_result("list_models (categories)", await session.call_tool("comfyui_list_models", {}))
            _print_result("list_models (checkpoints)", await session.call_tool("comfyui_list_models", {"category": "checkpoints"}))
            _print_result("list_nodes (search=audio)", await session.call_tool("comfyui_list_nodes", {"search": "audio"}))
            _print_result("node_info (KSampler)", await session.call_tool("comfyui_node_info", {"node_type": "KSampler"}))
            _print_result("queue", await session.call_tool("comfyui_queue", {}))
            _print_result("list_presets", await session.call_tool("comfyui_list_presets", {}))

            if do_gen:
                print("\n\n########## GENERATION TESTS ##########")
                _print_result(
                    "generate_image (default preset flux1-dev, small/fast)",
                    await session.call_tool(
                        "comfyui_generate_image",
                        {
                            "prompt": "a red cube on a blue background, simple, minimal",
                            "width": 512,
                            "height": 512,
                            "steps": 8,
                        },
                    ),
                )
                _print_result(
                    "generate_music (ACE-Step 10s)",
                    await session.call_tool(
                        "comfyui_generate_music",
                        {
                            "engine": "acestep15",
                            "tags": "lofi hip hop, chill, instrumental",
                            "lyrics": "",
                            "duration_seconds": 10,
                        },
                    ),
                )


if __name__ == "__main__":
    asyncio.run(main())