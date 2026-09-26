"""PowerShell CLIXML parser and terminal output normalizer."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from kratos_agent.system.shell.base import CommandResult

CLIXML_HEADER = "#< CLIXML"
PROGRESS_PATTERN = re.compile(r"<Obj S=\"progress\".*?</Obj>", re.DOTALL)


def parse_clixml(raw_xml: str) -> str:
    """Parses PowerShell CLIXML stream and extracts human-readable text."""
    # Strip progress records completely (§35)
    cleaned_xml = PROGRESS_PATTERN.sub("", raw_xml)

    # Decode common PowerShell hex character escapes (_x000D__x000A_ -> newline)
    cleaned_xml = re.sub(r"_x000D__x000A_", "\n", cleaned_xml)
    cleaned_xml = re.sub(r"_x000A_", "\n", cleaned_xml)
    cleaned_xml = re.sub(r"_x0009_", "\t", cleaned_xml)
    cleaned_xml = re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), cleaned_xml)

    # Extract all text inside <S S="Error"> or <ToString> or <S> elements
    extracted_lines = []
    try:
        # Wrap or find root if needed
        root_start = cleaned_xml.find("<Objs")
        if root_start >= 0:
            xml_body = cleaned_xml[root_start:]
            root = ET.fromstring(xml_body)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag in ("S", "ToString", "Obj") and elem.text:
                    t = elem.text.strip()
                    if t and t not in extracted_lines:
                        extracted_lines.append(t)
    except Exception:
        # Fallback regex extraction if XML is incomplete/malformed
        error_matches = re.findall(r'<S S="Error">(.*?)</S>', cleaned_xml, re.DOTALL)
        if error_matches:
            extracted_lines.extend(error_matches)
        else:
            # Strip tags directly
            stripped = re.sub(r"<[^>]+>", "", cleaned_xml).strip()
            if stripped:
                extracted_lines.append(stripped)

    return "\n".join(extracted_lines).strip()


def normalize_command_output(raw_output: str, exit_code: int = 0) -> CommandResult:
    """Normalizes raw subprocess output, stripping CLIXML and progress markers (§34, §35)."""
    text = raw_output or ""

    is_clixml = CLIXML_HEADER in text or "<Objs Version=" in text
    if is_clixml:
        header_idx = text.find(CLIXML_HEADER)
        if header_idx >= 0:
            prefix = text[:header_idx].strip()
            xml_part = text[header_idx + len(CLIXML_HEADER):]
            parsed_err = parse_clixml(xml_part)
            clean_text = f"{prefix}\n{parsed_err}".strip() if prefix else parsed_err
        else:
            clean_text = parse_clixml(text)

        error_type = "SHELL_PARSE_ERROR" if "not a valid statement separator" in clean_text else None
        return CommandResult(
            success=(exit_code == 0 and not clean_text),
            stdout="" if exit_code != 0 else clean_text,
            stderr=clean_text if exit_code != 0 else "",
            exit_code=exit_code,
            error_type=error_type,
        )

    # Standard non-XML output
    # Filter any accidental progress XML fragments
    clean_text = PROGRESS_PATTERN.sub("", text).strip()

    return CommandResult(
        success=(exit_code == 0),
        stdout=clean_text if exit_code == 0 else "",
        stderr=clean_text if exit_code != 0 else "",
        exit_code=exit_code,
    )
