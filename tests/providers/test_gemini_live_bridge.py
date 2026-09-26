"""Tests for GeminiLiveBridge, task delegation, visual context, and fault isolation."""

import pytest
from kratos_agent.providers.gemini_live_bridge import (
    GeminiLiveBridge,
    VisualSource,
)
from kratos_agent.providers.mock import MockProvider
from kratos_agent.providers.registry import ProviderRegistry
from kratos_agent.providers.router import ProviderRouter


@pytest.mark.asyncio
async def test_live_bridge_task_delegation(tmp_path):
    reg = ProviderRegistry()
    reg.register_provider(MockProvider(name="mock_worker", response_text="Worker completed task."))
    router = ProviderRouter(registry=reg, workspace_root=tmp_path)

    bridge = GeminiLiveBridge(router=router)

    res = await bridge.delegate_task(
        task_description="Inspect database schema and fix query",
        session_id="live-session-1",
        requested_provider="mock_worker",
    )

    assert res["status"] == "success"
    assert "Worker completed task" in res["output"]


@pytest.mark.asyncio
async def test_live_bridge_visual_context_sampling(tmp_path):
    reg = ProviderRegistry()
    reg.register_provider(MockProvider(name="mock_worker"))
    router = ProviderRouter(registry=reg, workspace_root=tmp_path)

    # Mock screen capture returning an object with width and height
    class MockFrame:
        width = 1920
        height = 1080

    bridge = GeminiLiveBridge(
        router=router,
        screen_capture_fn=lambda: MockFrame(),
    )

    snapshot = await bridge.capture_visual_context(VisualSource.SCREEN, force=True)
    assert snapshot is not None
    assert snapshot.source == VisualSource.SCREEN
    assert snapshot.width == 1920
    assert snapshot.height == 1080


@pytest.mark.asyncio
async def test_live_bridge_fault_isolation(tmp_path):
    reg = ProviderRegistry()
    reg.register_provider(MockProvider(name="mock_worker", response_text="Success despite broken camera."))
    router = ProviderRouter(registry=reg, workspace_root=tmp_path)

    # Broken camera that raises an error
    def failing_camera():
        raise RuntimeError("Camera disconnected or busy")

    bridge = GeminiLiveBridge(
        router=router,
        camera_capture_fn=failing_camera,
    )

    # Camera failure must be captured gracefully without raising
    snap = await bridge.capture_visual_context(VisualSource.CAMERA)
    assert snap is None

    # Core delegation must continue to succeed!
    res = await bridge.delegate_task(
        task_description="Fix CSS styling",
        session_id="live-session-fault",
        visual_source="camera",
        requested_provider="mock_worker",
    )
    assert res["status"] == "success"
