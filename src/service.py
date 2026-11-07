import json
import os
import time
from pathlib import Path
import yaml
from pydantic import ValidationError
from .guardrails import inspect_input, inspect_output
from .metrics import append_metric
from .providers import build_provider
from .schema import TriageResult

class TriageError(RuntimeError):
    pass

def load_prompt(version: str) -> dict:
    path = Path("prompts") / f"{version}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt version not found: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)

def triage(ticket: str, provider_name: str | None = None, prompt_version: str | None = None,
           metrics_path: str = "data/metrics.jsonl") -> TriageResult:
    enabled = os.getenv("ENABLE_INJECTION_GUARD", "true").lower() == "true"
    decision = inspect_input(ticket, enabled)
    if decision.blocked:
        # Blocked requests are also observable: zero tokens and zero estimated cost.
        append_metric("none", "none", 0, 0, 0.0, f"blocked:{decision.reason}", metrics_path)
        # No LLM call for blocked input; the fixed response is intentionally safe.
        return TriageResult(
            answer="No puedo procesar esa solicitud tal como está. Si necesitas soporte, describe el problema sin incluir instrucciones para revelar información interna ni credenciales.",
            confidence=0.99,
            category="other",
            actions=["Derivar el ticket a revisión humana por posible contenido malicioso o inválido"],
        )

    provider_name = (provider_name or os.getenv("LLM_PROVIDER", "openai")).lower()
    prompt = load_prompt(prompt_version or os.getenv("PROMPT_VERSION", "v2"))
    user_prompt = prompt["user_template"].format(ticket=ticket)
    provider = build_provider(provider_name)
    retries = int(os.getenv("MAX_RETRIES", "2"))
    last_error = None
    total_prompt = total_completion = 0
    model = "unknown"
    started = time.perf_counter()

    for attempt in range(retries + 1):
        try:
            response = provider.generate(
                prompt["system_prompt"],
                user_prompt if attempt == 0 else (
                    user_prompt + "\n\nLa respuesta anterior no cumplió el contrato. "
                    "Devuelve únicamente JSON válido con answer, confidence, category y actions."
                ),
            )
            total_prompt += response.prompt_tokens
            total_completion += response.completion_tokens
            model = response.model
            parsed = json.loads(response.text)
            result = TriageResult.model_validate(parsed)
            output_decision = inspect_output(result.answer, result.actions)
            if output_decision.blocked:
                raise ValueError(f"Output guardrail: {output_decision.reason}")
            append_metric(provider_name, model, total_prompt, total_completion,
                          time.perf_counter() - started, "success", metrics_path)
            return result
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                break
        except Exception as exc:
            last_error = exc
            break

    append_metric(provider_name, model, total_prompt, total_completion,
                  time.perf_counter() - started, "error", metrics_path)
    raise TriageError(f"LLM triage failed after retries: {last_error}") from last_error
