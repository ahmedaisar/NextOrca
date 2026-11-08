---
name: pre-commit-review
description: Review the staged diff and run focused checks before committing.
---

# Pre-commit review

1. Inspect the staged diff with git diff --cached.
2. Look for unrelated changes, secrets, debug output and generated artifacts.
3. Run the narrowest relevant tests and linters.
4. Summarize the staged changes and any remaining risks.
5. Do not create a commit unless the user explicitly asks.
