"""Validate the frozen benchmark graph; documentary judgments are not retrieval scores."""


def _step2316_vpack(value):
    import json
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode("utf-8")


def _step2316_vsha(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def validate_step2316_benchmark(questions,judgments,families,reviews,bindings,contract):
    """Check text/version bindings, all unit labels, claim spans and partition membership."""
    from collections import Counter
    checks=[]
    def check(name,condition,observed="verified"):
        if not bool(condition):raise ValueError("step2316_benchmark_invalid:"+name)
        checks.append({"check":name,"status":"pass","observed":str(observed)})
    def bound(row,field):
        return row.get(field)==_step2316_vsha(_step2316_vpack({k:v for k,v in row.items() if k!=field}))
    categories=("drill_and_resource","guideline_and_qualification","unsupported_by_identified_corpus")
    check("sixty_questions_judgments_and_thirty_paired_families",type(questions) is list and len(questions)==60
        and type(judgments) is list and len(judgments)==60 and type(families) is list and len(families)==30)
    check("exact_bound_corpus_and_unmodified_metric_contract",bindings["corpus_id"]==contract["corpus_id"]
        and bindings["expanded_retrieval_id"]==contract["expanded_retrieval_id"]
        and bindings["query_preparation_id"]==contract["query_preparation_id"]
        and contract["metric_policy_sha256"]==_step2316_vsha(_step2316_vpack(contract["metric_policy"]))
        and contract["metric_policy"]["planned_development_questions"]==contract["metric_policy"]["planned_held_out_questions"]==30
        and contract["metric_policy"]["planned_category_counts_per_partition"]=={c:10 for c in categories}
        and contract["metric_policy"]["question_families_cannot_cross_partitions"] is True
        and contract["benchmark_queries_executed"]==0 and contract["retrieval_method_selected"] is None)
    units={r["unit_key"]:r["record"] for r in bindings["reference_units"]}
    by_unit={r["reference_unit_id"]:r for r in units.values()};all_units=set(by_unit)
    check("eleven_unique_public_units_and_cores",len(units)==len(by_unit)==11
        and len({r["passage_id"] for r in by_unit.values()})==11
        and sum(r["source_alias_count"] for r in by_unit.values())==12)
    check("all_core_hashes_and_complete_delivery_records_preserved",all(
        r["text_sha256"]==_step2316_vsha(r["text"].encode())
        and r["required_delivery_record_sha256"]==_step2316_vsha(_step2316_vpack(r["required_delivery_record"]))
        and r["required_delivery_text_sha256"]==_step2316_vsha(r["required_delivery_text"].encode())
        and r["required_delivery_is_indivisible"] is True and r["standalone_core_delivery_allowed"] is False
        for r in by_unit.values()))
    question_ids=[q["question_id"] for q in questions];query_ids=[q["query_id"] for q in questions]
    check("unique_question_query_and_raw_text_identities",len(set(question_ids))==len(set(query_ids))==60
        and len({" ".join(q["text"].casefold().split()) for q in questions})==60)
    check("question_records_match_their_complete_hashes",all(bound(q,"question_record_sha256") for q in questions))
    check("reserved_implementation_diagnostics_are_not_benchmark_questions",all(
        q["text_sha256"] not in contract["reserved_diagnostic_text_hashes"] for q in questions))
    for partition in ("development","held_out"):
        rows=[q for q in questions if q["split"]==partition]
        check(partition+"_thirty_questions_ten_per_category",len(rows)==30 and Counter(q["category"] for q in rows)=={c:10 for c in categories})
        check(partition+"_query_ids_follow_frozen_partition_order",[q["partition_ordinal"] for q in rows]==list(range(1,31))
            and all(q["query_id"]=="retrieval-query:"+_step2316_vsha(_step2316_vpack({"ordinal":i,"text":q["text"]}))
                and q["text_sha256"]==_step2316_vsha(q["text"].encode()) and q["text"].strip() for i,q in enumerate(rows,1)))
    family_map={f["question_family_id"]:f for f in families}
    check("unique_reviewed_family_keys_and_record_hashes",len(family_map)==len({f["family_key"] for f in families})==30
        and all(bound(f,"family_record_sha256") and f["semantic_definition"].strip() for f in families))
    check("all_questions_belong_to_exactly_one_two_question_family",Counter(x for f in families for x in f["member_question_ids"])
        ==Counter(question_ids) and all(len(f["member_question_ids"])==2 for f in families))
    check("families_and_equivalent_question_rows_never_cross_partitions",all(
        q["question_family_id"] in family_map and q["question_id"] in family_map[q["question_family_id"]]["member_question_ids"]
        and q["split"]==family_map[q["question_family_id"]]["split"]
        and q["category"]==family_map[q["question_family_id"]]["category"] for q in questions))
    check("fifteen_families_and_five_per_category_in_each_partition",all(
        Counter(f["category"] for f in families if f["split"]==p)=={c:5 for c in categories} for p in ("development","held_out")))
    check("judgments_are_aligned_with_the_complete_question_order",[j["question_id"] for j in judgments]==question_ids)
    support_counts=Counter();empty=0
    for q,j in zip(questions,judgments):
        tag=str(q["authoring_ordinal"])
        m=j["metric_judgment"];relevant=m["relevant_unit_ids"];sets=m["complete_evidence_sets"]
        check("question_"+tag+"_judgment_version_and_partition_binding",bound(j,"judgment_record_sha256")
            and j["question_record_sha256"]==q["question_record_sha256"] and j["corpus_id"]==bindings["corpus_id"]
            and j["assistant_review_status"]=="accepted"
            and set(m)=={"query_id","split","category","judgment_status","support_status","relevant_unit_ids","complete_evidence_sets"}
            and m["query_id"]==q["query_id"] and m["split"]==q["split"] and m["category"]==q["category"]
            and m["judgment_status"]=="final")
        per=j["per_unit_judgments"]
        check("question_"+tag+"_all_eleven_unit_relevance_labels_reviewed",len(per)==11
            and {r["reference_unit_id"] for r in per}==all_units
            and all(r["relevance"] in ("relevant","not_relevant") and r["reason"].strip() for r in per)
            and len(relevant)==len(set(relevant)) and set(relevant)=={r["reference_unit_id"] for r in per if r["relevance"]=="relevant"})
        claims=j["required_claims"];claim_units=[];supported=missing=0
        valid=bool(claims) and len({c["claim_id"] for c in claims})==len(claims)
        for c in claims:
            evidence=c["evidence"];valid=valid and bool(c["claim"].strip()) and c["support"] in ("supported","not_in_corpus")
            if c["support"]=="supported":supported+=1;valid=valid and bool(evidence)
            else:missing+=1;valid=valid and not evidence
            ids=set()
            for e in evidence:
                uid=e["reference_unit_id"];r=by_unit.get(uid)
                valid=valid and r is not None and uid in relevant
                if r is not None:
                    start,end=e["start_character"],e["end_character"]
                    valid=valid and type(start) is int and type(end) is int and 0<=start<end<=len(r["text"])
                    valid=valid and r["text"][start:end]==e["exact_quote"] and e["passage_id"]==r["passage_id"]
                    valid=valid and e["quote_sha256"]==_step2316_vsha(e["exact_quote"].encode())
                ids.add(uid)
            claim_units.append(ids)
        status=m["support_status"]
        sufficient=(status=="supported" and supported==len(claims) and missing==0 and bool(sets))
        partial=(status=="partially_supported" and supported>0 and missing>0 and not sets and bool(relevant))
        absent=(status=="unsupported" and missing==len(claims) and supported==0 and not sets)
        category_ok=(status!="supported" if q["category"]=="unsupported_by_identified_corpus" else status=="supported")
        valid=valid and category_ok and (sufficient or partial or absent)
        valid=valid and len({frozenset(s) for s in sets})==len(sets) and all(
            bool(s) and len(s)==len(set(s)) and set(s).issubset(relevant) and all(set(s)&ids for ids in claim_units) for s in sets)
        check("question_"+tag+"_claim_spans_and_complete_support_states",valid)
        support_counts[status]+=1;empty+=not relevant
    review_questions=[r for r in reviews if r["review_scope"]=="question_relevance_and_support"]
    family_reviews=[r for r in reviews if r["review_scope"]=="question_family_partition_audit"]
    check("sixty_bound_assistant_question_reviews_and_one_family_audit",len(reviews)==61 and len(review_questions)==60 and len(family_reviews)==1
        and {r["question_id"] for r in review_questions}==set(question_ids)
        and all(r["reviewer_kind"]=="assistant" and r["finding"]=="accepted" and r["human_review"] is False
            and r["retrieval_outputs_observed"] is False and bound(r,"review_record_sha256")
            and r["corpus_id"]==bindings["corpus_id"] and r["rationale"].strip() for r in reviews))
    by_question={q["question_id"]:(q,j) for q,j in zip(questions,judgments)}
    check("assistant_events_bind_current_question_and_gold_versions",all(
        r["question_record_sha256"]==by_question[r["question_id"]][0]["question_record_sha256"]
        and r["judgment_record_sha256"]==by_question[r["question_id"]][1]["judgment_record_sha256"] for r in review_questions)
        and family_reviews[0]["family_record_sha256s"]==[f["family_record_sha256"] for f in families]
        and family_reviews[0]["semantic_cross_partition_overlap_found"] is False)
    return {"checks":checks,"question_rows":60,"question_families":30,"assistant_question_reviews":60,
        "assistant_family_audits":1,"human_reviews":0,"per_unit_judgments":660,"support_status_counts":dict(support_counts),
        "empty_relevant_set_questions":empty,"ranking_eligible_questions":60-empty,
        "benchmark_queries_executed":0,"semantic_family_review_is_documentary_not_proved_by_hashes":True}


def load_step2316_benchmark(release_root,expected_manifest_sha256):
    """Verify a separately trusted manifest before decoding the saved evaluation packet."""
    import json
    import re
    from pathlib import Path
    root=Path(release_root)
    if (not root.is_absolute() or root.resolve()!=root or not root.is_dir()
            or any(p.is_symlink() for p in (root,*root.parents))
            or re.fullmatch(r"[0-9a-f]{64}",str(expected_manifest_sha256)) is None):
        raise ValueError("step2316_benchmark_untrusted_path_or_manifest_hash")
    def decode(content):
        def pairs(rows):
            result={}
            for k,v in rows:
                if k in result:raise ValueError("duplicate_benchmark_json_key")
                result[k]=v
            return result
        return json.loads(content.decode("utf-8"),object_pairs_hook=pairs,
            parse_constant=lambda value:(_ for _ in ()).throw(ValueError("nonfinite_benchmark_json")))
    content=(root/"benchmark_manifest.json").read_bytes();manifest=decode(content)
    if (_step2316_vsha(content)!=expected_manifest_sha256 or _step2316_vpack(manifest)!=content
            or manifest["schema_version"]!="step23-benchmark-manifest-1"):
        raise ValueError("step2316_benchmark_manifest_changed")
    expected={"benchmark_questions.jsonl","benchmark_judgments.jsonl","question_families.jsonl",
        "assistant_review_events.jsonl","corpus_bindings.json","retrieval_benchmark_contract.json",
        "benchmark_validator.py","benchmark_checks.csv","benchmark_readiness.json"}
    hashes=manifest["payload_hashes"]
    if set(hashes)!=expected:raise ValueError("step2316_benchmark_payload_inventory_changed")
    for name,h in hashes.items():
        p=root/name
        if p.is_symlink() or not p.is_file() or _step2316_vsha(p.read_bytes())!=h:
            raise ValueError("step2316_benchmark_payload_hash_changed")
    allowed=expected|{"benchmark_manifest.json","step23_benchmark_preparation_summary.json"}
    if any(p.name not in allowed or p.is_symlink() or not p.is_file() for p in root.iterdir()):
        raise ValueError("step2316_benchmark_unrecognized_folder_entry_preserved")
    docs={name:([decode(line) for line in (root/name).read_bytes().splitlines()] if name.endswith(".jsonl")
        else decode((root/name).read_bytes())) for name in expected if name.endswith((".json",".jsonl"))}
    report=validate_step2316_benchmark(docs["benchmark_questions.jsonl"],docs["benchmark_judgments.jsonl"],
        docs["question_families.jsonl"],docs["assistant_review_events.jsonl"],docs["corpus_bindings.json"],
        docs["retrieval_benchmark_contract.json"])
    if (docs["corpus_bindings.json"]["corpus_id"]!=manifest["corpus_id"]
            or docs["retrieval_benchmark_contract.json"]["benchmark_preparation_id"]!=manifest["benchmark_preparation_id"]):
        raise ValueError("step2316_benchmark_manifest_identity_disagrees")
    return {"manifest":manifest,"documents":docs,"validation":report,"manifest_sha256":expected_manifest_sha256}


if __name__=="__main__":
    import json
    import sys
    try:
        request=json.load(sys.stdin)
        verified=load_step2316_benchmark(request["release_root"],request["expected_manifest_sha256"])
        print(json.dumps({"status":"verified_saved_benchmark_packet","manifest_sha256":verified["manifest_sha256"],
            "benchmark_preparation_id":verified["manifest"]["benchmark_preparation_id"],"validation":verified["validation"]},
            ensure_ascii=False,sort_keys=True,allow_nan=False))
    except Exception as error:
        print(json.dumps({"status":"failed","exception_type":type(error).__name__},sort_keys=True))
        raise SystemExit(1)
