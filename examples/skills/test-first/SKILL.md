---
name: test-first
description: Use focused tests to guide code changes and verify the result.
---

# Test-first workflow

1. Identify the smallest relevant test module before changing code.
2. Run the focused test or reproduce the failure when practical.
3. Make the smallest change that addresses the task.
4. Run the focused test again.
5. Run broader checks when the change affects shared behavior.
6. Report the commands you actually ran and their exit status. Never claim a test passed if it was not run.
