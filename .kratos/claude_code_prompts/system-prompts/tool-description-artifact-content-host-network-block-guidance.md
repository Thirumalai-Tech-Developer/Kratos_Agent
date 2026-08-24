<!--
name: "Tool Description: Artifact content host network block guidance"
description: "Explains the allowlist change required when an environment blocks the Artifact content host and forbids publishing again before the live version can be read"
ccVersion: "2.1.239"
variables:
  - "CLAUDE_AI_ENVIRONMENT"
-->
This environment's network allowlist blocks the artifact content host, so the live version can be neither read nor handed over here until ${CLAUDE_AI_ENVIRONMENT==="staging"?"*.frame.staging.claudeusercontent.com":"*.frame.claudeusercontent.com"} is added at environment settings → Code → Network access → Custom → Allowed domains. An admin can add the same entry to a shared environment from admin settings → Cloud environments; sessions that run in that environment get the access. Tell the user, and publish again only once you can build on the live version.
