# ADR 0010 · Cierre, escalamiento a N2 y registro ITSM sobre `operacion` (F5 + F6)

- **Estado:** aceptado · 2026-11-19 · P1

## Decisiones
1. **Documentación determinista** (`app/agentes/documentacion.py`): la ficha N2 (§7.2: síntoma, contexto del equipo,
   hipótesis/evidencia, acciones con su autorización y resultado, banderas, siguiente paso, ANS) y el registro de
   cierre se construyen **desde el estado del caso**, nunca desde la memoria ni el texto del LLM (hay una prueba).
2. **Escalar** es un nodo del grafo; el **motivo lo decide el código** (`operacion.escalamientos.motivo`):
   | Disparador | Motivo | ANS |
   |---|---|---|
   | «Hablar con una persona» (botón o texto, detectado por la guardia antes de cualquier LLM) | `pide_humano` | humano |
   | 2.º intento de una acción prohibida (respuesta fija + escalamiento) | `accion_prohibida` | seguridad |
   | N2 rechaza la acción | `n2_rechaza` | escalamiento |
   | La acción falla, o el usuario dice que no funcionó y no hay otra acción | `solucion_fallida` | escalamiento |
   | Hardware (fuera de alcance) | `fuera_alcance` | escalamiento |
   | Límite de turnos | `presupuesto_agotado` | escalamiento |
   Escalado o cerrado, el caso no se reabre por chat (respuesta fija; «Nuevo caso» para otro problema).
3. **Cierre (R5)** solo con verificación técnica (si existe la lectura) **y** confirmación del usuario. La respuesta a
   «¿ya te funciona?» se clasifica con reglas (`respuesta_confirmacion`); los botones envían textos exactos. Ambigua →
   se sigue esperando. «No» → se intenta la siguiente acción (esc. 1) o se escala.
4. **Proyección ITSM** al final de cada turno (`app/integraciones/itsm/`), idempotente y transaccional: `casos`
   (estado completo en `estado_caso`, versionado por trigger de P2), `eventos`, `mensajes`, `acciones` (+ token de
   consentimiento consumido antes de marcar `ejecutada`, como exige el trigger de P2), `banderas_seguridad` y
   `escalamientos`. Un fallo del registro no corta la respuesta al usuario (se registra y se emite `itsm.error`).
5. **Consola N2**: lista de escalamientos desde `operacion` con la ficha, «Tomar el caso» y la evaluación
   «¿Podrías continuar sin repreguntar?» (`completo_sin_repregunta` + *score* humano `escalamiento_completo` en la
   traza del turno que escaló). *Scores* `fcr` (1 cierre / 0 escalamiento).

## Limitaciones / pendientes
- Las acciones `aprobacion_n2` se aprueban en el canal del servidor MCP, que no informa el técnico; como
  `operacion.aprobaciones_n2` exige `tecnico_id`, se registran como `autorizada` con el resultado en `resultado`.
  Propuesta: que el MCP devuelva el aprobador, o que N2 apruebe desde nuestra consola.
- Guía paso a paso desde la KB (esc. 4) y `sin_hipotesis` (esc. 10) dependen de F3 (KB + embeddings vía Ollama).
- Vista de auditoría: muestra estado y línea de tiempo; falta presentarla por secciones (hoy JSON).

## Verificación en vivo (2026-11-19)
CASO-000004 y CASO-000006 en la BD de P2: eventos, mensajes, bandera, escalamiento con ANS y versiones del estado;
tomado por TEC-01 y evaluado «completo» desde la consola; *score* `escalamiento_completo = 1` en Langfuse.
