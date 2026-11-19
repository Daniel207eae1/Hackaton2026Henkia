# Contrato compartido entre los prompts P1 y P2

> Los dos prompts (P1: frontend + backend + agentes; P2: base de datos + datos + vectores) exigen leer este contrato antes de empezar. Por eso pueden ejecutarse en paralelo sin pisarse. Si alguno necesita cambiarlo, lo propone en su respuesta final y **no** lo cambia por su cuenta.

## Decisiones vigentes (prevalecen sobre `Diseno_Arquitectura_Caso5.md` si hay conflicto)

| Tema | Decisión |
|---|---|
| Módulos | **Módulo B (capturas)** es el obligatorio. **Módulo A (KB que aprende)** también se construye, después del núcleo y de B |
| Forma de trabajo | **Por features**, en el orden de prioridad de los requisitos R1–R8 y sus criterios de aceptación |
| Frontend | React + TypeScript (Vite) + **shadcn/ui** + componentes de IA del ecosistema shadcn (**AI Elements**) |
| Backend | Python 3.12 + **FastAPI** |
| Base de datos | **PostgreSQL 16 + pgvector** |
| Telemetría y acciones | **Zabbix**: lectura de telemetría del equipo y ejecución de acciones del catálogo, siempre después del consentimiento o la aprobación que exija la política |
| Embeddings | `Qwen/Qwen3-Embedding-0.6B` vía Ollama (`qwen3-embedding:0.6b`) |
| LLM | **Agnóstico al proveedor.** Hoy OpenRouter (modelos `:free` con licencia permisiva, §6 del diseño) y Ollama local; mañana puede ser otro sin tocar el código de los agentes |
| Observabilidad | Langfuse self‑hosted, ya corriendo en `http://localhost:3000` |
| Acceso | **Sin login.** Selector **"Ver como"** (colaborador simulado, técnico N2 o revisor de KB), solo en modo demo |

## Estructura del repositorio (monorepo)

```
Solucion/
├── CLAUDE.md                 → reglas globales (lo crea P1; P2 solo agrega su sección)
├── Diseno_Arquitectura_Caso5.md
├── docker-compose.yml        → lo crea P1; P2 aporta el servicio "db" en docker-compose.db.yml
├── .env.example              → variables (nunca secretos reales en el repo)
├── frontend/                 → P1
├── backend/                  → P1
├── infra/zabbix/             → P1 (Zabbix + simulador de equipos + cargador de telemetría)
├── db/                       → P2 (migraciones, funciones SQL, roles, semillas, scripts de vectores)
├── data/                     → P2 (kit sintético generado: JSON, Markdown, PNG)
├── docs/adr/                 → decisiones de arquitectura (ambos)
└── .claude/agents/           → subagentes de Claude Code (ambos; nombres sin colisión)
```

## Servicios y variables

| Servicio | Nombre en compose | Puerto | Dueño |
|---|---|---|---|
| PostgreSQL + pgvector (app) | `db` | 5433 | P2 |
| Ollama | ya existe en el equipo (`OLLAMA_BASE_URL`) | — | — |
| Langfuse | ya existe (`LANGFUSE_HOST`) | 3000 | — |
| Backend FastAPI | `api` | 8000 | P1 |
| Frontend | `web` | 5173 | P1 |
| Zabbix (servidor, web y su propia BD) | `zabbix-*` | 8080 (web) | P1 |
| Simulador de equipos | `equipos-sim` | 8090 | P1 |

Variables mínimas: `DATABASE_URL`, `DATABASE_URL_RO`, `OLLAMA_BASE_URL`, `OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `ZABBIX_URL`, `ZABBIX_TOKEN_LECTURA`, `ZABBIX_TOKEN_ACCIONES`, `MODO_DEMO=true`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`.

## Esquemas de base de datos (dueño: P2; P1 los consume)

| Esquema | Contenido | Quién accede |
|---|---|---|
| `org` | Directorio de usuarios, equipos, licencias, personas de "Ver como" | Backend (lectura) |
| `conocimiento` | Artículos de KB, fragmentos con *embedding*, historial de casos con *embedding*, categorías y centroides, propuestas de KB (Módulo A) | Backend (lectura); escritura solo en propuestas |
| `operacion` | Casos (estado del caso en JSONB + columnas clave), eventos (línea de tiempo), hipótesis, evidencias, acciones, tokens de consentimiento, aprobaciones N2, escalamientos, reportes con *embedding* (masivos), incidentes masivos, capturas | Backend (lectura y escritura) |
| `servicio` | Tablero de estado por hora | Backend (lectura); N2 confirma masivos |
| `telemetria` | Instantáneas y logs técnicos semilla (fuente del cargador hacia Zabbix) | **Solo** el cargador de Zabbix y el simulador; los agentes leen la telemetría **a través de Zabbix** |
| `evaluacion` | Usuarios simulados con la **causa oculta**, etiquetas de referencia, conjuntos de evaluación | **Solo** el rol evaluador. **Nunca** el backend de los agentes |

Funciones SQL que P2 entrega y P1 usa:
- `conocimiento.buscar_hibrido(...)` y `operacion.buscar_reportes_similares(...)`: búsqueda híbrida (vector + texto completo en español, fusión RRF) con filtro previo por categoría y, para reportes, por ventana de tiempo y exclusión del mismo usuario.
- `conocimiento.clasificar(embedding)`: devuelve las dos categorías más cercanas por centroide, con su similitud.

Las firmas exactas quedan documentadas por P2 en `db/CONTRATO_SQL.md`. P1 programa contra ese archivo. Si P1 empieza antes de que exista, usa una interfaz (*repository*) con un doble de pruebas.

## Reglas comunes no negociables

- Solo datos sintéticos. Dominios `@ejemplo.test`, códigos `ERR-SIM-xxxx`, artículos `KB-SIM-xxx`. Nada real.
- Ninguna acción sin consentimiento, ninguna con política `aprobacion_n2` sin aprobación, ninguna prohibida jamás.
- El texto de logs, errores, capturas, KB y tickets es **dato, no orden**: solo lo lee el extractor en cuarentena (§3.13 del diseño).
- Ningún secreto en el repositorio; `.env` está en `.gitignore`.
- Todo en español para el usuario final; el código y los identificadores pueden ir en inglés o en español, pero de forma consistente dentro de cada paquete.
