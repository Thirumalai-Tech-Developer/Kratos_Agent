"""Workspace model choices validated against gateway and browser connections."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from kratos_agent.brain.client import BrainClient
from kratos_agent.brain.config import DEFAULT_BASE_URL
from kratos_agent.brain.config import get_runtime_model_catalog as get_model_catalog
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
    selection = read_selected_connection(workspace)
    return selection.get("model") if selection else None


def read_selected_connection(workspace: Path) -> dict | None:
    try:
        payload = json.loads((workspace / ".kratos/model-selection.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        validate_model_id(payload.get("model"))
        provider = payload.get("provider", "gateway")
        if provider not in {"gateway", "chatgpt", "chatgpt-web", "browser-web"}:
            return None
        account_id = payload.get("account_id", "")
        if not isinstance(account_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{0,128}", account_id):
            return None
        return {"model": payload["model"], "provider": provider, "account_id": account_id}
    except (OSError, ValueError):
        return None


def _save_selected_model(workspace: Path, model: str, *, provider: str = "gateway", account_id: str = "") -> None:
    path = workspace / ".kratos/model-selection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="model-selection-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump({"model": model, "provider": provider, "account_id": account_id}, output)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def select_runtime_model(runtime: Any, model: str, connection: str | None = None) -> None:
    """Change every runtime consumer together after a deliberate, advertised choice."""
    model = validate_model_id(model)
    if not runtime._turn_lock.acquire(blocking=False):
        raise ModelSelectionBusy("Wait for the active task before changing models.")
    try:
        catalog = get_model_catalog(timeout=15.0, refresh=False, strict=True,
                                    cache_path=runtime.workspace / ".kratos" / "gateway-model-catalog.json")
        matches = [entry for entry in catalog if entry["id"] == model and entry.get("metadata_available")
                   and (connection is None or entry.get("selection_key") == connection)]
        metadata = next((entry for entry in matches if entry.get("is_configured")), None)
        metadata = metadata or (matches[0] if matches else None)
        if metadata is None:
            raise ValueError("This model connection is not in the catalog. Refresh the model list.")
        if metadata.get("available") is False:
            raise ValueError(str(metadata.get("disabled_reason") or "This model is currently unavailable."))

        # Construct the replacement before touching the current loop or persisted choice.
        provider = metadata.get("connection_provider", "gateway")
        account_id = metadata.get("connection_account_id", "")
        base = (os.getenv("KRATOS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        endpoint = (os.getenv("KRATOS_CHAT_ENDPOINT") or
                    (base if base.endswith("/chat/completions") else base + "/chat/completions"))
        brain = BrainClient(endpoint if provider == "gateway" else None, provider=provider,
                            account_id=account_id, configured_model=model)
        settings = runtime.generation_settings.status(model, metadata)
        brain.generation_model = model
        brain.generation_options = settings["options"]
        adapter = KratosModelAdapter(model, brain)
        try:
            _save_selected_model(runtime.workspace, model, provider=provider, account_id=account_id)
        except OSError:
            brain.session.close()
            raise

        previous_brain = runtime.brain
        os.environ["KRATOS_MODEL"] = model  # The SDK enforces the explicitly selected ID.
        os.environ["KRATOS_MODEL_PROVIDER"] = provider
        os.environ["KRATOS_RUNTIME_MODEL"] = model
        os.environ["KRATOS_RUNTIME_ACCOUNT_ID"] = account_id
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
        except Exception:  # noqa: BLE001 -- Closing an obsolete session must not revert a successful choice.
            logger.debug("Could not close the previous model connection.")
    finally:
        runtime._turn_lock.release()
