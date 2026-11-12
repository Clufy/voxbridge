"""FastAPI receiver for voxbridge webhooks and tool calls.

    VOICE_PROVIDER=retell RETELL_API_KEY=... uvicorn examples.fastapi_server:app

Point your provider's server URL at /webhooks and its tool/function URL at /tools.

Authentication: Retell requests are verified by default with RETELL_API_KEY (or
RETELL_WEBHOOK_SECRET if set), and signatures older than 5 minutes are rejected. Vapi requests
are NOT authenticated unless you set VAPI_WEBHOOK_SECRET: without it anyone can call /tools.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from voxbridge import (
    CallEnded,
    CallStarted,
    ProviderError,
    SignatureError,
    ToolCall,
    TranscriptChunk,
    VoiceClient,
)

app = FastAPI()


@cache
def get_client() -> VoiceClient:
    """Build the client on first use so importing this module needs no env."""
    return VoiceClient.from_env()


def book_appointment(args: dict[str, Any]) -> dict[str, Any]:
    return {"booked": args.get("day")}


TOOLS: dict[str, Callable[[dict[str, Any]], Any]] = {"book_appointment": book_appointment}


@app.post("/webhooks")
async def webhooks(request: Request) -> Response:
    event = get_client().parse_webhook(request.headers, await request.body())
    match event:
        case CallStarted():
            print("call started", event.call_id)
        case TranscriptChunk():
            print(f"{event.role}: {event.text}")
        case CallEnded():
            print("call ended", event.call_id, event.ended_reason)
    return Response(status_code=204)


@app.post("/tools")
async def tools(request: Request) -> JSONResponse:
    client = get_client()
    event = client.parse_webhook(request.headers, await request.body())
    if not isinstance(event, ToolCall) or event.name not in TOOLS:
        return JSONResponse({"error": "unknown tool"}, status_code=400)
    result = TOOLS[event.name](event.arguments)
    return JSONResponse(client.tool_response(event, result))


@app.exception_handler(SignatureError)
async def bad_signature(request: Request, exc: SignatureError) -> JSONResponse:
    return JSONResponse({"error": "invalid signature"}, status_code=401)


@app.exception_handler(ProviderError)
async def provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)
