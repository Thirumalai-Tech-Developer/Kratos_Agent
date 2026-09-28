"""Unmarked Kratos output stays on screen; only a paired directive is spoken."""
from unittest.mock import patch

from kratos_agent.live.config import LiveConfig
from kratos_agent.live.runtime import LiveRuntime


def test_live_runtime_rejects_unmarked_or_malformed_speech():
    runtime = LiveRuntime(config=LiveConfig(api_key="", enabled=True))
    with patch.object(runtime, "speak_marked") as speak_marked:
        runtime.speak("This should stay on screen.")
        runtime.speak("[[speak]]unfinished phrase")
    speak_marked.assert_not_called()


def test_live_runtime_speaks_only_the_paired_phrase():
    runtime = LiveRuntime(config=LiveConfig(api_key="", enabled=True))
    with patch.object(runtime, "speak_marked") as speak_marked:
        runtime.speak("Visible answer. [[speak]]Short spoken summary.[[/speak]] More visible text.")
    speak_marked.assert_called_once_with("Short spoken summary.")


def test_queue_based_speech_also_requires_a_valid_directive():
    from kratos_agent.output.voice import get_tts_queue

    queue = get_tts_queue()
    with patch("kratos_agent.live.get_live_runtime") as get_runtime:
        queue.speech_func("unmarked output stays on screen")
        get_runtime.assert_not_called()

        queue.speech_func("[[speak]]Short spoken summary.[[/speak]]")
        get_runtime.return_value.speak_marked.assert_called_once_with("Short spoken summary.")
