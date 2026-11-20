# ADR 0021 · Archivo sobrescrito: historial de versiones y restauración con parámetros ligados

- **Estado:** aceptado · 2026-11-20 · P1
- **Reemplaza:** la nota de ADR 0007 «restaurar una versión anterior (esc. 7) no tiene tool en el MCP: hoy se escala».

## Contexto
El MCP `zabbix-ofimatica` agregó dos tools:
- `versiones_archivo` (automática): historial de versiones de un archivo de OneDrive, solo metadatos.
- `restaurar_version_archivo` (consentimiento): restaura una versión y conserva la actual como copia. El servidor liga
  su consentimiento a `archivo` + `version_id`.

El escenario 7 del jurado espera `cerrado`. Hasta ahora no había tool, así que se escalaba.

## Decisión
- **Parámetros ligados al consentimiento.** `PARAMETROS_ACCION` declara qué parámetros exige cada acción.
  `PuertaZabbix` valida que vengan exactamente esos, con su formato:
  - `archivo`: nombre acotado, sin rutas ni `..`;
  - `version_id`: alfanumérico corto.

  Los guarda en la autorización y, al ejecutar, exige que sean idénticos. Un consentimiento para la versión v2 no
  sirve para la v1 ni para otro archivo. Las demás acciones no aceptan parámetros.
- **Quién elige qué.**
  - El **archivo** lo nombra el usuario. Primero se toma la palabra con extensión del mensaje (regex) y luego el
    nombre del intérprete, solo si termina en esa misma palabra. Siempre pasa por `nombre_archivo_seguro`: formato
    acotado y guardia de inyección.
  - La **versión** la elige el código: la anterior más reciente a la actual.
  - El LLM no elige ni la versión ni el nombre exacto, que es el que devuelve el historial.
- **Solo metadatos.** De `versiones_archivo` se guardan nombre, id, fecha y tamaño. Nunca la ruta (lleva el usuario
  de Windows) ni `modificadoPor`. El contenido del archivo no se lee nunca, y el diagnóstico solo usa conteos.
- **Diagnóstico.** La receta KB-SIM-017 (`telemetria.onedrive.versiones`) se confirma si hay versiones anteriores y
  se descarta si el archivo no está en OneDrive o no tiene versiones.
  - Sin nombre de archivo, el código le pide al conversacional que lo solicite.
  - Con varias coincidencias, que pregunte cuál.
- **Verificación.** Tras restaurar se vuelve a leer el historial, y la versión vigente debe tener el tamaño de la
  restaurada.

## Revisión de seguridad (2026-11-20)
Sin hallazgos críticos. Se corrigieron:
- **Alta · falso «ok» en la verificación.** La versión vigente después de restaurar debe tener otro id que la de
  antes, una fecha posterior y el tamaño de la elegida (comparado con el mismo redondeo). Además, si el historial no
  marca cuál es la vigente, no se propone nada.
- **Registro oficial.** `operacion.acciones.parametros`, el hash y el texto mostrado del token incluyen ahora el
  archivo y la versión autorizados.
- **Langfuse.** De `versiones_archivo` solo se registra un resumen (número de coincidencias y de versiones): nada de
  nombres, rutas ni autores.
- **Nombres de archivo y el LLM.** Si coinciden varios archivos, los nombres se muestran al usuario en el panel; al
  modelo solo le llega cuántos son.
- **Equipo de laboratorio.** Se asigna solo con `MODO_DEMO=true`.
- **Validación y mensajes.**
  - La puerta usa `fullmatch` en todos sus validadores (un salto de línea final ya no pasa).
  - El nombre del intérprete sin extensión debe aparecer tal cual en el mensaje del usuario.
  - El motivo técnico de un fallo ya no va al chat (va enmascarado al registro).
  - La fecha y el tamaño que se muestran quedan congelados en la acción.

## Consecuencias
- El esc. 7 pasa a `cerrado` (KB-SIM-017). En vivo con los modelos reales: 3 turnos, sin acciones sin token.
- `test_esc07_archivo.py` cubre:
  - parámetros obligatorios y ligados;
  - consentimiento de un solo uso;
  - rechazo de rutas;
  - metadatos sin ruta ni autor;
  - extracción del nombre;
  - el flujo completo por la API.
