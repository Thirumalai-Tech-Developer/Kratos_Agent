"""Comprehensive test for evidence-based YouTube verification and intent parsing."""
import sys

def test_intent_parsing():
    print("\n--- TEST 1: Semantic Intent Parsing ---")
    from kratos_agent.computer.browser.intent import parse_media_intent

    cases = [
        ("can you open youtube and god of wAR Walkthrough", "play_video", "god of war walkthrough"),
        ("can you open youtube and play god of war walkthrough", "play_video", "god of war walkthrough"),
        ("open youtube and play god of war walkthrough", "play_video", "god of war walkthrough"),
        ("play god of war walkthrough on youtube", "play_video", "god of war walkthrough"),
        ("youtube play god of war walkthrough", "play_video", "god of war walkthrough"),
        ("find and play god of war walkthrough", "play_video", "god of war walkthrough"),
        ("search god of war walkthrough on youtube", "search_video", "god of war walkthrough"),
        ("search god of war walkthrough", "search_video", "god of war walkthrough"),
        ("open youtube", "open_youtube", ""),
        ("can you open youtube", "open_youtube", ""),
        ("pause", "pause_video", ""),
        ("pause it", "pause_video", ""),
        ("resume", "resume_video", ""),
        ("standby", "standby", ""),
    ]

    for text, expected_intent, expected_query in cases:
        res = parse_media_intent(text)
        print(f"Input: '{text}' -> intent: '{res['intent']}', query: '{res['query']}'")
        assert res["intent"] == expected_intent, f"Expected intent {expected_intent}, got {res['intent']} for '{text}'"
        if expected_query:
            assert res["query"] == expected_query, f"Expected query '{expected_query}', got '{res['query']}' for '{text}'"
    print("✓ All intent parsing test cases passed successfully.")


def test_can_report_success_gate():
    print("\n--- TEST 2: can_report_success Gate (§19, §27) ---")
    from kratos_agent.computer.browser.playwright import BrowserActionResult, can_report_success

    # Case 1: Search results state — CANNOT REPORT SUCCESS
    search_res = BrowserActionResult(
        operation="youtube_play",
        executed=True,
        verified=False,
        state="SEARCH_RESULTS",
        error="VIDEO_NOT_OPEN",
        detail="Current page is search results.",
    )
    assert can_report_success(search_res) is False, "Search results page must NEVER report success"

    # Case 2: Even if someone maliciously set verified=True on search results, gate must reject it
    fake_success = BrowserActionResult(
        operation="youtube_play",
        executed=True,
        verified=True,
        state="SEARCH_RESULTS",
    )
    assert can_report_success(fake_success) is False, "SEARCH_RESULTS state must NOT pass termination gate"

    # Case 3: Video page open but playback not started
    unstarted = BrowserActionResult(
        operation="youtube_play",
        executed=True,
        verified=False,
        state="VIDEO_PAGE",
        error="PLAYBACK_NOT_STARTED",
    )
    assert can_report_success(unstarted) is False, "VIDEO_PAGE without playback must NOT pass termination gate"

    # Case 4: Video actually playing with physical verification
    real_play = BrowserActionResult(
        operation="youtube_play",
        executed=True,
        verified=True,
        state="VIDEO_PLAYING",
        evidence={"url": "https://www.youtube.com/watch?v=123", "current_time": 1.5},
    )
    assert can_report_success(real_play) is True, "VIDEO_PLAYING with verified evidence MUST pass termination gate"
    print("✓ can_report_success termination gate strictly enforced.")


def test_watch_id_resolution():
    print("\n--- TEST 3: Direct YouTube Watch ID Resolution (§15) ---")
    from kratos_agent.computer.browser.playwright import fetch_first_youtube_watch_id
    watch_id = fetch_first_youtube_watch_id("god of war walkthrough")
    print(f"Resolved watch ID for 'god of war walkthrough': {watch_id}")
    assert watch_id is not None, "Should resolve a valid YouTube watch ID"
    assert len(watch_id) == 11, "YouTube video IDs are 11 characters"
    print("✓ YouTube watch ID resolved without creating search tabs.")


if __name__ == "__main__":
    print("Running Evidence-Based YouTube Verification Tests...")
    test_intent_parsing()
    test_can_report_success_gate()
    test_watch_id_resolution()
    print("\n==========================================")
    print("ALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("==========================================")
