"""Explicit workspace model choices, validated against the gateway catalog."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from kratos_agent.brain.config import get_model_catalog
from kratos_agent.brain.client import BrainClient
from kratos_agent.core.context_pipeline import ContextBudget
from kratos_agent.core.model_adapter import KratosModelAdapter

logger = logging.getLogger(__name__)
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~\-]{0,511}\Z")


class ModelSelectionBusy(RuntimeError):
    """A model cannot change while a turn is running."""


def validate_model_id(model: Any) -> str:
    if not isinstance(model, str) or not _MODEL_ID.fullmatch(model):
        raise ValueError("Provide a valid model ID from the gateway catalog.")
    return model


def read_selected_model(workspace: Path) -> str | None:
    try:
        payload = json.loads((workspace / ".kratos/model-selection.json").read_text(encoding="utf-8"))
        return validate_model_id(payload.get("model")) if isinstance(payload, dict) else None
    except (OSError, ValueError):
        return None


def _save_selected_model(workspace: Path, model: str) -> None:
    path = workspace / ".kratos/model-selection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="model-selection-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump({"model": model}, output)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def select_runtime_model(runtime: Any, model: str) -> None:
    """Change every runtime consumer together after a deliberate, advertised choice."""
    model = validate_model_id(model)
    if not runtime._turn_lock.acquire(blocking=False):
        raise ModelSelectionBusy("Wait for the active task before changing models.")
    try:
        catalog = get_model_catalog(timeout=5.0, refresh=True, strict=True)
        metadata = next((entry for entry in catalog if entry["id"] == model
                         and entry.get("metadata_available")), None)
        if metadata is None:
            raise ValueError("This model is not advertised by the gateway. Refresh the model list.")
        if metadata.get("available") is False:
            raise ValueError(str(metadata.get("disabled_reason") or "This model is currently unavailable."))

        # Construct the replacement before touching the current loop or persisted choice.
        brain = BrainClient()
        settings = runtime.generation_settings.status(model, metadata)
        brain.generation_model = model
        brain.generation_options = settings["options"]
        adapter = KratosModelAdapter(model, brain)
        try:
            _save_selected_model(runtime.workspace, model)
        except OSError:
            brain.session.close()
            raise

        previous_brain = runtime.brain
        os.environ["KRATOS_MODEL"] = model  # The SDK enforces the explicitly selected ID.
        runtime.model_name = model
        runtime.brain = brain
        runtime.model = adapter
        runtime.loop.model = adapter
        # Restore baseline limits before applying the new model's capabilities.
        runtime.context.budget = ContextBudget()
        runtime.apply_model_metadata(metadata)
        runtime.loop.inspection_limit = settings["inspection_limit"]
        session = runtime.memory.active_session
        if session is not None:
            session.model = model
            try:
                runtime.memory.save()
            except OSError:
                logger.warning("Model choice saved, but session metadata could not be written.")
        harness = getattr(runtime, "harness", None)
        headroom = harness.get_plugin("headroom") if harness else None
        if headroom is not None:
            headroom.set_model(model)
        try:
            previous_brain.session.close()
        except Exception:
            logger.debug("Could not close the previous model connection.")
    finally:
        runtime._turn_lock.release()
