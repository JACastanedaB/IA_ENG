import json
import os
from datetime import datetime, timezone
from pathlib import Path

def estimate_cost(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    prefix = "OPENAI" if provider == "openai" else "ANTHROPIC"
    input_rate = float(os.getenv(f"{prefix}_INPUT_USD_PER_1M", "0"))
    output_rate = float(os.getenv(f"{prefix}_OUTPUT_USD_PER_1M", "0"))
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000

def append_metric(provider: str, model: str, prompt_tokens: int, completion_tokens: int,
                  latency_s: float, status: str, path: str = "data/metrics.jsonl") -> dict:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        },
        "latency_s": round(latency_s, 4),
        "estimated_cost_usd": round(estimate_cost(provider, prompt_tokens, completion_tokens), 8),
        "status": status,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
