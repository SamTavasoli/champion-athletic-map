# Results reproduction

We check a dedicated saved-results notebook in a new Python environment and a fresh kernel. We preserve the original experiment and compare its saved outputs with a separately recalculated copy.

Current verification: **needs_attention**. Source analysis: `d5e368e9f92725a9d3892b1d32878294d5bac243215dfb7f313ce69347daeba5`.

## Tested route

From the repository root, using the project Python interpreter:

```powershell
python results/reproducibility/repro_20261117T171907Z_89717b4e/reproduce.py --project-root .
```

This creates another versioned verification run. It does not resume or overwrite this run. The route installs its analysis dependencies into a new environment; package downloads may require an internet connection during setup. The analysis itself runs with network access disabled. No existing project package versions are changed.

The top-level analysis requirements for this run are:

```text
ipykernel==7.4.0
matplotlib==3.11.2
nbclient==0.10.4
nbformat==5.10.4
numpy==2.5.4
```

The resolved dependency versions, installation command, package report and freeze are recorded under `environment/`. For setup from the resolved lock, use a separate environment and `python -m pip install -r environment/pip_freeze.txt`; that exact resolved-lock reinstallation is a documented route, not a separate tested claim. Source artifacts must be present under the original recorded project-relative paths. Missing evidence stops the check instead of triggering downloads, retraining or replacement responses.

## What is compared

We verify IDs, statuses, counts, denominators, group membership and decoded bootstrap draws exactly. Documented numerical metrics use relative tolerance 1e-10 and absolute tolerance 1e-12. Figure source values and rendered labels/populations are checked; metadata or renderer-only changes are recorded separately. The full declared rules are in `verification_config.json`. Protected source files are hashed before and after the run.

## Scope

This verification concerns the dedicated results-only notebook and the selected Step 35 evidence. It does not establish that all 39 steps of the main project notebook execute cleanly from the beginning. The historical Step 12 catalog notebook is retained as build history, not claimed to have been reexecuted here. Data rebuilding, training repetition and live-backend generation remain separate, untested procedures in this run. Recorded team decisions and the single assisted response review are loaded unchanged; independent teammate agreement is not invented.

The run preserves the input inventory, environment, source code, standalone notebook, executed notebook, execution logs, result comparisons and protection checks. The external runner writes the completion record after notebook execution and comparison. Unexpected errors leave the partial notebook and failure details available.

The setup supports Python virtual environments and Jupyter notebook execution. Relevant primary documentation: [Python venv](https://docs.python.org/3/library/venv.html) and [NBClient execution](https://nbclient.readthedocs.io/en/latest/client.html).
