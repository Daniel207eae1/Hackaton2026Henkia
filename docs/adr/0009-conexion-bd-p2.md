# ADR 0009 · Conexión a la BD de P2 (remota, por túnel) con rol de mínimo privilegio

- **Estado:** aceptado · 2026-11-19 · P1
- **Insumo:** scripts del anfitrión `conectar_bd_hackathon.bat` y `test_conexion_pg.py` (túnel TCP de Cloudflare
  → `127.0.0.1:15432`, BD `hackathon`).

## Contexto
P2 corrió en otra máquina. Su PostgreSQL se expone con `cloudflared access tcp`. Hallazgos al conectar
(2026-11-19):
- PostgreSQL **17.12** (el contrato decía 16), extensiones `vector 0.8.7`, `pg_trgm`, `unaccent`.
- Esquemas del contrato completos (`org`, `conocimiento`, `operacion`, `servicio`, `telemetria`, `evaluacion`),
  migraciones 001–009 y las tres funciones del contrato.
- Roles `app_rw`, `agentes_ro`, `zabbix_loader`, `evaluador` **existen pero sin login**. El único usuario con
  login es `hackathon`, **superusuario**, que **sí puede leer `evaluacion`** (viola la invariante 6 si el backend
  lo usara tal cual).
- Ids del directorio: `USR-001`, `TEC-01`, `REV-01` (no `USR-SIM-…`); rol N2 = `tecnico_n2`.
- `db/CONTRATO_SQL.md` no está en este equipo: las firmas se tomaron de `pg_get_function_arguments`.

## Decisión
1. **Túnel como servicio del compose** (`db-tunel`, imagen `cloudflare/cloudflared:2026.11.1`), accesible solo en
   la red de Docker. El hostname temporal va en `DB_TUNEL_HOST` (`.env`). Para DBeaver se usa el script del
   anfitrión (`127.0.0.1:15432`).
2. **Usuario propio `app_backend`** (solo miembro de `app_rw`, ver Consecuencias) y **cada sesión fija `app_rw`**
   (`options=-c role=app_rw`, `DB_ROL_APP`). Al arrancar, la API verifica que
   `current_user = app_rw` y que **no** tiene `USAGE` sobre `evaluacion`; si no, no arranca.
   Verificado: `app_rw` no ve `evaluacion` ni `telemetria` y solo escribe en `operacion` y `conocimiento.propuestas_kb`.
3. **Directorio real** (`app/directorio/postgres.py`): el rol sale de `org.usuarios.rol`; `org.personas_demo`
   solo define el selector «Ver como» y su etiqueta. Sin `DATABASE_URL`, sigue el doble en memoria.

## Consecuencias
- (+) «Ver como» con las 22 personas del kit (escenarios 1–12, extras, 3 N2 y el revisor).
- **Resuelto el 2026-11-19 (con autorización del equipo):** se creó el usuario **`app_backend`** (`LOGIN`,
  `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION`, `NOBYPASSRLS`, `CONNECTION LIMIT 10`), **solo miembro de
  `app_rw`**, con clave aleatoria guardada únicamente en `.env`. La API se conecta con él (`DATABASE_URL`).
  Verificado en vivo: sesión `app_backend`/`app_rw`; tras `RESET ROLE` sigue en `app_rw`; denegados leer `evaluacion` y
  `telemetria`, `SET ROLE hackathon`, crear esquemas y modificar `org`. `hackathon` queda solo para administración.
  Pendiente opcional: un usuario equivalente miembro de `agentes_ro` para las herramientas de solo lectura.
- (−) Latencia del túnel ~1–2 s por conexión: pool con `min_size=1` reutiliza conexiones.
- Pendiente: esquema `orquestador` para el *checkpointer* (ADR 0003) — `app_rw` no puede crearlo; mientras
  tanto `MemorySaver` (un reinicio pierde los casos en curso). Proyección a `operacion.casos` en F5.
- Para F2/F3 hace falta generar el *embedding* de la consulta con el **mismo modelo** que P2
  (`qwen3-embedding:0.6b`, 1.024 dimensiones, según `schema_migrations`): requiere Ollama alcanzable.
