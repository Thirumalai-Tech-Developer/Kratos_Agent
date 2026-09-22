"""Long-horizon computer task planner and action decomposer."""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional

from kratos_agent.computer.state import ComputerAction, ComputerState


class ComputerPlanner:
    """Decomposes complex computer goals into ordered sequences of semantic actions."""

    def plan_task(self, goal: str, initial_state: ComputerState) -> List[ComputerAction]:
        """Decomposes user goal into a concrete plan of semantic ComputerActions."""
        actions: List[ComputerAction] = []
        g_lower = goal.lower()

        # Pattern: Launch / Open app
        m_open = re.search(r"(?:open|launch|start)\s+([a-zA-Z0-9_\-\.\s]+?)(?:$|\s+and|\s+then|\s*,)", g_lower)
        if m_open:
            app_target = m_open.group(1).strip()
            # If target is browser or specific URL
            if "youtube" in app_target or "http" in app_target or "google" in app_target:
                url = app_target if "http" in app_target else f"https://{app_target.replace(' ', '')}.com"
                actions.append(ComputerAction(action="browser_navigate", parameters={"action": "goto", "url": url}, expected_state={"url": url}))
            else:
                actions.append(ComputerAction(action="app_launch", parameters={"target": app_target}, expected_state={"process_running": app_target}))

        # Pattern: Search for query
        m_search = re.search(r"search\s+(?:for\s+)?['\"]?([^'\"]+?)['\"]?(?:$|\s+and|\s+then|\s*,)", g_lower)
        if m_search:
            q = m_search.group(1).strip()
            actions.append(ComputerAction(action="click", target={"role": "searchbox", "name": "search"}))
            actions.append(ComputerAction(action="type", parameters={"text": q}))
            actions.append(ComputerAction(action="press", parameters={"key": "enter"}))

        # Pattern: Click a target
        m_click = re.search(r"click\s+(?:on\s+)?['\"]?([^'\"]+?)['\"]?(?:$|\s+and|\s+then|\s*,)", g_lower)
        if m_click:
            target_name = m_click.group(1).strip()
            actions.append(ComputerAction(action="click", target={"name": target_name}))

        return actions
