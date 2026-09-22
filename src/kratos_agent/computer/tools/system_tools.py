"""System and filesystem computer tools."""
from __future__ import annotations
import json
from typing import Any, Dict, List, Optional

from kratos_agent.computer.filesystem.files import get_filesystem_engine
from kratos_agent.computer.apps.processes import get_process_manager


def computer_file_list(path: str = ".", recursive: bool = False, max_items: int = 100) -> str:
    """Lists files and folders with size and modification timestamp."""
    fs = get_filesystem_engine()
    res = fs.list_files(path=path, recursive=recursive, max_items=max_items)
    return json.dumps(res, indent=2)


def computer_file_read(path: str, max_bytes: int = 1048576) -> str:
    """Reads text content from a file."""
    fs = get_filesystem_engine()
    return fs.read_file(path=path, max_bytes=max_bytes)


def computer_file_write(path: str, content: str, overwrite: bool = True) -> str:
    """Writes text content to a file."""
    fs = get_filesystem_engine()
    res = fs.write_file(path=path, content=content, overwrite=overwrite)
    return json.dumps(res.to_dict(), indent=2)


def computer_file_move(src: str, dst: str) -> str:
    """Moves or renames a file or directory."""
    fs = get_filesystem_engine()
    res = fs.move_file(src=src, dst=dst)
    return json.dumps(res.to_dict(), indent=2)


def computer_file_copy(src: str, dst: str) -> str:
    """Copies a file or directory."""
    fs = get_filesystem_engine()
    res = fs.copy_file(src=src, dst=dst)
    return json.dumps(res.to_dict(), indent=2)


def computer_file_delete(path: str) -> str:
    """Deletes a file or directory."""
    fs = get_filesystem_engine()
    res = fs.delete_file(path=path)
    return json.dumps(res.to_dict(), indent=2)


def computer_process_list(filter: Optional[str] = None, limit: int = 50) -> str:
    """Lists running processes with CPU and memory usage."""
    pm = get_process_manager()
    res = pm.list_processes(filter_query=filter, limit=limit)
    return json.dumps(res, indent=2)
