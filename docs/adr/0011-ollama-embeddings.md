# ADR 0011 · Ollama local para embeddings compatibles con los vectores de P2

- **Estado:** aceptado · 2026-11-19 · P1

## Decisión
- Servicio `ollama` en el compose (`ollama/ollama:0.40.16`, CPU, solo red de Docker, modelos en el volumen
  `ollama-modelos`). La API lo usa en `http://ollama:11434` (sobrescribible con `OLLAMA_BASE_URL_CONTENEDOR`).
- Modelo: `qwen3-embedding:0.6b` (639 MB), el mismo de P2 (`schema_migrations`: 1.024 dimensiones). Primera vez:
  `docker compose exec ollama ollama pull qwen3-embedding:0.6b`.
- Los embeddings pasan por la capa LLM agnóstica (`registro.para("embeddings")`, `modelos.yaml`).

## Verificación (2026-11-19)
| Prueba | Resultado |
|---|---|
| Re-embeber `historial_casos.sintoma_texto` y comparar con el vector guardado por P2 | **coseno 1,0000** (3/3): mismo modelo y misma numérica |
| `kb_fragmentos`: P2 embebió con el título antepuesto (≈ `"{titulo}: {texto}"`, coseno 0,997) | Solo afecta a re-indexar; las consultas se embeben desde el texto del usuario |
| `conocimiento.clasificar` con 6 frases coloquiales (sin tildes, "parce", "flechitas azules") | 6/6 en la categoría correcta |
| `conocimiento.buscar_hibrido` ("outlook se queda cargando el perfil…", categoría `outlook.no_abre`) | 0,34 s → `KB-SIM-001` (síntoma, receta, pasos, causa, resumen) |
| Latencia de un embedding en CPU | 0,2 s en caliente (≈3 s la primera vez) |

## Hallazgos para F2/F3
- Las categorías de P2 (`conocimiento.categorias`) **no son** el *enum* del intérprete: p. ej. `teams.audio_video`
  (no `sin_audio`), `outlook.lenta`, `windows.lenta`, `onedrive.recuperar_archivo`, `hardware.dano_fisico`,
  `identidad.acceso`, `antivirus.seguridad`. F3 debe mapear (o el intérprete adoptar estas 16 categorías).
- Sin instrucción de consulta la similitud con los centroides es algo mayor (P2 calculó centroides sin instrucción).
  Para la búsqueda en la KB conviene medir con y sin instrucción en el *dataset* de evaluación (F9).
- El modelo local `qwen3.5:4b` (respaldo de los agentes de chat) **no** se descargó (~3 GB); se puede agregar con
  `ollama pull qwen3.5:4b` si se quiere un respaldo sin OpenRouter.
