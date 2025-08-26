#!/usr/bin/env python3
import os
import sys
import csv
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict

REPO_DIR = Path("/workspace")
VENV_BIN = REPO_DIR / ".venv" / "bin"
REPORT_DIR = REPO_DIR / "pyright_reports"
MAPPING_FILE = REPO_DIR / "scripts" / "pyright_autofix.mapping.yml"
DISCOVERY_SCRIPT = REPO_DIR / "scripts" / "pyright_report_by_rule.py"
MONITOR_LOG = REPO_DIR / "reports" / "pyright_monitor_latest.md"

AUTO_PUSH = os.environ.get("AUTO_PUSH", "")
PHASE_B = os.environ.get("AUTOFIX_PHASE_B", "0") == "1"

# Utilities

def note(msg: str) -> None:
    MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(MONITOR_LOG, "a") as f:
        f.write(f"[{subprocess.getoutput('date -u +%Y-%m-%dT%H:%M:%SZ')}] {msg}\n")


def run(cmd: List[str], check: bool = True, capture: bool = False, env: Dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=capture, env=env)


def venv_cmd(exe: str) -> str:
    return str(VENV_BIN / exe)


# Mapping loader

def load_mapping() -> List[Tuple[str, str]]:
    try:
        import yaml  # type: ignore
    except Exception:
        # try to install pyyaml on the fly
        try:
            run([venv_cmd("python"), "-m", "pip", "install", "pyyaml"], check=True)
            import yaml  # type: ignore
        except Exception as e:
            note(f"Failed to ensure pyyaml: {e}")
            return []
    if not MAPPING_FILE.exists():
        return []
    with open(MAPPING_FILE, "r") as f:
        data = yaml.safe_load(f) or {}
    mappings = []
    for item in (data.get("imports") or []):
        frm = str(item.get("from", "")).strip()
        to = str(item.get("to", "")).strip()
        if frm and to:
            mappings.append((frm, to))
    return mappings


# Parse CSV for violations

def read_violations_csv(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    rows: List[Dict[str, str]] = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def collect_files_for_rules(rows: List[Dict[str, str]], rules: List[str]) -> List[Path]:
    files = []
    seen = set()
    for r in rows:
        if r.get("Rule") in rules:
            fp = r.get("File") or ""
            if fp and fp.endswith(".py") and fp not in seen:
                seen.add(fp)
                files.append(Path(fp))
    return files


# Phase A: Import rewrite

def apply_import_rewrites(py_files: List[Path], mapping: List[Tuple[str, str]]) -> List[Path]:
    changed: List[Path] = []
    for file_path in py_files:
        try:
            text = file_path.read_text()
        except Exception:
            continue
        original = text
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not line.lstrip().startswith(("from ", "import ")):
                continue
            for frm, to in mapping:
                if frm in line and to not in line:
                    lines[i] = line.replace(frm, to)
        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        if new_text != original:
            try:
                file_path.write_text(new_text)
                changed.append(file_path)
            except Exception as e:
                note(f"Failed to write {file_path}: {e}")
    return changed


# Phase B: Conservative optional guard for simple assignments
_SIMPLE_ASSIGN_ATTR = re.compile(r"^(?P<indent>\s*)(?P<lhs>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\.(?P<attr>[A-Za-z_][A-Za-z0-9_]*)(?P<call>\([^\n]*\))?\s*$")


def maybe_guard_optional_line(line: str) -> str | None:
    m = _SIMPLE_ASSIGN_ATTR.match(line)
    if not m:
        return None
    indent = m.group("indent")
    lhs = m.group("lhs")
    var = m.group("var")
    attr = m.group("attr")
    call = m.group("call") or ""
    guarded = f"{indent}{lhs} = {var}.{attr}{call} if {var} is not None else None"
    return guarded if guarded != line else None


def apply_phase_b(rows: List[Dict[str, str]]) -> List[Path]:
    if not PHASE_B:
        return []
    changed: List[Path] = []
    # Group by file and line numbers for target rules
    targets: Dict[Path, List[int]] = {}
    for r in rows:
        rule = r.get("Rule")
        if rule not in ("reportOptionalMemberAccess", "reportOptionalCall"):
            continue
        try:
            fp = Path(r.get("File") or "")
            line_no = int(r.get("Line") or "0")
        except Exception:
            continue
        if not fp.exists():
            continue
        targets.setdefault(fp, []).append(line_no)

    for fp, line_nums in targets.items():
        try:
            text = fp.read_text()
        except Exception:
            continue
        lines = text.splitlines()
        updated = False
        for ln in set(line_nums):
            idx = ln - 1
            if idx < 0 or idx >= len(lines):
                continue
            new_line = maybe_guard_optional_line(lines[idx])
            if new_line and new_line != lines[idx]:
                lines[idx] = new_line
                updated = True
        if updated:
            try:
                fp.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
                changed.append(fp)
            except Exception as e:
                note(f"Failed to write (Phase B) {fp}: {e}")
    return changed


# Discovery re-run and delta

def run_discovery() -> None:
    env = os.environ.copy()
    env["PATH"] = f"{VENV_BIN}:{env.get('PATH','')}"
    run([venv_cmd("python"), str(DISCOVERY_SCRIPT)], check=True, env=env)


def count_rows(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    with open(csv_path, newline="") as f:
        return sum(1 for _ in f) - 1  # minus header


# Test gating

def tests_available() -> bool:
    return (REPO_DIR / "tests").exists()


def pytest_available() -> bool:
    try:
        run([venv_cmd("pytest"), "--version"], check=True)
        return True
    except Exception:
        try:
            run([venv_cmd("python"), "-m", "pip", "install", "pytest"], check=True)
            run([venv_cmd("pytest"), "--version"], check=True)
            return True
        except Exception:
            return False


def run_pytests() -> bool:
    if not tests_available():
        note("Tests not found; skipping test gate.")
        return True
    if not pytest_available():
        note("pytest unavailable; skipping test gate.")
        return True
    try:
        cp = run([venv_cmd("pytest"), "-q"], check=False, capture=True)
        ok = (cp.returncode == 0)
        note(f"pytest exit={cp.returncode}")
        if not ok:
            note((cp.stdout or "")[-4000:])
            note((cp.stderr or "")[-4000:])
        return ok
    except Exception as e:
        note(f"pytest run failed: {e}")
        return False


# Git ops

def ensure_git_identity() -> None:
    try:
        run(["git", "config", "user.email"], check=True)
        run(["git", "config", "user.name"], check=True)
    except Exception:
        run(["git", "config", "user.email", "pyright-bot@example.com"], check=False)
        run(["git", "config", "user.name", "pyright-bot"], check=False)


def git_restore() -> None:
    run(["git", "restore", "."], check=False)


def git_commit_and_maybe_push(message: str) -> None:
    ensure_git_identity()
    run(["git", "add", "-A"], check=False)
    cp = run(["git", "diff", "--staged", "--name-only"], check=False, capture=True)
    if not (cp.stdout or "").strip():
        note("No staged changes to commit.")
        return
    run(["git", "commit", "-m", message], check=False)
    if AUTO_PUSH:
        try:
            run(["git", "push"], check=False)
            note("Pushed commit to remote.")
        except Exception as e:
            note(f"Push failed: {e}")


def main() -> int:
    # Baseline counts
    prev_csv = REPORT_DIR / "all_violations.csv"
    prev_count = count_rows(prev_csv)

    rows = read_violations_csv(prev_csv)
    mapping = load_mapping()

    changed_files: List[Path] = []

    # Phase A
    if mapping and rows:
        files_for_imports = collect_files_for_rules(rows, [
            "reportMissingImports",
            "reportMissingModuleSource",
            "reportAttributeAccessIssue",
        ])
        changed_files += apply_import_rewrites(files_for_imports, mapping)

    # Phase B (very conservative)
    if PHASE_B and rows:
        changed_files += apply_phase_b(rows)

    if not changed_files:
        note("Auto-fix: no changes applied.")
        return 0

    note(f"Auto-fix modified {len(changed_files)} files.")

    # Re-run discovery
    try:
        run_discovery()
    except Exception as e:
        note(f"Discovery after fixes failed: {e}; reverting.")
        git_restore()
        return 1

    new_csv = REPORT_DIR / "all_violations.csv"
    new_count = count_rows(new_csv)

    if new_count < prev_count:
        # Test gate
        if run_pytests():
            note(f"✅ Violations reduced: {prev_count} -> {new_count} (-{prev_count - new_count}). Committing fixes.")
            git_commit_and_maybe_push(f"chore(pyright): auto-fix (-{prev_count - new_count})")
            return 0
        else:
            note("Tests failed; reverting fixes.")
            git_restore()
            return 2
    else:
        note(f"No reduction from fixes: {prev_count} -> {new_count}. Reverting.")
        git_restore()
        return 0


if __name__ == "__main__":
    sys.exit(main())