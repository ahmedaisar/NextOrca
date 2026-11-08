# Streaming Provider Responses

The normalized provider contract still supports ordinary request/response providers. Providers may additionally implement stream_complete and yield ProviderStreamChunk values.

A stream emits zero or more text deltas followed by exactly one final AssistantTurn. Tool-call argument fragments are buffered and parsed before the final turn is returned, so the runtime only executes complete, schema-validated calls. If a stream ends without a final turn or contains malformed tool arguments, the provider request fails.

The OpenAI Chat Completions adapter consumes Server-Sent Events. HybridRouter preserves the same local/cloud decision policy and may fall back from an unavailable local provider only if no stream output has been emitted. Once partial text has reached the terminal, it does not silently switch providers mid-answer.

The interactive CLI prints text deltas as they arrive and prints tool activity separately. Providers without streaming support continue to use complete() and display their final response normally.
