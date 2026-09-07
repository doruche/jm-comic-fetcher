import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "requirements.py"


def test_committed_requirements_match_uv_lock():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


def test_stale_export_check_does_not_write(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("requirements_export", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--check"])
    export = Mock(return_value=subprocess.CompletedProcess([], 0, "jmcomic==2.7.5\n", ""))
    monkeypatch.setattr(module.subprocess, "run", export)
    target = tmp_path / "requirements.txt"
    target.write_text("stale\n")
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 1
    assert target.read_text() == "stale\n"
