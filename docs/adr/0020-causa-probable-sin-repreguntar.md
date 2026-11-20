# ADR 0020 · Probar la causa más probable en vez de volver a preguntar

- **Estado:** aceptado · 2026-11-20 · P1

## Contexto
En las pruebas, tras 2 o 3 mensajes el chat «parecía olvidar»: volvía a preguntar lo mismo con otras palabras y
terminaba escalando sin haber probado nada. Caso real: `8fd74ac4` (Outlook: «no carga» → «se queda en blanco» → la
misma pregunta tres veces).

No era la ventana de contexto: el conversacional recibe hasta 80 mensajes y el síntoma entendido nunca se pierde.
Era la lógica del ciclo de hipótesis:
- Las hipótesis solo se confirman o descartan con evidencia estructurada (telemetría y logs). Lo que responde el
  usuario no la cambia, así que quedaban «no concluyentes» ronda tras ronda.
- En `aclarar`, el conversacional no sabía qué preguntar para avanzar y repetía la pregunta (a veces inventaba
  consejos fuera de la KB).
- Un artículo sin receta (p. ej., `KB-SIM-031`, publicado por el curador) quedaba `pendiente` para siempre y
  mantenía abierto el ciclo.

## Decisión
1. **Causa más probable** (`FlujoDiagnostico._probable`). En vez de preguntar otra vez, se prueba la hipótesis no
   descartada de mayor *prior* (KB + historial) cuya solución se puede aplicar por chat:
   - una guía se presenta como «la causa más frecuente…», no como «encontré la causa»;
   - una acción pasa por el flujo de siempre (consentimiento y, si aplica, aprobación de N2).

   Se dispara en tres casos:
   - **sin avance:** la ronda anterior fue `aclarar`, el usuario respondió y los estados no cambiaron;
   - **solución fallida:** el usuario dijo que no funcionó (se pasa directo a la siguiente);
   - **antes de escalar** por `sin_hipotesis`.

   Cada hipótesis se prueba una sola vez: si falla, se descarta. Cuando no queda ninguna aplicable, se escala.
2. **Sin pruebas no bloquea.** Una hipótesis con receta vacía no cuenta como «pendiente» para seguir preguntando. Si
   es la más probable, se ofrece como guía (sus pasos son la única solución que tiene).
3. **Compuerta de preguntas repetidas** (`compuerta_preguntas.es_repetida`). Una pregunta que comparte la mayoría de
   sus palabras clave (≥ 3 y ≥ 60 % de la más corta) con una ya hecha en el caso no llega al usuario. Emite el
   evento `compuerta.repetida`.
4. Ajustes menores:
   - el parser de confirmación reconoce «ya lo intenté y nada», «no me funcionó» y «no sirvió»;
   - los pasos de la KB se muestran sin doble numeración, viñetas ni Markdown.

## Consecuencias
- Se mantienen las invariantes: el LLM no elige la arista, ninguna acción corre sin consentimiento y los pasos
  salen de la KB.
- La métrica `diagnostico_correcto` sigue basada en hipótesis **confirmadas**. `diagnostico.probable` se registra
  como evento aparte para distinguirlas en Langfuse.
- Pruebas: `test_f3.py` (sin avance → prueba la más probable; compuerta con las frases del caso real),
  `test_f5_f6.py` (falló → siguiente guía sin volver a preguntar), `test_historial.py` (frases y pasos).
