"""External fresh-kernel executor for a standalone saved-analysis notebook.

Run ONLY with the new environment's Python::

    <run>/environment/venv/bin/python notebook_driver.py --config driver_config.json

The caller writes the notebook before launch.  The driver never launches itself,
generates model responses, or performs the final scientific result comparisons.
"""
from __future__ import annotations

import argparse
import atexit
import datetime as _datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback


def _now():
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _same_interpreter(actual, expected):
    # Resolving venv/bin/python symlinks would incorrectly accept the base Python.
    return os.path.normcase(os.path.abspath(actual)) == os.path.normcase(os.path.abspath(expected))


def _configure_paths(run_folder, python):
    for name in ("PYTHONPATH", "PYTHONHOME", "IPYTHONDIR", "JUPYTER_PATH", "JUPYTER_CONFIG_PATH"):
        os.environ.pop(name, None)
    paths = {"IPYTHONDIR": "ipython", "MPLCONFIGDIR": "matplotlib_config", "JUPYTER_DATA_DIR": "jupyter_data",
             "JUPYTER_CONFIG_DIR": "jupyter_config", "JUPYTER_RUNTIME_DIR": "jupyter_runtime"}
    for variable, name in paths.items():
        path = run_folder / name
        path.mkdir(parents=True, exist_ok=True)
        os.environ[variable] = str(path)
    os.environ.update({"PYTHONNOUSERSITE": "1", "JUPYTER_NO_CONFIG": "1", "MPLBACKEND": "Agg",
                       "JUPYTER_PATH": str(run_folder / "jupyter_data"),
                       "VIRTUAL_ENV": str(python.parent.parent)})
    os.environ["PATH"] = str(python.parent) + os.pathsep + os.environ.get("PATH", "")


def _local_path(config, key, default, run_folder):
    path = Path(config.get(key, default)).absolute()
    if not path.resolve().is_relative_to(run_folder.resolve()):
        raise ValueError(key + " must remain inside the new verification run.")
    return path


def _kernel_transport(config, run_folder):
    """Use official Jupyter IPC support on POSIX without opening TCP sockets."""
    transport = config.get("kernel_transport", "tcp" if os.name == "nt" else "ipc")
    if transport not in {"tcp", "ipc"}:
        raise ValueError("kernel_transport must be 'ipc' or 'tcp'.")
    if transport == "ipc" and os.name == "nt":
        raise ValueError("The IPC kernel transport is supported here only on POSIX.")
    temporary = None
    prefix = None
    if transport == "ipc":
        prefix = run_folder / "jupyter_runtime" / "k"
        # libzmq appends '-<channel number>' to this prefix. POSIX sockaddr_un
        # implementations commonly allow 108 bytes including the terminal NUL.
        if len(os.fsencode(str(prefix))) + len("-65535") + 1 >= 108:
            temporary = tempfile.TemporaryDirectory(prefix="s36-", dir="/tmp")
            prefix = Path(temporary.name) / "k"
    return transport, prefix, temporary


def execute(config):
    """Execute once; always retain a partial notebook and external status file.

    Required config: ``run_folder``, ``stage_root``, ``notebook_path``. Optional:
    ``python`` (defaults to this interpreter), ``kernel_name`` (step36-analysis),
    ``executed_notebook_path``, ``kernel_info_path``, ``execution_timeout`` (1200),
    ``startup_timeout`` (60), ``environment_file``, ``kernel_transport`` (POSIX
    default ``ipc``; Windows default ``tcp``). The notebook itself writes
    ``kernel_info_path`` using standard-library metadata in its first code cell.
    """
    run_folder = Path(config["run_folder"]).absolute()
    run_folder.mkdir(parents=True, exist_ok=True)
    record_path = run_folder / "kernel_execution.json"
    started = time.monotonic()
    record = {"schema_version": "step36-kernel-execution-1", "status": "running", "started_at": _now(),
              "driver_pid": os.getpid(), "driver_python": sys.executable, "fresh_kernel": False,
              "allow_errors": False, "notebook_completed": False, "kernel_info_verified": False}
    notebook = None
    raw_notebook = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    executed = run_folder / "executed_notebook.ipynb"
    nbformat_module = None
    manager = None
    client = None
    ipc_temporary = None
    try:
        executed = _local_path(config, "executed_notebook_path", executed, run_folder)
        notebook_path = _local_path(config, "notebook_path", run_folder / "reproduction_notebook.ipynb", run_folder)
        info_path = _local_path(config, "kernel_info_path", run_folder / "kernel_info.json", run_folder)
        stage_root = Path(config["stage_root"]).absolute()
        if not stage_root.is_dir() or not stage_root.resolve().is_relative_to(run_folder.resolve()):
            raise ValueError("stage_root must be an existing copied project inside the verification run.")
        python = Path(config.get("python", sys.executable)).absolute()
        timeout = int(config.get("execution_timeout", 1200))
        startup_timeout = int(config.get("startup_timeout", 60))
        if not 0 < timeout <= 1200 or not 0 < startup_timeout <= 60:
            raise ValueError("Kernel timeouts must be positive, at most 1200 seconds per cell and 60 seconds for startup.")
        kernel_name = config.get("kernel_name", "step36-analysis")
        if not isinstance(kernel_name, str) or not kernel_name or Path(kernel_name).name != kernel_name:
            raise ValueError("Invalid run-local kernel name.")
        record.update({"notebook_path": str(notebook_path), "executed_notebook_path": str(executed),
                       "stage_root": str(stage_root), "expected_python": str(python), "kernel_name": kernel_name,
                       "execution_timeout_seconds": timeout, "startup_timeout_seconds": startup_timeout,
                       "kernel_info_path": str(info_path)})
        _write_json(record_path, record)
        raw_notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        if not _same_interpreter(sys.executable, python) or sys.prefix == sys.base_prefix:
            raise RuntimeError("The external driver must run with the new isolated environment's Python.")
        if os.environ.get("PYTHONPATH") or os.environ.get("PYTHONHOME"):
            raise RuntimeError("The external driver must be launched without inherited PYTHONPATH or PYTHONHOME.")
        import site
        if site.ENABLE_USER_SITE:
            raise RuntimeError("User site packages are enabled in the external driver.")
        pyvenv_config = Path(sys.prefix) / "pyvenv.cfg"
        if not pyvenv_config.is_file() or "include-system-site-packages = false" not in pyvenv_config.read_text(encoding="utf-8").lower():
            raise RuntimeError("The external driver requires system_site_packages=False.")
        _configure_paths(run_folder, python)
        transport, ipc_prefix, ipc_temporary = _kernel_transport(config, run_folder)
        record.update({"kernel_transport": transport, "ipc_prefix": str(ipc_prefix) if ipc_prefix else None,
                       "ipc_temporary_directory": ipc_temporary.name if ipc_temporary else None})
        if info_path.exists():
            raise FileExistsError("A kernel-info record already exists; a new run must not reuse a prior kernel result.")
        # Import Jupyter only after selecting run-local paths. The kernel is
        # explicitly bound to this one kernelspec, independent of user/global specs.
        import nbformat
        from nbclient import NotebookClient
        from jupyter_client import KernelManager
        from jupyter_client.kernelspec import KernelSpecManager
        nbformat_module = nbformat
        # We read the on-disk format so source-line lists become cell text.
        notebook = nbformat.reads(json.dumps(raw_notebook, ensure_ascii=False), as_version=4)
        nbformat.validate(notebook)
        if any(not isinstance(cell.get("source", ""), str) for cell in notebook.cells):
            raise ValueError("The notebook reader did not return text for every cell.")
        for cell in notebook.cells:
            if cell.cell_type == "code":
                cell.outputs = []
                cell.execution_count = None
        spec_root = run_folder / "jupyter_data" / "kernels"
        spec_path = spec_root / kernel_name / "kernel.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if not spec.get("argv") or not _same_interpreter(spec["argv"][0], python):
            raise RuntimeError("The run-local kernel spec does not select the new environment's Python.")
        spec_manager = KernelSpecManager(kernel_dirs=[str(spec_root)], ensure_native_kernel=False)
        manager_options = {"kernel_name": kernel_name, "kernel_spec_manager": spec_manager,
                           "transport": transport,
                           "connection_file": str(run_folder / "jupyter_runtime" / "kernel.json")}
        if ipc_prefix is not None:
            manager_options["ip"] = str(ipc_prefix)
        manager = KernelManager(**manager_options)
        client = NotebookClient(notebook, km=manager, timeout=timeout, startup_timeout=startup_timeout,
                                allow_errors=False, resources={"metadata": {"path": str(stage_root)}},
                                record_timing=True)
        record.update({"kernel_spec_path": str(spec_path), "kernel_spec": spec,
                       "kernel_start_requested_at": _now(), "fresh_kernel_requested": True})
        _write_json(record_path, record)
        print("Our team is replaying the saved analysis in a new kernel.", flush=True)
        client.execute(env=dict(os.environ), cleanup_kc=True)
        errors = [{"cell_index": index, "ename": output.get("ename"), "evalue": output.get("evalue")}
                  for index, cell in enumerate(notebook.cells) if cell.cell_type == "code"
                  for output in cell.get("outputs", []) if output.get("output_type") == "error"]
        counts = [cell.execution_count for cell in notebook.cells if cell.cell_type == "code"]
        record.update({"cell_errors": errors, "code_cell_count": len(counts), "execution_counts": counts,
                       "notebook_completed": True, "fresh_kernel": True})
        if errors or not counts or any(count is None for count in counts):
            raise RuntimeError("Notebook execution did not complete every code cell without errors.")
        kernel_info = json.loads(info_path.read_text(encoding="utf-8"))
        record["kernel_interpreter"] = kernel_info
        if type(kernel_info.get("pid")) is not int or kernel_info["pid"] == os.getpid():
            raise RuntimeError("The notebook did not record a separate kernel process identity.")
        if not _same_interpreter(kernel_info["sys_executable"], python):
            raise RuntimeError("The notebook kernel did not use the new environment's Python.")
        if kernel_info["sys_prefix"] == kernel_info["sys_base_prefix"] or kernel_info.get("user_site_enabled", False):
            raise RuntimeError("The notebook kernel did not report an isolated virtual environment.")
        if "packages" not in kernel_info or not isinstance(kernel_info["packages"], dict):
            raise RuntimeError("The notebook did not record its installed package versions.")
        environment_file = _local_path(config, "environment_file", run_folder / "environment.json", run_folder)
        environment = json.loads(environment_file.read_text(encoding="utf-8"))
        if environment.get("status") != "passed" or not environment.get("fresh_dependency_install_tested"):
            raise RuntimeError("A successful fresh dependency installation record is required.")
        if not _same_interpreter(environment["python"], python):
            raise RuntimeError("The successful environment record identifies a different interpreter.")
        packages = {key.lower().replace("_", "-"): value for key, value in kernel_info["packages"].items()}
        for requirement in environment["requirements"]:
            name, version = requirement.split("==")
            if packages.get(name) != version:
                raise RuntimeError("The notebook package version differs from the fresh-install pin: " + name)
        record.update({"status": "passed", "kernel_info_verified": True})
        print("Our team completed the fresh-kernel notebook replay.", flush=True)
    except Exception as exc:
        record.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc),
                       "traceback": traceback.format_exc()})
        if notebook is not None:
            record["cell_errors"] = [{"cell_index": index, "ename": output.get("ename"), "evalue": output.get("evalue")}
                                     for index, cell in enumerate(notebook.cells) if cell.cell_type == "code"
                                     for output in cell.get("outputs", []) if output.get("output_type") == "error"]
            record["execution_counts"] = [cell.execution_count for cell in notebook.cells if cell.cell_type == "code"]
            if any(count is not None for count in record["execution_counts"]):
                record["fresh_kernel"] = True
        print("Our team retained the partial notebook and execution error.", flush=True)
    finally:
        # The manager is explicitly supplied, so the driver also owns shutdown.
        # Startup failures in nbclient 0.10.4 can precede its cleanup context.
        if manager is not None:
            try:
                if manager.has_kernel:
                    manager.shutdown_kernel(now=True)
                manager.cleanup_resources()
                if client is not None and client.kc is not None:
                    client.kc.stop_channels()
                record["kernel_cleanup_completed"] = True
            except Exception as cleanup_error:
                record.update({"status": "failed", "kernel_cleanup_completed": False,
                               "kernel_cleanup_error": str(cleanup_error)})
            if client is not None:
                atexit.unregister(client._cleanup_kernel)
        if ipc_temporary is not None:
            try:
                ipc_temporary.cleanup()
                record["ipc_temporary_directory_removed"] = not Path(ipc_temporary.name).exists()
            except OSError as cleanup_error:
                record.update({"status": "failed", "ipc_temporary_directory_removed": False,
                               "ipc_cleanup_error": str(cleanup_error)})
        # Even import/setup failures leave the caller's unexecuted copy available.
        try:
            executed.parent.mkdir(parents=True, exist_ok=True)
            if notebook is not None and nbformat_module is not None:
                nbformat_module.write(notebook, str(executed))
            else:
                _write_json(executed, raw_notebook)
            record["partial_or_completed_notebook_saved"] = True
        except Exception as save_error:
            record.update({"status": "failed", "notebook_save_error": str(save_error),
                           "partial_or_completed_notebook_saved": False})
        record.update({"finished_at": _now(), "elapsed_seconds": round(time.monotonic() - started, 6)})
        _write_json(record_path, record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    config = json.loads(Path(arguments.config).read_text(encoding="utf-8"))
    result = execute(config)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
