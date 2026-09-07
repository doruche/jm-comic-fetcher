import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "requirements.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("requirements_export", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_requirements_match_direct_dependencies():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


def test_stale_export_check_does_not_write(tmp_path, monkeypatch):
    module = load_generator()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--check"])
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["jmcomic==2.7.5"]\n')
    target = tmp_path / "requirements.txt"
    target.write_text("stale\n")
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 1
    assert target.read_text() == "stale\n"


def test_ranges_markers_and_extras_are_preserved_without_transitive_pins(tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text("""[project]
dependencies = ['httpx>=0.28,<0.29', 'example[extra]>=1; python_version >= "3.12"']
[dependency-groups]
dev = ["pytest==9.1.1"]
""")
    result = load_generator().render(project)
    assert result.endswith('httpx>=0.28,<0.29\nexample[extra]>=1; python_version >= "3.12"\n')
    assert "pytest" not in result and "anyio" not in result and "lxml" not in result


@pytest.mark.parametrize(
    "declaration",
    [
        'dynamic = ["dependencies"]',
        'dependencies = ["--index-url=https://example.org"]',
        'dependencies = ["pkg\\nother-package"]',
        'dependencies = "pkg"',
    ],
)
def test_unsupported_declarations_fail(tmp_path, declaration):
    project = tmp_path / "pyproject.toml"
    project.write_text(f"[project]\n{declaration}\n")
    with pytest.raises(ValueError):
        load_generator().render(project)
