CHAMPIONS ATHLETIC MAP — AGENT READY DATA PACKAGE

Master dataset is a union of heterogeneous entity records, NOT a joined athlete-food-exercise table.
Use entity_type to filter; data_json contains domain-specific fields. The master is intended for ingestion and indexing, not as a single feature matrix.
CAVEATS: nutrient_result lacks food identifier, nutrient unit and sufficient linkage to food_portion; do not infer per-food nutrition. food_sample_link is only a linkage table.
Player bios and career records are not automatically joined because player names are not reliable unique IDs.
Basketball season statistics can include TOT and team-specific records for traded players; aggregate only after deduplicating at the intended grain.
Missing exercise descriptions and missing nutrient amounts remain null; no values invented.
Missing athlete injury_status becomes unknown, never none. Profiles may contain sensitive personal data; apply access controls.
Exercise goal tags are conservative heuristic metadata and must not be used as validated exercise prescriptions.
Agent safety rules must be enforced separately; not supplied in these nine CSVs.
Review source data licensing, food units, age appropriateness and numeric ranges before production use.

Master columns: record_id, entity_type, source_file, source_row, entity_label, agent_text, data_json.

Records: 256337
