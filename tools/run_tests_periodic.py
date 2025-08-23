#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def discover_test_files(repo_root: Path) -> list[Path]:
    candidates: list[Path] = []
    # Look in repository root and tests/ directory
    patterns = [
        repo_root.glob("test_*.py"),
        (repo_root / "tests").glob("test_*.py") if (repo_root / "tests").exists() else [],
    ]
    for it in patterns:
        for p in it:
            if p.is_file():
                candidates.append(p)
    # De-duplicate and sort for stable order
    unique = sorted({p.resolve() for p in candidates})
    return list(unique)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def run_pytest_for_file(
    test_file: Path,
    output_dir: Path,
    repo_root: Path,
    extra_pytest_args: list[str] | None = None,
) -> dict:
    ensure_dir(output_dir)
    junit_path = output_dir / f"{test_file.stem}.xml"
    html_path = output_dir / f"{test_file.stem}.html"
    json_path = output_dir / f"{test_file.stem}.json"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(repo_root / "tests" / "pytest.ini"),
        str(test_file),
        "-q",
        f"--junitxml={junit_path}",
        f"--html={html_path}",
        f"--json-report",
        f"--json-report-file={json_path}",
    ]
    if extra_pytest_args:
        cmd.extend(extra_pytest_args)

    start = time.time()
    # Run from repository root so imports and config resolve correctly
    proc = subprocess.run(cmd, cwd=str(repo_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    duration = time.time() - start

    result = {
        "test_file": str(test_file),
        "exit_code": proc.returncode,
        "duration_seconds": duration,
        "stdout": proc.stdout.decode("utf-8", errors="replace"),
        "stderr": proc.stderr.decode("utf-8", errors="replace"),
        "junit_xml": str(junit_path),
        "html_report": str(html_path),
        "json_report": str(json_path),
    }
    return result


def summarize_run(per_file_results: list[dict]) -> dict:
    total = len(per_file_results)
    failed = sum(1 for r in per_file_results if r["exit_code"] != 0)
    succeeded = total - failed
    duration = sum(r.get("duration_seconds", 0.0) for r in per_file_results)
    return {
        "total_files": total,
        "succeeded": succeeded,
        "failed": failed,
        "aggregate_duration_seconds": duration,
        "files": per_file_results,
    }


def write_index(run_dir: Path, summary: dict) -> None:
    index_path = run_dir / "index.json"
    with index_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def run_once(repo_root: Path, reports_root: Path, extra_pytest_args: list[str] | None) -> dict:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = reports_root / timestamp
    ensure_dir(run_dir)

    test_files = discover_test_files(repo_root)
    per_file_results: list[dict] = []
    for test_file in test_files:
        file_output_dir = run_dir / test_file.stem
        result = run_pytest_for_file(test_file, file_output_dir, repo_root, extra_pytest_args)
        per_file_results.append(result)

    summary = summarize_run(per_file_results)
    write_index(run_dir, summary)
    return {"run_dir": str(run_dir), "summary": summary}


def parse_interval(value: str) -> int:
    # Accept integers (seconds) or strings like 15m, 1h
    try:
        return int(value)
    except ValueError:
        unit = value[-1]
        num = int(value[:-1])
        if unit in ("s", "S"):
            return num
        if unit in ("m", "M"):
            return num * 60
        if unit in ("h", "H"):
            return num * 3600
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Periodic pytest runner with per-file reporting")
    parser.add_argument("--reports-dir", default="reports", help="Root directory for reports")
    parser.add_argument("--interval", default=None, help="Repeat interval (e.g., 900, 15m, 1h). Omit to run once.")
    parser.add_argument("--once", action="store_true", help="Force single run and exit")
    parser.add_argument("--pytest-args", nargs=argparse.REMAINDER, help="Extra arguments passed to pytest after '--' delimiter")

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    reports_root = Path(args.reports_dir).resolve()
    ensure_dir(reports_root)

    extra_pytest_args = None
    if args.pytest_args:
        # Consumers pass like: --pytest-args -m smoke -k something
        extra_pytest_args = [a for a in args.pytest_args if a != "--"]

    if args.once or not args.interval:
        outcome = run_once(repo_root, reports_root, extra_pytest_args)
        print(json.dumps(outcome, indent=2))
        # Non-zero exit if any file failed
        failed = outcome["summary"]["failed"]
        return 1 if failed else 0

    interval_seconds = parse_interval(args.interval)
    try:
        while True:
            outcome = run_once(repo_root, reports_root, extra_pytest_args)
            print(json.dumps(outcome, indent=2))
            failed = outcome["summary"]["failed"]
            # Emit a simple status line for quick glance
            print(f"Completed run in {outcome['run_dir']}. Failed files: {failed}")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("Interrupted. Exiting.")
        return 0


if __name__ == "__main__":
    sys.exit(main())


