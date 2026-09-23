# Slim, self-contained image for the ComfyUI MCP server.
# `mcp` transitively pulls httpx, uvicorn, starlette, sse-starlette, etc.,
# so installing requirements.txt is all that is needed.
FROM python:3.11-slim

# Unbuffered output; skip .pyc files in the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the server package.
COPY comfyui_mcp/ ./comfyui_mcp/

# Default to serving MCP over streamable-http on a container-reachable port.
# Override via the docker compose `environment:` block as needed.
ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "comfyui_mcp.server"]