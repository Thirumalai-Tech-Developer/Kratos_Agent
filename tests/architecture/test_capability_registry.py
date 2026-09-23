from kratos_agent.capabilities.registry import get_capability_registry


def test_registry_has_core_capabilities():
    registry = get_capability_registry()
    for capability in (
        "browser.youtube.play",
        "whatsapp.send_message",
        "terminal.execute",
        "code.test",
    ):
        assert registry.validate(capability)


def test_discovery_returns_structured_specs():
    matches = get_capability_registry().discover("browser youtube play")
    assert matches
    assert matches[0].capability_id == "browser.youtube.play"
