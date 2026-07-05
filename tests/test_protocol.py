from voxbridge.providers.base import VoiceProvider


def test_protocol_is_runtime_checkable() -> None:
    class Dummy:
        pass

    assert not isinstance(Dummy(), VoiceProvider)


def test_protocol_lists_expected_methods() -> None:
    for m in ("create_agent", "get_call", "parse_webhook", "verify_signature", "acreate_agent"):
        assert hasattr(VoiceProvider, m)


def test_protocol_lists_async_twins() -> None:
    for m in ("acreate_call", "aclose"):
        assert hasattr(VoiceProvider, m)
