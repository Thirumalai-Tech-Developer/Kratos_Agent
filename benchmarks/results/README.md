# Terminal-Bench 4.0.0 status

Harbor resolves all three selected tasks and starts the isolated container.
Across the recorded runs there were 10 trial starts: three failed on an adapter
import bug before inference, six reached the model request and were rejected
because OmniRoute returned HTTP 401 (Invalid API key), and one was interrupted
without a verifier result. No task received a valid verifier score.

The corrected authentication-error handler reduced the observed error path
from 177 seconds to 63 seconds by avoiding retries of the same invalid token.
These are error-path timings, not agent task-solving results. The latest run
confirms the configured key is still rejected; the benchmark cannot measure
Kratos performance until a valid key is configured.

See [the machine-readable status](terminal-bench-4.0.0-kratos.json). It has no
score and must not be presented as benchmark performance. Once the OmniRoute
credential is fixed, use the command in the parent README to run the pilot.
