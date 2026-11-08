# Nubbix Support Triage — guía técnica archivo por archivo

**Versión documentada:** contenido del archivo `nubbix-support-triage.zip` generado el 7 de noviembre de 2026.  
**Objetivo:** explicar qué hace cada archivo, cómo se ejecuta el flujo, qué variables y funciones contiene y cómo se relacionan los módulos.

> **Alcance y precisión:** esta guía describe el código que está dentro del ZIP original. No presupone cambios que todavía no estén incorporados en ese archivo. En particular, esta versión contiene proveedores OpenAI y Anthropic; todavía no contiene el adaptador HTTP de OpenCode ni el proveedor DeepSeek. Si se añadió código localmente después de descargar el ZIP, esa versión local debe revisarse para sincronizar esta documentación.

---

## 1. ¿Qué resuelve el proyecto?

Nubbix Support Triage recibe un ticket de soporte escrito en lenguaje natural y lo transforma en una salida JSON con cuatro campos:

- `answer`: respuesta sugerida al cliente.
- `confidence`: confianza de clasificación entre `0.0` y `1.0`.
- `category`: categoría del ticket: `billing`, `technical`, `account` u `other`.
- `actions`: lista de pasos sugeridos para el agente humano. El sistema no ejecuta esas acciones.

El sistema aplica controles de entrada, carga un prompt versionado, llama a un proveedor LLM, valida la respuesta con Pydantic y registra métricas en formato JSONL.

## 2. Flujo de ejecución de extremo a extremo

1. `src/main.py` lee argumentos de consola o el texto enviado por `stdin`.
2. `load_dotenv()` carga variables definidas en `.env`.
3. `src/service.py::triage()` recibe el ticket y decide si debe bloquearse antes de llamar al modelo.
4. `src/guardrails.py::inspect_input()` comprueba entrada vacía, longitud excesiva y patrones conocidos de prompt injection.
5. Si la entrada se bloquea, se devuelve una respuesta fija segura y se registra una métrica con cero tokens.
6. Si la entrada pasa, `load_prompt()` lee `prompts/v1.yaml` o `prompts/v2.yaml`.
7. `build_provider()` instancia OpenAI o Anthropic, según el argumento CLI o `LLM_PROVIDER`.
8. El proveedor recibe el prompt de sistema y el prompt del usuario y devuelve un `LLMResponse`.
9. `triage()` convierte el texto devuelto a JSON y valida sus campos con `TriageResult`.
10. `inspect_output()` busca indicios de divulgación de contraseñas o claves API.
11. Si JSON, esquema o salida no pasan la validación, el servicio puede reintentar hasta `MAX_RETRIES` veces, agregando una instrucción correctiva.
12. Se registra una línea de métricas con tokens, latencia, costo estimado y estado.
13. La CLI imprime el JSON validado. Si ocurre un error no recuperable, imprime un objeto `error` en `stderr` y termina con código `2`.

## 3. Estructura general

```text
nubbix-support-triage/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── service.py
│   ├── providers.py
│   ├── schema.py
│   ├── guardrails.py
│   └── metrics.py
├── prompts/
│   ├── v1.yaml
│   └── v2.yaml
├── evals/
│   ├── dataset.jsonl
│   ├── runner.py
│   ├── adversarial.jsonl
│   └── adversarial_check.py
└── data/
    └── .gitkeep
```

---

# 4. Documentación detallada por archivo

## 4.1 `src/__init__.py`

**Propósito:** marca `src` como paquete Python. Está vacío intencionalmente.

**Contenido:** no declara variables, clases ni funciones.

**¿Por qué existe?** permite ejecutar módulos con importaciones relativas, por ejemplo:

```powershell
python -m src.main "Me cobraron dos veces la suscripción"
```

No requiere configuración adicional.

## 4.2 `src/main.py` — interfaz de línea de comandos (CLI)

**Propósito:** es el punto de entrada ejecutable. Recibe el ticket, los parámetros de ejecución, invoca el servicio y presenta el resultado.

### Imports

- `argparse`: define y procesa argumentos de consola.
- `json`: serializa errores como JSON.
- `sys`: lee `stdin`, escribe en `stderr` y permite establecer el código de salida.
- `load_dotenv`: carga variables de entorno desde `.env`.
- `triage`, `TriageError`: función principal de negocio y excepción propia del servicio.

### Función `main()` paso a paso

1. Ejecuta `load_dotenv()` para que la configuración del archivo `.env` esté disponible mediante `os.getenv()`.
2. Crea un `ArgumentParser` con la descripción de la CLI.
3. Define los argumentos:
   - `ticket`: argumento posicional opcional. Si no se entrega, el texto se lee desde `stdin`.
   - `--provider`: proveedor permitido por esta versión: `openai` o `anthropic`. Si se omite, el servicio usa `LLM_PROVIDER` o `openai`.
   - `--prompt`: versión de prompt permitida: `v1` o `v2`. Si se omite, el servicio usa `PROMPT_VERSION` o `v2`.
   - `--metrics`: ruta del archivo JSONL de métricas. Valor predeterminado: `data/metrics.jsonl`.
4. Resuelve el texto del ticket usando `args.ticket` o `sys.stdin.read()`.
5. Llama a `triage(ticket, provider, prompt, metrics)`.
6. Si recibe un `TriageResult`, imprime `model_dump_json()`.
7. Si ocurre `TriageError`, `ValueError` o `KeyError`, escribe `{"error": ...}` en `stderr` y termina con código `2`.

### Variables locales

| Variable | Significado |
|---|---|
| `parser` | Configuración del analizador de argumentos. |
| `args` | Valores ingresados por el usuario en la consola. |
| `ticket` | Texto que se va a clasificar. |
| `result` | Objeto Pydantic validado devuelto por el servicio. |
| `exc` | Excepción capturada para comunicar el error. |

### Ejemplos

```powershell
python -m src.main "Me cobraron dos veces la suscripción"
python -m src.main --provider anthropic --prompt v2 "No puedo abrir el dashboard"
echo "Quiero agregar un usuario" | python -m src.main
```

## 4.3 `src/service.py` — orquestación del triage

**Propósito:** coordina las distintas partes del sistema. No implementa el SDK de ningún proveedor; delega esa tarea a `providers.py`.

### Imports

- `json`: interpreta la respuesta del modelo.
- `os`: lee controles y configuración desde variables de entorno.
- `time`: mide duración con `time.perf_counter()`.
- `Path`: construye la ruta del prompt.
- `yaml`: interpreta los archivos YAML.
- `ValidationError`: identifica errores de validación Pydantic.
- `inspect_input`, `inspect_output`: guardrails de entrada y salida.
- `append_metric`: persiste métricas.
- `build_provider`: construye el adaptador LLM.
- `TriageResult`: contrato de salida.

### Clase `TriageError`

Excepción propia que representa un fallo final durante el proceso de triage. Se usa para envolver el último error ocurrido durante la generación, el parseo o la validación.

### Función `load_prompt(version: str) -> dict`

**Parámetro:**
- `version`: identificador del prompt, por ejemplo `v1` o `v2`.

**Proceso:**
1. Construye `prompts/<version>.yaml`.
2. Comprueba que el archivo exista.
3. Abre el archivo con codificación UTF-8.
4. Usa `yaml.safe_load()` para convertir YAML a un diccionario Python.
5. Devuelve ese diccionario al servicio.

**Error posible:** `FileNotFoundError` si no existe el archivo solicitado.

### Función `triage(ticket, provider_name=None, prompt_version=None, metrics_path=...)`

**Parámetros:**

| Parámetro | Descripción |
|---|---|
| `ticket` | Texto de entrada del cliente. |
| `provider_name` | Proveedor opcional. Si es `None`, se usa `LLM_PROVIDER` y, como último valor, `openai`. |
| `prompt_version` | Prompt opcional. Si es `None`, se usa `PROMPT_VERSION` y, como último valor, `v2`. |
| `metrics_path` | Ruta de salida de las métricas. Predeterminada: `data/metrics.jsonl`. |

**Variables internas principales:**

| Variable | Uso |
|---|---|
| `enabled` | Activa o desactiva el filtro de patrones de injection según `ENABLE_INJECTION_GUARD`. |
| `decision` | Resultado de la inspección de entrada. |
| `provider_name` | Nombre normalizado del proveedor. |
| `prompt` | Diccionario cargado desde YAML. |
| `user_prompt` | Plantilla de usuario con `{ticket}` reemplazado por el texto real. |
| `provider` | Instancia del proveedor elegida. |
| `retries` | Número máximo de reintentos adicionales, leído desde `MAX_RETRIES`. |
| `last_error` | Última excepción capturada. |
| `total_prompt` | Acumulado de tokens de entrada reportados por el proveedor. |
| `total_completion` | Acumulado de tokens de salida reportados por el proveedor. |
| `model` | Identificador del modelo informado por el adaptador. |
| `started` | Instante inicial usado para calcular latencia. |
| `attempt` | Índice de intento actual, desde cero hasta `retries`. |
| `response` | Instancia `LLMResponse` devuelta por el proveedor. |
| `parsed` | Diccionario obtenido al decodificar el JSON de texto. |
| `result` | Objeto `TriageResult` validado. |
| `output_decision` | Resultado de la inspección de salida. |

**Proceso detallado:**

1. Lee `ENABLE_INJECTION_GUARD`; por defecto está habilitado.
2. Ejecuta `inspect_input(ticket, enabled)`.
3. Si la entrada está bloqueada, registra una métrica con proveedor/modelo `none`, cero tokens y estado `blocked:<razón>`. Devuelve una respuesta fija segura con categoría `other`; no llama al LLM.
4. Determina proveedor y versión de prompt usando argumentos o variables de entorno.
5. Carga el prompt y sustituye `{ticket}` dentro de `user_template`.
6. Construye el adaptador con `build_provider()`.
7. Lee `MAX_RETRIES` (por defecto `2`). El total de intentos es `retries + 1`.
8. Inicia el cronómetro.
9. En cada intento, llama a `provider.generate(system_prompt, user_prompt)`.
10. En intentos posteriores agrega una instrucción para que el modelo devuelva exclusivamente JSON con las cuatro claves del contrato.
11. Acumula tokens y guarda el nombre del modelo.
12. Ejecuta `json.loads()` y luego `TriageResult.model_validate()`.
13. Ejecuta `inspect_output()` para buscar indicios de secretos.
14. Si la respuesta es válida, escribe métricas con estado `success` y devuelve el resultado.
15. Si ocurre `JSONDecodeError`, `ValidationError` o `ValueError`, guarda el error y reintenta mientras queden intentos.
16. Cualquier otra excepción se captura como error final sin continuar el bucle.
17. Si todos los intentos fallan, registra estado `error` y lanza `TriageError`.

**Nota de comportamiento:** el bloque de reintentos no reintenta todos los errores de red/API; la implementación corta ante excepciones generales. Esto evita reintentos ilimitados, pero no implementa todavía backoff específico para rate limits.

## 4.4 `src/providers.py` — abstracción y adaptadores LLM

**Propósito:** aislar la integración con los SDK de proveedores para que el servicio use una interfaz común.

### Imports

- `os`: lee API keys, modelos y parámetros desde variables de entorno.
- `dataclass`: genera automáticamente métodos básicos de la clase de datos `LLMResponse`.
- `Protocol`: define la interfaz que deben respetar los proveedores.

### Clase `LLMResponse`

Contenedor de datos devuelto por cada adaptador.

| Campo | Tipo | Significado |
|---|---|---|
| `text` | `str` | Texto generado por el modelo; se espera que contenga JSON. |
| `prompt_tokens` | `int` | Tokens de entrada reportados por el SDK. |
| `completion_tokens` | `int` | Tokens de salida reportados por el SDK. |
| `model` | `str` | Nombre del modelo utilizado. |

### Protocolo `LLMProvider`

Define el método que debe ofrecer cualquier proveedor:

`generate(system_prompt: str, user_prompt: str) -> LLMResponse`

`Protocol` permite expresar la interfaz esperada sin obligar a que las clases hereden de una clase base concreta.

### Clase `OpenAIProvider`

**`__init__()`**
1. Importa `OpenAI` dentro del constructor.
2. Crea el cliente con `OPENAI_API_KEY`.
3. Lee `OPENAI_MODEL`; si no existe, utiliza `gpt-4o-mini`.

**`generate(system_prompt, user_prompt)`**
1. Llama a `chat.completions.create()`.
2. Envía modelo, temperatura, límite de tokens, formato JSON y mensajes system/user.
3. Lee texto de `response.choices[0].message.content`.
4. Lee tokens desde `response.usage`.
5. Devuelve un `LLMResponse`.

**Variables de configuración relacionadas:** `OPENAI_API_KEY`, `OPENAI_MODEL`, `TEMPERATURE`, `MAX_OUTPUT_TOKENS`.

### Clase `AnthropicProvider`

**`__init__()`**
1. Importa `Anthropic` dentro del constructor.
2. Crea el cliente con `ANTHROPIC_API_KEY`.
3. Lee `ANTHROPIC_MODEL`; valor predeterminado: `claude-3-5-haiku-latest`.

**`generate(system_prompt, user_prompt)`**
1. Llama a `messages.create()` con modelo, límite de tokens, prompt de sistema y mensaje del usuario.
2. Une los bloques de texto devueltos.
3. Lee tokens de `response.usage.input_tokens` y `output_tokens`.
4. Devuelve un `LLMResponse`.

**Advertencia importante detectada en el código:** la versión incluida en el ZIP envía `temperature` a `Anthropic.messages.create()`. Algunas versiones actuales del SDK/API de Anthropic no aceptan ese argumento, lo que produce el error `Messages.create() got an unexpected keyword argument 'temperature'`. Si aparece ese error, elimina el argumento `temperature=...` de esa llamada. La variable global `TEMPERATURE` puede seguir siendo utilizada por OpenAI.

### Función `build_provider(name: str) -> LLMProvider`

1. Quita espacios y convierte el nombre a minúsculas.
2. Si es `openai`, devuelve `OpenAIProvider()`.
3. Si es `anthropic`, devuelve `AnthropicProvider()`.
4. Para cualquier otro valor, lanza `ValueError` con los proveedores admitidos.

**Importante:** el código de este ZIP no registra `opencode` ni `deepseek`. Para incorporar OpenCode se debe implementar el adaptador, añadir su rama en `build_provider()` y ampliar las opciones CLI y del runner.

## 4.5 `src/schema.py` — contrato JSON con Pydantic

**Propósito:** define y valida la estructura que debe tener la respuesta de triage.

### Imports

- `Literal`: restringe una variable a un conjunto fijo de cadenas.
- `BaseModel`: clase base de modelos Pydantic.
- `Field`: define límites y restricciones de los campos.
- `ConfigDict`: configura el comportamiento del modelo.
- `field_validator`: permite aplicar validación personalizada.

### Tipo `Category`

```python
Category = Literal["billing", "technical", "account", "other"]
```

No permite categorías diferentes a las cuatro declaradas.

### Clase `TriageResult`

| Campo | Tipo / restricciones | Descripción |
|---|---|---|
| `answer` | `str`, 1 a 2000 caracteres | Respuesta sugerida al cliente. |
| `confidence` | `float`, entre 0 y 1 | Confianza de clasificación. |
| `category` | `Category` | Categoría permitida. |
| `actions` | Lista de cadenas, entre 1 y 8 elementos | Acciones sugeridas al agente humano. |

`model_config = ConfigDict(extra="forbid")` impide campos adicionales que no estén definidos en el contrato.

### Validador `validate_actions(actions)`

1. Recorre los elementos de la lista.
2. Elimina espacios al inicio y al final.
3. Descarta elementos vacíos.
4. Si no queda ningún elemento, lanza `ValueError`.
5. Devuelve la lista depurada.

Pydantic ejecuta esta validación cuando se construye el modelo o se llama a `TriageResult.model_validate()`.

## 4.6 `src/guardrails.py` — controles de entrada y salida

**Propósito:** aplicar filtros heurísticos antes y después de la llamada al modelo. No reemplaza un sistema completo de moderación o seguridad.

### Imports

- `re`: búsqueda mediante expresiones regulares.
- `dataclass`: define el contenedor `GuardrailDecision`.

### Constante `INJECTION_PATTERNS`

Lista de patrones regex que buscan instrucciones conocidas de prompt injection, como ignorar instrucciones anteriores, revelar prompts, activar modos de desarrollador o exfiltrar secretos.

### Constante `SENSITIVE_REQUEST_PATTERNS`

Contiene patrones relacionados con solicitudes de contraseñas, claves y tokens. En la versión actual esta constante está declarada, pero no es utilizada por `inspect_input()` ni por otra función. Su presencia no implica que esas expresiones estén bloqueadas.

### Clase `GuardrailDecision`

| Campo | Tipo | Descripción |
|---|---|---|
| `blocked` | `bool` | Indica si la entrada o salida se bloqueó. |
| `reason` | `str` | Código breve de la razón; por defecto cadena vacía. |

### Función `inspect_input(ticket, enabled=True)`

1. Si el texto está vacío o contiene solo espacios, bloquea con `empty_input`.
2. Si supera 12.000 caracteres, bloquea con `input_too_long`.
3. Si `enabled` es verdadero, convierte el ticket a minúsculas y evalúa los patrones de `INJECTION_PATTERNS`.
4. Si coincide con alguno, bloquea con `suspected_prompt_injection`.
5. Si no se cumple ninguna condición, devuelve `blocked=False`.

### Función `inspect_output(answer, actions)`

1. Une respuesta y acciones en un único texto en minúsculas.
2. Busca frases que parezcan revelar una contraseña.
3. Busca patrones de claves API de OpenAI (`sk-...`) o Anthropic (`sk-ant-...`).
4. Si encuentra coincidencia, devuelve decisión de bloqueo con la razón correspondiente.
5. En caso contrario, permite la salida.

**Limitaciones:** los filtros se basan en patrones exactos o aproximados. Pueden dejar pasar ataques parafraseados y bloquear texto benigno. Deben complementarse con controles adicionales y pruebas adversariales.

## 4.7 `src/metrics.py` — observabilidad y costos estimados

**Propósito:** agrega una línea JSON por ejecución a un archivo JSONL, sin sobrescribir los registros anteriores.

### Imports

- `json`: serializa cada registro.
- `os`: lee tarifas configuradas en variables de entorno.
- `datetime`, `timezone`: genera timestamp UTC.
- `Path`: crea directorios y maneja la ruta de destino.

### Función `estimate_cost(provider, prompt_tokens, completion_tokens)`

1. Selecciona prefijo `OPENAI` si `provider == "openai"`; para cualquier otro valor usa `ANTHROPIC`.
2. Lee tarifas por millón de tokens desde `<PREFIJO>_INPUT_USD_PER_1M` y `<PREFIJO>_OUTPUT_USD_PER_1M`.
3. Calcula el costo como `(tokens_entrada * tarifa_entrada + tokens_salida * tarifa_salida) / 1.000.000`.
4. Devuelve el costo estimado en USD.

**Precaución:** esta lógica presupone que cualquier proveedor distinto de OpenAI es Anthropic. Al añadir OpenCode/DeepSeek habrá que ampliar el cálculo; de lo contrario se asignará una tarifa incorrecta. Si no hay tarifas configuradas, el valor predeterminado es cero.

### Función `append_metric(...)`

**Parámetros:** proveedor, modelo, tokens de entrada, tokens de salida, latencia en segundos, estado y ruta de archivo.

**Proceso:**
1. Construye un timestamp ISO-8601 en UTC.
2. Crea el objeto con proveedor, modelo, tokens, latencia, costo estimado y estado.
3. Crea el directorio padre si no existe.
4. Abre el archivo en modo append (`a`).
5. Escribe un JSON por línea y retorna el diccionario registrado.

**Campos registrados:**

- `timestamp`: fecha/hora UTC.
- `provider`: proveedor usado.
- `model`: modelo usado.
- `tokens.prompt`: tokens de entrada.
- `tokens.completion`: tokens de salida.
- `tokens.total`: suma de ambos.
- `latency_s`: duración redondeada a cuatro decimales.
- `estimated_cost_usd`: costo estimado redondeado a ocho decimales.
- `status`: `success`, `error` o estado de bloqueo.

## 4.8 `prompts/v1.yaml` — prompt baseline zero-shot

**Propósito:** primera versión de instrucciones para el modelo.

### Variables/campos YAML

- `version`: identificador de versión (`v1`).
- `name`: nombre descriptivo (`zero_shot_basic`).
- `technique`: técnica declarada (`zero-shot`).
- `system_prompt`: rol, categorías, tono, restricciones y formato esperado.
- `user_template`: plantilla que contiene `{ticket}`; el servicio reemplaza ese marcador por el ticket recibido.

### Comportamiento

El prompt instruye al modelo a clasificar en cuatro categorías, responder en español, no inventar políticas ni acciones realizadas, evitar solicitar secretos y devolver exclusivamente JSON.

Se usa como baseline para comparar el efecto de la versión más elaborada `v2`.

## 4.9 `prompts/v2.yaml` — few-shot y límites de confianza

**Propósito:** versión de prompt con reglas más explícitas y ejemplos.

### Variables/campos YAML

- `version`: `v2`.
- `name`: `few_shot_with_trust_boundaries`.
- `technique`: few-shot y delimitación explícita de datos no confiables.
- `system_prompt`: define el rol, las categorías, reglas de seguridad y ejemplos de tickets con salidas JSON.
- `user_template`: presenta el ticket dentro de etiquetas `<ticket>...</ticket>`.

### Diferencias frente a v1

1. Define cada categoría con ejemplos de temas asociados.
2. Aclara que el ticket es dato no confiable y no debe cambiar las instrucciones del sistema.
3. Explicita que `actions` son sugerencias para un humano y no operaciones ejecutadas.
4. Aclara que `confidence` mide certeza de clasificación, no probabilidad de resolución.
5. Incluye ejemplos few-shot de facturación, error técnico y gestión de usuarios.
6. Delimita el texto del ticket para separar instrucciones del sistema y contenido aportado por el cliente.

La delimitación y las instrucciones del prompt no son una barrera de seguridad suficiente por sí solas; se combinan con los guardrails y la validación estructural.

## 4.10 `evals/dataset.jsonl` — dataset de evaluación etiquetado

**Propósito:** contiene 32 ejemplos de tickets para medir clasificación y validez estructural.

Cada línea es un objeto JSON independiente con estos campos:

| Campo | Tipo | Uso |
|---|---|---|
| `id` | `str` | Identificador único del caso, por ejemplo `b01`. |
| `ticket` | `str` | Texto de entrada simulado. |
| `category` | `str` | Etiqueta esperada: `billing`, `technical`, `account` u `other`. |

El dataset incluye 8 casos por categoría. No se carga completo en memoria por un framework externo; `evals/runner.py` lo lee línea por línea y convierte cada línea a diccionario.

**Cómo agregar un caso:** añade una nueva línea JSON válida, conserva las tres claves y utiliza una categoría permitida. No agregues comentarios dentro del JSONL.

## 4.11 `evals/runner.py` — ejecución automatizada de evaluaciones

**Propósito:** ejecuta el servicio contra el dataset y calcula métricas globales y por categoría.

### Imports y configuración

- `argparse`: parámetros CLI.
- `json`: lectura de JSONL y salida del reporte.
- `os`: valor de proveedor por defecto desde entorno.
- `sys`: agrega la raíz del proyecto al path de importación.
- `defaultdict`: acumula resultados por categoría.
- `Path`: determina la raíz del repositorio.
- `load_dotenv`: carga `.env`.
- `triage`: función evaluada.

### Constante `ROOT`

Ruta absoluta a la carpeta raíz del proyecto, calculada a partir de la ubicación del script.

### Función `load_dataset(path)`

Abre el archivo JSONL, ignora líneas vacías, decodifica cada línea con `json.loads()` y devuelve una lista de casos.

### Función `main()` paso a paso

1. Carga variables de entorno.
2. Define opciones:
   - `--provider`: `openai` o `anthropic`.
   - `--prompt`: `v1` o `v2`, predeterminado `v2`.
   - `--dataset`: ruta del dataset, predeterminada `evals/dataset.jsonl`.
   - `--limit`: máximo de casos; `0` significa todos.
   - `--metrics`: ruta de métricas, predeterminada `data/eval_metrics.jsonl`.
3. Carga el dataset y aplica el límite si se especificó.
4. Crea acumuladores por categoría con `n`, `correct` y `valid`.
5. Ejecuta `triage()` para cada caso.
6. Considera válido un caso si el servicio devuelve un `TriageResult` sin excepción.
7. Considera correcta la clasificación si `result.category == category`.
8. Ante error, marca el caso como no válido/no correcto e imprime el error en `stderr`.
9. Calcula accuracy global, tasa de éxito de esquema y métricas por categoría.
10. Imprime un reporte JSON.

### Métricas del reporte

- `category_accuracy`: predicciones de categoría correctas / total de casos.
- `schema_success_rate`: respuestas que completaron el servicio y pasaron el esquema / total de casos.
- `by_category`: los mismos indicadores calculados por categoría.

**Comandos:**

```powershell
python evals/runner.py --provider openai --prompt v1
python evals/runner.py --provider openai --prompt v2
python evals/runner.py --provider anthropic --prompt v1
python evals/runner.py --provider anthropic --prompt v2
python evals/runner.py --provider openai --prompt v2 --limit 5
```

La ejecución requiere credenciales y llamadas reales al proveedor. Los resultados no deben inventarse ni copiarse de una ejecución anterior con otro modelo.

## 4.12 `evals/adversarial.jsonl` — ejemplos de ataques

**Propósito:** documenta 10 entradas adversariales que intentan modificar el rol del modelo, revelar el prompt, extraer secretos o ignorar reglas.

Cada línea incluye:

- `id`: identificador del ataque (`adv01`, etc.).
- `ticket`: texto adversarial que se entrega al filtro.
- `expected`: comportamiento esperado, en este dataset `blocked_or_safe_refusal`.
- `attack_type`: clasificación del tipo de ataque, por ejemplo `prompt_exfiltration` o `role_override`.

Este archivo es un conjunto de ejemplos para la prueba del filtro; por sí solo no ejecuta pruebas ni garantiza que el modelo resista ataques.

## 4.13 `evals/adversarial_check.py` — comprobación del filtro de entrada

**Propósito:** ejecuta `inspect_input()` directamente sobre los 10 ejemplos adversariales y reporta cuántos fueron bloqueados.

### Variables

- `ROOT`: raíz del repositorio.
- `cases`: lista de objetos leídos de `adversarial.jsonl`.
- `detected`: contador de entradas bloqueadas.
- `case`: caso adversarial actual.
- `decision`: resultado `GuardrailDecision`.

### Función `main()`

1. Lee y decodifica las líneas de `adversarial.jsonl`.
2. Inicializa el contador en cero.
3. Recorre los casos y llama a `inspect_input(ticket, enabled=True)`.
4. Incrementa el contador si la decisión está bloqueada.
5. Imprime ID, estado y razón.
6. Calcula y muestra la proporción de detección.

**Comando:**

```powershell
python evals/adversarial_check.py
```

La detección inicial documentada en el README original fue 8/10 (80%) para esos ejemplos exactos. Esa cifra no demuestra robustez frente a ataques nuevos o parafraseados.

## 4.14 `.env.example` — plantilla de configuración

**Propósito:** muestra las variables de entorno requeridas sin incluir credenciales reales. Se copia a `.env` y se completan las claves localmente.

| Variable | Descripción | Valor de ejemplo |
|---|---|---|
| `LLM_PROVIDER` | Proveedor predeterminado. | `openai` |
| `OPENAI_API_KEY` | Clave privada de OpenAI. | Vacía en plantilla. |
| `OPENAI_MODEL` | Modelo de OpenAI. | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Clave privada de Anthropic. | Vacía en plantilla. |
| `ANTHROPIC_MODEL` | Modelo de Anthropic. | `claude-3-5-haiku-latest` |
| `PROMPT_VERSION` | Prompt predeterminado. | `v2` |
| `MAX_RETRIES` | Reintentos adicionales ante errores recuperables. | `2` |
| `MAX_OUTPUT_TOKENS` | Límite de salida enviado al SDK. | `500` |
| `TEMPERATURE` | Temperatura enviada por el adaptador OpenAI y, en el ZIP original, también por Anthropic. | `0` |
| `OPENAI_INPUT_USD_PER_1M` | Tarifa de entrada OpenAI por millón de tokens. | `0.15` |
| `OPENAI_OUTPUT_USD_PER_1M` | Tarifa de salida OpenAI por millón de tokens. | `0.60` |
| `ANTHROPIC_INPUT_USD_PER_1M` | Tarifa de entrada Anthropic por millón de tokens. | `0.80` |
| `ANTHROPIC_OUTPUT_USD_PER_1M` | Tarifa de salida Anthropic por millón de tokens. | `4.00` |
| `ENABLE_INJECTION_GUARD` | Activa el filtro heurístico de injection. | `true` |

Los valores de precios son ejemplos de configuración y deben verificarse contra la tarifa vigente del modelo utilizado. Nunca se debe subir `.env` con claves reales.

## 4.15 `requirements.txt` — dependencias Python

**Propósito:** declara las bibliotecas que `pip` instala para ejecutar el proyecto.

| Paquete | Función en el proyecto |
|---|---|
| `openai` | SDK para llamadas a modelos OpenAI. |
| `anthropic` | SDK para llamadas a modelos Anthropic. |
| `pydantic` | Validación del contrato de salida. |
| `PyYAML` | Lectura de prompts YAML. |
| `python-dotenv` | Carga de variables desde `.env`. |

**Instalación:**

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 4.16 `.gitignore` — archivos excluidos de Git

**Propósito:** evita versionar archivos locales, secretos y cachés.

- `.env`: evita publicar claves API y configuración privada.
- `.venv/`: excluye el entorno virtual local.
- `__pycache__/`: excluye bytecode generado por Python.
- `*.py[cod]`: excluye archivos compilados `.pyc`, `.pyo` y `.pyd`.
- `.pytest_cache/`: excluye caché de pytest si se utiliza localmente.
- `.DS_Store`: excluye metadatos del Finder de macOS.

## 4.17 `README.md` — documentación de entrada del repositorio

**Propósito:** es la primera guía para quien clona el proyecto.

Incluye:

1. Resumen del MVP y del contrato JSON.
2. Requisitos de instalación.
3. Creación del entorno virtual e instalación de dependencias.
4. Configuración del archivo `.env`.
5. Ejemplos de uso CLI y entrada por `stdin`.
6. Estructura y responsabilidades de los módulos.
7. Explicación de `v1` y `v2` y de la técnica few-shot.
8. Comandos para ejecutar evaluaciones.
9. Descripción de métricas y costos estimados.
10. Limitaciones de seguridad y próximos pasos.

Este archivo es una guía de inicio rápido; el presente documento amplía la explicación técnica de cada módulo.

## 4.18 `data/.gitkeep` — conservación de carpeta

**Propósito:** archivo vacío que permite que Git incluya el directorio `data/` aunque todavía no existan métricas.

Durante la ejecución se crean archivos como:

- `data/metrics.jsonl`: métricas de ejecuciones normales de la CLI.
- `data/eval_metrics.jsonl`: métricas generadas por el runner de evaluaciones.

Estos archivos se generan dinámicamente; no forman parte del código fuente inicial.

---

# 5. Variables de entorno: resumen centralizado

| Variable | Consumida por | Efecto |
|---|---|---|
| `LLM_PROVIDER` | `service.py` | Proveedor por defecto. |
| `OPENAI_API_KEY` | `providers.py` | Autenticación OpenAI. |
| `OPENAI_MODEL` | `providers.py` | Modelo OpenAI. |
| `ANTHROPIC_API_KEY` | `providers.py` | Autenticación Anthropic. |
| `ANTHROPIC_MODEL` | `providers.py` | Modelo Anthropic. |
| `PROMPT_VERSION` | `service.py` | Prompt predeterminado. |
| `MAX_RETRIES` | `service.py` | Número de reintentos adicionales. |
| `MAX_OUTPUT_TOKENS` | `providers.py` | Límite de salida del modelo. |
| `TEMPERATURE` | `providers.py` | Temperatura configurada en las llamadas que aceptan el parámetro. |
| `ENABLE_INJECTION_GUARD` | `service.py` | Habilita/deshabilita detección heurística de injection. |
| `OPENAI_INPUT_USD_PER_1M` | `metrics.py` | Tarifa de entrada OpenAI. |
| `OPENAI_OUTPUT_USD_PER_1M` | `metrics.py` | Tarifa de salida OpenAI. |
| `ANTHROPIC_INPUT_USD_PER_1M` | `metrics.py` | Tarifa de entrada Anthropic. |
| `ANTHROPIC_OUTPUT_USD_PER_1M` | `metrics.py` | Tarifa de salida Anthropic. |

Los argumentos de CLI `--provider`, `--prompt` y `--metrics` prevalecen sobre los valores predeterminados correspondientes.

# 6. Archivos generados en tiempo de ejecución

| Archivo | Quién lo crea | Contenido |
|---|---|---|
| `data/metrics.jsonl` | `append_metric()` desde `triage()` | Una línea JSON por llamada de triage o entrada bloqueada. |
| `data/eval_metrics.jsonl` | `append_metric()` durante el runner | Métricas de las llamadas ejecutadas en la evaluación. |

JSONL significa que cada línea es un JSON independiente. Es un formato append-only: las nuevas ejecuciones se agregan al final.

# 7. Limitaciones y observaciones técnicas detectadas

1. **Anthropic y `temperature`:** el adaptador del ZIP original pasa `temperature` a `messages.create()`. En SDKs actuales que no aceptan ese argumento, la llamada falla. Eliminar ese parámetro de la llamada Anthropic si aparece el error indicado.
2. **OpenCode/DeepSeek no están en el ZIP original:** `build_provider()`, `main.py`, `evals/runner.py`, `.env.example`, `metrics.py` y `requirements.txt` aún no registran ese proveedor.
3. **Costos multi-proveedor:** `estimate_cost()` solo distingue OpenAI frente a “cualquier otro” como Anthropic. Al agregar un tercer proveedor se debe implementar una tabla de tarifas por proveedor/modelo.
4. **Tokens:** el servicio registra los tokens informados por el SDK. Si el proveedor no entrega usage, se debe representar como desconocido, no como consumo real igual a cero.
5. **Guardrails heurísticos:** los regex no garantizan protección integral. El dataset adversarial mide solo esos diez ejemplos.
6. **Constante sin uso:** `SENSITIVE_REQUEST_PATTERNS` está declarada, pero no participa actualmente en el filtro.
7. **Rutas relativas:** los prompts y rutas de métricas se resuelven respecto al directorio actual desde el que se ejecuta el comando. Ejecutar desde la raíz del proyecto evita errores de ruta.
8. **Evaluación:** el runner mide exactitud de categoría y tasa de éxito de esquema; no evalúa automáticamente calidad lingüística, utilidad de la respuesta ni seguridad semántica completa.
9. **Métricas de evaluación:** las llamadas de evals también escriben métricas, en el archivo indicado por `--metrics`.

# 8. Comandos habituales en Windows PowerShell

Crear entorno virtual con Python 3.13:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Ejecutar CLI:

```powershell
python -m src.main --provider openai --prompt v2 "Me cobraron dos veces la suscripción"
```

Ejecutar evaluaciones:

```powershell
python evals/runner.py --provider openai --prompt v1
python evals/runner.py --provider openai --prompt v2
```

Ejecutar suite adversarial:

```powershell
python evals/adversarial_check.py
```

# 9. Recomendación para mantener la documentación

Cada vez que se agregue un proveedor o se cambie una función pública:

1. Actualizar su docstring y este documento.
2. Actualizar `.env.example` y `requirements.txt` si aparecen nuevas variables o dependencias.
3. Actualizar las opciones de `src/main.py` y `evals/runner.py`.
4. Revisar el cálculo de tokens y costos en `src/metrics.py`.
5. Añadir pruebas de integración y actualizar el README.
6. Ejecutar una prueba CLI y las evaluaciones con el proveedor seleccionado.

