# Champions Athletic Map

Champions Athletic Map is our AAI 590 capstone project at the University of San Diego. We built a local basketball-planning prototype for athletes ages 13–17, parents and coaches. The project combines exercise-text classification, basketball references, recorded food facts and four language-model planning workflows.

Our question was whether adding references, specialist roles and review steps would improve weekly planning compared with a language model alone. We completed the comparison and kept the unsuccessful responses as part of the results.

**Current status — November 17, 2026:** the classifier evaluation, final planner comparison, results analysis and saved-analysis reproduction are complete. The interface supports saved examples, edits, progress tracking and file restoration. Reliable end-to-end planning remains unfinished, and live generation in the interface remains gated.

## Start here

- [Main project notebook](notebooks/champion_athletic_map.ipynb): our preparation, experiments, observations and project workflow.
- [Prototype user guide](docs/prototype_user_guide.md): opening saved examples, editing plans and restoring files.
- [Technical guide](docs/technical_guide.md): components, data flow, execution boundaries and saved results.
- [Results and limitations](docs/results_limitations_and_future_improvements.md): our discussion from Step 37.
- [Statistical analysis](docs/statistical_analysis_findings.md): the comparison tables and interpretation from Step 35.
- [Reproducibility guide](docs/reproducibility.md): the tested saved-results route from Step 36.
- [Figures and code exports](docs/report_figures_and_code_exports.md): source files, captions and export instructions.

## What we built

| Component           | Purpose                                                      | What the results establish                                   |
| ------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| Exercise classifier | Predict a supported body-part category from an exercise name and description. | Performance on a held-out exercise-text test set.            |
| Reference search    | Find relevant basketball and supporting guidance from our frozen sources. | Ranking performance on the saved retrieval questions.        |
| Food lookup         | Return recorded nutrient values for a stated amount of a selected food. | Source-linked food facts; it does not prescribe a diet.      |
| Four planners       | Compare progressively more involved weekly-planning workflows. | Recorded format, execution, timing and request-check results on fictional profiles. |
| Local interface     | View and edit saved plans, track completion and restore snapshots. | Tested interface behavior; it does not establish reliable live planning. |

The exercise classifier and basketball planners solve different tasks. A body-part prediction does not approve an exercise for a young athlete or make it a suitable basketball drill. Gym exercise records remain unavailable to the planner under our current resource decisions.

## Models and planning workflows

We trained and compared a majority baseline, TF-IDF with logistic regression, and a neural exercise classifier. **L5 logistic regression** was selected using validation results and remained the selected classifier for the final test.

For reference search, we used the pretrained `all-MiniLM-L6-v2` sentence encoder. For planning, all four versions used the same local **`llama3.1:8b` model through Ollama**. We did not train or fine-tune that language model. Specialist roles are separate prompted calls to the same model.

| Planner                       | Workflow                                                     |
| ----------------------------- | ------------------------------------------------------------ |
| 1 — Language model alone      | Use the supplied athlete information without retrieved references. |
| 2 — With references           | Add a reference packet and recorded lookup information.      |
| 3 — With specialist roles     | Add specialist contributions and combine them into a response. |
| 4 — With checks and revisions | Add coded checks, an evaluator and a bounded revision process. |

The final cases were matched across the four versions. Planners 2–4 shared the reference packet for a given case. Reference access was managed by Python; native language-model tool calling was not enabled. Private benchmark expectations stayed outside the model inputs.

## Final results

### Exercise classification

The final test contained **438 records in 385 exercise groups across 16 categories**. Macro-F1 was our primary classifier measure; accuracy provides additional context.

| Classifier             |   Macro-F1 |   Accuracy |
| ---------------------- | ---------: | ---------: |
| Majority baseline      |     0.0234 |     23.06% |
| L5 logistic regression | **0.6143** | **73.29%** |
| N3 neural classifier   |     0.5288 |     67.81% |

L5 performed best among these tested classifiers. The result concerns exercise-text categories, not basketball-plan quality or athlete outcomes.

### Reference search

We retained **30 held-out questions in 15 families**: 20 supported, two partly supported and eight unsupported. The original ranking population contained 24 questions with nonempty relevant-reference sets.

| Saved ranking measure                   | Result |       Scored questions |
| --------------------------------------- | -----: | ---------------------: |
| Mean Recall@5                           | 1.0000 |                     24 |
| MRR@5                                   | 0.9792 |                     24 |
| Complete ranked evidence-set coverage@5 | 1.0000 | 20 supported questions |

All 30 queries returned candidates, including unsupported requests. Strong ranking does not establish that a request is answerable, that all required facts reached the planner or that its answer used them correctly. We preserved the source labels and denominators when they differed from the earlier planned answerability counts.

### Four-planner comparison

We evaluated **200 fictional profiles with all four workflows: 800 saved outcomes**. Of the 200 profiles, 150 were feasible planning requests, 20 lacked information, 15 contained conflicting constraints and 15 were outside scope. The full comparison used **2,636 cumulative local model submissions**, including specialist, evaluator and revision calls.

| Planner                       | Valid format | Workflow completed | Valid completed plans | Coded checks passed | Full verification | Median time |
| ----------------------------- | -----------: | -----------------: | --------------------: | ------------------: | ----------------: | ----------: |
| 1 — Language model alone      |       75/200 |            199/200 |                45/150 |               0/150 |             0/150 |     10.57 s |
| 2 — With references           |       62/200 |            186/200 |                40/150 |               0/150 |             0/150 |     18.41 s |
| 3 — With specialist roles     |       67/200 |            199/200 |                39/150 |               0/150 |             0/150 |     26.98 s |
| 4 — With checks and revisions |       69/200 |            198/200 |                47/150 |               0/150 |             0/150 |     62.10 s |

Format and workflow completion use all 200 profiles per planner. Plan and verification counts use the 150 feasible requests. Timing includes all terminal outcomes, including failures. A valid completed plan has the required structure and declares a plan; it may still violate the request. A completed Planner 4 workflow may reach its revision limit without internal acceptance.

The baseline returned the most correctly formatted replies overall and took the least time. Planner 4 returned slightly more valid completed plans for feasible requests but took much longer. None of its final outcomes was internally accepted. More involved workflows did not consistently improve the recorded measures, so we did not select a generally superior planner.

No generated plan achieved full verification. The automatic goal check was unfinished and resource checking had limited coverage. Saved assessments also found actual errors, including missing or changed existing commitments, incorrect session counts and exceeded training limits. Unresolved checks remain separate from observed violations.

### Team review and uncertainty

Our supplementary team review covered **160 replies from 40 selected profiles**, with 800 entries across five separate dimensions. It used one assisted review. Two independent teammate rating sets were not collected, so reviewer agreement was not estimated. The sample contained 25 feasible and 15 challenge profiles; its pooled ratings do not represent all 800 outcomes.

Step 35 retained four matched planner contrasts and 2,000 paired group resamples with seed 42. Zero-success verification flags produced constant intervals; these do not establish equal planner quality or zero uncertainty beyond this benchmark. Some planner numerical conventions were clarified during analysis after the results were available and are recorded in the method note.

## Open the local prototype

Use the prepared project environment and the saved data and artifacts described below. From the project root in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run app/streamlit_app.py --server.address 127.0.0.1
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). If Streamlit asks for an email address on the first run, leave it blank and press Enter to continue. Stop the server with `Ctrl+C`.

The tested interface supports:

1. Loading a saved fictional example and viewing its response status.
2. Editing athlete information or a proposed session and saving a new version.
3. Marking sessions pending, completed or skipped, then choosing **Update progress**.
4. Downloading CSV or a JSON snapshot.
5. Restoring a JSON snapshot explicitly, including compatible saved edits and progress.

Changes to session definitions can reset the affected progress entry. Progress is self-reported completion, not a measure of athletic improvement. Download a JSON snapshot to retain work across browser sessions.

Live generation and model review require a separate matching application readiness record. Completing the research comparison does not enable them automatically. Saved development plans can contain known errors, and editing a plan makes an earlier model review historical.

### Environment and required inputs

Our development work used Windows and Python 3.12.6. Use the recorded release environments for classifier loading. `requirements/prototype.txt` pins the Streamlit interface dependency; it is **not a complete dependency lock for the research project**. The November 9 environment record is historical. Step 36 records the separately installed analysis environment used for the successful reproduction.

The prepared unified dataset belongs in `data/unified/v1/`, with these four files unchanged:

- `READ_ME_FIRST.txt`
- `champions_unified_dataset.csv`
- `dataset_manifest.json`
- `load_unified_dataset.py`

The project also needs its saved schemas, prompts, reference index, approved resource release, classifier artifacts, planner configurations and result files. A source-only checkout is not sufficient to reproduce every experiment. The source register and saved manifests identify the required versions.

We used the master dataset package as part of our source inventory and preparation. We used the exercise data for classification and source-linked basketball and food records for their respective tools. The unified dataset supplies a shared input format; it does not mean that the entire master CSV was sent to the language model or used to train it.

## Reproduce the saved results analysis

Step 36 passed **37 output comparisons** in a separate environment and fresh kernel. The protected originals stayed unchanged, with no new model calls.

From the root of the complete prepared project, the successful run provides this command:

```powershell
python results/reproducibility/repro_20261117T174153Z_3e7049a7/reproduce.py --project-root .
```

It creates another verification folder, installs dependencies into a separate environment, recalculates the saved analysis and compares the outputs. Package installation may require internet access; the analysis runs with network access disabled. It does not repeat classifier training or generate another set of planner replies.

The tested route covers saved-results analysis. A complete fresh-clone rebuild of data preparation, training and live generation remains a separate task. See [the reproduction guide](docs/reproducibility.md) for the recorded requirements and comparison rules.

## Software checks

Step 30 recorded **248 passing checks and no failures** after its corrections. That is a historical result for the prepared suite, not a claim that the entire later project was freshly retested together. Later steps recorded their own targeted checks.

The recorded controlled runner is:

```powershell
python tests/run_step30.py
```

It verifies its recorded source bindings before running. Later source changes can cause it to stop rather than silently test a different version. Software checks, planner output checks and team ratings measure different things.

## Report figures and code exports

Our final analysis figures are in:

```text
results/statistical_analysis/analysis_d5e368e9f92725a9d389/figures/
```

| Figure                                | Content                                                      |
| ------------------------------------- | ------------------------------------------------------------ |
| `planner_execution.svg`               | Format validity and workflow completion across all 200 profiles per planner. |
| `planner_runtime.svg`                 | Median all-terminal workflow time, including failures.       |
| `classifier_macro_f1_differences.svg` | Matched classifier Macro-F1 differences and individual 95% exercise-group bootstrap intervals. |

To copy the existing SVGs for the report, without recalculating them:

```powershell
New-Item -ItemType Directory -Force reports/figures | Out-Null
Copy-Item results/statistical_analysis/analysis_d5e368e9f92725a9d389/figures/*.svg reports/figures/
```

Readable helper-source exports for Steps 35–37 accompany this documentation in `reports/code_exports/`. Their manifest records source hashes. The project's `src/` modules and versioned notebook remain the primary implementation.

To export the current main notebook as Python without executing it, use an environment with `nbconvert` installed:

```powershell
python -m nbconvert --to python notebooks/champion_athletic_map.ipynb --output-dir reports/code_exports
```

This command is an optional export instruction; it does not create the README. The exported notebook can retain cell-order dependencies, IPython commands and expensive experiment calls. Exporting it does not make it a standalone reproduction program. Use the tested Step 36 route for saved-analysis reproduction.

## Project layout

| Location                     | Contents                                                     |
| ---------------------------- | ------------------------------------------------------------ |
| `notebooks/`                 | Main project notebook and preparation history.               |
| `src/champion_athletic_map/` | Classifier, reference, planner, checking and application modules. |
| `app/`                       | Streamlit entry point.                                       |
| `data/`                      | Registered inputs and unified dataset files.                 |
| `artifacts/`                 | Versioned models, schemas, prompts, reference resources and configurations. |
| `results/`                   | Saved replies, assessments, reviews, analysis and reproduction evidence. |
| `reports/`                   | Report assets and readable code exports.                     |
| `docs/`                      | User instructions, technical notes, methods and findings.    |
| `requirements/`              | Dependency files for specific project components.            |
| `tests/`                     | Software checks and controlled test fixtures.                |

## Limitations and next improvements

We evaluated fictional profiles with one local planning model and fixed saved outcomes. We did not measure changes in real athletes' performance. The system has incomplete goal checking, limited resource verification and a single assisted review stream.

Our next priorities are to construct calendars with explicit scheduling logic, preserve existing commitments, validate approved drill requirements, display food facts directly from verified lookups and complete the missing checks. We would simplify the prompts and response structure before comparing further workflow or model changes. Changes based on these final results need a new experiment version and fresh evaluation cases.

The prototype provides general planning support and recorded food facts. Medical diagnosis, injury rehabilitation and dietary prescriptions are outside its scope.

## Sources and resource decisions

The source register is [data/source_manifest.csv](data/source_manifest.csv). Dataset packages and frozen manifests retain source identities, versions and file hashes. Our resource activation recorded 127 available basketball records, nine general warm-ups and 29 rule definitions; seven drill records were held. Resource availability does not establish individual suitability or prove that a plan follows every rule.

Upstream datasets, guidance and model weights retain their source-specific terms. Team approval for use in this project does not grant blanket redistribution rights. Preserve the recorded attribution and usage notices when sharing source-derived material. CDC references are used for this educational project with their source notices; CDC does not endorse this project. No new blanket license for third-party material is introduced by this README.

## Team

AAI 590, Team 6 — Aditi Jha, Beakal Zekaryas and Saman (Sam) Tavasoli.

Repository: [SamTavasoli/champion-athletic-map](https://github.com/SamTavasoli/champion-athletic-map). This README describes the completed local work through Step 37; a remote checkout contains these outputs only after the corresponding project files are published.