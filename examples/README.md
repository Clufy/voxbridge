# Examples

Install with `pip install voxbridge` (the FastAPI example also needs `pip install fastapi uvicorn`).

## quickstart.py

Creates an agent and places an outbound call.

```bash
export VOICE_PROVIDER=vapi          # or retell
export VAPI_API_KEY=...             # or RETELL_API_KEY
export TO_NUMBER=+15551234567
export FROM_NUMBER=+15557654321     # required for Retell; optional for Vapi
python examples/quickstart.py
```

## fastapi_server.py

Receives webhooks (`POST /webhooks`, returns 204) and tool calls (`POST /tools`, returns the
provider-shaped tool response). Bad signatures get 401. The client is built from the environment on
the first request.

```bash
export VOICE_PROVIDER=retell
export RETELL_API_KEY=...
uvicorn examples.fastapi_server:app --port 8000
```

Retell verifies requests with the API key by default; for Vapi set `VAPI_WEBHOOK_SECRET`.
