import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.guardrails import inspect_input

def main():
    cases = [json.loads(x) for x in open(ROOT / "evals/adversarial.jsonl", encoding="utf-8") if x.strip()]
    detected = 0
    for case in cases:
        decision = inspect_input(case["ticket"], enabled=True)
        detected += int(decision.blocked)
        print(f'{case["id"]}: {"BLOCKED" if decision.blocked else "NOT BLOCKED"} ({decision.reason})')
    print(f"Detection: {detected}/{len(cases)} ({detected/len(cases):.1%})")
if __name__ == "__main__":
    main()
