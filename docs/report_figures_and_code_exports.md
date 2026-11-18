# Report figures and code exports

We use the existing final analysis figures and readable source exports to support the report. Copying a figure or exporting a notebook does not rerun an experiment or change a result.

## Final figures

The current source folder is `results/statistical_analysis/analysis_d5e368e9f92725a9d389/figures/`. Its parent `output_manifest.json` records the original output hashes. The Step 35 summary points to the same analysis, and Step 36 reproduced its 37 outputs.

| Source figure | Suggested report caption | Interpretation |
|---|---|---|
| `planner_execution.svg` | Response format and workflow completion for four planning workflows on 200 matched fictional profiles each. | Workflow completion and correct format are separate; neither establishes complete request fulfillment. |
| `planner_runtime.svg` | Median local workflow time across all 200 terminal outcomes per planner, including failures. | The figures describe this setup and these workflows; they are not deployment-cost estimates. |
| `classifier_macro_f1_differences.svg` | Paired classifier Macro-F1 differences with individual 95% exercise-group bootstrap intervals from 2,000 resamples. | The same held-out exercise groups are paired across classifiers; intervals describe the saved test outputs. |

Use the SVG files for scalable report graphics. Keep their source folder and manifest unchanged. To make report copies from the project root in PowerShell:

```powershell
New-Item -ItemType Directory -Force reports/figures | Out-Null
Copy-Item results/statistical_analysis/analysis_d5e368e9f92725a9d389/figures/*.svg reports/figures/
```

The copies retain the existing figure bytes. We have not rerendered or substituted the figures in this documentation package. In particular, software-test classifier plots must not replace the final classifier figure.

The classifier values and planner counts are also available as tables in the final analysis folder. Use those tables when a report needs exact numbers. See [the results discussion](results_limitations_and_future_improvements.md) for the verification limits that belong with the figures.

## Readable helper exports included here

`reports/code_exports/` contains plain Python copies of the helpers embedded in the delivered Steps 35–37 notebooks. We checked their bytes against the corresponding notebook sources. `export_manifest.json` lists the source notebook, module name and SHA-256 for each export.

| Folder | Exported code |
|---|---|
| `step35/` | Statistical calculations, classifier-input adapter, retrieval analysis, native-runtime analysis and analysis runner. |
| `step36/` | Reproduction input checks, environment preparation, notebook runner, output comparator, comparison runner and coordinator. |
| `step37/` | Results-discussion writer. |

These exports make the helper code readable without decoding notebook payloads. Some helpers use imports and configuration supplied by their notebook or versioned reproduction folder. They are not advertised as standalone command-line programs. The existing project modules under `src/champion_athletic_map/` remain the authoritative implementation for the classifiers, references, planners and interface.

## Export the current main notebook

To export the latest local main notebook as Python, use an environment with `nbconvert` installed:

```powershell
python -m nbconvert --to python notebooks/champion_athletic_map.ipynb --output-dir reports/code_exports
```

This converts the notebook without executing it. We have not claimed an export of the current full main notebook in this package; the readable helper exports are the code copies already included. Run the command above on the current project notebook when preparing its report copy.

An exported notebook can retain IPython calls, cell-order dependencies and cells that train models or submit planner requests. Do not use a full-script execution as a shortcut for reading saved results. The tested analysis entry point remains:

```powershell
python results/reproducibility/repro_20261117T174153Z_3e7049a7/reproduce.py --project-root .
```

See [the reproduction guide](reproducibility.md) for the required saved inputs and execution scope.

## Documentation package scope

This package supplies the completed README, technical guide, figure/source index and readable helper exports. It does not contain upstream datasets, model weights, copied raw planner replies or a replacement set of research figures. The existing local project supplies those versioned resources. The README is a finished Markdown file; no cell or script is needed to create it.
