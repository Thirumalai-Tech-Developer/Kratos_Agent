from __future__ import annotations

import asyncio
import json
from typing import Any, Dict


class WhatsAppExecutor:
    capability = "whatsapp.send_message"

    async def execute(self, contact: str, message: str) -> Dict[str, Any]:
        from kratos_agent.utils.computer_tools import browser_whatsapp_send_message
        raw = await asyncio.get_running_loop().run_in_executor(
            None, browser_whatsapp_send_message, contact, message, True, 30.0
        )
        try:
            return json.loads(raw)
        except Exception:
            return {"ok": False, "verified": False, "detail": raw}
