import pytest

from kratos_agent.brain.tool_calls import extract_tool_calls_from_text
from kratos_agent.core.model_adapter import KratosModelAdapter


@pytest.mark.parametrize('marker', ['｜｜DSML｜｜ ', '||DSML|| ', '| | DSML | | '])
def test_screenshot_call_accepts_hyphenated_mcp_name(marker):
    raw = f'<{marker}calls>\n<{marker}invoke name="mcp__computer-use__screenshot">\n</{marker}invoke>\n</{marker}calls>'
    clean, calls = extract_tool_calls_from_text(raw)
    assert clean == ''
    assert calls == [{'name': 'mcp__computer-use__screenshot', 'args': {}}]


def test_multiple_calls_parameters_and_prose():
    raw = '''Inspecting your screen.
<||DSML|| calls>
<||DSML|| invoke name="mcp__computer-use__screenshot"></||DSML|| invoke>
<||DSML|| invoke name="mcp__browser__click">
<||DSML|| parameter name="selector" string="true">button[data-id="123"]</||DSML|| parameter>
<||DSML|| parameter name="timeout" string="false">1000</||DSML|| parameter>
<||DSML|| parameter name="options" string="false">{"exact":true}</||DSML|| parameter>
</||DSML|| invoke>
</||DSML|| calls>'''
    clean, calls = extract_tool_calls_from_text(raw)
    assert clean == 'Inspecting your screen.'
    assert len(calls) == 2
    assert calls[1]['args'] == {'selector': 'button[data-id="123"]', 'timeout': 1000, 'options': {'exact': True}}


class StreamingClient:
    def __init__(self, raw, native=None):
        self.raw, self.native = raw, native or []

    def complete(self, **kwargs):
        callback = kwargs.get('on_chunk')
        if callback:
            for char in self.raw:
                callback(char)
        return self.raw, self.native


@pytest.mark.parametrize('prefix', ['', 'Checking your screen.\n'])
def test_fragmented_dsml_does_not_leak_and_normalizes_native_duplicate(prefix):
    raw = prefix + '< | | DSML | | calls>< | | DSML | | invoke name="mcp__computer-use__screenshot"></ | | DSML | | invoke></ | | DSML | | calls>'
    client = StreamingClient(raw, [{'name': 'mcp__computer-use__screenshot', 'args': {}, 'id': 'native-id'}])
    chunks = []
    result = KratosModelAdapter('deepseek-web', client).complete({'messages': [], 'tools': []}, on_chunk=chunks.append)
    assert ''.join(chunks) == prefix
    assert result.text == prefix.strip()
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].call_id == 'native-id'
    assert result.tool_calls[0].name == 'mcp__computer-use__screenshot'


@pytest.mark.parametrize('raw', [
    '<||DSML|| invoke name="mcp__computer-use__screenshot">',
    '<||DSML|| invoke name="read_file"><||DSML|| parameter name="file_path" string="false">INVALID JSON</||DSML|| parameter></||DSML|| invoke>',
])
def test_malformed_calls_are_not_executed_or_shown_as_final_answer(raw):
    with pytest.raises(ValueError, match='invalid tool call'):
        KratosModelAdapter('test', StreamingClient(raw)).complete({'messages': []})


def test_regular_prose_streaming_is_preserved():
    raw = 'Your screen is available. Here is <strong>ordinary HTML</strong>.'
    chunks = []
    result = KratosModelAdapter('test', StreamingClient(raw)).complete({'messages': []}, on_chunk=chunks.append)
    assert ''.join(chunks) == raw
    assert result.text == raw
