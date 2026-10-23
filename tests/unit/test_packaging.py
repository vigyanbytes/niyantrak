"""Packaging: metadata a stranger (and PyPI) needs, every package shipped, and — opt-in — a real wheel smoke test."""
import os
import subprocess
import sys
import venv

import pytest

tomllib = pytest.importorskip("tomllib")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PY = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))
PROJECT = PY["project"]


def test_every_package_is_listed():
    found = sorted(os.path.relpath(d, ROOT).replace(os.sep, ".")
                   for d, _, fs in os.walk(os.path.join(ROOT, "niyantrak"))
                   if "__init__.py" in fs and "__pycache__" not in d)
    assert sorted(PY["tool"]["setuptools"]["packages"]) == found


def test_web_assets_are_package_data():
    assert "web/*" in PY["tool"]["setuptools"]["package-data"]["niyantrak"]


def test_metadata_complete():
    for key in ("name", "version", "description", "readme", "license", "requires-python", "authors",
                "keywords", "classifiers", "urls"):
        assert PROJECT.get(key), key
    assert PROJECT["license"] == "Apache-2.0"
    assert {"Homepage", "Source", "Issues", "Changelog"} <= set(PROJECT["urls"])
    cls = PROJECT["classifiers"]
    assert "Development Status :: 3 - Alpha" in cls
    assert all(f"Programming Language :: Python :: 3.{v}" in cls for v in (10, 11, 12, 13))
    assert PROJECT["dependencies"] == []          # the free tools stay standard-library only


def test_extras():
    extras = PROJECT["optional-dependencies"]
    assert {"discovery", "telemetry", "decisions", "all", "dev"} <= set(extras)
    named = {d for k, v in extras.items() if k not in ("all", "dev") for d in v}
    assert named <= set(extras["all"])


def test_version_matches_package():
    import niyantrak
    assert niyantrak.__version__ == PROJECT["version"]


def test_cli_version(capsys):
    from niyantrak.cli import main
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and PROJECT["version"] in capsys.readouterr().out


@pytest.mark.skipif(not os.environ.get("NIYANTRAK_PACKAGING_TEST"), reason="set NIYANTRAK_PACKAGING_TEST=1 (needs `build`)")
def test_wheel_installs_and_runs(tmp_path):
    dist = tmp_path / "dist"
    subprocess.run([sys.executable, "-m", "build", "--outdir", str(dist), ROOT], check=True, capture_output=True)
    wheels = list(dist.glob("*.whl"))
    assert wheels and list(dist.glob("*.tar.gz"))
    env_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    bindir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    subprocess.run([str(bindir / "python"), "-m", "pip", "install", "-q", str(wheels[0])], check=True)
    cli = str(bindir / "niyantrak")
    out = subprocess.run([cli, "scan", "My Aadhaar is 2345 6789 0124"], capture_output=True, text=True,
                         cwd=tmp_path, env=dict(os.environ, NIYANTRAK_STATE_ROOT=str(tmp_path / "state")))
    assert out.returncode == 0 and "<AADHAAR_1>" in out.stdout and "2345 6789 0124" not in out.stdout
    out = subprocess.run([cli, "panel", "--help"], capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0 and "--port" in out.stdout
