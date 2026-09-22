# Computer Use Security Policy

## 1. Privileged & Destructive Actions
All privileged or destructive computer operations are audited and governed by Kratos approval policies:
* Process termination
* File deletion outside workspace
* System power operations
* OS registry modifications
* Elevated administrator commands

## 2. Invariant Inviolability
Kratos strictly prevents actions that attempt to:
* Terminate Kratos itself (`taskkill /f /im kratos`, `killall kratos`)
* Format storage volumes (`format c:`, `mkfs`)
* Delete root operating system directories (`rm -rf /`, `del /s /q c:\windows`)
* Overwrite or erase audit trails and checkpoints

## 3. Boundary Respect
Kratos detects and respects OS permission boundaries (UAC, sudo, authentication prompts) and will never bypass operating system security models.
