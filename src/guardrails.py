import re
from dataclasses import dataclass

INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"ignora (todas )?las instrucciones",
    r"reveal (the )?(system|developer) prompt",
    r"muestra(me)? el (prompt|mensaje) del sistema",
    r"act as (an? )?(unrestricted|different)",
    r"jailbreak",
    r"developer mode",
    r"exfiltrat(e|ion)",
    r"print.*(api key|secret|token)",
]

SENSITIVE_REQUEST_PATTERNS = [
    r"(password|contraseña|clave).{0,30}(envía|envia|compart|send|provide)",
    r"(api key|token|código mfa|codigo mfa)",
]

@dataclass
class GuardrailDecision:
    blocked: bool
    reason: str = ""

def inspect_input(ticket: str, enabled: bool = True) -> GuardrailDecision:
    if not ticket.strip():
        return GuardrailDecision(True, "empty_input")
    if len(ticket) > 12000:
        return GuardrailDecision(True, "input_too_long")
    if enabled:
        lowered = ticket.lower()
        if any(re.search(p, lowered) for p in INJECTION_PATTERNS):
            return GuardrailDecision(True, "suspected_prompt_injection")
    return GuardrailDecision(False)

def inspect_output(answer: str, actions: list[str]) -> GuardrailDecision:
    combined = (answer + " " + " ".join(actions)).lower()
    if re.search(r"(tu contraseña es|your password is)\s+\S+", combined):
        return GuardrailDecision(True, "possible_secret_disclosure")
    if re.search(r"\b(sk-[a-z0-9]{12,}|sk-ant-[a-z0-9-]{12,})\b", combined):
        return GuardrailDecision(True, "possible_api_key_disclosure")
    return GuardrailDecision(False)
