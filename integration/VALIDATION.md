# Integration validation record

The source ledger records 2,083 feature entry points across the current OmniRoute snapshot. An included file or route is not a validated user workflow. The table below records executed checks, with unresolved work listed explicitly.

| Area | Executed check | Result |
| --- | --- | --- |
| Kratos Python runtime | Full Python 3.12 suite before final Headroom fix | 434 passed, 1 failed, 1 skipped. The Headroom failure was fixed; its 14 focused tests then passed. |
| Gateway stream safety | SDK and web contract tests, including a real silent SSE server and cancellation | 10 stream contract tests passed; cancellation released the blocked reader. |
| Data migration | Snapshot of the user's current OmniRoute data into a separate test directory | SQLite `quick_check` passed; 135 tables present; source encryption key preserved; rollback and restore rehearsal passed. |
| Shared launcher | Isolated fresh and imported stores on separate loopback ports, then the imported default store on ports 20128/7860 | Both services reached readiness in all three cases; original source checkouts and data remained untouched. |
| Browser | Fresh Studio login, Kratos navigation, embedded console and MCP management page | Rendered through the production authenticated proxy. Kratos console showed Ready and MCP page showed connected server statuses. |
| Gateway build | Production Next build and standalone assembly | Final build passed after the MCP custom-port fix; the packaged MCP page displayed the active port and connected server statuses. |
| Focused OmniRoute integrations | Responses fallback, webhooks, rate reservations, Kratos proxy | Focused tests passed; see `WORK_LOG.md`. |
| Broad OmniRoute unit suite | `npm run test:unit:ci` | Stopped after 729 passing markers and 5 failure markers. Adobe Firefly route tests opened a browser-backed provider session despite mocked fetch; further broad runs need a strict offline test boundary. A catalog event-loop timing test also failed under concurrent build load. |

## Unverified before claiming full parity

- Every source ledger entry still needs a recorded runtime result. The imported feature surface is available, but inclusion alone does not prove every route, provider, plugin, or UI action works in Studio.
- Live provider, webhook, and paid-service calls need configured test credentials and explicit bounded checks. No production credentials are stored in this repository.
- OmniRoute plugin/skill lifecycle and agent delegation through Kratos require workflow-level verification beyond availability of their native OmniRoute pages and Kratos MCP manager.
- The imported default Studio data directory passed SQLite `quick_check` with 135 tables and the source encryption key. Its previous directory remains available as a rollback sibling.
