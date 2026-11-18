# Step 23 — Scoped retrieval findings

The development-frozen retrieval route is **semantic**. Held-out outcomes did not change that choice. No alternative method was evaluated on held-out questions.

| Partition | Route | Completed questions | Ranking denominator | Recall@5 | MRR@5 | Sufficient-set denominator | Coverage@5 |
|---|---|---:|---:|---:|---:|---:|---:|
| development | lexical | 30 | 24 | 1.0 | 0.9375 | 20 | 1.0 |
| development | semantic | 30 | 24 | 1.0 | 1.0 | 20 | 1.0 |
| held_out | semantic | 30 | 24 | 1.0 | 0.9791666666666666 | 20 | 1.0 |

Each partition contains30 questions in15 paired information-need families. Six questions per partition have empty relevant sets and unavailable Recall/MRR; they remain in the complete30-outcome accounting. Ranking means use24 questions; evidence-set coverage uses20 supported requests. Verification replays do not increase these denominators.

The corpus contains11 units and12 source-record aliases from CDC sleep guidance, CDC youth-activity guidance and one UGA basketball textbook. Gold judgments were authored and reviewed by assistants; human benchmark reviews are zero. The supported questions each require one unit, so this benchmark does not test multi-unit synthesis, representative drill coverage, answer correctness or abstention accuracy. High ranking scores on this small corpus do not establish broader performance.

The scoped corpus/index/query/benchmark work is complete. Step24 must verify the generation model's own tokenizer and complete prompt budget while retaining each result's full mandatory context and usage companion. Source freshness remains subject to Step31; planner eligibility, human review and Step32 classifier evaluation remain separate. No source refresh, source-label change, model training or new exercise approval occurred.
