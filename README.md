# Champions Athletic Map

**University of San Diego · AAI 590 Capstone · Team 6**

Aditi Jha, Beakal Zekaryas, and Saman Tavasoli

We built Champions Athletic Map for basketball players ages 13–17 and the parents and coaches who help them plan their week. An athlete might have a ball, two free evenings, and a goal of improving their dribbling. Could a planner suggest drills they can actually do, fit them into those evenings, and leave their team practices alone?

We compared four ways to generate a weekly plan. Giving the model references, specialist roles, and a chance to revise its work did not consistently improve the results. Our exercise classifier matched 321 of 438 held-out body-part labels. In a separate application, two runs of one dribbling request produced the same two-session calendar. The notebook shows where each part worked and where it fell short.

## Start here

1. [Ten-step master notebook](notebooks/Champion_athletic_map_master_notebook.ipynb). Start here for the full project. The tables, charts, calendars, recovery guidance, food facts, and conclusions are saved in the notebook. You can read them without installing anything or running a cell.
2. [Development notebook](notebooks/champion_athletic_map.ipynb). This is our original 39-step workflow, including the training runs, failed planner responses, changes we tested, and the reasons for our decisions.
3. [Basketball catalog build history](notebooks/step12_basketball_catalog_build_history.ipynb). This shows how we traced a drill back to its practice plan, handled repeated appearances, and recorded what still needed team review.

Steps 1–3 of the master notebook cover loading, cleaning, and exploring the Unified dataset. Steps 4–6 explain the frozen splits, trainable models, and held-out classifier results. Steps 7–9 move from reference search to plan generation and the four-planner comparison. Step 10 walks through the fictional athlete’s week and shows exactly what the separate live application returned.

## Exercise classification

We wanted to suggest a body-part label for each exercise using its name and description. The Unified dataset contains 2,909 exercise records. We used the 2,872 eligible records and kept related exercises together in the original splits. That gave us 1,999 training exercises, 435 for validation, and 438 for the final test. The test covered 385 exercise groups and 16 body-part labels.

**L5** and **N3** are the names we used for two training configurations. L5 is logistic regression using TF-IDF weights for individual words and adjacent word pairs. N3 is a neural network that learns a vector for each token and averages those vectors to predict a label. The majority baseline always guesses *abdominals*, the most common training label.

| Classifier | Test macro-F1 | Test accuracy |
|---|---:|---:|
| Majority baseline | 0.0234 | 23.06% |
| L5 logistic regression | **0.6143** | **73.29%** |
| N3 neural classifier | 0.5288 | 67.81% |

We chose L5 on the validation set before opening the test results. It matched 321 of the 438 held-out labels. Macro-F1 was our main measure because it gives each category equal weight. For example, L5 missed all four test exercises labeled *abductors* and both labeled *adductors*. We used L5 to suggest labels for team review of the training and validation catalog records. Approval of basketball drills was a separate decision. [Classifier model card](docs/classifier_model_card.md)

## Reference search and food facts

We used the pretrained `all-MiniLM-L6-v2` sentence encoder to rank 11 short reference passages for a question. We tested it with 30 held-out questions from 15 families. The collection supported 20 questions fully and two partly. Eight asked for information the collection did not contain.

| Retrieval measure | Result | Questions scored |
|---|---:|---|
| Mean recall in the first five results (Recall@5) | 1.0000 | 24 with at least one passage marked relevant |
| Mean reciprocal rank in the first five (MRR@5) | 0.9792 | The same 24 questions |
| All required passages appeared in the first five | 1.0000 | 20 fully supported questions |

The original ranking labels and the answerability labels were scored separately. The search returned candidates for all 30 questions, even the eight it could not answer. We also found that the planner’s prompt limit affected which passages it actually saw.

For food questions, we used a separate lookup that reads recorded nutrient values for a selected food and amount. Step 10 shows the result for 150 g of raw bananas. The food values came from the lookup and stayed outside the live scheduling request.

## Four-planner comparison

All four workflows used the same local `llama3.1:8b` model through Ollama, without fine-tuning. We changed what information and checks surrounded each call. The specialist and evaluator roles used the same model with different prompts.

| Planner | How we generated a reply |
|---|---|
| 1 · Model alone | Supply the athlete’s request without retrieved references. |
| 2 · With references | Add a reference packet and recorded lookup results. |
| 3 · With specialist roles | Ask specialists for input, then combine their contributions into a reply. |
| 4 · With checks and revisions | Run coded checks, ask an evaluator to review the reply, and allow a limited number of revisions. |

We gave each planner the same 200 fictional profiles. Of those, 150 had feasible planning requests, 20 lacked information, 15 had conflicting constraints, and 15 were outside the project’s scope. Planners 2–4 shared the same reference packet for a given case. Python handled retrieval and lookups. We kept the expected answers out of the prompts. The study recorded **800 outcomes** and **2,636 local model submissions**, including specialist, evaluator, and revision calls.

| Planner | Valid format | Workflow completed | Valid completed plans | Passed coded checks | Fully verified plans | Median time |
|---|---:|---:|---:|---:|---:|---:|
| 1 · Model alone | 75/200 | 199/200 | 45/150 | 0/150 | 0/150 | 10.57 s |
| 2 · With references | 62/200 | 186/200 | 40/150 | 0/150 | 0/150 | 18.41 s |
| 3 · With specialist roles | 67/200 | 199/200 | 39/150 | 0/150 | 0/150 | 26.98 s |
| 4 · With checks and revisions | 69/200 | 198/200 | 47/150 | 0/150 | 0/150 | 62.10 s |

Format, workflow completion, and median time cover all 200 cases per planner, including failed runs. The three plan columns cover the 150 feasible requests. A valid completed plan had the required structure and returned a plan. We then checked whether it actually followed the athlete’s request.

Planner 1 was fastest and returned the most correctly formatted replies. Planner 4 produced two more valid completed plans than Planner 1, took about six times as long at the median, and reached no final outcome that its evaluator accepted. **None of the four planners produced a fully verified plan.** Some calendars dropped existing practices, added the wrong number of sessions, or exceeded training limits. Our automatic goal check was also unfinished, and some resource checks were inconclusive. We kept those gaps separate from the errors we could confirm. [Statistical analysis](docs/statistical_analysis_findings.md) · [Results and limitations](docs/results_limitations_and_future_improvements.md)

### Team review and uncertainty

After the results were known, we used one assisted team review to examine 160 replies from 40 selected profiles. The sample included 25 feasible profiles and 15 challenge profiles. Across five dimensions, the review recorded 799 numeric scores and one entry marked not applicable. We collected no independent teammate rating sets, so we could not calculate agreement between reviewers. The ratings describe this sample. [Recorded review method](results/team_review/review_1c8c6d51f99740e019ac/review_method_amendment.json)

For four matched planner comparisons, we resampled the groups 2,000 times with seed 42. Every planner had zero fully verified plans, so resampling this benchmark also produced zero differences on that measure. That leaves the planners’ relative quality on new requests open. We documented the numerical conventions we clarified after seeing the results. [Analysis method note](results/statistical_analysis/analysis_d5e368e9f92725a9d389/analysis_method_note.json)

## Fictional-athlete demonstration

The separate **CODE-4 live application** received one request from a fictional 16-year-old beginner who wanted two 15-minute dribbling sessions. It filtered drills by the athlete’s resources, supplied a weekly-rest rule, and checked the returned schedule. Two saved runs of that same request passed the app’s format and completion checks and produced the same calendar.

| Day | Local time | Drill |
|---|---|---|
| Monday, November 16, 2026 | 5:30–5:45 p.m. | 5-5-5 Creative Dribble |
| Wednesday, November 18, 2026 | 5:30–5:45 p.m. | Rhythm Dribbling |

The source descriptions give one minute for the first drill and three minutes for the second. The app fit the sessions into the available time, but the draft still left most of each 15-minute block unexplained. These two runs belong to the application demonstration. The four-planner comparison uses only the 800 study outcomes above. Step 10 displays the saved calendar by default. Generating a new plan is optional and creates a separate job. [Saved demonstration runs](results/app_live/jobs/)

## Running the project locally

### Get the data for a new Windows checkout

You only need to download the data if you want to execute the notebook or run the applications. For a new Windows checkout, install Git LFS and run the following in PowerShell. The clone setting preserves line endings in files whose checksums the notebook verifies.

```powershell
git lfs install
git clone -c core.autocrlf=false --branch main https://github.com/SamTavasoli/champion-athletic-map.git champion-athletic-map-review
cd champion-athletic-map-review
git lfs pull --include="data/unified/v1/champions_unified_dataset.csv"
```

The master notebook uses [`data/unified/v1/`](data/unified/v1/) as its working dataset. Keep `champions_unified_dataset.csv`, `dataset_manifest.json`, `load_unified_dataset.py`, and `READ_ME_FIRST.txt` together. The Unified CSV is 525,355,627 bytes. On Windows you can check that the full file downloaded with `(Get-Item .\data\unified\v1\champions_unified_dataset.csv).Length`. Step 1 also checks it against the release manifest.

We developed on Windows with Python 3.12.6. Use the prepared project environment and the saved model, schema, prompt, reference, and result files for the part you want to run. `requirements/prototype.txt` pins Streamlit. The classifier has its own recorded package versions. The master notebook leaves new predictions and plan generation switched off by default. [Recorded development environment](docs/current_environment_recorded.md) · [Technical guide](docs/technical_guide.md)

### Open a Streamlit application

From the project root, activate the prepared environment with `.\.venv\Scripts\Activate.ps1`, then choose one of the two commands below. Open the local address printed by Streamlit, usually `http://127.0.0.1:8501`. Press `Ctrl+C` to stop the server.

**Saved-example viewer.** Use this to open a fictional example, edit its calendar, mark a session completed or skipped, and download a CSV or JSON snapshot. Restore the JSON to keep your edits and progress across browser sessions. Some saved examples contain known planning errors. If you change a session, its earlier review refers to the old version and you may need to record progress again. Progress is self-reported. In this viewer, live generation and model review require a matching readiness record. [Prototype user guide](docs/prototype_user_guide.md)

```powershell
python -m streamlit run app/streamlit_app.py --server.address 127.0.0.1
```

**Live planner.** Use this when you want to generate a *new* draft. It requires the local Ollama service and the installed `llama3.1:8b` model matching the project’s recorded digest. A run writes a new job under `results/app_live/jobs/`. You can inspect the two saved demonstration runs without starting Ollama.

```powershell
python -m streamlit run app/live_planner.py --server.address 127.0.0.1
```

## Reproducing the analysis and checking the software

In Step 36 of the development notebook, we recalculated the saved analysis in a separate environment and fresh kernel. **All 37 output comparisons passed.** To repeat that check from the prepared project root, run the command below. It creates a new verification folder. Installing the dependencies may need internet access. The analysis itself runs offline and uses the original saved outcomes. A complete rebuild of every experiment from a fresh clone remains unverified. [Reproducibility guide](docs/reproducibility.md)

```powershell
python results/reproducibility/repro_20261117T174153Z_3e7049a7/reproduce.py --project-root .
```

The Step 30 software suite recorded **248 passing checks and no failures** after its corrections. Later changes had their own targeted checks. The original runner verifies the source version before it proceeds, so a later checkout can stop at that check. To run it in the matching environment:

```powershell
python tests/run_step30.py
```

### Figures and code exports

The three [analysis figures](results/statistical_analysis/analysis_d5e368e9f92725a9d389/figures/) show planner completion and format validity (`planner_execution.svg`), median workflow time including failures (`planner_runtime.svg`), and differences in classifier macro-F1 with 95% exercise-group bootstrap intervals (`classifier_macro_f1_differences.svg`). To copy the existing figures for a report:

```powershell
New-Item -ItemType Directory -Force reports/figures | Out-Null
Copy-Item results/statistical_analysis/analysis_d5e368e9f92725a9d389/figures/*.svg reports/figures/
```

The [code exports](reports/code_exports/) include the helpers from Steps 35–37 and a record of their source hashes. To make a fresh Python export of the development notebook without running it, use a separate output folder so the archived export stays intact. The exported code still depends on notebook cell order and its project environment, and some cells start expensive experiments. [Figures and exports guide](docs/report_figures_and_code_exports.md)

```powershell
python -m nbconvert --to python notebooks/champion_athletic_map.ipynb --output-dir reports/local_exports
```

## Repository layout

| Folder | What it contains |
|---|---|
| `notebooks/` | Ten-step master notebook, development notebook, catalog build history, and preparation notebooks. Earlier supporting work is in `supporting/` and the dated backup is in `archive/`. |
| `data/` | Unified working dataset, source register, and reference files. |
| `src/champion_athletic_map/` | Classification, reference search, planning, and validation code. |
| `app/` | Both Streamlit entry points and the live planner’s supporting code. |
| `artifacts/` | Versioned models, prompts, schemas, reference resources, and configurations. |
| `results/` | Saved replies, calendars, checks, team review, analysis, and reproduction records. |
| `docs/` | User guide, technical notes, methods, and findings. |
| `reports/` | Report draft, figures, and archived exports. |
| `requirements/` | Dependency lists for individual components. |
| `tests/` | Software checks and their fixtures. |

## Sources, scope, and next steps

The source register identifies where each dataset came from. At the planning stage we made 127 basketball records, nine general warm-ups, and 29 rule definitions available. We held back seven drill records. Gym exercises stayed outside the planner. A resource being available for the project does not establish its suitability for a particular athlete. When sharing source material, we follow the original terms for the datasets, guidance, and model weights and keep the attribution notices. Separate permission may be needed to redistribute source materials. CDC guidance is included for educational use. CDC does not endorse this project. [Source register](data/source_manifest.csv)

We tested fictional profiles and one local planning model. We did not measure changes in real athletes’ performance. The prototype covers general planning and recorded food facts. Medical diagnosis, injury rehabilitation, and dietary prescriptions are outside its scope.

Our first change to the planning code would be to place the athlete’s existing practices on the calendar before adding any sessions. We would then check time windows, session counts, rest days, and drill requirements in code, and ask the model to explain how the drills fill each block. Food facts can keep coming directly from the recorded lookup. We would test those changes on fresh cases so the 800 outcomes reported here remain the record of the original comparison.

[Project repository on GitHub](https://github.com/SamTavasoli/champion-athletic-map)
