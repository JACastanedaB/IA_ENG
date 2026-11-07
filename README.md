

M1PI | Proyecto 

# Nubbix Support Triage

MVP de una CLI de triage para tickets de soporte. Recibe texto libre y devuelve JSON validado con `answer`, `confidence`, `category` y `actions`.

> **Estado de evaluación:** el repositorio incluye un dataset reproducible de 32 casos y un runner. No se publican scores ficticios: para completar la tabla hay que ejecutar las evals con credenciales y registrar los resultados reales.

## Requisitos

- Python 3.10+
- Una API key de OpenAI o Anthropic
- Conexión a internet para invocar el proveedor

## Instalación

```bash
git clone <URL_DEL_REPOSITORIO>
cd nubbix-support-triage
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Completa en `.env` la clave del proveedor elegido y configura `LLM_PROVIDER`. Nunca subas `.env` al repositorio.

## Uso

```bash
python -m src.main "Me cobraron dos veces la suscripción"
```

También puedes seleccionar proveedor y versión de prompt:

```bash
python -m src.main --provider anthropic --prompt v2 "No puedo abrir el dashboard"
```

La salida estándar contiene solo el JSON de negocio. Los errores se escriben en stderr y terminan con código distinto de cero. La CLI acepta texto por stdin:

```bash
echo "Quiero agregar un usuario" | python -m src.main
```

Ejemplo ilustrativo de forma (el contenido real depende del modelo):

```json
{
  "answer": "Lamentamos el inconveniente. Vamos a revisar los cargos asociados a tu suscripción. ¿Podrías compartir las fechas y los importes?",
  "confidence": 0.97,
  "category": "billing",
  "actions": [
    "Verificar los movimientos y sus identificadores en el sistema de pagos",
    "Comprobar si existe un cargo duplicado antes de gestionar un ajuste"
  ]
}
```

## Arquitectura

- `src/providers.py`: interfaz mínima y adaptadores OpenAI / Anthropic.
- `src/schema.py`: contrato Pydantic estricto; categorías cerradas y campos obligatorios.
- `src/service.py`: orquestación, carga YAML, reintentos ante JSON o esquema inválido.
- `src/guardrails.py`: rechazo temprano de patrones de injection, límites de tamaño y validación de salida.
- `src/metrics.py`: métricas append-only JSONL con tokens, latencia y costo estimado.
- `prompts/`: prompts YAML versionados.
- `evals/`: dataset etiquetado, runner y casos adversariales.

## Context engineering: few-shot + límites de confianza

`v1` es zero-shot y sirve como baseline. `v2` usa few-shot examples representativos, definiciones operativas de categorías, reglas explícitas contra afirmaciones no verificadas y una delimitación `<ticket>` para tratar el texto del usuario como dato no confiable.

La hipótesis es que ejemplos breves y criterios de clasificación explícitos reducen ambigüedad entre categorías y mejoran consistencia. La delimitación no es una frontera de seguridad por sí sola: se combina con detección heurística previa, contrato Pydantic y revisión del contenido de salida.

**Selección basada en evidencia:** ejecutar ambos prompts sobre el mismo dataset y proveedor, guardar los reportes y completar la tabla. No elegir `v2` como ganador hasta comparar los resultados medidos.

## Evals

```bash
python evals/runner.py --provider openai --prompt v1
python evals/runner.py --provider openai --prompt v2
python evals/runner.py --provider anthropic --prompt v1
python evals/runner.py --provider anthropic --prompt v2
```

El runner reporta accuracy de categoría y tasa de respuestas que pasaron validación Pydantic, global y por categoría. Las ejecuciones escriben métricas en `data/eval_metrics.jsonl`. El dataset tiene 32 casos (8 por categoría).

| Proveedor | Prompt | Casos | Accuracy global | Validación de esquema |
|---|---|---:|---:|---:|
| Pendiente de ejecución | v1 | 32 | — | — |
| Pendiente de ejecución | v2 | 32 | — | — |

Para una iteración rápida: `--limit 5`. No compares resultados de distintas muestras; usa el mismo dataset y condiciones.

## Métricas y costo

Cada llamada exitosa o fallida escribe una línea en `data/metrics.jsonl` con timestamp UTC, proveedor, modelo, tokens de entrada/salida/total, latencia y costo estimado. Los precios por millón de tokens están en `.env`; actualízalos según el precio vigente de tu modelo y documenta la fecha usada. El costo es una estimación basada en usage informado por el proveedor, no una factura.

Las entradas bloqueadas antes de llamar al LLM no generan consumo de tokens ni registro de llamada en esta versión.

## Seguridad y limitaciones

- Guardrail de entrada: patrones frecuentes de prompt injection/jailbreak, entrada vacía y límite de longitud.
- Guardrail de salida: rechazo de posibles secretos/API keys y validación estricta del esquema.
- Las acciones son sugerencias para un agente humano; no se ejecutan.
- `evals/adversarial.jsonl` documenta 10 ataques. El bloqueo heurístico es intencionalmente conservador y puede tener falsos positivos y negativos. La suite está documentada, pero su tasa de bloqueo debe medirse ejecutando pruebas específicas; no se debe asumir que el filtro regex resiste ataques parafraseados.
- No se integra moderación comercial del proveedor en esta primera versión. Para producción, añadir moderación dedicada, rate limiting, trazabilidad por request y revisión humana para baja confianza.
- No enviar datos personales innecesarios ni secretos a proveedores externos.

## Prueba adversarial

El guardrail de entrada bloquea los patrones explícitos incluidos en la suite antes de invocar el modelo. Para medir efecto, ejecutar una prueba que importe `inspect_input` y recorra `evals/adversarial.jsonl`; registrar detección por tipo de ataque y falsos positivos en tickets benignos. En la comprobación local inicial, el filtro detectó 8/10 (80%) de estos ejemplos exactos; no equivale a robustez general.

## Decisiones y próximos pasos

1. Mantener una abstracción pequeña de proveedor para evitar acoplar la lógica de negocio a un SDK.
2. Usar temperatura 0 para favorecer reproducibilidad en clasificación.
3. Reintentar solo errores de parseo, validación o contenido de salida; errores transitorios de API se reportan sin un bucle ilimitado.
4. Mantener JSONL en lugar de una base de datos para cumplir el alcance del módulo.
5. Antes de producción: moderación de entrada/salida, backoff para rate limits, timeout explícito, tests unitarios, calibración de confidence y métricas de falsos positivos/negativos.

## Configuración

Variables principales: `LLM_PROVIDER`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `PROMPT_VERSION`, `MAX_RETRIES`, `MAX_OUTPUT_TOKENS`, `TEMPERATURE` y precios por millón de tokens. Ver `.env.example`.
