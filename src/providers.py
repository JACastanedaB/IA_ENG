import os
from dataclasses import dataclass
from typing import Protocol

@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str

class LLMProvider(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse: ...

class OpenAIProvider:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=float(os.getenv("TEMPERATURE", "0")),
            max_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "500")),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        usage = response.usage
        return LLMResponse(
            text=response.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            model=self.model,
        )

class AnthropicProvider:
    def __init__(self):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")

    def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "500")),
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        usage = response.usage
        return LLMResponse(
            text=text,
            prompt_tokens=usage.input_tokens,
            completion_tokens=usage.output_tokens,
            model=self.model,
        )

def build_provider(name: str) -> LLMProvider:
    normalized = name.strip().lower()
    if normalized == "openai":
        return OpenAIProvider()
    if normalized == "anthropic":
        return AnthropicProvider()
    raise ValueError(f"Unsupported provider: {name}. Choose openai or anthropic.")
