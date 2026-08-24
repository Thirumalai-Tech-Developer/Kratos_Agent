<!--
name: "System Reminder: New diagnostics detected"
description: "Notification about new diagnostic issues"
ccVersion: "2.1.122"
variables:
  - "DIAGNOSTICS_TRACKER_CLASS"
  - "DIAGNOSTICS_LIST"
-->
<new-diagnostics>The following new diagnostic issues were detected:

${DIAGNOSTICS_TRACKER_CLASS.formatDiagnosticsSummary(DIAGNOSTICS_LIST)}</new-diagnostics>
