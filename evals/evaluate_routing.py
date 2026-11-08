from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from nextorca.routing import classify_task


def evaluate(cases: list[dict[str, Any]]) -> tuple[float, list[dict[str, str]], dict[str, dict[str, int]]]:
    total = len(cases)
    if total == 0:
        raise ValueError("The routing evaluation corpus is empty.")

    correct = 0
    mismatches: list[dict[str, str]] = []
    per_class: dict[str, Counter[str]] = {}
    for item in cases:
        prompt = item.get("prompt")
        expected = item.get("expected")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Every routing case must include a non-empty prompt.")
        if not isinstance(expected, str) or not expected:
            raise ValueError("Every routing case must include an expected task class.")

        actual = classify_task([{"role": "user", "content": prompt}])
        counts = per_class.setdefault(expected, Counter())
        counts["total"] += 1
        if actual == expected:
            correct += 1
            counts["correct"] += 1
        else:
            mismatches.append(
                {"prompt": prompt, "expected": expected, "actual": actual}
            )

    accuracy = correct / total
    return accuracy, mismatches, {key: dict(value) for key, value in per_class.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate NextOrca task classification.")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).with_name("routing_cases.json"),
        help="JSON routing evaluation corpus.",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=0.90,
        help="Exit with failure when accuracy is below this fraction.",
    )
    args = parser.parse_args()
    if not 0.0 <= args.fail_under <= 1.0:
        parser.error("--fail-under must be between 0 and 1.")

    try:
        cases = json.loads(args.corpus.read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise ValueError("Routing corpus must be a JSON array.")
        accuracy, mismatches, per_class = evaluate(cases)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"routing evaluation: {exc}\n")

    print(f"Routing accuracy: {accuracy:.1%} ({len(cases) - len(mismatches)}/{len(cases)})")
    for task, counts in sorted(per_class.items()):
        print(f"  {task}: {counts.get('correct', 0)}/{counts['total']}")
    for mismatch in mismatches:
        print(
            "  mismatch: "
            f"expected={mismatch['expected']} actual={mismatch['actual']} "
            f"prompt={mismatch['prompt']!r}"
        )
    if accuracy < args.fail_under:
        print(f"Accuracy below required threshold {args.fail_under:.1%}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
