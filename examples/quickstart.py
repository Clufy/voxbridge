"""Create an agent and place a call, on whichever provider the env selects.

    export VOICE_PROVIDER=vapi VAPI_API_KEY=...
    export TO_NUMBER=+15551234567 FROM_NUMBER=+15557654321
    python examples/quickstart.py

FROM_NUMBER is the caller number, required on both providers: an E.164 number
you own (on Vapi, a number imported into your account, or its phone-number id).
"""

from __future__ import annotations

import os

from voxbridge import Agent, VoiceClient


def main() -> None:
    to_number = os.environ["TO_NUMBER"]
    from_number = os.environ["FROM_NUMBER"]
    with VoiceClient.from_env() as client:
        agent = client.create_agent(
            Agent(
                name="Front desk",
                system_prompt="You are a friendly receptionist. Keep answers short.",
                model="gpt-4o",
                # "provider:voice"; voice catalogs differ per provider.
                voice="openai:alloy",
                first_message="Hi, how can I help?",
            )
        )
        assert agent.id is not None
        call = client.create_call(agent.id, to_number, from_number=from_number)
        print(f"agent {agent.id} calling: call {call.id} is {call.status}")


if __name__ == "__main__":
    main()
