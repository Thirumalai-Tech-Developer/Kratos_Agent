"""DeepSeek Model Plugin - Reasoning token separation, DSML tool extraction, and hyperparameter management."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from ..plugin import HarnessPlugin, PluginMetadata

if TYPE_CHECKING:
    from ..kernel import HarnessKernel

logger = logging.getLogger(__name__)


class DeepSeekModelPlugin(HarnessPlugin):
    """Handles DeepSeek-specific reasoning patterns (<think>...</think>), DSML tool call parsing, and hyperparameters."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            metadata=PluginMetadata(
                name="deepseek_model",
                version="1.0.0",
                description="Specialized adapter for DeepSeek-V3 and DeepSeek-R1 reasoning and DSML format.",
                category="model",
            ),
            config=config,
        )
        self.temperature: float = 0.5
        self.max_tokens: int = 8192
        self.thinking_enabled: bool = True

    def on_load(self, kernel: HarnessKernel) -> None:
        super().on_load(kernel)
        kernel.register_service("deepseek_model", self)

    def on_unload(self) -> None:
        if self.kernel:
            self.kernel.unregister_service("deepseek_model")
        super().on_unload()

    def apply_preset(self, preset_name: str, config: dict[str, Any]) -> None:
        """Update model hyperparameters based on preset."""
        super().apply_preset(preset_name, config)
        if "temperature" in config:
            self.temperature = float(config["temperature"])
        if "max_tokens" in config:
            self.max_tokens = int(config["max_tokens"])
        if "thinking_enabled" in config:
            self.thinking_enabled = bool(config["thinking_enabled"])

    @staticmethod
    def extract_reasoning_and_content(raw_text: str) -> tuple[str, str]:
        """Extract reasoning from <think>...</think> blocks and return (reasoning, clean_content)."""
        if not raw_text:
            return "", ""

        think_pattern = re.compile(r"<think>(.*?)(?:</think>|$)", re.DOTALL | re.IGNORECASE)
        matches = think_pattern.findall(raw_text)

        reasoning = "\n\n".join(m.strip() for m in matches if m.strip())
        cleaned_content = think_pattern.sub("", raw_text).strip()

        return reasoning, cleaned_content

    @staticmethod
    def extract_dsml_tool_calls(raw_text: str) -> list[dict[str, Any]]:
        """Parse DSML formatted tool invocations:
        <tool>{"name": "...", "arguments": {...}}</｜｜DSML｜｜ parameter>
        or standard <tool>...</tool> blocks.
        """
        if not raw_text:
            return []

        tool_calls: list[dict[str, Any]] = []

        # 1. DSML XML-style invoke syntax:
        # <｜｜DSML｜｜ invoke name="...">...<｜｜DSML｜｜ parameter name="...">...</｜｜DSML｜｜ parameter></｜｜DSML｜｜ invoke>
        dsml_invoke_pattern = re.compile(
            r'<[｜|]{1,2}DSML[｜|]{1,2}\s*invoke\s+name=["\']?([a-zA-Z0-9_]+)["\']?\s*>([\s\S]*?)(?:</[｜|]{1,2}DSML[｜|]{1,2}\s*invoke>|(?=<[｜|]{1,2}DSML[｜|]{1,2}\s*invoke)|$)',
            re.IGNORECASE,
        )
        dsml_param_pattern = re.compile(
            r'<[｜|]{1,2}DSML[｜|]{1,2}\s*parameter\s+name=["\']?([a-zA-Z0-9_]+)["\']?[^>]*>([\s\S]*?)(?:</[｜|]{1,2}DSML[｜|]{1,2}\s*parameter>|(?=<[｜|]{1,2}DSML[｜|]{1,2}\s*parameter)|(?=</[｜|]{1,2}DSML[｜|]{1,2}\s*invoke>)|$)',
            re.IGNORECASE,
        )
        for m in dsml_invoke_pattern.finditer(raw_text):
            tool_name = m.group(1)
            body = m.group(2)
            args = {}
            for p in dsml_param_pattern.finditer(body):
                p_name = p.group(1)
                p_val = p.group(2).strip()
                try:
                    p_val = json.loads(p_val)
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)
                args[p_name] = p_val
            tool_calls.append({"name": tool_name, "arguments": args})

        # 1b. DSML JSON-style payload syntax:
        dsml_pattern = re.compile(
            r"<tool>(.*?)(?:</[｜\|]{2}DSML[｜\|]{2}\s*parameter>|\s*</tool>)",
            re.DOTALL | re.IGNORECASE,
        )

        for match in dsml_pattern.finditer(raw_text):
            payload_str = match.group(1).strip()
            payload_str = re.sub(r"</[｜\|]{2}DSML[｜\|]{2}\s*invoke>", "", payload_str).strip()

            try:
                data = json.loads(payload_str)
                if isinstance(data, dict) and "name" in data:
                    tool_calls.append({
                        "name": data["name"],
                        "arguments": data.get("arguments", {}),
                    })
            except Exception:
                sub_match = re.search(r"\{.*\}", payload_str, re.DOTALL)
                if sub_match:
                    try:
                        data = json.loads(sub_match.group(0))
                        if isinstance(data, dict) and "name" in data:
                            tool_calls.append({
                                "name": data["name"],
                                "arguments": data.get("arguments", {}),
                            })
                    except Exception as exc:
                        logger.debug("Operation error suppressed: %s", exc)

        # 2. <|tool calls|> or <｜tool calls｜> blocks
        tc_block_pattern = re.compile(
            r"<[｜\|]tool calls[｜\|]>(.*?)(?:<[｜\|]/tool calls[｜\|]>|$)",
            re.DOTALL | re.IGNORECASE,
        )
        for block_match in tc_block_pattern.finditer(raw_text):
            block_text = block_match.group(1)
            for json_match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", block_text):
                try:
                    data = json.loads(json_match.group(0))
                    if isinstance(data, dict) and "name" in data:
                        tool_calls.append({
                            "name": data["name"],
                            "arguments": data.get("arguments", {}),
                        })
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

        # Deduplicate while preserving order
        unique_calls: list[dict[str, Any]] = []
        seen = set()
        for call in tool_calls:
            sig = (call["name"], json.dumps(call.get("arguments", {}), sort_keys=True))
            if sig not in seen:
                seen.add(sig)
                unique_calls.append(call)

        return unique_calls

    def parse_model_output(self, raw_text: str) -> dict[str, Any]:
        """Comprehensive parsing of model output into reasoning, clean content, and tool calls."""
        reasoning, content = self.extract_reasoning_and_content(raw_text)
        tool_calls = self.extract_dsml_tool_calls(raw_text)

        # Remove tool call blocks from content for clean user-facing response
        clean_content = re.sub(
            r"<[｜|]{1,2}DSML[｜|]{1,2}\s*invoke[\s\S]*?</[｜|]{1,2}DSML[｜|]{1,2}\s*invoke>",
            "",
            content,
            flags=re.IGNORECASE,
        )
        clean_content = re.sub(
            r"</?[｜|]{1,2}DSML[｜|]{1,2}\s*calls>",
            "",
            clean_content,
            flags=re.IGNORECASE,
        )
        clean_content = re.sub(
            r"<tool>.*?(?:</[｜\|]{2}DSML[｜\|]{2}\s*parameter>|\s*</tool>)",
            "",
            clean_content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        clean_content = re.sub(
            r"</[｜\|]{2}DSML[｜\|]{2}\s*invoke>",
            "",
            clean_content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        clean_content = re.sub(
            r"<[｜\|]tool calls[｜\|]>.*?(?:<[｜\|]/tool calls[｜\|]>|$)",
            "",
            clean_content,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()

        result = {
            "reasoning": reasoning,
            "content": clean_content,
            "tool_calls": tool_calls,
            "raw": raw_text,
        }

        if self.kernel:
            self.kernel.emit("model_output_parsed", **result)

        return result
