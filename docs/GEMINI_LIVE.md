# Gemini Live speech output

Gemini Live is an optional text-to-speech transport. Kratos is the only reasoning model and the only component allowed to choose or execute tools.

## Data boundary

```text
Local System.Speech -> text -> Kratos agent -> screen response
                                      `-> [[speak]] phrase [[/speak]] -> Gemini audio
```

The Live connection is configured for audio output only. It declares no tools, accepts no microphone transcription, and has no send path for audio or video frames. Unexpected tool-call events are ignored. Screen/camera captures stay local until an explicit Kratos vision request sends the image through the configured Kratos model.

Only a valid paired `[[speak]]...[[/speak]]` segment may be voiced. Markers are removed from visible text, malformed directives fail closed, and speech text is sanitized before delivery. The same approved phrase is sent to the OpenPets speech bubble when available. Event narration and unmarked final replies are disabled.

## Configuration

- `GEMINI_API_KEY` or `GOOGLE_API_KEY`: optional Live speech credentials.
- `KRATOS_LIVE_MODEL`: Gemini Live speech model ID.
- `KRATOS_LIVE_VOICE`: voice preset; defaults to `Zephyr`.
- `KRATOS_LIVE_ENABLED`: set to `false` to disable speech input/output integration.

Speech recognition runs locally with Windows System.Speech. If Gemini is disconnected or not configured, Kratos keeps its response on screen and can speak marked phrases with Windows SAPI. This failure does not change the Kratos task result.

## Runtime health

`LiveRuntime` starts the local recognizer and speaker output. It starts a Gemini connection only when credentials are available. The connection retries in the background with bounded backoff. The CLI `/live status` shows connection and component health; `/live reconnect` restarts the output session.
