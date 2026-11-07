import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.service import triage

def load_dataset(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run Nubbix triage evaluations")
    parser.add_argument("--provider", choices=["openai", "anthropic"])
    parser.add_argument("--prompt", choices=["v1", "v2"], default="v2")
    parser.add_argument("--dataset", default="evals/dataset.jsonl")
    parser.add_argument("--limit", type=int, default=0, help="0 means all cases")
    parser.add_argument("--metrics", default="data/eval_metrics.jsonl")
    args = parser.parse_args()

    cases = load_dataset(args.dataset)
    if args.limit:
        cases = cases[:args.limit]
    totals = defaultdict(lambda: {"n": 0, "correct": 0, "valid": 0})
    all_correct = all_valid = 0
    for case in cases:
        category = case["category"]
        bucket = totals[category]
        bucket["n"] += 1
        try:
            result = triage(case["ticket"], args.provider, args.prompt, args.metrics)
            valid = True
            correct = result.category == category
        except Exception as exc:
            valid = correct = False
            print(f"ERROR [{case['id']}]: {exc}", file=sys.stderr)
        bucket["valid"] += int(valid)
        bucket["correct"] += int(correct)
        all_valid += int(valid)
        all_correct += int(correct)

    n = len(cases)
    report = {
        "prompt": args.prompt,
        "provider": args.provider or os.getenv("LLM_PROVIDER", "openai"),
        "cases": n,
        "category_accuracy": round(all_correct / n, 4) if n else 0,
        "schema_success_rate": round(all_valid / n, 4) if n else 0,
        "by_category": {
            cat: {
                "cases": v["n"],
                "accuracy": round(v["correct"] / v["n"], 4),
                "schema_success_rate": round(v["valid"] / v["n"], 4),
            } for cat, v in sorted(totals.items())
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
