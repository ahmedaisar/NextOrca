# Local and Cloud Orchestration

NextOrca keeps one agent runtime, tool registry, session and permission policy while routing model turns between providers.

## Configure both providers

Set these environment variables:

    NEXTORCA_LOCAL_BASE_URL=http://127.0.0.1:8080/v1
    NEXTORCA_LOCAL_MODEL=your-local-model
    NEXTORCA_CLOUD_BASE_URL=https://openrouter.ai/api/v1
    NEXTORCA_CLOUD_MODEL=your-provider/cloud-model
    NEXTORCA_CLOUD_API_KEY=your-api-key

When both endpoint variables are set and NEXTORCA_ROUTE_MODE is not explicitly set, the CLI defaults to auto routing. Explicit CLI flags and NEXTORCA_ROUTE_MODE still override the default.

## Interactive controls

- /route status — show route mode and configured models.
- /route auto — use task-aware routing.
- /route local — force the local provider.
- /route cloud — force the cloud provider.
- /privacy status — show the privacy mode.
- /privacy local-only — require local inference and disable cloud fallback.
- /privacy balanced — allow the configured routing policy.

Changes apply to the current interactive session. Restarting NextOrca restores environment/CLI configuration.

## Current policy

Auto routing sends repository exploration and explanation to local when available. Editing, debugging, testing, review and planning go to cloud. A temporary local provider outage may fall back to cloud if no stream output has been emitted yet. After partial output, NextOrca fails the turn rather than silently switching providers and mixing two model responses.

Local-only mode prevents cloud selection and fallback. Cloud route overrides are rejected while local-only is active.

The classifier is deterministic and intentionally simple. It is not a learned quality estimator. Manual route controls remain available, and route decisions are displayed in the interactive terminal.
