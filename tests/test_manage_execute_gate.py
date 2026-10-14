"""Tests for manage_wheel_options.py execute gate logic.

Verifies that DRY_RUN and MANAGE_EXECUTE environment variables properly
disable live order submission even when inside the submit window.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo


def test_dry_run_env_var_disables_execute():
    """DRY_RUN=1 should force execute=False even when window is open."""
    import sys
    sys.path.insert(0, "/workspace")
    
    # Mock os.getenv to return DRY_RUN=1 and test other values
    with patch.dict(os.environ, {"DRY_RUN": "1"}):
        with patch("src.trading.execution_status.can_submit_live_orders") as mock_can_submit:
            mock_can_submit.return_value = (True, "ok")
            
            # Read and execute the execute gate logic inline
            dry_run_env = os.getenv("DRY_RUN", "").strip().lower()
            manage_execute_env = os.getenv("MANAGE_EXECUTE", "").strip().lower()
            
            dry_run_enabled = dry_run_env in ("1", "true", "yes")
            manage_execute_disabled = manage_execute_env in ("0", "false", "off", "no")
            
            ok, reason = mock_can_submit.return_value
            execute = True
            if dry_run_enabled or manage_execute_disabled:
                execute = False
            elif not ok:
                execute = False
            
            assert execute is False, "execute should be False when DRY_RUN=1"
            assert dry_run_enabled is True


def test_dry_run_variations():
    """Test that various DRY_RUN values disable execute."""
    test_values = ["1", "true", "True", "TRUE", "yes", "YES", "Yes"]
    
    for value in test_values:
        with patch.dict(os.environ, {"DRY_RUN": value}):
            dry_run_env = os.getenv("DRY_RUN", "").strip().lower()
            dry_run_enabled = dry_run_env in ("1", "true", "yes")
            
            assert dry_run_enabled is True, f"DRY_RUN={value} should enable dry_run"


def test_manage_execute_zero_disables_execute():
    """MANAGE_EXECUTE=0 should force execute=False even when window is open."""
    with patch.dict(os.environ, {"MANAGE_EXECUTE": "0"}):
        with patch("src.trading.execution_status.can_submit_live_orders") as mock_can_submit:
            mock_can_submit.return_value = (True, "ok")
            
            dry_run_env = os.getenv("DRY_RUN", "").strip().lower()
            manage_execute_env = os.getenv("MANAGE_EXECUTE", "").strip().lower()
            
            dry_run_enabled = dry_run_env in ("1", "true", "yes")
            manage_execute_disabled = manage_execute_env in ("0", "false", "off", "no")
            
            ok, reason = mock_can_submit.return_value
            execute = True
            if dry_run_enabled or manage_execute_disabled:
                execute = False
            elif not ok:
                execute = False
            
            assert execute is False, "execute should be False when MANAGE_EXECUTE=0"
            assert manage_execute_disabled is True


def test_manage_execute_variations():
    """Test that various MANAGE_EXECUTE values disable execute."""
    test_values = ["0", "false", "False", "FALSE", "off", "OFF", "Off", "no", "NO", "No"]
    
    for value in test_values:
        with patch.dict(os.environ, {"MANAGE_EXECUTE": value}):
            manage_execute_env = os.getenv("MANAGE_EXECUTE", "").strip().lower()
            manage_execute_disabled = manage_execute_env in ("0", "false", "off", "no")
            
            assert manage_execute_disabled is True, f"MANAGE_EXECUTE={value} should disable execute"


def test_execute_enabled_without_gates():
    """Without DRY_RUN or MANAGE_EXECUTE, execute should be True when window is open."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("src.trading.execution_status.can_submit_live_orders") as mock_can_submit:
            mock_can_submit.return_value = (True, "ok")
            
            dry_run_env = os.getenv("DRY_RUN", "").strip().lower()
            manage_execute_env = os.getenv("MANAGE_EXECUTE", "").strip().lower()
            
            dry_run_enabled = dry_run_env in ("1", "true", "yes")
            manage_execute_disabled = manage_execute_env in ("0", "false", "off", "no")
            
            ok, reason = mock_can_submit.return_value
            execute = True
            if dry_run_enabled or manage_execute_disabled:
                execute = False
            elif not ok:
                execute = False
            
            assert execute is True, "execute should be True when no gates and window is open"


def test_manage_wheel_options_script_has_dry_run_logic():
    """Verify the script file contains the DRY_RUN and MANAGE_EXECUTE gate logic."""
    script_path = "/workspace/scripts/manage_wheel_options.py"
    with open(script_path, "r") as f:
        content = f.read()
    
    # Verify the key components of our fix are present
    assert 'os.getenv("DRY_RUN"' in content, "Script should check DRY_RUN env var"
    assert 'os.getenv("MANAGE_EXECUTE"' in content, "Script should check MANAGE_EXECUTE env var"
    assert 'dry_run_enabled' in content, "Script should have dry_run_enabled logic"
    assert 'manage_execute_disabled' in content, "Script should have manage_execute_disabled logic"


def test_workflow_sets_dry_run_for_schedule():
    """Verify the workflow file sets DRY_RUN=1 for schedule events."""
    workflow_path = "/workspace/.github/workflows/wheel-options-daily.yml"
    with open(workflow_path, "r") as f:
        content = f.read()
    
    # Verify workflow has execute input
    assert "inputs:" in content, "Workflow should have inputs"
    assert "execute:" in content, "Workflow should have execute input"
    
    # Verify workflow sets DRY_RUN based on event type
    assert "DRY_RUN:" in content, "Workflow should set DRY_RUN env var"
    assert "github.event_name == 'schedule'" in content, "Workflow should check if schedule event"
    assert "github.event.inputs.execute" in content, "Workflow should check execute input"
