"""Tests for live status reporting."""
import unittest

from kratos_agent.live.events import LiveState, LiveStatusHub


class LiveStatusTests(unittest.TestCase):
    def test_live_state_transitions(self):
        hub = LiveStatusHub()
        states_recorded = []
        hub.subscribe(lambda status: states_recorded.append(status.current_state))

        for state in (
            LiveState.CONNECTING,
            LiveState.IDLE,
            LiveState.LISTENING,
            LiveState.THINKING,
            LiveState.SPEAKING,
        ):
            hub.update(current_state=state)

        self.assertEqual(
            states_recorded,
            [
                LiveState.CONNECTING,
                LiveState.IDLE,
                LiveState.LISTENING,
                LiveState.THINKING,
                LiveState.SPEAKING,
            ],
        )


if __name__ == "__main__":
    unittest.main()
