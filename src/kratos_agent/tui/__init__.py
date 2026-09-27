"""Kratos TUI — live interactive execution display package."""
from .completion_view import render_completion_card
from .highlighter import detect_language, print_code_dialog, render_code_dialog, render_markdown_code_blocks
from .live_renderer import KratosLiveRenderer

__all__ = [
    "KratosLiveRenderer",
    "render_completion_card",
    "render_code_dialog",
    "print_code_dialog",
    "render_markdown_code_blocks",
    "detect_language",
]
