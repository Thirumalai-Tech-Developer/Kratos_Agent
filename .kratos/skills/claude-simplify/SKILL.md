---
name: claude-simplify
description: 4-angle codebase simplification and refactoring sweep targeting code reuse, syntactic simplification, algorithmic efficiency, and architectural altitude.
tags: simplify, refactor, clean-code, optimization, maintenance
source_url: https://github.com/Piebald-AI/claude-code-system-prompts
---

# 4-Angle Code Simplification & Refactoring Sweep

You are improving the clarity, maintainability, and efficiency of the code without breaking existing behavioral contracts or introducing regressions.

## 4 Cleanup Angles

### 1. Reuse & Deduplication
- Find repeated logic across functions, handlers, or modules.
- Extract common patterns into clean utility functions or reusable hooks/components.
- Check if standard library functions or existing project utilities can replace homegrown reimplementations.

### 2. Syntactic & Structural Simplification
- Eliminate nested `if`/`else` ladders through early returns and guard clauses.
- Remove redundant intermediate variables, dead parameters, and convoluted boolean expressions.
- Flatten deeply nested callbacks and promises into clean `async`/`await` workflows.
- Remove obsolete comments that merely restate obvious code.

### 3. Efficiency & Resource Optimization
- Replace $O(N^2)$ lookups with hash sets or map lookups ($O(1)$).
- Eliminate duplicate database/API queries or redundant file system I/O within hot paths.
- Avoid unnecessary array copies, excessive string concatenations in tight loops, and memory leaks.

### 4. Architectural Altitude & Separation of Concerns
- Ensure functions do one thing well with clear inputs and outputs.
- Separate business logic from presentation and transport protocols.
- Avoid leaky abstractions where lower-level details bleed into high-level orchestrators.

## Execution Workflow
1. **Analyze**: Gather diff or inspect target file.
2. **Review**: Identify candidates across the 4 angles with precise `file:line` locations and cost justifications.
3. **Apply**: Write optimized code using `write_file`.
4. **Verify**: Run tests or build commands via `run_terminal_command` to verify no syntax errors or regressions occurred.
