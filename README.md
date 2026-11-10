# Champions Athletic Map

Champions Athletic Map is an AAI 590 capstone project developing a weekly basketball planning prototype for athletes ages 13–17, their parents, and coaches. The planned system considers goals, available time, equipment, and existing practices or games.

The project also studies four planning workflows: a language model alone; a model with references; specialist roles using those references; and specialist planning with checks, evaluation, and bounded revision.

## Current status — November 9, 2026

This is a **work-in-progress research repository**. It contains executed data-preparation and exploratory-analysis code, saved evidence, and a detailed implementation plan. The final trained classifier, planning workflows, and application are not implemented in this snapshot.

| Work | Status |
|---|---|
| Environment and feasibility checks | Saved outputs available; the model request is a smoke test |
| Dataset inventory, exercise preparation, and EDA | Saved outputs available |
| Basketball catalog | Source-linked schema prepared: 144 candidate groups, 156 source occurrences; approval remains open and planner eligibility is zero |
| Planning rules | 34 candidates and 102 draft test specifications prepared; no rules adopted and no runtime validator tests executed |
| USDA food reference | Frozen SR Legacy snapshot: 100 foods, 341 supported portions; saved calculation and source-comparison cases passed |
| Classifier training, retrieval, four planners, and application | Planned in Steps 15–29 |
| Testing, final evaluation, reproducibility, and delivery | Planned in Steps 30–39 |

The food snapshot is ready for the planned lookup integration; the application lookup is not enabled. Completed preparation checks do not approve drills or adopt planning rules.

## Start here

- [Main notebook](notebooks/champion_athletic_map.ipynb): executed preparation work, observations, and the 39-step project plan.
- [Step 12 build history](notebooks/step12_basketball_catalog_build_history.ipynb): the earlier catalog-construction work and its dependencies.
- [Current review](docs/project_review_2026-11-09.md): review scope, corrections, verification evidence, and remaining work.
- [GitHub push notes](docs/github_push_notes.md): what to check before staging files.
- [Recorded environment](docs/current_environment_recorded.md): versions shown by the saved environment check.
- [Source register](data/source_manifest.csv): source identities, file hashes, limitations, and recorded permission-review status.

## What is in this snapshot

`notebooks/` contains the main notebook, earlier preparation notebooks, and catalog build history. `data/` contains the committed source register and earlier processed and synthetic inputs. `docs/` contains review and environment documentation.

The complete local preparation evidence—including generated reports and newer reference bundles—is not yet published on this branch. Saved outputs are visible in the main notebook. Complete reproduction will require the remaining inputs and artifacts through a documented access route.

## Running the current work

Open the main notebook to inspect its saved outputs. The current implemented cells depend on the recorded local inputs and run in sequence. They include file writes, official-source downloads, and a local Ollama request; running every cell is not yet a read-only analysis workflow.

The saved environment uses Python 3.12.6 on Windows. The recorded neural execution check uses PyTorch 2.14.1+cu126; the language-model smoke test uses Ollama 0.40.15 with the pinned local `llama3.1:8b` artifact. Details are in the environment record.

A tested fresh-install dependency specification, the default saved-results reproduction mode, and application launch instructions are still pending. Do not treat the recorded package versions as a verified installation recipe.

## Data access and publication

The current source register contains 33 entries marked `pending_review`, five with documented source terms, and one team-generated entry. Review those records before publishing third-party content or source-derived artifacts. A public link does not itself document redistribution permission.

The supplied dataset package includes a 98.9 MiB master CSV. Keep its distribution deliberate rather than adding the entire working folder without reviewing the staged files. Large archives, local backups, environments, and model weights should use appropriate documented handling.

If data is kept outside the public repository, the access instructions must identify the exact versions and locations needed to run the preparation code. This snapshot does not yet establish full reproduction from a fresh clone.

## Evaluation plan

The planned final comparison uses 200 fictional profiles processed by all four versions: 800 scheduled jobs. The primary planning measure uses all 150 feasible profiles per version. Challenge cases, the 40-profile human-review sample, and resource usage have separate reporting rules.

The neural exercise classifier will be trained within the project. The language model and retrieval embeddings are pretrained components used for inference. No final model or planner performance is claimed yet.

The prototype's scope is planning support and general food facts. The benchmark does not measure real athletes' outcomes or establish professional validation of the recommendations.
