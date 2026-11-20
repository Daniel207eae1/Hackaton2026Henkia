# ADR 0016 · Módulo A: curador de KB por lotes + revisor humano (F8)

- **Estado:** aceptado · 2026-11-19 · P1

## Decisiones
1. **Detección en código** (`agentes/curador_kb.detectar`) sobre `conocimiento.historial_casos` (solo el conjunto de
   entrenamiento; el de prueba queda para F9) y `conocimiento.articulos`:
   - **Faltante:** casos `resuelto` **sin** `articulo_id`, agrupados por (categoría, causa, `solucion_normalizada`),
     con ≥ 3 casos. Quedan fuera las soluciones que no son un procedimiento documentable (`vinculado_masivo`,
     `escalar*`, `derivar*`).
   - **Desactualizado:** un artículo publicado usado por ≥ 3 casos de los últimos 180 días cuya `version_app` no
     cubre ninguna de sus `versiones_aplicables`. «Teams 24xxx» cubre «Teams 24257»; la `x` es comodín. También
     cuenta un artículo con más de 3 años sin actualizar que siga en uso.
2. **Cuarentena de los tickets**:
   - Los campos `sintoma_texto`, `causa` y `solucion` se enmascaran y se recortan a 400 caracteres.
   - Un ticket con forma de instrucción se **descarta** y se cuenta en `tickets_descartados`.
   - Al redactor (agente `curador_kb`, LLM sin herramientas) solo llegan datos del grupo y tickets limpios, entre
     marcadores aleatorios.
3. **Redacción:**
   - Salida con esquema cerrado (`BorradorKB`: título, síntoma, causa, pasos ≤ 8, verificación, cambios propuestos).
   - La salida se re-escanea. Si está contaminada o no hay modelo, se usa una **plantilla sin pasos inventados**
     («Por redactar con N2»).
   - El markdown lo arma el código y siempre lleva el pie «Casos que lo respaldan: HC-…» y «requiere revisión
     humana».
4. **Escritura mínima:** solo en `conocimiento.propuestas_kb` (estado `pendiente`), la única tabla de conocimiento
   donde `app_rw` puede escribir.
   - **Idempotencia:** la clave del grupo va en la justificación (`[clave=…]`), así que un segundo lote no duplica.
   - **Publicar** = `estado=publicada` con revisor y fecha.
   - **Devolver** = `rechazada` con comentario obligatorio (≥ 10 caracteres).
   - Llevar el texto aprobado a `conocimiento.articulos` le toca al dueño de la KB (P2), porque el backend no tiene
     privilegio de escritura ahí.
5. **Ejecución:**
   - CLI `python -m app.agentes.curador_kb`, pensado para correr programado.
   - Botón «Ejecutar lote ahora» en la vista del revisor (`POST /api/kb/lote`).
   - Solo el rol `revisor_kb` (N2 tampoco) lista, ejecuta, publica y devuelve.
   - Langfuse: traza `lote_curador_kb` con el span `curador_kb` y los eventos `kb.propuesta.creada`, `.publicada`
     y `.devuelta`.

## Verificación en vivo (2026-11-19, historial de P2 + gpt-oss-120b en Hugging Face)
El lote tardó 30 s y produjo 3 propuestas, justo lo que siembra el kit para el escenario 11:
- **Faltante «borrar credenciales de Teams»:** 5 casos de entrenamiento (HC-0025, 0039, 0042, 0073, 0134).
- **KB-SIM-003:** el artículo cubre Office 2016 y es de 2019; los casos usan Microsoft 365 2408.
- **KB-SIM-016:** el artículo cubre OneDrive 19.x y es de 2020; los casos usan OneDrive 24.x.

Las propuestas quedaron `pendiente` en la BD compartida para la demo. Se revisaron en la vista del revisor del
navegador.

## Pendientes
- El redactor a veces agrega detalles de menú que no están en los tickets: el prompt lo prohíbe y el revisor es el
  control final. Una opción es medir la fidelidad en F9 (juez LLM contra los tickets).
- No hay cola de anotación de Langfuse: se usa la vista propia del revisor.
