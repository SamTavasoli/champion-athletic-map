"""Create and record the independent analysis environment for Step 36.

This module intentionally imports only the Python standard library.  It never
loads an application model, training dependency, or an earlier environment.
"""
from __future__ import annotations

import datetime as _datetime
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit
import venv


_ANALYSIS_PACKAGES = {"numpy", "matplotlib", "nbclient", "nbformat", "ipykernel"}
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]*$")


def _now():
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _redact_url(match):
    raw = match.group(0)
    # Pip occasionally wraps a URL in punctuation. Keeping that punctuation is
    # cosmetic; removing user information and all query contents is essential.
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        if ":" in host:
            host = "[" + host + "]"
        if parts.port:
            host += ":" + str(parts.port)
        if parts.username is not None or parts.password is not None:
            host = "<redacted>@" + host
        return urlunsplit((parts.scheme, host, parts.path, "<redacted>" if parts.query else "", ""))
    except ValueError:
        return "<redacted-url>"


def redact(value):
    """Remove URL credentials/query values from persisted commands and logs."""
    if isinstance(value, str):
        return re.sub(r"(?:https?|ftp)://[^\s\"'<>]+", _redact_url, value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def _parent_version(package, fallback=None):
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        if fallback is not None:
            return fallback
        raise ValueError("The source analysis must supply a pinned " + package + " version.")


def analysis_requirements(numpy_version, matplotlib_version=None, ipykernel_version=None):
    """Build the five top-level pins; NumPy must come from the source manifest."""
    return {
        "numpy": str(numpy_version),
        "matplotlib": str(matplotlib_version or _parent_version("matplotlib")),
        "nbclient": "0.10.4",
        "nbformat": "5.10.4",
        "ipykernel": str(ipykernel_version or _parent_version("ipykernel", "6.30.1")),
    }


def _pins(requirements):
    if isinstance(requirements, dict):
        pins = {str(key).lower().replace("_", "-"): str(value) for key, value in requirements.items()}
    else:
        pins = {}
        for requirement in requirements:
            if not isinstance(requirement, str) or requirement.count("==") != 1:
                raise ValueError("Analysis requirements must be exact package==version pins.")
            name, version = requirement.split("==")
            name = name.lower().replace("_", "-")
            if name in pins:
                raise ValueError("Duplicate analysis requirement: " + name)
            pins[name] = version
    if set(pins) - _ANALYSIS_PACKAGES:
        raise ValueError("Only the five analysis/Jupyter top-level packages may be installed.")
    if "numpy" not in pins:
        raise ValueError("NumPy must be pinned to bootstrap_settings.numpy_version from the source manifest.")
    if "matplotlib" not in pins:
        pins["matplotlib"] = _parent_version("matplotlib")
    pins.setdefault("nbclient", "0.10.4")
    pins.setdefault("nbformat", "5.10.4")
    if "ipykernel" not in pins:
        pins["ipykernel"] = _parent_version("ipykernel", "6.30.1")
    for name, version in pins.items():
        if not _VERSION.fullmatch(version):
            raise ValueError("Invalid exact version for " + name)
    if pins["nbclient"] != "0.10.4" or pins["nbformat"] != "5.10.4":
        raise ValueError("The Step 36 runner pins nbclient==0.10.4 and nbformat==5.10.4.")
    return [name + "==" + pins[name] for name in sorted(pins)]


def isolated_environment(run_folder, python=None):
    """Environment shared by the external driver and its new notebook kernel."""
    run_folder = Path(run_folder).resolve()
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "IPYTHONDIR", "JUPYTER_PATH", "JUPYTER_CONFIG_PATH"):
        env.pop(name, None)
    env.update({
        "PYTHONNOUSERSITE": "1",
        "IPYTHONDIR": str(run_folder / "ipython"),
        "MPLCONFIGDIR": str(run_folder / "matplotlib_config"),
        "JUPYTER_DATA_DIR": str(run_folder / "jupyter_data"),
        "JUPYTER_CONFIG_DIR": str(run_folder / "jupyter_config"),
        "JUPYTER_RUNTIME_DIR": str(run_folder / "jupyter_runtime"),
        "JUPYTER_PATH": str(run_folder / "jupyter_data"),
        "JUPYTER_NO_CONFIG": "1",
        "MPLBACKEND": "Agg",
    })
    if python is not None:
        python_path = Path(python).absolute()
        env["VIRTUAL_ENV"] = str(python_path.parent.parent)
        env["PATH"] = str(python_path.parent) + os.pathsep + env.get("PATH", "")
    for name in ("IPYTHONDIR", "MPLCONFIGDIR", "JUPYTER_DATA_DIR", "JUPYTER_CONFIG_DIR", "JUPYTER_RUNTIME_DIR"):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    return env


def _memory():
    try:
        return {"physical_memory_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
                "available_memory_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")}
    except (AttributeError, ValueError, OSError):
        return {"physical_memory_bytes": None, "available_memory_bytes": None}


_INSPECT = """import importlib.metadata as m,json,os,platform,site,sys
print(json.dumps({'sys_executable':sys.executable,'sys_prefix':sys.prefix,'sys_base_prefix':sys.base_prefix,'python_version':platform.python_version(),'sys_path':sys.path,'user_site_enabled':site.ENABLE_USER_SITE,'pid':os.getpid(),'packages':{d.metadata['Name']:d.version for d in m.distributions()}},sort_keys=True))
"""


def prepare_environment(run_folder, requirements, config, emit=None):
    """Install pins in a NEW venv and preserve both successful and failed setup.

    ``config`` supports ``wheelhouse`` (offline ``--no-index`` installation),
    ``pip_index_url``, ``pip_extra_index_url``/``pip_extra_index_urls``, and finite
    ``pip_install_timeout_seconds``/``pip_network_timeout_seconds``/``pip_retries``.
    A failed install returns ``status='failed'`` without trying a host interpreter.
    An existing environment directory raises FileExistsError and is untouched.
    """
    config = dict(config or {})
    run_folder = Path(run_folder).resolve()
    run_folder.mkdir(parents=True, exist_ok=True)
    folder = run_folder / "environment"
    folder.mkdir(exist_ok=False)
    requirements_path = folder / "requirements.txt"
    python = folder / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python = python.absolute()  # Do not resolve the venv symlink to its base Python.
    record_path = run_folder / "environment.json"
    record = {
        "schema_version": "step36-analysis-environment-1", "status": "running", "started_at": _now(),
        "mode": "fresh_install", "fresh_dependency_install_tested": False,
        "system_site_packages": False, "python": str(python), "launcher_python": sys.executable,
        "platform": platform.platform(), "os": platform.system(), "machine": platform.machine(),
        "cpu": platform.processor() or None, "cpu_count": os.cpu_count(), **_memory(),
        "accelerator_check": "not_required_for_saved_analysis; no model runtime imported",
        "requirements_file": str(requirements_path), "environment_folder": str(folder),
        "venv_creation": {"method": "venv.EnvBuilder(with_pip=True, system_site_packages=False, clear=False)",
                          "path": str(folder / "venv")},
        "install_stdout": str(folder / "install_stdout.log"), "install_stderr": str(folder / "install_stderr.log"),
        "pip_report": str(folder / "pip_report.json"), "pip_freeze": str(folder / "pip_freeze.txt"),
    }
    result = {"status": "failed", "python": str(python), "environment": record,
              "environment_file": str(record_path), "requirements_file": str(requirements_path)}
    started = time.monotonic()
    (folder / "install_stdout.log").write_text("", encoding="utf-8")
    (folder / "install_stderr.log").write_text("", encoding="utf-8")
    raw_report = folder / "pip_report.raw.json"
    _write_json(record_path, record)
    try:
        if config.get("environment_mode", "fresh_install") != "fresh_install":
            raise ValueError("This runner requires an independent fresh_install environment.")
        exact = _pins(requirements)
        requirements_path.write_text("\n".join(exact) + "\n", encoding="utf-8")
        record["requirements"] = exact
        install_timeout = float(config.get("pip_install_timeout_seconds", 600))
        network_timeout = float(config.get("pip_network_timeout_seconds", 30))
        retries = int(config.get("pip_retries", 1))
        if not 0 < install_timeout <= 3600 or not 0 < network_timeout <= 300 or not 0 <= retries <= 5:
            raise ValueError("Pip timeouts/retries must be finite and within the documented limits.")
        if emit:
            emit("Our team is creating the separate analysis environment.")
        # venv refuses no existing path on its own, so enforce that explicitly.
        if (folder / "venv").exists():
            raise FileExistsError("The analysis venv already exists; choose a new run directory.")
        venv.EnvBuilder(with_pip=True, system_site_packages=False, clear=False).create(folder / "venv")
        command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                   "--timeout", str(network_timeout), "--retries", str(retries), "--report", str(raw_report),
                   "-r", str(requirements_path)]
        wheelhouse = config.get("wheelhouse")
        if wheelhouse:
            wheelhouse = Path(wheelhouse).expanduser().resolve(strict=True)
            if not wheelhouse.is_dir():
                raise ValueError("wheelhouse must name an existing local directory.")
            command.extend(["--no-index", "--find-links", str(wheelhouse)])
            record["package_sources"] = {"mode": "local_wheelhouse", "wheelhouse": str(wheelhouse)}
        else:
            sources = {"mode": "configured_pip_index", "index_url": config.get("pip_index_url", "pip configured/default index")}
            if config.get("pip_index_url"):
                command.extend(["--index-url", str(config["pip_index_url"])])
            extra = config.get("pip_extra_index_urls", config.get("pip_extra_index_url", []))
            extra = [extra] if isinstance(extra, str) else list(extra)
            for url in extra:
                command.extend(["--extra-index-url", str(url)])
            sources["extra_index_urls"] = extra
            record["package_sources"] = redact(sources)
        record["install_command"] = redact(command)
        record["install_timeout_seconds"] = install_timeout
        _write_json(record_path, record)
        env = isolated_environment(run_folder, python)
        try:
            completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=install_timeout, check=False)
            stdout, stderr = completed.stdout, completed.stderr
            record["install_returncode"] = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout or "", exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            record["install_returncode"] = None
            record["install_timed_out"] = True
        (folder / "install_stdout.log").write_text(redact(stdout), encoding="utf-8")
        (folder / "install_stderr.log").write_text(redact(stderr), encoding="utf-8")
        if record.get("install_returncode") != 0:
            raise RuntimeError("Fresh-environment dependency installation failed; inspect the preserved install logs.")
        inspection = subprocess.run([str(python), "-I", "-c", _INSPECT], env=env, capture_output=True,
                                    text=True, timeout=60, check=False)
        (folder / "inspection_stderr.log").write_text(redact(inspection.stderr), encoding="utf-8")
        if inspection.returncode:
            raise RuntimeError("The new environment could not report its interpreter and installed packages.")
        observed = json.loads(inspection.stdout)
        record["interpreter"] = observed
        if observed["sys_prefix"] == observed["sys_base_prefix"] or observed["user_site_enabled"]:
            raise RuntimeError("The installed interpreter is not an isolated virtual environment.")
        observed_packages = {key.lower().replace("_", "-"): value for key, value in observed["packages"].items()}
        for requirement in exact:
            name, version = requirement.split("==")
            if observed_packages.get(name) != version:
                raise RuntimeError("Installed package does not match its analysis pin: " + name)
        frozen = subprocess.run([str(python), "-m", "pip", "freeze", "--all", "--disable-pip-version-check"],
                                env=env, capture_output=True, text=True, timeout=60, check=False)
        (folder / "pip_freeze.txt").write_text(redact(frozen.stdout), encoding="utf-8")
        (folder / "pip_freeze_stderr.log").write_text(redact(frozen.stderr), encoding="utf-8")
        if frozen.returncode:
            raise RuntimeError("Recording pip freeze failed in the new environment.")
        kernel_name = "step36-analysis"
        kernel_folder = run_folder / "jupyter_data" / "kernels" / kernel_name
        kernel_folder.mkdir(parents=True, exist_ok=False)
        spec = {"argv": [str(python), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                "display_name": "Step 36 isolated analysis", "language": "python"}
        _write_json(kernel_folder / "kernel.json", spec)
        record.update({"status": "passed", "fresh_dependency_install_tested": True,
                       "kernel_name": kernel_name, "kernel_spec": spec,
                       "kernel_spec_path": str(kernel_folder / "kernel.json"),
                       "jupyter_data_dir": str(run_folder / "jupyter_data")})
        result.update({"status": "passed", "kernel_name": kernel_name,
                       "kernel_spec_path": str(kernel_folder / "kernel.json"),
                       "jupyter_data_dir": str(run_folder / "jupyter_data")})
        if emit:
            emit("Our team installed and recorded the pinned analysis dependencies.")
    except Exception as exc:
        record.update({"status": "failed", "error_type": type(exc).__name__, "error": redact(str(exc))})
        if emit:
            emit("Our team retained the failed environment setup and its logs.")
    finally:
        if raw_report.exists():
            try:
                _write_json(folder / "pip_report.json", redact(json.loads(raw_report.read_text(encoding="utf-8"))))
            except (ValueError, OSError) as exc:
                _write_json(folder / "pip_report.json", {"status": "unreadable", "error": redact(str(exc))})
            raw_report.unlink()
        elif not (folder / "pip_report.json").exists():
            _write_json(folder / "pip_report.json", {"status": "not_produced", "install_returncode": record.get("install_returncode")})
        if python.exists() and not (folder / "pip_freeze.txt").exists():
            # Failure evidence should show any packages actually left installed,
            # including pip/setuptools in an otherwise empty new environment.
            try:
                env = isolated_environment(run_folder, python)
                frozen = subprocess.run([str(python), "-m", "pip", "freeze", "--all", "--disable-pip-version-check"],
                                        env=env, capture_output=True, text=True, timeout=30, check=False)
                (folder / "pip_freeze.txt").write_text(redact(frozen.stdout), encoding="utf-8")
                (folder / "pip_freeze_stderr.log").write_text(redact(frozen.stderr), encoding="utf-8")
                record["freeze_returncode"] = frozen.returncode
                if "interpreter" not in record:
                    inspected = subprocess.run([str(python), "-I", "-c", _INSPECT], env=env, capture_output=True,
                                               text=True, timeout=30, check=False)
                    if inspected.returncode == 0:
                        record["interpreter"] = json.loads(inspected.stdout)
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                record["failed_setup_inspection_error"] = redact(str(exc))
        if not (folder / "pip_freeze.txt").exists():
            (folder / "pip_freeze.txt").write_text("", encoding="utf-8")
            record["freeze_status"] = "not_produced"
        record.update({"finished_at": _now(), "elapsed_seconds": round(time.monotonic() - started, 6)})
        _write_json(record_path, redact(record))
    return result
