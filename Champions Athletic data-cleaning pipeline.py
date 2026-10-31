
import pandas as pd
import numpy as np
import json
import os
import re
import zipfile
from pathlib import Path

# ========================================================== 1. SETUP # ==========================================================

root = Path.cwd()
out = root / "champions_cleaned"
out.mkdir(exist_ok=True)

files = {
    "exercise": "megaGymDataset(1).csv",
    "player_bio": "Players(1).csv",
    "player_career": "player_data(1).csv",
    "basketball_season": "Seasons_Stats(1).csv",
    "food_sample_link": "sub_sample_food(1).csv",
    "nutrient_result": "sub_sample_result(1).csv",
    "food_category": "food_category(1).csv",
    "food_portion": "food_portion(1).csv",
    "athlete_profile": "athlete_test_profiles.csv"
}

records = []
audit = []

# ========================================================== 2. CLEANING HELPERS # ==========================================================

def norm(v):
    if pd.isna(v):
        return None

    if isinstance(v, str):
        v = re.sub(r"\s+", " ", v).strip()
        return v if v else None

    if isinstance(v, (np.integer, np.floating)):
        return v.item()

    return v


def jsonsafe(r):
    return {
        k: norm(v)
        for k, v in r.items()
        if norm(v) is not None
    }


# ==========================================================# 3. LOAD AND CLEAN ALL DATASETS # ==========================================================

for typ, filename in files.items():

    d = pd.read_csv(root / filename, low_memory=False)

    initial = len(d)

    # Remove unnecessary columns
    d = d.loc[
        :,
        ~d.columns.str.match(
            r"^Unnamed:|^blanl$|^blank2$"
        )
    ].copy()

    # Standardize column names
    d.columns = [
        re.sub(
            "_+",
            "_",
            re.sub(
                r"[^a-z0-9]+",
                "_",
                c.lower().replace("%", "_pct")
            )
        ).strip("_")
        for c in d.columns
    ]

    # Ensure unique column names
    seen = {}
    unique = []

    for c in d.columns:
        seen[c] = seen.get(c, 0) + 1
        unique.append(
            c if seen[c] == 1 else f"{c}_{seen[c]}"
        )

    d.columns = unique

    # Normalize string values
    for c in d.select_dtypes(include="object").columns:
        d[c] = d[c].map(norm)

    # Remove exact duplicates
    d = d.drop_duplicates().reset_index(drop=True)

    # ======================================================  4. DATASET-SPECIFIC CLEANING  ======================================================

    if typ == "exercise":

        d = d.rename(columns={
            "title": "exercise_name",
            "desc": "description",
            "type": "exercise_type",
            "bodypart": "body_part",
            "level": "difficulty_level"
        })

        # Remove records without exercise names
        d = d[d.exercise_name.notna()].copy()

        # Standardize categories
        for c in [
            "body_part",
            "equipment",
            "difficulty_level",
            "exercise_type"
        ]:
            d[c] = d[c].str.lower()

        # Generate exercise goal tags
        d["goal_tag"] = d["body_part"].map(
            lambda x:
                "core"
                if x and (
                    "abdominal" in x or "core" in x
                )
                else "strength"
                if x and x in [
                    "chest",
                    "back",
                    "shoulders"
                ]
                else "general_fitness"
        )

        # Generate searchable agent text
        d["agent_text"] = (
            d[
                [
                    "exercise_name",
                    "exercise_type",
                    "body_part",
                    "equipment",
                    "difficulty_level",
                    "description"
                ]
            ]
            .fillna("")
            .agg(" | ".join, axis=1)
        )

        key = "exercise_name"

    elif typ == "athlete_profile":

        d["age"] = pd.to_numeric(
            d.age,
            errors="coerce"
        )

        d["available_days"] = pd.to_numeric(
            d.available_days,
            errors="coerce"
        )

        # Unknown injury status is not assumed safe
        d["injury_status"] = (
            d["injury_status"].fillna("unknown")
        )

        key = "athlete_id"

    elif typ == "basketball_season":

        d = d.rename(columns={
            "year": "season_year",
            "player": "player_name",
            "pos": "position",
            "tm": "team",
            "g": "games",
            "mp": "minutes_played",
            "pts": "points",
            "ast": "assists",
            "trb": "rebounds",
            "stl": "steals",
            "blk": "blocks"
        })

        key = None

    elif typ == "player_bio":

        d = d.rename(columns={
            "player": "player_name",
            "collage": "college",
            "born": "birth_year"
        })

        key = None

    elif typ == "player_career":

        d = d.rename(columns={
            "name": "player_name"
        })

        key = None

    elif typ == "food_portion":
        key = "id"

    elif typ == "food_category":
        key = "id"

    else:
        key = None

    # Missing nutrient values are not imputed.
    # No unsupported foreign-key relationships are assumed.

    # ====================================================== # 5. EXPORT CLEANED DOMAIN TABLE  # ======================================================

    output = out / f"{typ}_clean.csv"

    d.to_csv(output, index=False)

    # ====================================================== 6. BUILD CENTRALIZED AGENT RECORDS # ======================================================

    for i, r in enumerate(d.to_dict("records")):

        payload = jsonsafe(r)

        rid = (
            str(payload.get(key))
            if key and payload.get(key) is not None
            else str(i + 1)
        )

        title = (
            payload.get("exercise_name")
            or payload.get("player_name")
            or payload.get("nutrient_name")
            or payload.get("description")
            or payload.get("athlete_id")
            or f"{typ} {rid}"
        )

        record_id = (
            f"{typ}:{rid}:{i+1}"
            if key and d[key].duplicated().any()
            else f"{typ}:{rid}"
        )

        agent_text = (
            payload.get("agent_text")
            or " | ".join(
                f"{k}: {v}"
                for k, v in payload.items()
                if k not in ("footnote",)
            )[:3000]
        )

        records.append({
            "record_id": record_id,
            "entity_type": typ,
            "source_file": filename,
            "source_row": i + 1,
            "entity_label": str(title)[:200],
            "agent_text": agent_text,
            "data_json": json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False
            )
        })

    # ====================================================== # 7. DATA QUALITY AUDIT # ======================================================

    audit.append({
        "dataset": typ,
        "source_rows": initial,
        "clean_rows": len(d),
        "removed_rows": initial - len(d),
        "missing_cells": int(d.isna().sum().sum()),
        "clean_columns": len(d.columns),
        "output_file": output.name
    })


# ========================================================== 8. CREATE CENTRALIZED MASTER DATASET # ==========================================================

master = pd.DataFrame(records)

master.to_csv(
    out / "champions_master_agent_ready.csv",
    index=False
)

pd.DataFrame(audit).to_csv(
    out / "data_quality_audit.csv",
    index=False
)

# ==========================================================  9. CREATE DOCUMENTATION # ==========================================================

with open(out / "README.txt", "w") as f:

    f.write(
        "CHAMPIONS ATHLETIC MAP — AGENT READY DATA PACKAGE\n\n"
    )

    f.write(
        "Master dataset is a union of heterogeneous entity "
        "records, NOT a joined athlete-food-exercise table.\n"
    )

    f.write(
        "Use entity_type to filter; data_json contains "
        "domain-specific fields. The master is intended "
        "for ingestion and indexing, not as a single "
        "feature matrix.\n"
    )

    f.write(
        "CAVEATS: nutrient_result lacks food identifier, "
        "nutrient unit and sufficient linkage to food_portion; "
        "do not infer per-food nutrition. "
        "food_sample_link is only a linkage table.\n"
    )

    f.write(
        "Player bios and career records are not automatically "
        "joined because player names are not reliable unique IDs.\n"
    )

    f.write(
        "Basketball season statistics can include TOT and "
        "team-specific records for traded players; aggregate "
        "only after deduplicating at the intended grain.\n"
    )

    f.write(
        "Missing exercise descriptions and missing nutrient "
        "amounts remain null; no values invented.\n"
    )

    f.write(
        "Missing athlete injury_status becomes unknown, "
        "never none. Profiles may contain sensitive personal "
        "data; apply access controls.\n"
    )

    f.write(
        "Exercise goal tags are conservative heuristic "
        "metadata and must not be used as validated "
        "exercise prescriptions.\n"
    )

    f.write(
        "Agent safety rules must be enforced separately; "
        "not supplied in these nine CSVs.\n"
    )

    f.write(
        "Review source data licensing, food units, "
        "age appropriateness and numeric ranges before "
        "production use.\n"
    )

    f.write(
        "\nMaster columns: record_id, entity_type, "
        "source_file, source_row, entity_label, "
        "agent_text, data_json.\n"
    )

    f.write(
        "\nRecords: " + str(len(master)) + "\n"
    )


# ========================================================= # 10. CREATE COMPLETE ZIP PACKAGE # ==========================================================

zip_path = (
    root / "Champions_Athletic_Agent_Ready_Package.zip"
)

with zipfile.ZipFile(
    zip_path,
    "w",
    zipfile.ZIP_DEFLATED
) as z:

    for f in out.iterdir():
        z.write(f, arcname=f.name)


# ========================================================== # 11. FINAL VALIDATION AND SUMMARY # ==========================================================

print("MASTER", len(master))
print("ZIP", zip_path)

print(
    pd.DataFrame(audit).to_string(index=False)
)

print("Unique IDs:", master.record_id.is_unique)
