"""Prepare our discussion from the preserved analysis and reproduction records."""
from pathlib import Path
import hashlib
import html
import json


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def render_html(markdown):
    parts = []
    for block in markdown.strip().split("\n\n"):
        lines = block.splitlines()
        if block.startswith("| "):
            rows = [[html.escape(cell.strip()) for cell in line.strip("|").split("|")] for line in lines]
            parts.append("<table><thead><tr>" + "".join("<th>" + cell + "</th>" for cell in rows[0])
                         + "</tr></thead><tbody>" + "".join("<tr>" + "".join("<td>" + cell + "</td>" for cell in row)
                         + "</tr>" for row in rows[2:]) + "</tbody></table>")
        elif lines[0].startswith("# "):
            parts.append("<h1>" + html.escape(lines[0][2:]) + "</h1>")
        elif lines[0].startswith("## "):
            parts.append("<h2>" + html.escape(lines[0][3:]) + "</h2>")
        elif all(line.startswith("- ") for line in lines):
            parts.append("<ul>" + "".join("<li>" + html.escape(line[2:]) + "</li>" for line in lines) + "</ul>")
        else:
            parts.append("<p>" + html.escape(" ".join(lines)) + "</p>")
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>Champions Athletic Map — Results and limitations</title><style>"
            "body{font:17px/1.65 system-ui,sans-serif;color:#22313d;max-width:1060px;margin:40px auto;padding:0 24px}"
            "h1,h2{color:#174569;line-height:1.3}h2{margin-top:36px}table{border-collapse:collapse;width:100%;font-size:15px}"
            "th,td{text-align:left;padding:9px;border-bottom:1px solid #d4dee6}th{background:#eff4f7}"
            "li{margin:9px 0}@media print{body{font-size:11pt;margin:0}h2{break-after:avoid}tr{break-inside:avoid}}"
            "</style><main>" + "".join(parts) + "</main></html>\n").encode("utf-8")


def prepare_discussion(root):
    root = Path(root).resolve()
    sources = {}

    def read(relative):
        require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
                "A discussion source has an invalid project path.")
        path = (root / relative).resolve()
        require(path.is_relative_to(root), "A discussion source leaves the project folder.")
        raw = path.read_bytes()
        require(relative not in sources or sources[relative] == sha(raw), "A discussion source changed while reading.")
        sources[relative] = sha(raw)
        return raw

    analysis = json.loads(read("results/step35_statistical_analysis_summary.json"))
    reproduction = json.loads(read("results/step36_reproducibility_summary.json"))
    require(analysis.get("schema_version") == "step35-statistical-analysis-1"
            and analysis.get("status") == "saved_evidence_analysis_complete_with_recorded_limits",
            "The complete saved Step 35 analysis is needed before preparing the discussion.")
    folder = analysis["analysis_folder"]
    require(json.loads(read(folder + "/analysis_summary.json")) == analysis,
            "The Step 35 index differs from its saved analysis.")
    manifest = json.loads(read(folder + "/output_manifest.json"))
    require(manifest["analysis_id"] == analysis["analysis_id"], "The analysis output manifest refers to another run.")
    for name, expected in manifest["files"].items():
        require(sha(read(folder + "/" + name)) == expected, "A saved analysis output changed: " + name)
    identity = json.loads(read(folder + "/analysis_input_manifest.json"))
    require(sha(packed(identity)) == analysis["analysis_id"], "The analysis input identity differs.")
    require(reproduction.get("schema_version") == "step36-reproducibility-1"
            and reproduction.get("status") == "passed"
            and reproduction.get("source_analysis_id") == analysis["analysis_id"]
            and reproduction.get("protected_inputs_unchanged") is True
            and all(reproduction.get(key) == "passed" for key in
                    ("fresh_dependency_installation", "fresh_kernel_execution", "result_comparison")),
            "Step 36 must have reproduced this same analysis successfully.")
    require(reproduction == json.loads(read(reproduction["verification_folder"] + "/verification_summary.json")),
            "The Step 36 index differs from its saved verification.")
    require(reproduction["files_compared"] == len(manifest["files"]) + 1,
            "The reproduced output count differs from the saved analysis.")
    classifier = analysis["classifier"]
    require(classifier.get("status") == "complete", "Saved classifier test results are incomplete.")
    observed = json.loads(read(folder + "/classifier_summary.json"))
    require(observed == classifier["observed"], "The classifier tables and summary differ.")
    retrieval = analysis["retrieval"]
    require(retrieval["heldout_questions"] == 30 and retrieval["support_status_counts"] ==
            {"supported": 20, "partially_supported": 2, "unsupported": 8}, "The retrieval population differs.")
    route = next(row for row in retrieval["reported_route_metrics"] if row["route"] == retrieval["selected_route"])
    lookup = {(row["population"], row["metric"], row["planner"]): row for row in analysis["headline_planner_rows"]}
    timing = {row["planner"]: row for row in analysis["timing_all_terminal"]}

    def count(version, metric, population="all_planner"):
        row = lookup[population, metric, version]
        return str(row["numerator"]) + "/" + str(row["denominator"])

    names = {1: "1 — Language model alone", 2: "2 — With references",
             3: "3 — With specialist roles", 4: "4 — With checks and revisions"}
    lines = ["# Step 37 — Results, Limitations, and Future Improvements", "",
        "We built Champions Athletic Map as a local prototype for weekly teen basketball planning. Our work includes an exercise-text classifier, reference search, recorded food lookups, four planning workflows and an interface for viewing, editing and tracking saved plans. We evaluated these components separately because success in one part does not establish that the complete planner is reliable.", "",
        "## Main findings", "",
        "Our exercise classifier completed its evaluation and performed better than its majority baseline. L5 logistic regression had the highest observed Macro-F1 and accuracy among the three tested classifiers. Our four planning workflows produced mixed results: adding references, specialist roles and revisions did not give us a consistent improvement across the recorded measures.", "",
        "## Exercise classification", "",
        f"We evaluated the saved predictions for {classifier['records']} test records in {classifier['groups']} exercise groups and {classifier['class_count']} categories. Macro-F1 gives each category equal weight, while accuracy measures the proportion of records classified correctly.", "",
        "| Classifier | Macro-F1 | Accuracy |", "|---|---:|---:|"]
    for key, label in (("majority", "Majority baseline"), ("logistic_regression", "L5 logistic regression"), ("neural", "N3 neural classifier")):
        lines.append(f"| {label} | {observed[key]['macro_f1']:.4f} | {100 * observed[key]['accuracy']:.2f}% |")
    lines += ["", "L5 remains our validation-selected classifier. These results support its use for assigning exercise categories from text. A body-part label alone does not tell us whether an exercise is suitable for a basketball goal, an athlete's limitations or the available equipment. Gym exercises also remain unavailable to the planner under our current resource decisions.", "",
        "## Four planning workflows", "",
        f"We used the same local llama3.1:8b model across {analysis['planner_profiles']} fictional profiles, with {analysis['planner_outcomes']} saved outcomes. The final comparison used {analysis['cumulative_planner_model_submissions']:,} cumulative model submissions, including specialist, evaluator and revision work. The comparison concerns the complete workflows rather than different underlying language models.", "",
        "| Planner | Valid format | Workflow completed | Valid completed plans | Coded checks passed | Full verification | Median time |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for version in range(1, 5):
        values = [count(version, key, population) for key, population in
                  (("strict_format_valid", "all_planner"), ("designated_workflow_completed", "all_planner"),
                   ("completed_valid_plan", "feasible"), ("automated_declared_checks_pass", "feasible"),
                   ("automated_feasible_plan_success", "feasible"))]
        lines.append("| " + names[version] + " | " + " | ".join(values) + f" | {timing[version]['median_seconds']:.2f} s |")
    lines += ["", "Format and workflow completion use all 200 profiles per planner. Plan and verification counts use the 150 feasible requests per planner. Timing includes all terminal outcomes, including failures. A valid completed plan means that a completed reply has the required structure and declares a plan; it does not mean the calendar satisfies every requirement.", "",
        "The baseline returned the most correctly formatted responses overall and had the lowest observed time. Planner 4 returned slightly more valid completed plans for feasible requests, but took much longer. Its internal checks accepted none of the final outcomes. We therefore cannot select a generally superior planner from these results.", "",
        "No planner achieved full verification. The automatic goal check was not implemented, and resource checking covered only a limited range of activity descriptions. Our saved assessments also found actual errors, including changed or missing existing commitments, incorrect session counts and exceeded extra-training limits. Both the missing checks and the observed output errors matter. An unknown result stays unresolved; it does not establish that the plan is safe, unsafe or useless.", "",
        "The challenge cases exposed another weakness. None of the workflows successfully handled the 20 missing-information cases or the 15 conflicting-constraint cases under the recorded checks. Outside-scope handling varied across workflows. This shows that asking for clarification and recognizing a request that cannot be fulfilled need more reliable handling.", "",
        "## Reference search and food facts", "",
        f"The saved reference-search evaluation contained {retrieval['heldout_questions']} held-out questions in {retrieval['question_families']} families: 20 supported, two partly supported and eight unsupported. Mean Recall@5 was {route['mean_recall_at_5']:.4f} and MRR@5 was {route['mrr_at_5']:.4f} over the {route['ranking_scored_denominator']} questions with nonempty relevant-reference sets. Complete ranked evidence-set coverage was {route['complete_evidence_set_coverage_rate_at_5']:.4f} over {route['complete_evidence_scored_denominator']} supported questions.", "",
        "These scores show that relevant references were often ranked near the top in the saved retrieval task. All 30 questions returned candidates, including unsupported questions. Returning a reference does not prove that the question is answerable, that the system should answer it or that the planner used the correct evidence. The saved ranking task is also distinct from the planner's merged reference packet. Earlier planned answerability counts differed from the final source labels; we kept the original labels and ranking denominators visible.", "",
        "Our lookup tools could return recorded food values, but reliable lookup and reliable generated answers are separate parts of the workflow. We need to keep verified amounts, units and source identifiers attached to the displayed answer. We do not treat a successful food lookup as proof that every requested food fact appeared correctly in a planner reply.", "",
        "## Team review and reproducibility", "",
        f"Our supplementary team review covered {analysis['review_responses']} replies from {analysis['review_profiles']} selected profiles, with {analysis['review_dimension_entries']} entries across five separate dimensions. It used one assisted review rather than two independent teammate rating sets. Reviewer agreement was therefore not estimated. The sample included 25 feasible profiles and 15 challenge profiles, so its pooled ratings should not be treated as scores for the entire benchmark.", "",
        f"Step 36 reproduced the saved analysis in a separate environment and a fresh kernel. All {reproduction['files_compared']} output files passed the declared comparison checks, and the protected originals remained unchanged. This supports reproduction of the saved-results analysis. It does not measure variation from retraining or another round of language-model generation.", "",
        "## Limitations", "",
        "- We used constructed fictional profiles. We did not measure training outcomes with real athletes, parents or coaches.",
        "- The final planner comparison used one local language model and one recorded outcome per profile and workflow. It does not compare model families or estimate repeated-generation variability.",
        "- Our evaluation has incomplete goal verification and limited resource coverage. The coded-check and full-verification measures remain separate, and neither produced a passing feasible plan in this run.",
        "- The review was a single assisted assessment. Independent ratings, reviewer agreement and coaching validation remain uncollected.",
        "- Although feasible cases had 150 adopted family IDs, they came from only three original wording patterns. This limits how broadly we can interpret performance on different requests.",
        "- The 2,000 paired group resamples describe the fixed saved outputs. Constant zero-success intervals do not establish equal planner quality or zero uncertainty outside this benchmark.",
        "- Some numerical conventions for planner resampling were clarified during analysis after the outputs were available. We recorded that timing rather than claim those details were frozen earlier.",
        "- Observed runtime describes our local setup. We have not established deployment costs or performance on other hardware.", "",
        "## Future improvements", "",
        "| Priority | Improvement | Problem it addresses |",
        "|---|---|---|",
        "| 1 | Build calendars with explicit scheduling logic, preserving existing commitments before adding sessions. | Missing practices, incorrect dates, overlaps and session-count errors. |",
        "| 2 | Select approved drill identifiers and validate their equipment, space and participant requirements. | Activities whose resource requirements cannot be verified. |",
        "| 3 | Display food amounts, units and sources directly from verified lookup results. | Omitted or altered factual answers. |",
        "| 4 | Complete goal and resource checks, keeping unknown results separate from violations. | Incomplete verification and unclear failure reasons. |",
        "| 5 | Simplify prompts and response structures, then compare any model or workflow change in a new experiment. | Format errors, long revision cycles and request-size limits. |",
        "| 6 | Collect separate team ratings and qualified basketball feedback, then test broader cases. | Limited review independence and uncertain practical suitability. |", "",
        "We would use the language model to describe and explain a schedule while program logic protects dates, commitments and numerical limits. These are proposed changes, not features demonstrated by the present results. Because the final cases have now been examined, improvements based on them should be developed separately and evaluated on fresh cases. Our original final outcomes and scores stay unchanged.", "",
        "## Project conclusion", "",
        "We completed an evaluated prototype and a reproducible saved-results analysis. The exercise classifier performed substantially better than its majority baseline, and reference search returned relevant material in its ranking task. The planning comparison showed that more elaborate workflows did not consistently solve the scheduling and response problems. Reliable end-to-end basketball planning remains a development goal; the current results do not establish readiness for independent use with athletes.", "",
        "## Saved sources", "",
        "- Step 35 analysis: " + folder,
        "- Planner and request results: planner_summary.csv, parent_check_summary.csv and failure_analysis.csv in that analysis folder.",
        "- Classifier, retrieval and timing: classifier_summary.json, retrieval_analysis_status.json and runtime_resource_summary.csv in that analysis folder.",
        "- Review and method: team_rating_distributions.csv, team_rating_comparisons.csv and analysis_method_note.json in that analysis folder.",
        "- Step 36 verification: " + reproduction["report_path"], ""]
    markdown = "\n".join(lines).encode("utf-8")
    identity = {"schema_version": "step37-discussion-sources-1", "source_analysis_id": analysis["analysis_id"],
                "source_verification_run_id": reproduction["run_id"], "source_sha256": sources,
                "software_sha256": sha(Path(__file__).read_bytes()), "discussion_sha256": sha(markdown)}
    discussion_id = sha(packed(identity))
    output_folder = "results/discussion/discussion_" + discussion_id[:20]
    summary = {"schema_version": "step37-discussion-1", "status": "saved", "discussion_id": discussion_id,
               "source_analysis_id": analysis["analysis_id"], "source_verification_run_id": reproduction["run_id"],
               "planner_outcomes": analysis["planner_outcomes"], "reviewed_replies": analysis["review_responses"],
               "reproduced_files": reproduction["files_compared"], "new_model_calls": 0, "new_predictions": 0,
               "new_reference_queries": 0, "original_scores_changed": False, "original_outcomes_changed": False,
               "best_planner_selected": False, "review_method": analysis["review_method"],
               "independent_reviewer_agreement_estimated": False, "output_folder": output_folder,
               "report_path": output_folder + "/results_discussion.html",
               "markdown_path": output_folder + "/results_limitations_and_future_improvements.md",
               "documentation_path": "docs/results_limitations_and_future_improvements.md"}
    files = {"source_manifest.json": packed(identity), "discussion_summary.json": packed(summary),
             "results_limitations_and_future_improvements.md": markdown, "results_discussion.html": render_html(markdown.decode("utf-8"))}
    pointer = root / "results/step37_discussion_summary.json"
    doc = root / summary["documentation_path"]
    if pointer.exists():
        previous = json.loads(pointer.read_bytes())
        require(previous.get("schema_version") == summary["schema_version"], "An unrelated Step 37 summary was preserved.")
        require(json.loads(read(previous["output_folder"] + "/discussion_summary.json")) == previous,
                "The earlier Step 37 index differs from its saved report.")
        allowed_docs = [read(previous["markdown_path"]), markdown]
    else:
        allowed_docs = [markdown]
    require(not doc.exists() or doc.read_bytes() in allowed_docs, "Edited discussion documentation was preserved. Save the edits separately before replacing it.")
    for name, raw in files.items():
        path = root / output_folder / name
        require(not path.exists() or path.read_bytes() == raw, "An earlier discussion artifact differs and was preserved: " + name)
    for name, expected in sources.items():
        require(sha((root / name).read_bytes()) == expected, "A discussion source changed before saving: " + name)
    for name, raw in files.items():
        path = root / output_folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_bytes(markdown)
    pointer.write_bytes(packed(summary))
    return summary
