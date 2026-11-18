"""Run the dedicated classifier evaluation in a fresh Python process."""

from pathlib import Path
import importlib.util
import json
import sys


def main():
    root = Path(sys.argv[1]).resolve()
    evidence = json.loads(Path(sys.argv[2]).read_bytes())
    source = root / "src/champion_athletic_map/classifier_test_evaluation.py"
    spec = importlib.util.spec_from_file_location("champion_final_classifier_evaluator", source)
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    result = evaluator.execute(root, software_evidence=evidence,
                               emit=lambda message: print(message, flush=True))
    Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                           allow_nan=False) + "\n", encoding="utf-8")
    return 0 if result.get("all_models_complete") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
