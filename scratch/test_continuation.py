"""Comprehensive automated tests for Kratos Continuation Patch."""
import sys
import time
from typing import Dict, Any

def test_browser_target():
    print("\n--- TEST 1: BrowserTarget & Manager Persistence ---")
    from kratos_agent.computer.browser.target import BrowserTarget, get_target_manager, log_browser_target
    mgr = get_target_manager()
    mgr.clear_target()
    assert mgr.get_active_target() is None, "Target should be None after clear"

    # Command 1: open youtube
    target1 = BrowserTarget(
        browser_pid=1234,
        window_handle=56789,
        url="https://www.youtube.com",
        title="YouTube",
        created_by_kratos=False,
        user_selected=False,
        last_verified=time.time(),
        browser_name="chrome",
        foreground=True,
    )
    mgr.set_active_target(target1)
    retrieved1 = mgr.get_active_target()
    assert retrieved1 is not None
    assert retrieved1.url == "https://www.youtube.com"
    assert retrieved1.window_handle == 56789
    assert retrieved1.browser_pid == 1234
    assert retrieved1.user_selected is False
    assert retrieved1.last_verified is not None

    # Command 2: play GTA Vice City walkthrough (reuse same target)
    retrieved2 = mgr.get_active_target()
    assert retrieved2 is not None
    assert retrieved2.window_handle == 56789, "Must reuse same window handle"
    mgr.update_target(
        url="https://www.youtube.com/watch?v=GTA123",
        title="GTA Vice City Walkthrough - YouTube",
        last_verified=time.time(),
    )
    assert mgr.get_active_target().url == "https://www.youtube.com/watch?v=GTA123"
    print("✓ BrowserTarget persistence verified across sequential commands.")


def test_policies():
    print("\n--- TEST 2: BrowserTaskPolicy & GuiExecutionPolicy Defaults ---")
    from kratos_agent.computer.browser.manager import BrowserTaskPolicy, GuiExecutionPolicy
    btp = BrowserTaskPolicy()
    assert btp.reuse_browser is True
    assert btp.reuse_window is True
    assert btp.reuse_tab is True
    assert btp.allow_new_window is False
    assert btp.allow_new_tab is False

    gep = GuiExecutionPolicy()
    assert gep.require_foreground is True
    assert gep.require_visible_window is True
    assert gep.verify_focus is True
    assert gep.verify_after_action is True
    print("✓ Default policies enforce reuse and visible foreground interaction.")


def test_windows_and_focus():
    print("\n--- TEST 3: Windows Enumeration & Focus Controller ---")
    from kratos_agent.computer.apps.windows import enumerate_chrome_windows
    from kratos_agent.computer.apps.focus import focus_window
    wins = enumerate_chrome_windows()
    print(f"Detected {len(wins)} Chrome/Chromium windows.")
    for w in wins:
        assert "hwnd" in w
        assert "pid" in w
        assert "title" in w
        assert "visible" in w
        assert "foreground" in w

    # Test focus on dummy non-existent handle (should fail bounded in 3 attempts)
    success = focus_window(999999999)
    assert success is False, "Focusing non-existent window should return False"
    print("✓ Window enumeration and bounded focus verification working.")


def test_continuation_memory():
    print("\n--- TEST 4: ContinuationState in WorkingMemory ---")
    from kratos_agent.memory.working import WorkingMemory, ContinuationState
    from kratos_agent.computer.browser.target import BrowserTarget
    wm = WorkingMemory()
    assert wm.get_continuation() is None

    t = BrowserTarget(browser_pid=1234, window_handle=56789, url="https://www.youtube.com")
    c = ContinuationState(
        task_id="task_001",
        objective="play GTA Vice City walkthrough",
        active_browser_target=t,
        current_step="play_video",
        completed_steps=["open_youtube", "search_video"],
        verified_state={"video_playing": True},
    )
    wm.set_continuation(c)
    retrieved_c = wm.get_continuation()
    assert retrieved_c is not None
    assert retrieved_c.task_id == "task_001"
    assert retrieved_c.active_browser_target.window_handle == 56789
    assert retrieved_c.verified_state["video_playing"] is True

    # Test serialization
    d = wm.to_dict()
    assert "continuation" in d
    assert d["continuation"]["task_id"] == "task_001"

    # Reset clears continuation
    wm.reset()
    assert wm.get_continuation() is None
    print("✓ ContinuationState properly integrated into WorkingMemory.")


def test_playwright_video_methods():
    print("\n--- TEST 5: PlaywrightDriver Video Control & Diagnostics ---")
    from kratos_agent.computer.browser.playwright import PlaywrightDriver
    drv = PlaywrightDriver()
    diag = drv.diagnostics()
    assert "url" in diag
    assert "closed" in diag

    # Test pause and resume methods
    p_res = drv.pause_video()
    assert p_res.ok is True
    assert p_res.action == "video_pause"

    r_res = drv.resume_video()
    assert r_res.ok is True
    assert r_res.action == "video_resume"
    print("✓ Video pause and resume methods verified.")


def test_clear_command_target_reset():
    print("\n--- TEST 6: /clear Resets Target Without Browser Destruction ---")
    from kratos_agent.computer.browser.target import BrowserTarget, get_target_manager
    mgr = get_target_manager()
    mgr.set_active_target(BrowserTarget(browser_pid=1234, window_handle=56789, url="https://www.youtube.com"))
    assert mgr.get_active_target() is not None

    # Simulate /clear
    mgr.clear_target()
    assert mgr.get_active_target() is None
    print("✓ /clear resets active_browser_target cleanly.")


if __name__ == "__main__":
    print("Running Kratos Continuation Patch Tests...")
    test_browser_target()
    test_policies()
    test_windows_and_focus()
    test_continuation_memory()
    test_playwright_video_methods()
    test_clear_command_target_reset()
    print("\n==========================================")
    print("ALL 6 CONTINUATION TESTS PASSED SUCCESSFULLY!")
    print("==========================================")
