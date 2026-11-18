# Evidence accounting — prepared evaluation component

This component checks arithmetic and bookkeeping using supplied artificial assessments. It does not extract claims, resolve actual source IDs, judge factual support, or score study responses. Those operational implementations remain pending.

| Measure | Numerator | Denominator |
|---|---|---|
| Supplied reference validity | Resolvable distinct supplied IDs | All distinct supplied IDs in the declared response |
| Cited claim support | Supported cited claims assessed | Cited claims assessed |
| Attribution coverage | Reviewed source-dependent claims with usable attribution | Source-dependent claims reviewed |

Call the helpers for one declared response and evidence-assessment scope. Preserve response/version IDs, source versions, locators, sample/claim inventories, evaluator version, and detailed findings in the later evidence ledger. These pure helpers return counts, not an auditable case ledger or factual verdict.

Duplicate occurrences of one ID do not increase its validity denominator. Do not deduplicate identifiers across an entire set of responses. A resolved ID establishes existence only. A citation may be unusable or fail to support its claim. An uncited claim can still be correct; check it against adopted neutral evidence and report its attribution separately.

Claim support reports cited and uncited subsets separately. Each claim has one supplied primary support finding: supported, contradicted, insufficient support, missing qualification, or unknown. Retain richer source findings separately. A completed unknown is an unresolved semantic finding, not an execution error or proven falsehood.

Before publishing a ratio, finish the declared inventory and its expected assessments. Missing records, unrun checks, and checker errors retain separate counts and leave the affected ratio unavailable. A completed empty scope has denominator zero and a null ratio. A complete cited subset can be reported while an uncited subset is still pending, with both scopes disclosed. No assessment is inserted or inferred by the helpers.

Complete assessment work can still contain unknown findings. The completion flag does not establish conclusive support, adequate evidence, or a successful response. Inventories concern substantive claims actually present in returned text; omitted requested answers belong to completeness checks. Source dependence and citation presence are upstream annotations requiring review, not facts established by this helper. In particular, changing source dependence must not become a way to discard attribution obligations.

For support, use the evidence associated with the claim and its relevant ages, units, quantities, conditions, and qualifications. Do not label an authored scheduling duration as a publisher prescription. Evidence-basis strings must later be bound to adopted source versions; their presence here does not verify a source.

The artificial marker-square example pairs a resolvable reference with an independently authored contradiction finding. The code checks the accounting of those supplied findings. It does not interpret the example's text.

Retrieval has a separate Step 23 benchmark: Hit@k and Recall@k at 1, 3, and 5; MRR@5; and accepted complete evidence bundles. Select using development Recall@5, then MRR@5, then the simpler lexical method. Report unsupported questions and evidence-adequacy failures separately. No retrieval evaluation occurs here.

Actual adopted references, claim extraction, source resolution, source-dependent checkers and human evidence review remain open. These measures do not produce a human evidence-accuracy rating, approve any planning rule, or establish full Step 17 readiness.
