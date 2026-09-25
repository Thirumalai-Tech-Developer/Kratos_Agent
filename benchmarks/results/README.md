# Terminal-Bench 4.0.0 status

Harbor now resolves the three selected tasks and starts the isolated container.
Three early trials failed on a Kratos adapter import bug before model inference;
that bug is fixed. Two corrected trials reached Kratos's model request, but
OmniRoute returned HTTP 502 because the upstream provider rejected the
configured token as invalid. No task received a valid verifier score.

The corrected authentication-error handler reduced the observed error path
from 177 seconds to 63 seconds by avoiding retries of the same invalid token.
This is an error-recovery timing, not an agent task-solving result.

See [the machine-readable status](terminal-bench-4.0.0-kratos.json). It has no
score and must not be presented as benchmark performance. Once the OmniRoute
credential is fixed, use the command in the parent README to run the pilot.
