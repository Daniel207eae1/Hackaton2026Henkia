# Prompt P1 · Frontend (React + shadcn) y Backend (FastAPI) con sus agentes

> **Cómo usarlo:** abre una sesión nueva de Claude Code en `C:\Users\69377\Desktop\Hackaton\Solucion` y pega todo lo que está bajo la línea. Puede correr en paralelo con P2 gracias al contrato compartido.

---

## Rol

Eres el **arquitecto líder y desarrollador full‑stack** del caso 5 de la Prompatón. En esta sesión **no construyes todo el sistema**. Dejas el proyecto listo para construirse por features:

1. Las reglas del proyecto (`CLAUDE.md`).
2. Los subagentes de Claude Code que trabajarán en él.
3. El planteamiento inicial por features con criterios de aceptación.
4. El esqueleto funcional de frontend, backend e infraestructura.
5. La primera feature (F0) funcionando de punta a punta.

## Lee primero (en este orden)

1. `prompts/00_Contrato_Compartido.md`: decisiones vigentes, estructura, servicios, esquemas de BD y reglas comunes. **Prevalece sobre el diseño si hay conflicto.**
2. `Diseno_Arquitectura_Caso5.md`: arquitectura completa. Lee especialmente:
   - §3 (agentes, estado del caso, flujo, catálogo, consentimiento, RAG, módulos A y B, masivos, tablero, extractor)
   - §4 (seguridad)
   - §5 (Langfuse)
   - §6 (modelos)
   - §7 (UX)
   - §8 (escenarios)
3. `front_validacion/` (prototipo HTML con datos quemados) y su `LEEME.md`. Es la referencia funcional de **qué** deben ver y hacer el usuario y N2 en cada escenario. No copies su código: replica su comportamiento con React.

Si encuentras contradicciones entre estas fuentes, anótalas y resuélvelas en un ADR (`docs/adr/`), sin detenerte.

## Entregables de esta sesión

### 1. `CLAUDE.md` raíz + `frontend/CLAUDE.md` + `backend/CLAUDE.md`

Cortos y accionables (menos de 150 líneas cada uno). El raíz incluye:
- **Propósito**
- **Mapa del monorepo**
- **Comandos** (levantar todo, pruebas, *lint*)
- **Invariantes de seguridad** (las del contrato + §4 del diseño)
- **Definición de "terminado"** por feature
- **Cómo se trazan las cosas en Langfuse**
- **Regla de agnosticismo de modelos**
- **"Lo que nunca se hace"**

Deja una sección vacía titulada `## Datos y base de datos (P2)` para que P2 la complete. Si `CLAUDE.md` ya existe porque P2 corrió antes, **intégrate** en él sin borrar su sección.

### 2. Subagentes de Claude Code en `.claude/agents/`

Formato oficial: frontmatter con `name`, `description` (cuándo usarlo), `tools` mínimos y `model` opcional, más un cuerpo con instrucciones. Prefijo `p1-` para no chocar con los de P2. Mínimo:

| Subagente | Responsabilidad |
|---|---|
| `p1-frontend-react` | Componentes React + shadcn/ui + AI Elements, accesibilidad, estado, *streaming* en la UI |
| `p1-backend-fastapi` | API, orquestador, persistencia, contratos, pruebas |
| `p1-agentes-llm` | *Prompts*, salidas estructuradas, capa agnóstica de modelos, Langfuse (prompts, trazas, *scores*) |
| `p1-seguridad` | Revisa cada cambio contra las invariantes: consentimiento, cuarentena, catálogo, inyección, privacidad. Solo lectura; reporta hallazgos |
| `p1-zabbix` | Integración con Zabbix, simulador de equipos, *scripts* del catálogo |
| `p1-qa-escenarios` | Convierte los 12 escenarios del jurado en pruebas automáticas y en un *dataset* de Langfuse; mantiene el usuario simulado |

### 3. Planteamiento inicial: `docs/PLAN_FEATURES.md`

Plan **por features**, priorizado por requisitos y criterios de aceptación del caso. Cada feature incluye:
- Requisitos que cubre
- Historias de usuario
- **Criterios de aceptación verificables** (tomados del caso)
- Escenarios del jurado que la prueban
- Componentes de frontend y backend
- Agentes involucrados
- Trazas y *scores* de Langfuse
- Riesgos
- Estimación en horas

Orden obligatorio (ajústalo solo con una justificación):

| # | Feature | Requisitos | Escenarios |
|---|---|---|---|
| F0 | Fundaciones: monorepo, compose, capa LLM agnóstica, Langfuse, "Ver como", chat con *streaming*, esqueleto del orquestador | Transversal | — |
| F1 | Entender el síntoma y consultar antes de preguntar (*slots* + compuerta de preguntas + telemetría vía Zabbix) | R1 | 4 |
| F2 | Detección de masivos (clúster semántico + tablero + propuesta a N2) | R3 | 3 |
| F3 | Diagnóstico por hipótesis + extractor en cuarentena | R2 | 1, 2, 10 |
| F4 | Consentimiento, motor de políticas, aprobación N2 y ejecución vía Zabbix | R4 | 1, 2, 6, 7, 8 |
| F5 | Verificación, cierre y registro ITSM | R5 | 2, 4, 6, 7 |
| F6 | Escalamiento a N2 con diagnóstico completo + "hablar con una persona" | R6 | 5, 8, 9, 10 |
| F7 | **Módulo B:** capturas (visión en cuarentena) | R8 | 12 |
| F8 | **Módulo A:** curador de KB + vista del revisor | R7 | 11 |
| F9 | Evaluación: usuario simulado, *datasets*, métricas y costo por agente en Langfuse | NFR | Todos |

### 4. Esqueleto + F0 funcionando

Al cerrar la sesión debe ser posible:
1. Levantar con `docker compose up` (más los servicios que ya existen: Langfuse y Ollama).
2. Abrir el frontend y elegir a alguien en "Ver como".
3. Escribir en el chat y recibir una respuesta en *streaming* de un agente real vía la capa LLM agnóstica.
4. Ver la traza en Langfuse (sesión = `case_id`).

**F1 en adelante NO se implementan en esta sesión**, solo se planifican.

## Frontend: especificación

- **Stack:** React + TypeScript + Vite + **shadcn/ui** + **AI Elements**, la librería de componentes de IA construida sobre shadcn. **Consulta su documentación vigente antes de instalarla:** registro, dependencias (usa el AI SDK de Vercel en el cliente) y compatibilidad con Vite. Decide en un ADR una de estas dos opciones:
  - **(a)** Usar `useChat` del AI SDK. El backend FastAPI implementa el protocolo de *streaming* que espera (SSE).
  - **(b)** Usar los componentes solo como presentación, con un cliente SSE propio.

  Elige la opción que mantenga el backend independiente del proveedor de LLM.
- **Componentes de IA a aprovechar** (según su disponibilidad en la versión vigente):
  - Conversación, mensaje y *prompt input* (con adjuntos para el Módulo B)
  - Razonamiento o tarea, para el panel **"Lo que estoy revisando"**
  - *Tool* o paso, para cada consulta a Zabbix o a la KB
  - *Sources*, para citar `KB-SIM-xxx`
  - *Actions*, cargador e imagen
  - Para las tarjetas de consentimiento y aprobación: componentes base de shadcn (card, button, alert, badge, dialog)
- **"Ver como" (sin login):**
  - Selector persistente en la barra superior con personas de `org` (colaboradores simulados, técnicos N2 y revisor de KB).
  - Envía un encabezado `X-Ver-Como` que el backend acepta **solo** si `MODO_DEMO=true`.
  - Muestra siempre la etiqueta visible "Modo demostración".
  - **El rol sale de la base de datos, nunca de lo que diga el chat.**
- **Vistas (paridad funcional con `front_validacion/`):**
  1. **Chat del colaborador:**
     - Conversación en *streaming*.
     - Panel "Lo que estoy revisando".
     - Tarjetas de consentimiento: qué hará, efecto, reversión y riesgo; botones Sí/No que generan un **evento de UI**, nunca texto interpretado por el LLM.
     - Estado de espera de N2.
     - Botón fijo "Hablar con una persona".
     - Adjuntar capturas (Módulo B).
     - Indicador de la etapa del flujo.
  2. **Consola N2:**
     - Aprobaciones (política `aprobacion_n2`).
     - Escalamientos, con la ficha completa (§7.2 del diseño).
     - Posibles masivos, con Confirmar (con el mensaje para los usuarios) / Descartar.
  3. **Revisor de KB (Módulo A):** propuestas de artículo nuevo o de corrección, con los casos que las respaldan y las opciones Publicar / Devolver.
  4. **Auditoría del caso:** estado completo, línea de tiempo, hipótesis y evidencia, acciones y tokens, banderas, enlace a la traza de Langfuse.
  5. **Métricas:** FCR, precisión, tiempo hasta el diagnóstico, preguntas por caso, costo real vs. costo de referencia por agente (leídos del backend, que a su vez consulta Langfuse o la BD).
- **Calidad:** accesible (teclado, contraste, `aria`), responsivo, en español, sin `dangerouslySetInnerHTML` para texto que venga del backend. El texto de errores y capturas se muestra **escapado** como cita.

## Backend: especificación

### Estructura sugerida (hexagonal, por módulos)

`backend/app/` con:
- `api/` (rutas FastAPI y esquemas Pydantic)
- `orquestador/` (grafo de estados)
- `agentes/` (uno por agente)
- `politicas/` (catálogo + motor de políticas + tokens)
- `llm/` (capa agnóstica)
- `rag/` (repositorios sobre las funciones SQL de P2)
- `integraciones/zabbix/`
- `integraciones/itsm/` (ITSM simulada sobre el esquema `operacion`)
- `seguridad/` (guardias de entrada y salida, extractor en cuarentena)
- `observabilidad/` (Langfuse)
- `config/`

### Orquestador
Implementa el grafo de §3.5 del diseño, con persistencia del estado del caso en PostgreSQL y esperas (consentimiento, aprobación N2). **LangGraph** es la opción recomendada (tiene *interrupts*, *checkpointer* en Postgres e integración con Langfuse); si eliges otra, regístralo en un ADR. **El flujo lo decide el código, no el LLM.**

### Agentes del sistema
Uno por módulo, cada uno con su lista mínima de herramientas permitidas (tabla §3.3 del diseño):

| Agente | Notas |
|---|---|
| Conversacional | Adapta el nivel técnico; explica los errores en inglés en español |
| Contexto y Masivos | Directorio, telemetría vía Zabbix, tablero, búsqueda de reportes similares |
| Diagnosticador | Recetas de hipótesis desde la KB, priors del historial; nunca ve texto no confiable |
| Extractor en cuarentena | Texto + visión. **Sin herramientas**, con esquema forzado, anclaje de códigos y doble bandera (heurística + modelo) |
| Ejecutor | **Sin LLM.** Solo ejecuta con un token válido |
| Escalamiento y Documentación | Ficha N2 y registro ITSM, construidos desde el estado del caso |
| Curador de KB (Módulo A) | Proceso por lotes con salida a propuestas; nada se publica sin revisor |

Los *prompts* de cada agente se versionan en Langfuse (etiquetas `production` y `staging`), con *fallback* embebido.

### Capa LLM agnóstica (obligatoria)
- Una interfaz propia (puerto) con capacidades declaradas: `chat`, `streaming`, `tools`, `salida_estructurada`, `vision` y `embeddings`.
- **Adaptadores:** primero uno **compatible con OpenAI** (cubre OpenRouter, Ollama y cualquier proveedor compatible). La arquitectura debe admitir más adaptadores sin tocar los agentes. Evalúa en un ADR si conviene LiteLLM como implementación del puerto.
- **Configuración por agente** en un archivo versionado (p. ej., `config/modelos.yaml`): proveedor, modelo, parámetros, cadena de *fallback* y capacidad requerida. Al arrancar se valida que cada modelo declarado cumple las capacidades que necesita el agente. **Ningún nombre de modelo ni de proveedor aparece en el código de los agentes.**
- **Salida estructurada portable:** usa `response_format` si el modelo lo soporta. Si no, *tool calling* forzado. Como último recurso, JSON con validación Pydantic y un reintento.
- **Resiliencia:** manejo del error 429 y de los límites del tier gratuito de OpenRouter (20 RPM; 50 o 1.000 al día), con *backoff* y *fallback* al siguiente modelo de la cadena.
- Los *embeddings* pasan por la misma capa, con `EMBEDDING_MODEL` y `EMBEDDING_DIM` desde la configuración.

### Políticas y consentimiento
- Catálogo de acciones del caso (§3.6 del diseño + tabla del documento del caso) en un archivo de configuración. **Las acciones prohibidas no se registran como herramientas.**
- Tokens de un solo uso, firmados (HMAC), ligados a `case_id`, acción, parámetros y *hash* del texto mostrado, con vencimiento.
- Endpoints de consentimiento y aprobación separados del chat.

### Zabbix
Aplica a la telemetría **y** a las acciones (`infra/zabbix/`):
- **Despliegue:** Zabbix en Docker (versión LTS vigente) con **su propia base de datos**, separada de la de la app.
- **Equipos simulados:**
  - Cada equipo del directorio es un *host* de Zabbix en el grupo `Equipos-Simulados`.
  - Ítems *trapper* para la telemetría (SO, versión de Office, disco, licencia, OneDrive, cola de impresión, dispositivos de audio) y para los logs técnicos.
  - Un **cargador** toma la semilla del esquema `telemetria` (P2) y la envía con `zabbix_sender`.
- **Acciones:** cada acción permitida del catálogo se mapea a **un *script* global de Zabbix de tipo *webhook***, restringido al grupo de *hosts* simulados, que llama al **simulador de equipos** (`equipos-sim`). El simulador:
  - Aplica el efecto sobre el equipo ficticio (p. ej., libera la cola o limpia la caché).
  - Reenvía la telemetría resultante a Zabbix, para que la verificación lea el nuevo estado.
  - **No se ejecutan comandos reales en ninguna máquina.**
- **Mínimo privilegio:**
  - Un token de API **solo de lectura** para la telemetría.
  - Otro token cuyo usuario **solo** puede ejecutar los *scripts* de la lista blanca sobre ese grupo.
  - El backend nunca envía comandos libres: solo `scriptid` de la lista blanca, y solo después de validar el token de consentimiento o aprobación.
  - Desactiva los comandos personalizados globales.
- **Leer logs** también es una acción con consentimiento (según el catálogo). Lo que devuelve Zabbix va **directo al extractor en cuarentena**.
- **Observabilidad:** cada llamada a Zabbix es un *span* en Langfuse.

### Langfuse
- Una sesión por caso, *spans* con nombres estables por agente, eventos de política y de tokens.
- *Scores* deterministas (§5.3 del diseño), enmascaramiento de datos personales y precios de referencia para los modelos `:free`.

### Pruebas
- `pytest` para el motor de políticas (todas las combinaciones de acción × política × estado del token), el extractor (incluidas las inyecciones del kit), la compuerta de preguntas y la capa LLM con dobles de prueba.
- Pruebas de contrato contra `db/CONTRATO_SQL.md`.
- En el frontend, pruebas de componentes de las tarjetas de consentimiento.

## Reglas de trabajo para esta sesión

- **Antes de instalar o fijar versiones,** consulta la documentación vigente (shadcn/ui, AI Elements, AI SDK, FastAPI, LangGraph, SDK de Langfuse v3, API de Zabbix LTS). Fija las versiones exactas.
- **No toques** `db/` ni `data/` (son de P2), salvo para leer `db/CONTRATO_SQL.md`.
- **Un ADR por decisión relevante:** protocolo de *streaming*, orquestador, LiteLLM o adaptador propio, mapeo de Zabbix, "Ver como".
- Si un paso requiere credenciales que no tienes, deja la variable en `.env.example` y documenta cómo obtenerla. **No inventes claves.**
- Cierra verificando F0 de punta a punta.

## Respuesta final

1. Archivos y carpetas creados.
2. Subagentes creados y cuándo usar cada uno.
3. Resumen del plan por features (tabla) y el siguiente paso recomendado.
4. Evidencia de que F0 funciona: qué levantaste, qué probaste y el enlace a la traza.
5. ADRs creados.
6. Dudas abiertas y cambios propuestos al contrato compartido, si los hay.
