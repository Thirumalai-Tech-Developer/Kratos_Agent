---
name: build-web-apps
description: Build and review usable web apps across frontend behavior, backend data, accessibility, deployment, and operational readiness.
tags: web, frontend, database, deployment, accessibility, application
---

# Build and prepare web apps

Use for web app features, new web projects, UI debugging, database-backed behavior, and deployment preparation.

1. Inspect the existing framework, routes, scripts, UI conventions, data layer, and deployment target before choosing an implementation.
2. Define the user flow and visible states: loading, empty, success, validation, and failure. Reuse the project's design system and keep responsive and accessible behavior in scope.
3. For framework APIs that may have changed, use the `context7` workflow and the installed dependency version. For React or Next.js, load the existing `vercel-react-best-practices` skill when relevant.
4. Keep data access server-side where appropriate. Validate inputs at boundaries, use parameterized queries, minimize stored data, and design schema changes with safe migrations and rollback considerations.
5. For deployment, inspect the existing platform and build pipeline. Keep secrets in the platform's secret store, verify environment-variable names without printing values, and call out migrations, domains, permissions, and rollback steps.
6. Review the final UI and data flow against the requested outcome. Report what can be observed locally and what would require a deployed environment.

Use the configured Kratos model only. Do not add another model provider unless the user explicitly changes that constraint. Do not deploy, publish, or alter production data without the user's direct request and the required approval.
