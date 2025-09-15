#!/usr/bin/env python3
"""
Script to run pyright with specific rule filters.
"""
import subprocess
import sys
import argparse
from typing import List, Optional


def run_pyright_for_rules(
    include_rules: Optional[List[str]] = None,
    exclude_rules: Optional[List[str]] = None,
    output_format: str = "text",
) -> None:
    """Run pyright and filter by specific rules."""

    # Build pyright command
    cmd = ["pyright"]

    if output_format == "json":
        cmd.append("--outputjson")

    # Run pyright
    result = subprocess.run(cmd, capture_output=True, text=True)

    if output_format == "json":
        import json

        data = json.loads(result.stdout)
        diagnostics = data.get("generalDiagnostics", [])

        # Filter diagnostics
        filtered = []
        for diag in diagnostics:
            rule = diag.get("rule", "unknown")

            # Apply filters
            if include_rules and rule not in include_rules:
                continue
            if exclude_rules and rule in exclude_rules:
                continue

            filtered.append(diag)

        # Output filtered results
        data["generalDiagnostics"] = filtered
        print(json.dumps(data, indent=2))
    else:
        # For text output, filter lines
        lines = result.stdout.splitlines()
        include_next = False

        for line in lines:
            # Check if line contains a rule we care about
            should_include = False

            if include_rules:
                for rule in include_rules:
                    if f"({rule})" in line:
                        should_include = True
                        break
            else:
                should_include = True

            if exclude_rules:
                for rule in exclude_rules:
                    if f"({rule})" in line:
                        should_include = False
                        break

            if should_include or not any(f"(report" in line for line in [line]):
                print(line)


def main():
    parser = argparse.ArgumentParser(description="Run pyright with rule filters")
    parser.add_argument("--include", nargs="+", help="Only include these rules")
    parser.add_argument("--exclude", nargs="+", help="Exclude these rules")
    parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    args = parser.parse_args()

    run_pyright_for_rules(
        include_rules=args.include,
        exclude_rules=args.exclude,
        output_format=args.format,
    )


if __name__ == "__main__":
    main()
