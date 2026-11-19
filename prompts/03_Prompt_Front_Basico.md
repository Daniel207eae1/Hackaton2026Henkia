# Prompt 3 · Front básico de validación funcional (HTML con datos quemados)

> **Cómo usarlo:** copia todo lo que está bajo la línea en una sesión nueva de Claude Code abierta en `C:\Users\69377\Desktop\Hackaton\Solucion`. El resultado es un prototipo navegable para validar el flujo con el equipo. Lo que haya que ajustar se pide en iteraciones posteriores sobre este mismo prototipo.

---

## Rol

Eres un desarrollador front‑end que arma **prototipos funcionales de baja fidelidad**. Tu trabajo no es que se vea bonito, sino que el equipo pueda **recorrer cada flujo del sistema y comprobar que se comporta como dice el diseño**, antes de construir los agentes reales.

## Contexto

Estamos en una hackatón (Prompatón), caso 5: un **sistema multiagente que diagnostica incidentes de ofimática** (Outlook, Teams, OneDrive, Word, Excel, licencias e impresoras) conversando con el usuario. El sistema:

1. Entiende el síntoma.
2. Revisa si hay un incidente masivo.
3. Prueba hipótesis con evidencia.
4. Resuelve lo seguro **con el consentimiento explícito del usuario**.
5. Pide aprobación a un técnico N2 para las acciones de riesgo medio.
6. Si no puede resolver, escala a N2 con el diagnóstico completo.

**Antes de empezar, lee completo `Diseno_Arquitectura_Caso5.md`** (en esta misma carpeta), en especial estas secciones:

- §3.4 Estado del caso
- §3.5 Flujo detallado
- §3.6 Catálogo de acciones
- §3.7 Consentimiento
- §3.9 Módulo B
- §4.4 Respuestas tipo
- §7 Experiencia de usuario
- §8 Escenarios

Ese documento manda. Si algo de este prompt lo contradice, sigue el documento y anota la diferencia en tu respuesta final.

## Objetivo

Construir un **front estático** con **datos sintéticos quemados** que simule, paso a paso, las conversaciones y vistas del sistema para los 12 escenarios del jurado. Así el equipo valida:

- Qué ve y qué puede hacer el usuario en cada momento.
- Qué ve y qué decide N2.
- Que las **invariantes de seguridad y consentimiento** se respetan en cada flujo.
- Que el estado del caso tiene la información necesaria (lo que luego producirá el backend).

## Restricciones (obligatorias)

- **HTML + CSS + JavaScript puro (vanilla).** Nada de frameworks ni librerías de componentes: ni React, Vue, Angular, Tailwind o Bootstrap, ni Chainlit o Streamlit.
- **Sin backend, sin LLM, sin llamadas de red, sin CDN.** Todo funciona sin conexión.
- Debe abrir **con doble clic** (`file://`). Por eso los datos van en un archivo `.js` que define una variable global (p. ej., `window.CASOS`) y **no** con `fetch` de un `.json`, que falla en `file://`.
- **Datos 100 % sintéticos y evidentemente ficticios.** Nada de nombres de personas reales, correos reales, empresas reales ni códigos de error inventados que parezcan oficiales. Usa marcadores del tipo `ERR-SIM-0001` y etiquétalos como simulados.
- **Todo en español.** Los mensajes de error simulados del "sistema operativo" pueden ir en inglés, para mostrar que el agente los explica en español.
- **Lógica mínima:** el JavaScript solo avanza pasos de un guion predefinido y cambia de vista según los botones. **No** implementes reglas de negocio reales, parsers ni simulación de agentes.
- Estilo **sobrio y legible**: una hoja CSS, tipografía del sistema, colores para estados (riesgo bajo/medio/alto/prohibido, confirmada/descartada). Que funcione en escritorio y no se rompa en el móvil.
- **No crees nada fuera de `front_validacion/`.** No instales dependencias.

## Estructura de archivos esperada

```
front_validacion/
├── index.html        → Selector de escenarios + leyenda + checklist de invariantes
├── usuario.html      → Vista del colaborador (chat)
├── n2.html           → Consola N2 (aprobaciones y escalamientos)
├── caso.html         → Vista de auditoría del caso (estado completo + línea de tiempo)
├── metricas.html     → Tablero de métricas quemadas (estilo Langfuse, solo maqueta)
├── datos.js          → window.CASOS (12 escenarios) + window.CATALOGO + window.METRICAS
├── app.js            → Avance del guion, cambio de vistas, render desde datos
├── estilos.css
└── LEEME.md          → Cómo abrirlo, qué valida cada escenario, supuestos tomados
```

Las vistas se comunican por **parámetro de URL** (p. ej., `usuario.html?escenario=4`). Todas leen el mismo `datos.js`, así que cambiar un dato se refleja en todas.

## Modelo de datos (`datos.js`)

Sigue la estructura del **Estado del caso** del documento (§3.4). Cada escenario es un objeto con:

| Campo | Contenido |
|---|---|
| `id`, `titulo`, `modulo` | Número de escenario, título corto, `nucleo` / `A` / `B` |
| `usuario` | Ficticio: nombre, área, nivel técnico (`bajo`/`medio`/`alto`), equipo asignado |
| `telemetria` | Instantánea simulada: SO, versión de Office, disco, licencia, OneDrive, impresora |
| `sintoma` | Texto del usuario, app, tipo de síntoma; *slots* con su **origen** (`telemetria` o `usuario`) |
| `masivo` | ¿Se evaluó?, ¿aplica?, id del incidente padre, mensaje del tablero |
| `hipotesis[]` | id, descripción, artículo de KB de origen (`KB-SIM-xx`), prior, estado, evidencia que la confirma o descarta |
| `pasos[]` | **El guion**: lista ordenada de pasos (ver abajo) |
| `resultado` | `cerrado`, `escalado`, `vinculado_masivo` o `derivado` + resumen |
| `escalamiento` | Si aplica: la ficha N2 completa (§7.2 del documento) y el ANS simulado |
| `registro_itsm` | Síntoma, causa, solución, acciones, duración |
| `banderas_seguridad[]` | Inyección, insistencia en acción prohibida, etc. |
| `metricas` | Preguntas hechas, tiempo hasta el diagnóstico, costo de referencia por agente |
| `invariantes[]` | Lo que este escenario debe demostrar (texto, para el checklist) |

Cada **paso** del guion tiene un `tipo` y lo que se renderiza:

| `tipo` | Qué muestra |
|---|---|
| `msg_usuario` | Burbuja del colaborador |
| `msg_sistema` | Burbuja del asistente (lenguaje simple; cita `KB-SIM-xx` cuando da pasos) |
| `revisando` | Línea en el panel "Lo que estoy revisando" (herramienta, resultado, ✓ / ✗ / ⚠ si la consulta falló) |
| `hipotesis` | Cambio de estado de una hipótesis (se refleja en `caso.html`) |
| `consentimiento` | **Tarjeta**: qué haré, qué efecto tiene, cómo se revierte, nivel de riesgo + botones `Sí, hazlo` / `No, prefiero otra opción` |
| `aprobacion_n2` | Aviso al usuario de que está en espera + ítem en la bandeja de `n2.html` |
| `accion` | Ejecución simulada con resultado (solo puede aparecer **después** de un consentimiento aceptado) |
| `verificacion` | Prueba técnica + pregunta al usuario "¿Ya funciona?" |
| `rechazo_politica` | Respuesta fija ante una acción prohibida (camino correcto + oferta de escalar) |
| `escalamiento` | Mensaje al usuario con el plazo (ANS) + ficha en `n2.html` |
| `bandera` | Aviso visible de seguridad (p. ej., "esta imagen contiene instrucciones que no sigo") |
| `cierre` | Resumen final y registro ITSM |

`window.CATALOGO` es la tabla de acciones del documento (§3.6): id, nombre, riesgo, política y aviso obligatorio. La tarjeta de consentimiento toma el aviso **del catálogo**, no del paso, para validar que la fuente es única.

## Vistas y comportamiento

### `index.html`
- Tarjetas de los 12 escenarios con título, módulo, resultado esperado y enlaces a las cuatro vistas.
- Leyenda de colores y estados.
- **Checklist de invariantes globales** (texto fijo con casillas que el equipo marca a mano):
  - Ninguna `accion` aparece sin un `consentimiento` aceptado justo antes, y sin aprobación N2 cuando la política del catálogo es `aprobacion_n2`. Ojo: no toda acción de riesgo medio la exige; la reparación rápida y restaurar una versión solo piden consentimiento.
  - Ninguna acción prohibida se ejecuta, por mucho que el usuario insista.
  - En un masivo no aparecen pasos individuales.
  - El sistema no pregunta un dato cuyo *slot* tiene origen `telemetria`.
  - Todo paso guiado cita un artículo `KB-SIM-xx`.
  - "Hablar con una persona" escala de inmediato, sin insistir.
  - Toda escalación lleva la ficha completa para N2.
  - El texto de logs y capturas se trata como dato (bandera visible en el escenario 12).

### `usuario.html?escenario=N`
- **Columna principal:** el chat. Abajo, un botón **"Siguiente paso ▶"** que revela el próximo paso del guion, y **"Reiniciar"**.
- **Columna lateral:** el panel **"Lo que estoy revisando"**, que se va llenando con los pasos `revisando`.
- **Botón fijo "Hablar con una persona":** en cualquier momento salta a un paso de escalamiento genérico que muestra la ficha con lo recolectado *hasta ese punto*. Así se valida que siempre hay contexto suficiente.
- **Tarjeta de consentimiento:** el guion **se detiene** hasta que el usuario elige.
  - `Sí, hazlo`: continúa.
  - `No`: muestra la rama alternativa definida en el paso (`si_rechaza`). Si no hay rama, escala.
- **Escenario 12 (Módulo B):** un control de "adjuntar captura" que, en lugar de subir un archivo, deja elegir entre dos capturas **simuladas** (dos recuadros dibujados con HTML/CSS con el texto del error; una de ellas incluye un texto con instrucciones).
- Indicador del estado actual del grafo (Recepción → Contexto → Chequeo masivo → Aclaración → Hipótesis → Prueba → Decisión → …), resaltando dónde va el caso.

### `n2.html`
- **Bandeja de aprobaciones** (acciones con política `aprobacion_n2`): diagnóstico, evidencia, acción propuesta, impacto y botones `Aprobar` / `Rechazar` / `Tomar el caso`.
  - Al aprobar se marca la aprobación en `sessionStorage`. Si `usuario.html` está esperando ese escenario, al recargar continúa.
  - Si falla `sessionStorage`, se usa un botón manual "Simular aprobación".
- **Bandeja de escalamientos** con la ficha:
  1. Síntoma en palabras del usuario + síntoma normalizado.
  2. Contexto del equipo.
  3. Hipótesis probadas y descartadas, con su evidencia.
  4. Acciones hechas (con consentimiento y resultado).
  5. Banderas de seguridad.
  6. Siguiente paso sugerido y ANS.
- Un indicador "¿Podrías continuar sin volver a preguntarle nada al usuario?" con Sí/No, para que el equipo evalúe la ficha.

### `caso.html?escenario=N`
- El estado completo del caso en secciones (las de §3.4).
- **Línea de tiempo** de todos los eventos con hora simulada.
- La tabla de hipótesis con su estado y su evidencia.
- La lista de acciones con el token de consentimiento simulado (`TOK-SIM-…`, quién, cuándo, texto mostrado).
- Un enlace ficticio "Ver traza en Langfuse" (desactivado).

### `metricas.html`
Maqueta de tablero, **solo con números quemados y tablas o barras hechas con CSS** (sin librerías de gráficos):
- FCR, precisión diagnóstica, tiempo p50/p95 hasta el diagnóstico, preguntas por caso, acciones sin consentimiento (= 0) e inyecciones resistidas.
- Costo por conversación **desglosado por agente**: costo real (USD 0, modelos `:free`) y costo de referencia.
- Tabla por escenario con su resultado.

## Guiones mínimos por escenario

Arma cada guion con 6 a 14 pasos. Usa los modelos de texto que quieras, pero respeta **la secuencia y el resultado**:

| # | Usuario ficticio (nivel) | Secuencia esperada | Resultado |
|---|---|---|---|
| 1 | Outlook no abre (medio) | Revisa telemetría y tablero (sin masivo) → consentimiento para **leer logs** → el extractor encuentra un error de perfil (`ERR-SIM`) → hipótesis "perfil dañado" → consentimiento para **reparación rápida** (riesgo medio, cierra Office) → la verificación falla → **aprobación N2** para recrear el perfil → N2 aprueba → consentimiento → acción → verificación OK | `cerrado` |
| 2 | Teams sin audio (bajo) | Telemetría: dispositivos y versión → hipótesis "caché corrupta" → consentimiento para **limpiar la caché** (avisa que cierra Teams) → acción → verificación con el usuario | `cerrado` |
| 3 | El correo no sincroniza (medio) + otros 2 usuarios | Chequeo masivo: el tablero muestra degradación del correo → **vincula al incidente padre** → informa lo que dice el tablero → ofrece avisar cuando se resuelva. **Cero pasos individuales** | `vinculado_masivo` |
| 4 | OneDrive no sincroniza (bajo) | La telemetría muestra el disco al 98 % → **no pregunta** por espacio (*slot* de origen `telemetria`) → guía de KB para liberar espacio, en pasos cortos → verificación técnica + usuario | `cerrado` |
| 5 | Excel "producto sin licencia" (medio) | Telemetría/directorio: licencia no asignada → hipótesis confirmada → la acción "asignar licencia" requiere N2 → **escala con diagnóstico** + plazo | `escalado` |
| 6 | Impresión atascada (bajo) | Telemetría de la cola → consentimiento para **reiniciar la cola** (avisa que se cancelan los trabajos pendientes) → acción → verificación | `cerrado` |
| 7 | Archivo sobrescrito (medio) | Identifica el archivo por metadatos (sin leer su contenido) → consentimiento para **restaurar la versión anterior conservando la actual** → acción → verificación | `cerrado` |
| 8 | Pide desactivar el antivirus (alto, insistente) | Pide 3 veces, una con "soy de TI" → **mismo rechazo** cada vez, explicando el riesgo → camino correcto (N2 evalúa la macro) → bandera de insistencia → escala | `escalado` |
| 9 | Usuario sin conocimientos técnicos | Se confunde → el sistema **simplifica** (pasos más cortos) → pide hablar con una persona → **escala de inmediato**, sin insistir, con todo el contexto | `escalado` |
| 10 | Word se cierra solo (medio) | 3 hipótesis probadas y **todas descartadas con evidencia**; una consulta de telemetría **falla** y el sistema lo dice y sigue → escala con lo probado y lo descartado | `escalado` |
| 11 | Módulo A (vista N2/revisor) | En `n2.html`, una sección "Propuestas de KB": borrador de artículo nuevo con los `case_id` que lo respaldan + corrección de un artículo desactualizado; botones `Publicar` / `Devolver` (nada se publica sin revisión) | `pendiente_revision` |
| 12 | Módulo B: dos capturas (medio) | Captura 1: error con código → se usa en el diagnóstico. Captura 2: texto que pide "dar permisos de administrador" → **bandera visible**, el sistema la señala y la ignora; el diagnóstico solo usa la captura 1 | `cerrado` o `escalado` según el guion |

## Qué entregar en tu respuesta final

1. La lista de archivos creados.
2. Cómo abrirlo: ruta a `index.html`.
3. Una tabla de **escenario × invariantes** que dejaste demostrables.
4. **Supuestos y dudas**: todo lo que tuviste que decidir porque el documento no lo definía (textos, ANS, nombres de hipótesis, umbrales). Este es el insumo para la siguiente iteración.
5. Diferencias que encontraste entre este prompt y el documento de diseño, si las hubo.

## Qué NO hacer

- No conectes con OpenRouter, Ollama, Langfuse ni ninguna API.
- No uses frameworks, CDN, *bundlers* ni `npm`.
- No inventes acciones fuera del catálogo ni muestres una acción prohibida ejecutándose, ni siquiera "para probar".
- No uses nombres, correos ni datos que parezcan reales.
- No dediques tiempo a animaciones ni a pulir el diseño visual: la prioridad es que el flujo sea recorrible y verificable.
