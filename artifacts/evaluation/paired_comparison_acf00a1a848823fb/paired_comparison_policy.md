# Paired planner comparisons and independent scoring — prepared component

This component tests accounting for supplied artificial feasible-case outcomes. It does not score study responses, accept profiles or families, choose returned responses, or calculate confidence intervals.

The fixed contrasts are Version 2 minus Version 1, Version 3 minus Version 2, Version 4 minus Version 3, and Version 4 minus Version 1. V1–V4 are analyst aliases; their frozen workflow/run mapping must be established before actual evaluation.

Keep the complete declared feasible-profile roster and match outcomes by profile/version ID. Every profile retains its family ID. The planned final population has 150 feasible profiles, but small artificial fixtures use their own explicitly declared denominators. The pure helper does not enforce or verify the actual study population. Its population_ready flag is a supplied prerequisite, not profile acceptance or proof that the roster is complete.

Point estimates give one weight to each profile. Success rates use the entire declared feasible population for each version. Count improved, worsened, unchanged-success, unchanged-non-success and incomplete pairs. Report later-minus-earlier success differences in percentage points as 100 times (improved minus worsened) divided by profile count. Family sizes do not reweight that point estimate.

Missing outcomes and unfinished execution/assessment remain null. A completed non-success is False and remains distinct from unfinished work. Do not discard incomplete partners and reduce the denominator. Full rates/differences remain unavailable for an unready population, incomplete contrasted outcomes or zero denominator. A completed contrast can be reported while a different version remains pending, with the overall experiment marked incomplete. Empty populations do not establish completed experiments.

The helper validates compact supplied outcome records. It does not verify independent-score provenance, parse returned responses or implement rule validation. The later score-ledger adapter must bind actual run/version/profile/family identifiers, designated response hashes and scorer versions to adopted expectations and references. Per-case pair records remain available to independent evaluation; this cell prints aggregate artificial check counts only.

## Independent final scoring

Give every workflow the same public profile inputs, shared response contract, base model and common generation settings. Record retrieval, specialist roles, internal evaluation and revision as intended workflow differences. Establish a designated-response rule before final runs and score its saved returned response before user edits.

Version 4's internal acceptance flag is not its research result. If the frozen workflow returns its last checked candidate at the revision limit, score that designated candidate independently under the same rules. Fatal workflow errors remain failures; earlier diagnostic drafts do not silently replace the designated response. Preserve failures and avoid selecting the best of multiple completed generations unless that selection is explicitly part of a frozen workflow. Optional source IDs remain optional formatting, with attribution assessed separately. Any change prompted by final results belongs to a documented new experiment.

## Step 31 uncertainty handoff

Plan 2,000 paired group-bootstrap resamples, seed 42, with individual 95% percentile intervals. Resample adopted profile families for planner comparisons and frozen exercise groups for classifier comparisons. Keep matched version/model outcomes together and preserve group membership and repeated-draw multiplicity. Recompute profile-level or record-level metrics; do not average group scores with equal group weights instead.

These settings are a planned handoff. The operational procedure and implementation remain pending Step 31, and no resampling or intervals are produced here. Their intended interpretation is sensitivity to the constructed benchmark, not real-athlete training outcomes or training-seed variability.

Accepted roster/family bindings, frozen workflow aliases, designated-response provenance, actual independent score ledgers and bootstrap implementation remain open. Consolidated Step 17 protocol assembly follows separately.
