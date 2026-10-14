"""A tool start must reach the client while execution is still blocked."""
import json
import threading

from test_studio_web import call, server as shared_server

from kratos_agent.core.event_bus import event_bus
from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent

server = shared_server


def test_tool_start_streams_before_tool_returns(server):
    started = threading.Event()
    finish = threading.Event()

    def execute(*args, **kwargs):
        event_bus.publish(RuntimeEvent(EventKind.TOOL_CALL_STARTED, {
            "call_id": "held-tool", "name": "read_file", "arguments": {"file_path": "README.md"},
        }))
        started.set()
        assert finish.wait(4), "Tool start was buffered until execution finished"
        event_bus.publish(RuntimeEvent(EventKind.TOOL_COMPLETED, {
            "call_id": "held-tool", "name": "read_file", "content": "File content", "is_error": False,
        }))
        return "Read complete"

    server.runtime.run_agent.side_effect = execute
    try:
        with call(server, "/api/chat", {"prompt": "Read README.md"}) as response:
            events = []
            for raw in response:
                if not raw.startswith(b"data: "):
                    continue
                event = json.loads(raw[6:])
                events.append(event)
                if event.get("type") == "tool_call":
                    break
            assert started.is_set() and not finish.is_set()
            assert events[-1]["tool_call"]["call_id"] == "held-tool"
            assert not any(event["type"] in ("tool_result", "done") for event in events)
            finish.set()
            events.extend(json.loads(raw[6:]) for raw in response.read().decode().splitlines()
                          if raw.startswith("data: "))
        assert any(event["type"] == "tool_result" for event in events)
        assert events[-1]["type"] == "done"
    finally:
        finish.set()
