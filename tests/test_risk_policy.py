from kratos_agent.core.risk_policy import assess_tool_risk
from kratos_agent.core.runtime_contracts import ToolPermission, ToolSpec


def _spec(name: str, *, permission: ToolPermission = ToolPermission.EXECUTE, annotations=None) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Test tool",
        parameters={"type": "object"},
        permission=permission,
        source="mcp:test",
        annotations=annotations or {},
    )


def test_external_message_requires_direct_action_and_exact_recipient():
    spec = _spec("mcp__mail__send_email")
    arguments = {"to": "alex@example.com", "subject": "Review", "body": "The draft is ready."}

    draft_only = assess_tool_risk(spec, arguments, "Draft an email to alex@example.com about the review.")
    direct_send = assess_tool_risk(spec, arguments, "Send an email to alex@example.com about the review.")
    other_recipient = assess_tool_risk(spec, arguments, "Send the review email to sam@example.com.")

    assert draft_only is not None and draft_only.authorized is False
    assert direct_send is not None and direct_send.authorized is True
    assert other_recipient is not None and other_recipient.authorized is False


def test_destructive_command_requires_exact_path():
    spec = _spec("run_terminal_command")
    arguments = {"command": 'Remove-Item -LiteralPath "C:\\data\\old.txt" -Force'}

    missing_target = assess_tool_risk(spec, arguments, "Delete the temporary data file.")
    exact_target = assess_tool_risk(spec, arguments, "Delete C:\\data\\old.txt permanently.")

    assert missing_target is not None and missing_target.authorized is False
    assert exact_target is not None and exact_target.authorized is True


def test_financial_action_requires_requested_item_and_target():
    spec = _spec("mcp__shop__purchase_item")
    arguments = {"item_id": "sku-481", "account_id": "acct-7"}

    decision = assess_tool_risk(spec, arguments, "Purchase sku-481 using acct-7.")
    assert decision is not None and decision.category == "financial or booking action"
    assert decision.authorized is True


def test_mcp_destructive_annotation_is_enforced_even_if_tool_name_is_generic():
    spec = _spec("mcp__storage__apply", annotations={"destructiveHint": True})
    arguments = {"target": "archive-2024"}

    decision = assess_tool_risk(spec, arguments, "Apply the changes to archive-2024.")
    assert decision is not None
    assert decision.authorized is False


def test_read_only_tool_is_not_blocked_by_write_risk_words():
    spec = _spec("search_deleted_files", permission=ToolPermission.READ)
    assert assess_tool_risk(spec, {"query": "deleted accounts"}, "Search deleted accounts") is None


def test_exception_message_property_is_not_external_communication():
    command = "node -e \"try{require('playwright')}catch(e){console.log(e.message)}\""
    assert assess_tool_risk(_spec("run_terminal_command"), {"command": command}, "Check Playwright") is None


def test_message_and_send_methods_still_require_authorization():
    for command in ("node -e 'client.message()'", "node -e 'client.send()'", "curl -X POST https://example.com"):
        decision = assess_tool_risk(_spec("run_terminal_command"), {"command": command}, "Check dependencies")
        assert decision is not None and not decision.authorized
