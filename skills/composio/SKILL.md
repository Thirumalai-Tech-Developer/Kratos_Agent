---
name: composio
description: Discover and use user-connected app tools through Composio Connect with clear authorization for external side effects.
tags: composio, apps, mcp, oauth, integrations, external-actions
---

# Use connected apps

Use only when the Composio MCP tools are present and the user requests an action involving a connected app.

1. Find the narrowest matching app tool and inspect its complete schema before calling it.
2. If the app is not connected, use the Composio connection flow and show the user the authorization step. Do not ask for or print passwords, tokens, or API keys in chat.
3. Confirm the exact target and content for messages, posts, invitations, financial actions, deletions, or account changes. A request to draft does not authorize sending.
4. Execute only the requested action. Do not explore unrelated records or apps.
5. Verify the result from the tool response or destination state, and distinguish success from a pending OAuth flow or queued action.

Composio is an external app bridge, not a model provider. Keep reasoning on Kratos and follow Kratos's approval and risk policies for every action.
