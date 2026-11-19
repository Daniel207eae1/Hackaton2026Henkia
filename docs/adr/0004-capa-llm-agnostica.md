# ADR 0004 · Capa LLM agnóstica: puerto propio + adaptador OpenAI‑compatible (sin LiteLLM)

- **Estado:** aceptado · 2026-11-19 · P1
- **Versiones:** `httpx==0.28.1` (cliente HTTP del adaptador; no se usa el SDK `openai` para no depender de su API ni de un vendor), `langfuse==5.2.0`.

## Contexto
El contrato exige agnosticismo: hoy OpenRouter (`:free`) y Ollama; mañana otro proveedor sin tocar
los agentes. Se evaluó **LiteLLM** (`litellm==1.110.1`) como implementación del puerto.

## Decisión
1. **Puerto propio** `backend/app/llm/puerto.py`: `ProveedorLLM` con `chat()`, `chat_stream()`,
   `estructurado()` y `embeddings()`, y un conjunto declarado de `Capacidad`
   (`chat`, `streaming`, `tools`, `salida_estructurada`, `vision`, `embeddings`).
2. **Adaptador `openai_compatible`** (cubre OpenRouter, Ollama `/v1` y cualquier API compatible) y
   **`fake`** (doble determinista para pruebas y para correr sin claves).
3. **Registro** `RegistroLLM.para("<agente>")` que lee `backend/config/modelos.yaml`: proveedor,
   modelo, parámetros, cadena de *fallback*, capacidades requeridas y precio de referencia. Al
   arrancar valida que **cada opción de la cadena** tenga las capacidades requeridas por el agente;
   si no, la API no arranca y dice qué falta.
4. **Salida estructurada portable:** `response_format: json_schema` si el modelo declara
   `salida_estructurada`; si no, *tool calling* forzado si declara `tools`; si no, JSON + Pydantic
   con un reintento.
5. **Resiliencia:** 429/5xx/timeout → reintento con *backoff* exponencial con *jitter* (respeta
   `Retry-After`), luego la siguiente opción de la cadena. Último eslabón recomendado: Ollama local.
6. **Langfuse** se instrumenta en la capa (una *generation* por llamada, con el nombre lógico del
   agente, modelo real, uso y costo de referencia), no en los agentes.

> **Actualización (ADR 0012):** el proveedor por defecto pasó de OpenRouter a Hugging Face Inference Providers sin
> tocar ningún agente (solo `modelos.yaml`), lo que valida el diseño de esta capa.

## Por qué no LiteLLM (por ahora)
- Todos los proveedores actuales hablan la API de OpenAI: el adaptador propio es ~200 líneas.
- LiteLLM agrega una dependencia grande (y transitivas) a un sistema cuyo argumento central es la
  seguridad; menos superficie = menos riesgo de cadena de suministro.
- Necesitamos controlar con precisión la cadena de *fallback*, la validación de capacidades al
  arrancar y la *generation* de Langfuse por intento.
- **Puerta abierta:** si se suma un proveedor no compatible (p. ej., API nativa de otro vendor), se
  puede escribir un adaptador `litellm` que implemente el mismo puerto sin tocar los agentes.

## Consecuencias
- (+) Agentes libres de nombres de modelo/proveedor; probar con `fake` sin red.
- (−) Mantenemos nosotros el manejo de errores por proveedor.
