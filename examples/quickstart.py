"""Create an agent and place a call, on whichever provider the env selects.

    VOICE_PROVIDER=vapi VAPI_API_KEY=... TO_NUMBER=+15551234567 python examples/quickstart.py

Retell also needs FROM_NUMBER (an E.164 number you own).
"""

from __future__ import annotations

import os

from voxbridge import Agent, VoiceClient


def main() -> None:
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
        call = client.create_call(
            agent.id, os.environ["TO_NUMBER"], from_number=os.environ.get("FROM_NUMBER")
        )
        print(f"agent {agent.id} calling: call {call.id} is {call.status}")


if __name__ == "__main__":
    main()
