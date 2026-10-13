"""
Repository integrity tests: prevent merge conflicts and broken workflow YAML.

These tests run in CI to catch:
1. Leftover merge conflict markers in any tracked file
2. Invalid YAML syntax in GitHub Actions workflows
"""

import subprocess
from pathlib import Path

import pytest
import yaml


def test_no_merge_conflict_markers():
    """
    Fail if any tracked text file contains merge conflict markers.
    
    Catches unresolved conflicts (<<<<<<< HEAD, =======, >>>>>>>) that
    would break workflows or configs but pass CI if nothing parses them.
    
    We specifically look for:
    - Lines starting with "<<<<<<< " (conflict start)
    - Lines starting with ">>>>>>> " (conflict end)
    - Lines that are exactly "=======" or start with "=======" + whitespace (conflict divider)
    
    This avoids false positives from legitimate uses of "=======" in documentation.
    """
    repo_root = Path(__file__).parent.parent
    
    # Get all tracked files from git
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    
    files_with_conflicts = []
    
    for file_path in tracked_files:
        full_path = repo_root / file_path
        
        # Skip binary files (only check text files)
        if not full_path.is_file():
            continue
            
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
                for line_num, line in enumerate(lines, 1):
                    # Check for git conflict markers with precise matching
                    if line.startswith("<<<<<<< "):
                        files_with_conflicts.append(
                            f"{file_path}:{line_num} → <<<<<<< (conflict start)"
                        )
                    elif line.startswith(">>>>>>> "):
                        files_with_conflicts.append(
                            f"{file_path}:{line_num} → >>>>>>> (conflict end)"
                        )
                    elif line == "=======" or (line.startswith("=======") and line[7:8] in ("", " ", "\t")):
                        # Only flag "=======" if it's alone or followed by whitespace
                        # (git conflict markers), not if it's part of a longer line
                        files_with_conflicts.append(
                            f"{file_path}:{line_num} → ======= (conflict divider)"
                        )
        except (UnicodeDecodeError, OSError):
            # Skip files that can't be read as text
            continue
    
    if files_with_conflicts:
        conflict_list = "\n  ".join(files_with_conflicts)
        pytest.fail(
            f"Found {len(files_with_conflicts)} merge conflict marker(s):\n  {conflict_list}\n"
            "Resolve all conflicts before committing."
        )


def test_github_workflows_valid_yaml():
    """
    YAML-parse every GitHub Actions workflow file.
    
    Catches syntax errors (including unresolved conflict markers) that
    would silently break workflow execution while CI passes.
    """
    repo_root = Path(__file__).parent.parent
    workflows_dir = repo_root / ".github" / "workflows"
    
    if not workflows_dir.exists():
        pytest.skip("No .github/workflows directory found")
    
    workflow_files = list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
    
    if not workflow_files:
        pytest.skip("No workflow YAML files found")
    
    invalid_files = []
    
    for workflow_path in workflow_files:
        try:
            with open(workflow_path, "r", encoding="utf-8") as f:
                yaml.safe_load(f)
        except yaml.YAMLError as e:
            invalid_files.append(
                f"{workflow_path.relative_to(repo_root)}: {str(e)}"
            )
    
    if invalid_files:
        error_list = "\n  ".join(invalid_files)
        pytest.fail(
            f"Found {len(invalid_files)} invalid workflow YAML file(s):\n  {error_list}\n"
            "Fix YAML syntax errors before committing."
        )
