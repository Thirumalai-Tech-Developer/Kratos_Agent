<!--
name: "Tool Description: Artifact identical resubmission refusal"
description: "Formats the Artifact publish refusal for unchanged content previously rejected against an unseen or newer live version and requires rereading and merging before retrying"
ccVersion: "2.1.239"
variables:
  - "PUBLISH_REFUSED_PREFIX"
  - "IDENTICAL_RESUBMISSION_RECORD"
-->
${PUBLISH_REFUSED_PREFIX} this is the identical content already refused ${IDENTICAL_RESUBMISSION_RECORD.live===void 0?"because you had not viewed this artifact's live version":`against the newer version ${IDENTICAL_RESUBMISSION_RECORD.live}`}, resent unchanged. Merge your edits onto ${IDENTICAL_RESUBMISSION_RECORD.live===void 0?"the live version's":"that version's"} source (handed to you or read in the turn that refused this content; if neither, re-read it first) and publish the merged result. If your content genuinely already includes that version's changes, re-read the artifact to confirm it and, once you have that read's result, publish again
