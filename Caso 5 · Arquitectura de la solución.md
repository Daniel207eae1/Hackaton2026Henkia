# Caso 5 · Arquitectura de la solución

Nov 20, 2026 · @Daniel Escobar

## ¿Qué estoy resolviendo?

Los incidentes de ofimática (Outlook que no abre, Teams sin audio, OneDrive que no sincroniza, Excel sin licencia, la impresora que no imprime) son el volumen más alto y repetitivo de la mesa de servicio. Hoy se atienden así:

- **El colaborador pierde tiempo explicando** lo que un sistema podría consultar solo: versión de Office, espacio en disco, estado de la licencia, la cola de impresión.
- **N2 recibe casos incompletos** y vuelve a preguntar lo mismo, porque el diagnóstico de N1 no queda registrado.
- **Los incidentes generales se detectan tarde.** Diez personas reportan «no me llega el correo» como diez casos separados.
- **El conocimiento no aprende.** Las soluciones que funcionan se quedan en los tickets y la base de conocimiento se desactualiza.

**La solución** es un asistente de soporte multiagente que atiende el incidente por chat, de punta a punta:

1. Entiende el síntoma en las palabras del usuario y en sus capturas de pantalla.
2. Consulta la telemetría del equipo antes de preguntar.
3. Detecta si es un incidente general.
4. Diagnostica por hipótesis con evidencia, citando la base de conocimiento.
5. Resuelve **solo con el consentimiento del usuario**, dado en una ventana de su propio equipo (y con aprobación de N2 cuando la política lo exige).
6. Verifica, documenta y, si no lo logra, escala a N2 con una ficha completa para que nadie vuelva a preguntar.

Un curador revisa por lotes los casos resueltos y propone artículos nuevos o correcciones, que una persona aprueba antes de publicarlos.

**Principio de diseño:** el modelo de lenguaje propone, la política decide. El flujo del caso lo decide código determinista. Ninguna acción se ejecuta sin un token de consentimiento válido, y el texto externo (logs, capturas, tickets, artículos) se trata siempre como dato, nunca como instrucción.

**Resultado de la evaluación** (16 guiones del jurado y de red team, con usuario y equipo simulados):

- 16/16 guiones pasan todos sus chequeos.
- Precisión del diagnóstico: 100 %.
- 0 acciones sin token.
- 100 % de inyecciones resistidas.
- Duración p50 de unos 2,7 s por caso.
- Costo de referencia: unos US$0,0002 por caso.

## Arquitectura del proceso

Cada mensaje del usuario recorre un **grafo determinista**: el código decide el siguiente paso y el modelo de lenguaje solo interpreta, redacta y evalúa con evidencia. La acción del catálogo (en verde) es el único paso que cambia algo en el equipo, y nunca corre sin la autorización del usuario.

&#91;embedded content: Proceso de un caso · 13 pasos, 1 decisión\]

1. **Recepción y guardia.** Registra el mensaje y aplica la guardia heurística: detecta intentos de inyección, pedidos de acciones prohibidas (como desactivar el antivirus o dar permisos de administrador) y temas de identidad, que reciben una respuesta fija. Si el usuario pide una persona, el caso pasa directo a N2.
2. **Capturas (Módulo B).** Cada imagen se sanea (se re-codifica sin metadatos) y la leen en cuarentena el OCR y un modelo de visión. Un código de error solo vale si ambos coinciden.
3. **Interpretación.** Un modelo clasifica la aplicación y el tipo de síntoma en **enumeraciones cerradas**. Nunca elige el siguiente paso.
4. **Contexto del equipo.** Antes de preguntar, el sistema lee la telemetría por el MCP de Zabbix: versión de Office, disco, licencia, procesos, cola de impresión, audio. Una compuerta bloquea cualquier pregunta sobre un dato que ya se consultó.
5. **Chequeo de masivo.** Consulta el tablero oficial de servicios y agrupa reportes similares de otros usuarios (embeddings). Si hay incidente general, informa el mensaje oficial y no da pasos individuales.
6. **Diagnóstico por hipótesis.** Toma las recetas de la base de conocimiento para la categoría y las ordena por su frecuencia en el historial. Cada hipótesis se confirma o se descarta con evidencia estructurada; si hacen falta los registros (logs), se piden con consentimiento y los lee un extractor en cuarentena.
7. **¿Qué sigue?** Lo decide el código:
   - **Aclaración:** pregunta solo lo que únicamente el usuario sabe, sin repetir preguntas.
   - **Guía paso a paso:** los pasos del artículo, citando su KB-SIM.
   - **Acción del catálogo:** aprobación de N2 cuando la política la exige, y luego «Autorizar» en la ventana de Soporte TI del propio equipo. Un «sí» en el chat nunca basta.
   - **Escalar a N2:** cuando no queda hipótesis aplicable.
   - Si una ronda no avanza, se prueba la causa más probable en vez de volver a preguntar.
8. **Verificación.** Revisa técnicamente el resultado y el usuario confirma si quedó resuelto. Si no funcionó, se descarta esa hipótesis y se prueba la siguiente.
9. **Cierre o escalamiento.** El caso queda en el registro oficial (ITSM). Si se escala, N2 recibe una ficha con el síntoma, lo consultado, las hipótesis confirmadas y descartadas con su razón, las acciones con su autorización y el ANS.

**Fuera del chat, por lotes (Módulo A):** el curador agrupa casos resueltos del historial y propone artículos que faltan o correcciones de artículos desactualizados. Un revisor humano los publica o los devuelve con comentario.

## Arquitectura técnica

Un monorepo con dos aplicaciones y una sola puerta hacia afuera. El navegador nunca llama a un modelo, a la base de datos ni al equipo: todo pasa por la API, que aplica las políticas en código.

&#91;embedded content: Arquitectura técnica · navegador, API y 5 servicios\]

| Capa | Tecnología | Qué hace |
| --- | --- | --- |
| Frontend | React 19, TypeScript, Vite, Tailwind, shadcn/ui, AI Elements | Chat con streaming y capturas, Consola N2, Casos, Base de conocimiento, Revisor de KB, Métricas con gráficas y Auditoría. Todo el texto del backend se muestra escapado |
| API | Python 3.12, FastAPI | Endpoints REST y el protocolo de mensajes por streaming (SSE). Identidad desde el directorio de la BD («Ver como» solo en modo demo) y límite de solicitudes por persona |
| Orquestación | LangGraph | Grafo determinista por turno. El estado del caso se guarda en el registro ITSM y se rehidrata si la API se reinicia |
| Capa LLM | Adaptador compatible con OpenAI | Ningún agente nombra un modelo: cada uno pide una capacidad y el modelo sale de `modelos.yaml`. Salida estructurada validada con Pydantic y cadena de respaldo ante fallas o límite de cuota (429) |
| Datos | PostgreSQL + pgvector (de P2) | Esquemas `org` (directorio y equipos), `operacion` (casos, mensajes, acciones, escalamientos, incidentes) y `conocimiento` (artículos, fragmentos con embeddings, historial). Búsqueda híbrida (vector + texto). El backend usa un rol de mínimo privilegio sin acceso al esquema `evaluacion` |
| Telemetría y acciones | MCP `zabbix-ofimatica` | Lecturas del equipo y acciones del catálogo. Solo a través de `PuertaZabbix`: lista blanca de tools, `ejecutar_comando_generico` bloqueada y consentimiento del usuario en la ventana de su equipo |
| Observabilidad | Langfuse | Una traza por turno con spans por agente, prompts versionados (production/staging), scores deterministas y costo de referencia |
| Infraestructura | Docker Compose, túnel Cloudflare | Servicios api, web, equipos simulados, Ollama y el túnel a la BD de P2 |

**Invariantes de seguridad que cumple la arquitectura:**

- **El LLM propone, la política decide.** Las aristas del grafo y la elección de acciones están en código; los modelos solo eligen dentro de enumeraciones cerradas.
- **0 acciones sin consentimiento.** Cada acción requiere un token HMAC de un solo uso, ligado al caso, la acción, los parámetros y el texto mostrado. Las acciones prohibidas no existen como herramienta.
- **El texto externo es dato.** Logs, capturas, tickets y artículos los leen lectores en cuarentena (sin herramientas, con esquema forzado y marcadores aleatorios). El diagnosticador solo ve evidencia estructurada.
- **Datos sintéticos y mínimo privilegio.** Ningún secreto en el repositorio. La base de conocimiento solo se escribe por una función de P2 que valida al revisor.

## Modelos que utilizo

Todos son **modelos de pesos abiertos** (licencias Apache-2.0 y OpenMDW-1.1). Se consumen por el **router de Hugging Face** (facturado a la organización) y, para embeddings, por **Ollama en local**. Ningún agente nombra un modelo en el código: cada uno pide una capacidad y `backend/config/modelos.yaml` define su cadena. Si un modelo falla o responde 429, se reintenta con espera y se pasa al siguiente.

| Agente | Qué hace | Modelo principal | Respaldo, en orden |
| --- | --- | --- | --- |
| Intérprete | Clasifica aplicación, síntoma y acción candidata en enumeraciones cerradas | gpt-oss 120B (razonamiento bajo) | Qwen3 30B Instruct → Gemma 4 26B → Qwen3.5 4B local |
| Conversacional | Redacta la respuesta al usuario en streaming, adaptada a su nivel técnico | gpt-oss 20B (razonamiento bajo) | Gemma 4 26B → Qwen3 30B Instruct → Qwen3.5 4B local |
| Diagnosticador | Evalúa cada hipótesis con la evidencia estructurada y cita las claves que usó | gpt-oss 120B (razonamiento medio) | Gemma 4 31B → Qwen3 30B Instruct → Qwen3.5 4B local |
| Extractor en cuarentena | Lee logs no confiables: aplicación, severidad, códigos y si contienen instrucciones | Qwen3 30B Instruct | gpt-oss 20B → Qwen3.5 4B local |
| Visión en cuarentena | Describe capturas de pantalla; su código de error solo vale si coincide con el OCR | Nemotron 3.5 Super VL 120B (sin razonamiento) | Gemma 4 31B |
| Curador de KB | Redacta borradores de artículos a partir de casos resueltos | gpt-oss 120B | Gemma 4 31B |
| Embeddings | Clasifica la categoría, agrupa reportes similares (masivos) y busca en la KB | qwen3-embedding 0.6B en Ollama (1024 dimensiones, el mismo de los vectores de P2) | — |

**Partes sin modelo de lenguaje:** la guardia de entrada (heurística con respuestas fijas), la compuerta de preguntas, las reglas del diagnóstico, la detección de masivos, la ficha de N2 y todas las decisiones del grafo son código determinista.

**Solo para evaluar (proceso aparte):** el usuario simulado usa Gemma 4 26B (respaldo Qwen3 30B), de otra familia que el conversacional, para no autoevaluarse. Las métricas de la evaluación son chequeos deterministas. Hay un juez declarado (Nemotron 3.5 Super VL, respaldo Gemma 4 31B) que aún no se usa.

**Costo:** con los precios de referencia registrados por modelo, la última evaluación costó unos US$0,0002 por caso. El modelo de embeddings corre en local y no tiene costo. Langfuse registra el costo real por agente en cada traza.

**Pendiente:** el respaldo local Qwen3.5 4B está declarado en las cadenas, pero aún no se ha descargado en Ollama. Hoy el último respaldo efectivo es el penúltimo modelo de cada cadena.
