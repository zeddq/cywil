#!/usr/bin/env python3
"""
Script to parse Pyright JSON output and create separate reports for each violation rule.
"""
import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any
import subprocess


def run_pyright_json() -> Dict[str, Any]:
    """Run pyright and get JSON output."""
    try:
        result = subprocess.run(
            ["pyright", "--outputjson"],
            capture_output=True,
            text=True,
            check=False
        )
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Error: Could not parse pyright output as JSON")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: pyright not found. Please install it with: pip install pyright")
        sys.exit(1)


def group_diagnostics_by_rule(pyright_output: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Group diagnostics by their rule name."""
    diagnostics_by_rule = defaultdict(list)
    
    # Get diagnostics from the generalDiagnostics
    diagnostics = pyright_output.get("generalDiagnostics", [])
    
    for diagnostic in diagnostics:
        rule = diagnostic.get("rule", "unknown")
        diagnostics_by_rule[rule].append(diagnostic)
    
    return dict(diagnostics_by_rule)


def create_report_for_rule(rule_name: str, diagnostics: List[Dict[str, Any]], output_dir: Path) -> None:
    """Create a report file for a specific rule."""
    output_file = output_dir / f"{rule_name}.txt"
    
    with open(output_file, 'w') as f:
        f.write(f"Pyright Diagnostic Report: {rule_name}\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total violations: {len(diagnostics)}\n\n")
        
        # Group by file
        by_file = defaultdict(list)
        for diag in diagnostics:
            file_path = diag.get("file", "unknown")
            by_file[file_path].append(diag)
        
        # Write diagnostics grouped by file
        for file_path, file_diagnostics in sorted(by_file.items()):
            f.write(f"\n{file_path} ({len(file_diagnostics)} violations)\n")
            f.write("-" * len(file_path) + "\n")
            
            for diag in file_diagnostics:
                range_info = diag.get("range", {})
                start = range_info.get("start", {})
                line = start.get("line", 0) + 1  # Convert to 1-based
                column = start.get("character", 0) + 1
                
                severity = diag.get("severity", "unknown")
                message = diag.get("message", "No message")
                
                f.write(f"  Line {line}:{column} [{severity}]: {message}\n")


def create_summary_report(diagnostics_by_rule: Dict[str, List[Dict[str, Any]]], output_dir: Path) -> None:
    """Create a summary report of all rules."""
    summary_file = output_dir / "SUMMARY.txt"
    
    with open(summary_file, 'w') as f:
        f.write("Pyright Diagnostics Summary\n")
        f.write("=" * 80 + "\n\n")
        
        # Sort rules by number of violations (descending)
        sorted_rules = sorted(
            diagnostics_by_rule.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )
        
        total_violations = sum(len(diags) for _, diags in sorted_rules)
        f.write(f"Total rules with violations: {len(sorted_rules)}\n")
        f.write(f"Total violations: {total_violations}\n\n")
        
        f.write("Violations by Rule:\n")
        f.write("-" * 50 + "\n")
        
        for rule, diags in sorted_rules:
            f.write(f"{rule:40} {len(diags):>8} violations\n")


def create_csv_report(diagnostics_by_rule: Dict[str, List[Dict[str, Any]]], output_dir: Path) -> None:
    """Create a CSV report for easy analysis."""
    import csv
    
    csv_file = output_dir / "all_violations.csv"
    
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Rule", "File", "Line", "Column", "Severity", "Message"])
        
        for rule, diagnostics in sorted(diagnostics_by_rule.items()):
            for diag in diagnostics:
                file_path = diag.get("file", "unknown")
                range_info = diag.get("range", {})
                start = range_info.get("start", {})
                line = start.get("line", 0) + 1
                column = start.get("character", 0) + 1
                severity = diag.get("severity", "unknown")
                message = diag.get("message", "No message")
                
                writer.writerow([rule, file_path, line, column, severity, message])


def main():
    """Main function to orchestrate the report generation."""
    print("Running pyright analysis...")
    pyright_output = run_pyright_json()
    
    # Create output directory
    output_dir = Path("pyright_reports")
    output_dir.mkdir(exist_ok=True)
    
    # Clear previous reports
    for old_file in output_dir.glob("*.txt"):
        old_file.unlink()
    for old_file in output_dir.glob("*.csv"):
        old_file.unlink()
    
    # Group diagnostics by rule
    diagnostics_by_rule = group_diagnostics_by_rule(pyright_output)
    
    if not diagnostics_by_rule:
        print("No diagnostics found!")
        return
    
    print(f"\nFound {len(diagnostics_by_rule)} different rules with violations")
    print(f"Creating reports in: {output_dir.absolute()}")
    
    # Create individual reports for each rule
    for rule_name, diagnostics in diagnostics_by_rule.items():
        create_report_for_rule(rule_name, diagnostics, output_dir)
        print(f"  Created report for: {rule_name} ({len(diagnostics)} violations)")
    
    # Create summary report
    create_summary_report(diagnostics_by_rule, output_dir)
    print(f"\nCreated summary report: {output_dir / 'SUMMARY.txt'}")
    
    # Create CSV report
    create_csv_report(diagnostics_by_rule, output_dir)
    print(f"Created CSV report: {output_dir / 'all_violations.csv'}")
    
    # Save raw JSON for reference
    json_file = output_dir / "raw_pyright_output.json"
    with open(json_file, 'w') as f:
        json.dump(pyright_output, f, indent=2)
    print(f"Saved raw JSON output: {json_file}")
    
    print(f"\nAll reports generated in: {output_dir.absolute()}")


if __name__ == "__main__":
    main()
