<!--
name: "System Reminder: Question context"
description: "Provides potentially relevant context entries to use only when highly relevant to the current task"
ccVersion: "2.1.235"
variables:
  - "OBJECT_CONSTRUCTOR"
  - "QUESTION_CONTEXT"
  - "CONTEXT_ENTRY_TITLE"
  - "CONTEXT_ENTRY_CONTENT"
-->
<system-reminder>
As you answer the user's questions, you can use the following context:
${OBJECT_CONSTRUCTOR.entries(QUESTION_CONTEXT).map(([CONTEXT_ENTRY_TITLE,CONTEXT_ENTRY_CONTENT])=>`# ${CONTEXT_ENTRY_TITLE}
${CONTEXT_ENTRY_CONTENT}`).join(`
`)}

      IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.
</system-reminder>
