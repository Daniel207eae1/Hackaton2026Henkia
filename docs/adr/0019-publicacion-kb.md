# ADR 0019 · Publicación de propuestas en la KB por una función de P2

- **Estado:** aceptado · función aplicada por P2 y verificada en vivo el 2026-11-20 · P1

## Contexto
El revisor de KB (F8, ADR 0016) aprobaba propuestas, pero el artículo nunca llegaba a `conocimiento.articulos`.
`app_rw` solo lee la KB, y darle escritura directa abriría la puerta a que cualquier fallo del backend la ensucie.

## Decisión
- **Escritura solo por función.** El backend llama a `conocimiento.publicar_propuesta(propuesta, revisor, fragmentos,
  modelo)`, una función `SECURITY DEFINER` de P2. La función valida el rol `revisor_kb`, el estado de la propuesta y
  nunca toca la receta de diagnóstico. El SQL está en `docs/propuestas/P2-cambios-contrato.md`.
- **El backend valida antes de publicar** (`app/rag/publicacion_kb.py`):
  - no publica si el borrador tiene «por redactar» o «por confirmar» (plantilla sin LLM o pasos dudosos);
  - exige las secciones síntoma, causa y pasos;
  - pasa cada sección por la guardia de inyección;
  - quita el pie con los casos de soporte.
- **Embeddings:** cada sección se embebe con el agente `embeddings` (mismo modelo que la KB de P2), así el artículo
  es encontrable al instante. Si el servicio falla, se publica sin vector y P2 re-embebe.
- **Degradación:** si la función aún no existe (`UndefinedFunction`), la propuesta queda `aprobada`. El lote no la
  repite y la UI ofrece «Reintentar publicación».

## Revisión de seguridad (2026-11-19)
- La función **no confía en el llamador**: cada fragmento debe ser texto literal del `borrador_md` revisado, el
  `contenido_md` se reconstruye solo con las secciones validadas (sin pie ni «Cambios propuestos») y una corrección
  exige un artículo existente y no retirado. `app_rw` queda con UPDATE solo en las columnas de revisión de
  `propuestas_kb`.
- Validación del backend igual de estricta que la Guía: `heuristica_instrucciones` o cualquier bandera de la guardia
  (inyección, acción prohibida, identidad) sobre el título y cada sección.
- El curador ya no recibe el `contenido_md` de un artículo si tiene forma de instrucción. Así se corta el ciclo
  LLM → KB → LLM.
- Los prompts de cuarentena (extractor, visión, curador) se usan **siempre desde el repo**. Langfuse solo enlaza la
  versión si es idéntica; una versión distinta emite `seguridad.bandera` (`prompt_cuarentena_distinto`).
- `UndefinedFunction` solo se interpreta como «falta la función» si el mensaje la nombra. Un error dentro de la
  función no se oculta.

## Verificación en vivo (2026-11-20, transacción revertida)
- La función rechaza fragmentos que no son texto del borrador, la sección `receta` y un revisor sin rol `revisor_kb`.
- Propuesta 4 → `KB-SIM-031` publicado, receta vacía, 5 fragmentos con vector de 1024 y la propuesta en `publicada`.
  `buscar_hibrido` lo devuelve primero (similitud 0,83) para «Los chats y el calendario de Teams no se actualizan».

## Consecuencias
- El Módulo A cierra el ciclo (lote → revisión humana → KB) en cuanto P2 aplica la función.
- La corrección de un artículo desactualizado no cambia `versiones_aplicables` ni la receta. Eso lo sigue
  decidiendo P2/N2.
- Pruebas: `tests/test_f8.py` (fragmentos sin pie, cuatro borradores rechazados, 422 que deja la propuesta
  pendiente, artículo nuevo y corrección).
