# ADR 0012 · Hugging Face Inference Providers como proveedor de chat + selector de modelo (pruebas)

- **Estado:** aceptado · 2026-11-19 · P1 · complementa ADR 0004 (capa agnóstica)

## Contexto
OpenRouter `:free` resultó insuficiente para probar: 429 constantes en el pool compartido y cuota de 50 solicitudes al día.
El equipo decide usar el router de Hugging Face (`https://router.huggingface.co/v1`, API compatible con OpenAI,
facturado a la organización con la cabecera `X-HF-Bill-To`).

## Decisión
1. **Nuevo proveedor `huggingface`** en `config/modelos.yaml` (mismo adaptador `openai_compatible`; cero cambios en los
   agentes): token en `HF_TOKEN`, organización en `HF_BILL_TO` (cabecera leída del entorno con `cabeceras_env`; si está
   vacía se omite). Sin token, el proveedor queda «no disponible» y se salta.
2. **Catálogo curado** (licencias permisivas del §6; capacidades y precio de referencia tomados de
   `GET /v1/models`, que es público): gpt-oss 20B y 120B (Apache 2.0), Gemma 4 26B y 31B (Apache 2.0, visión),
   Qwen3 30B Instruct (Apache 2.0), Nemotron 3.5 Lightning y Super VL (OpenMDW). Todos declaran *tools* y salida
   estructurada en el router.
3. **Cadenas por defecto** en HF: conversacional y documentación → gpt-oss 20B; intérprete, diagnosticador y curador
   → gpt-oss 120B; visión → Nemotron Super VL / Gemma 4 31B; juez → otra familia (Nemotron Super VL). OpenRouter queda
   en el catálogo como alternativa, fuera de las cadenas.
4. Los modelos de razonamiento declaran `max_tokens: 2000` y la capa toma **el mayor** entre modelo y agente, para que
   no agoten los tokens pensando sin responder (lo que pasó con Nemotron en OpenRouter).
5. **Embeddings se quedan en Ollama** (`qwen3-embedding:0.6b`): sus vectores coinciden exactamente con los de P2 (ADR 0011),
   corren local (gratis, sin red, ~0,2 s) y no dependen de cuota. Cambiar a HF exigiría verificar que el proveedor sirve
   el mismo modelo con la misma numérica; si no, habría que re-embeber toda la BD. No se justifica hoy.
6. **Selector de modelo en la página (solo modo demo)**: `GET /api/modelos` (catálogo con disponibilidad) y cabecera
   `X-Modelo` en `/api/chat`. El modelo elegido va **primero** en la cadena de cada agente que lo pueda usar; si no cumple
   las capacidades del agente (p. ej., visión), ese agente sigue con su cadena. Se valida contra el catálogo (422 si no
   existe, si no es de chat o si es un doble). Con `LLM_MODO=fake` se ignora. Se etiqueta la traza con `modelo:<alias>`.
   Implementado con una `ContextVar` por petición (no se filtra a otras peticiones).

## Verificación en vivo (2026-11-19, con `HF_TOKEN` y `X-HF-Bill-To: henkia`)
| Prueba | Resultado |
|---|---|
| Los 7 modelos HF: chat, *streaming* y `response_format: json_schema` | 7/7 en las tres; el JSON valida con Pydantic. Latencia 0,4–2 s (gpt-oss 20B con esquema: 48 s en una corrida, a vigilar) |
| Intérprete real (gpt-oss 120B + prompt de Langfuse) con 10 frases del kit | **10/10**, 1–5 s por frase; extrae `que_ve` («Cannot start Microsoft Outlook») y hardware |
| Turno completo por la API (cadena automática) | 8,8 s (≈3 s son Zabbix); generaciones ligadas a los prompts v1; costo de referencia ≈ **0,00015 USD/turno** |
| Selector: `X-Modelo: hf-gemma4-26b` y, desde la UI, Qwen3 30B | Intérprete **y** conversacional usaron el modelo elegido (confirmado en la traza) |

## Pendiente
- `qwen3.5:4b` (respaldo local) aparece en el selector pero no está descargado en Ollama.
- Medir la variación de latencia de gpt-oss 20B con salida estructurada (si persiste, sacarlo de las cadenas que la exigen).
