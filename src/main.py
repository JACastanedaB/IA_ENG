import argparse
import json
import sys
from dotenv import load_dotenv
from .service import triage, TriageError

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Nubbix Support Triage CLI")
    parser.add_argument("ticket", nargs="?", help="Ticket text. If omitted, read stdin.")
    parser.add_argument("--provider", choices=["openai", "anthropic"])
    parser.add_argument("--prompt", choices=["v1", "v2"])
    parser.add_argument("--metrics", default="data/metrics.jsonl")
    args = parser.parse_args()
    ticket = args.ticket if args.ticket is not None else sys.stdin.read()
    try:
        result = triage(ticket, args.provider, args.prompt, args.metrics)
        print(result.model_dump_json())
    except (TriageError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)

if __name__ == "__main__":
    main()
