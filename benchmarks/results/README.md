# Latest benchmark attempt

The Terminal-Bench 4.0.0 run is currently **not run**. The Kratos Harbor
adapter imports and passes Harbor's agent preflight, and Harbor's metadata-only
dry-run resolves all three selected tasks. Docker is available, but no task
attempts have started because a minimal chat request to the configured OmniRoute
model was rejected upstream as an invalid token. The model-list endpoint alone
was not sufficient to validate chat access.

See [the machine-readable status](terminal-bench-4.0.0-preflight.json). It has
no score and must not be presented as benchmark performance. Once Docker is
running and the OmniRoute credential is corrected, use the command in the
parent README to run the pinned three-task pilot.
