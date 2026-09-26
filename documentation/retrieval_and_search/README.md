# Subsystem: Search Fabric, Retrieval & Semantic Understanding
## Packages: `kratos_agent.search`, `kratos_agent.retrieval`, `kratos_agent.semantic`, `kratos_agent.vision`

Source Directories:
- [`src/kratos_agent/search/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/search/)
- [`src/kratos_agent/retrieval/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/retrieval/)
- [`src/kratos_agent/semantic/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/semantic/)
- [`src/kratos_agent/vision/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/vision/)

---

### 1. Architectural Purpose & Overview

This combined subsystem equips Kratos with multi-source external information gathering, contextual retrieval, semantic intent understanding, and visual grounding:
- **Unified Search Fabric (`search`)**: Multi-provider search routing (DuckDuckGo, SearXNG, Tavily, GitHub API) with automated web scraping and citation generation.
- **Retrieval Engine (`retrieval`)**: Hybrid dense/sparse indexing for workspace documentation and codebase search.
- **Semantic Understanding (`semantic`)**: Classifies user queries into discrete operational intents and structures unformatted inputs.
- **Vision Grounding (`vision`)**: Resolves coordinates and semantic anchors from screenshots and UI images.

---

### 2. Core Modules & Key Classes

#### Search Fabric (`kratos_agent.search`)
- **[`agent_search.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/search/agent_search.py)**:
  - Agent-level search coordinator that breaks queries into sub-queries, executes parallel searches, extracts page content, and synthesizes answers with citations.
- **[`hybrid.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/search/hybrid.py)**:
  - Merges keyword-based BM25 scoring with vector embeddings for high-precision document recall.
- **[`extraction.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/search/extraction.py)**:
  - Strips HTML boilerplate, navigation menus, and scripts from web pages using `trafilatura` / `BeautifulSoup` to return clean markdown text.

#### Semantic Analysis (`kratos_agent.semantic`)
- **[`intent.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/semantic/intent.py): `IntentClassifier`**:
  - Classifies user requests into high-level categories: `CODE_MODIFICATION`, `TERMINAL_EXECUTION`, `RESEARCH_QUERY`, `DESKTOP_ACTION`, or `CONVERSATIONAL`.
  - Determines if the agent should activate Sovereign mode or prompt for supervision.

#### Vision Grounding (`kratos_agent.vision`)
- **[`grounding.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/vision/grounding.py)**:
  - Correlates visual bounding boxes from screenshots with accessibility tree nodes to resolve ambiguous UI controls.
