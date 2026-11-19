# ADR 0008 · Intérprete único por turno, compuerta por frase y guardia heurística (F1)

- **Estado:** aceptado · 2026-11-19 · P1

## Contexto
R1 pide entender lenguaje vago y no preguntar lo consultable. El tier gratuito de OpenRouter limita a
20 solicitudes por minuto y **50 al día** (cuentas con < 10 créditos), y los modelos `:free` de Gemma dan
429 frecuentes en el pool compartido.

## Decisiones
1. **Intérprete único** (`app/agentes/interprete.py`): una sola salida estructurada por turno con los *slots*
   del usuario (aplicación, tipo de síntoma, qué ve, desde cuándo, hardware) **y** la acción candidata (enum).
   Reemplaza al selector de F4: 2 llamadas LLM por turno en vez de 3. `Decision` pasa a ser 100 % código.
2. **Compuerta de preguntas por frase** (`app/seguridad/compuerta_preguntas.py`): el texto del Conversacional
   se filtra frase a frase sobre el *stream*; una pregunta por un *slot* con origen `telemetria` nunca llega a
   la pantalla. Si la consulta de ese dato falló, sí se permite. *Score* `pregunto_consultable` = 0 por
   construcción; los intentos quedan en `metricas.bloqueos` y en el evento `compuerta.bloqueo`.
3. **Guardia de entrada heurística** (`app/seguridad/guardia_entrada.py`) antes de cualquier LLM: inyección,
   autoridad, prohibidas (solo **peticiones** al asistente, no descripciones del síntoma) e identidad. Prohibida o
   identidad → respuesta **fija** (plantilla del catálogo), idéntica en cada intento, sin LLM; bandera de
   insistencia desde el 2.º intento (esc. 8). El clasificador LLM local se suma cuando haya Ollama.
4. **Lecturas según el síntoma** antes de preguntar: OneDrive, cola de impresión, Teams y perfil de Outlook,
   guardando solo campos no personales (nunca rutas, usuario ni nombres de cuentas).
5. **Masivo con el tablero oficial** (`estado_servicio`, §3.12): servicio degradado + relacionado con la app ⇒
   `masivo_confirmado`; el mensaje oficial se cita **por código** (tras pasar la guardia), nunca por el LLM. Se
   vuelve a revisar cuando la app se conoce en un turno posterior. Respaldo: `problemas_activos` (retirada del
   servidor el 2026-11-19).
6. **Modelos de razonamiento con `reasoning: {enabled: false}`** (Nemotron Lightning y Super VL): si no, agotan
   `max_tokens` pensando y no responden. Una respuesta vacía se trata como fallo y pasa al siguiente modelo.
7. **Cuota diaria agotada** (`429 free-models-per-day`): no se reintenta; el proveedor se omite el resto del día
   (UTC) para no gastar segundos por turno.

## Consecuencias
- (+) Intérprete real: 10/10 en frases del kit (coloquial, sin tildes, inglés, ambiguo, hardware) a ~1 s.
- (−) La compuerta es por patrones: una pregunta muy indirecta podría pasar. Se mide con el dataset en F9.
- (−) Sin Ollama ni créditos, 50 solicitudes al día alcanzan para ~20 turnos: **comprar 10 créditos** (1.000/día)
  o configurar Ollama antes de la demo.
