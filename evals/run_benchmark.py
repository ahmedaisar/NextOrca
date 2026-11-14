from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from evals.benchmark import (
    FakeProvider,
    build_summary,
    load_manifest,
    run_task,
    write_reports,
)
from nextorca.provider_registry import (
    ProviderEndpoint,
    RuntimeProviderConfig,
    build_runtime_provider,
    create_default_provider_registry,
)


def _source_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _provider_key(adapter: str, generic: str | None = None) -> str | None:
    if adapter == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY") or generic
    if adapter == "gemini":
        return os.environ.get("GEMINI_API_KEY") or generic
    return generic


def _live_provider_factory(args: argparse.Namespace):
    def create(_task):
        registry = create_default_provider_registry()
        if args.route_mode == "single":
            adapter = args.adapter
            base_url = args.base_url
            if adapter == "openai-compatible" and not base_url:
                raise ValueError("--base-url or NEXTORCA_BASE_URL is required for openai-compatible.")
            config = RuntimeProviderConfig(
                route_mode="single",
                privacy_mode="balanced",
                single=ProviderEndpoint(
                    adapter,
                    base_url,
                    args.model,
                    _provider_key(adapter, os.environ.get("NEXTORCA_API_KEY")),
                ),
                local=ProviderEndpoint("openai-compatible", None, "unused"),
                cloud=ProviderEndpoint("openai-compatible", None, "unused"),
            )
            provider, model = build_runtime_provider(config, registry=registry)
            return provider, model, adapter, args.route_mode

        local_adapter = os.environ.get("NEXTORCA_LOCAL_PROVIDER_ADAPTER", "openai-compatible")
        cloud_adapter = os.environ.get("NEXTORCA_CLOUD_PROVIDER_ADAPTER", "openai-compatible")
        local_base_url = os.environ.get(
            "NEXTORCA_LOCAL_BASE_URL", "http://127.0.0.1:8080/v1"
        )
        cloud_base_url = os.environ.get("NEXTORCA_CLOUD_BASE_URL")
        if (
            args.route_mode in {"auto", "local"}
            and not local_base_url
            and registry.requires_base_url(local_adapter)
        ):
            raise ValueError("NEXTORCA_LOCAL_BASE_URL is required for this local adapter.")
        if (
            args.route_mode in {"auto", "cloud"}
            and not cloud_base_url
            and registry.requires_base_url(cloud_adapter)
        ):
            raise ValueError("NEXTORCA_CLOUD_BASE_URL is required for this cloud adapter.")
        config = RuntimeProviderConfig(
            route_mode=args.route_mode,
            privacy_mode="balanced",
            single=ProviderEndpoint("openai-compatible", None, "unused"),
            local=ProviderEndpoint(
                local_adapter,
                local_base_url,
                os.environ.get("NEXTORCA_LOCAL_MODEL", "local-model"),
                _provider_key(local_adapter, os.environ.get("NEXTORCA_LOCAL_API_KEY")),
            ),
            cloud=ProviderEndpoint(
                cloud_adapter,
                cloud_base_url,
                os.environ.get("NEXTORCA_CLOUD_MODEL", "cloud-model"),
                _provider_key(cloud_adapter, os.environ.get("NEXTORCA_CLOUD_API_KEY")),
            ),
        )
        provider, model = build_runtime_provider(config, registry=registry)
        return provider, model, f"hybrid(local={local_adapter},cloud={cloud_adapter})", args.route_mode

    return create


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run_benchmark",
        description="Run the deterministic NextOrca coding-task benchmark.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("benchmark_tasks.json"),
        help="Versioned benchmark task manifest.",
    )
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Task ID to run; repeat to select multiple tasks. Defaults to the full corpus.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results"),
        help="Directory for redacted JSON reports.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use a real configured provider. Without this flag, only the deterministic fake provider runs.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run only the short bug-fix fake-provider smoke task (for CI).",
    )
    parser.add_argument(
        "--route-mode",
        choices=["single", "auto", "local", "cloud"],
        default="single",
        help="Provider routing mode for live runs.",
    )
    parser.add_argument(
        "--adapter",
        default=os.environ.get("NEXTORCA_PROVIDER_ADAPTER", "openai-compatible"),
        help="Provider adapter for single-provider live runs.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("NEXTORCA_MODEL"),
        help="Model identifier for single-provider live runs.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NEXTORCA_BASE_URL"),
        help="Provider base URL for single-provider live runs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.smoke and args.live:
        parser.error("--smoke is an offline-only check and cannot be combined with --live.")
    if args.live and args.route_mode == "single" and not args.model:
        parser.error("--model or NEXTORCA_MODEL is required with --live --route-mode single.")

    try:
        corpus_version, tasks = load_manifest(args.manifest.expanduser().resolve(strict=True))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.smoke:
        selected_ids = {"bug-fix"}
    else:
        selected_ids = set(args.task)
    if selected_ids:
        known = {task.id for task in tasks}
        unknown = selected_ids - known
        if unknown:
            parser.error("Unknown task ID(s): " + ", ".join(sorted(unknown)))
        tasks = [task for task in tasks if task.id in selected_ids]
    if not tasks:
        parser.error("No benchmark tasks were selected.")

    manifest_path = args.manifest.expanduser().resolve(strict=True)
    fixture_root = manifest_path.parent / "fixtures"
    source_commit = _source_commit()
    if args.live:
        provider_factory = _live_provider_factory(args)
    else:
        provider_factory = lambda task: (FakeProvider(task.id), "deterministic-fake", "fake", "fake")

    results = [
        run_task(
            task,
            fixture_root=fixture_root,
            provider_factory=provider_factory,
            source_commit=source_commit,
        )
        for task in tasks
    ]
    summary = build_summary(
        corpus_version=corpus_version,
        source_commit=source_commit,
        results=results,
    )
    aggregate_path, runs_path = write_reports(summary, args.output_dir.expanduser())
    print(
        f"Benchmark: {summary['success_count']}/{summary['task_count']} tasks passed "
        f"({summary['success_rate']:.1%})"
        if summary["success_rate"] is not None
        else "Benchmark produced no results."
    )
    print(f"Summary: {aggregate_path}")
    print(f"Runs: {runs_path}")
    return 0 if summary["success_count"] == summary["task_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
