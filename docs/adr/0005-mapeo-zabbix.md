# ADR 0005 · Telemetría y acciones vía Zabbix

- **Estado:** reemplazado parcialmente por **ADR 0007** (Zabbix vía MCP `zabbix-ofimatica`). Lo de aquí
  queda como diseño del **Zabbix local de respaldo** (`infra/zabbix/`, perfil `zabbix`) · 2026-11-19 · P1
- **Versiones:** Zabbix **7.0 LTS** (`zabbix/zabbix-server-pgsql:ubuntu-7.0.32`,
  `zabbix/zabbix-web-nginx-pgsql:ubuntu-7.0.32`), `zabbix-utils==2.0.5`.

## Contexto
El contrato fija Zabbix para leer la telemetría y ejecutar acciones del catálogo. 8.0 LTS salió el
2026-11-05 (dos semanas); 7.0 LTS tiene soporte completo hasta 2027-06-30.

## Decisión
- **7.0 LTS** por estabilidad para la Prompatón (8.0 es muy reciente y cambia `history.get`).
  Migrar a 8.0 solo cambia la etiqueta de imagen; queda anotado.
- Zabbix con **su propia BD** PostgreSQL (`zabbix-db`), separada de la app. Perfil `zabbix` en el compose.
- **Equipos:** cada `EQ-SIM-xxx` del directorio = *host* del grupo `Equipos-Simulados`.
- **Ítems *trapper*** (`type: 2`): `sim.so`, `sim.office.version`, `sim.disco.libre_gb`,
  `sim.disco.uso_pct`, `sim.licencia.estado`, `sim.onedrive.estado`, `sim.impresion.cola`,
  `sim.audio.dispositivos`, `sim.red.estado`, `sim.log.<app>` (texto).
- **Cargador** (`infra/zabbix/cargador/`): lee `telemetria` (rol `zabbix_loader` de P2) y envía con
  `zabbix_utils.Sender` (protocolo de `zabbix_sender`).
- **Acciones:** cada acción **permitida** del catálogo con efecto en el equipo = un *script* global
  `type: 5` (webhook), `scope: 2` (acción manual de host), `groupid` = `Equipos-Simulados`, que hace
  `POST http://equipos-sim:8090/acciones/<accion_id>` con `{HOST.HOST}`. `equipos-sim` aplica el
  efecto **ficticio** y reenvía la telemetría resultante por *trapper*. Ninguna acción prohibida
  tiene script. `leer_logs` es un script que devuelve el ítem de log (su salida va al extractor).
- **Mínimo privilegio:**
  - `ZABBIX_TOKEN_LECTURA`: usuario con rol de solo lectura (API permitida: `host.get`, `item.get`, `history.get`).
  - `ZABBIX_TOKEN_ACCIONES`: usuario cuyo rol tiene `rules.api.mode = 1` (lista blanca) con solo
    `script.execute` y permiso únicamente sobre `Equipos-Simulados`; los scripts tienen `usrgrpid` de ese grupo.
  - `ZBX_ENABLEGLOBALSCRIPTS=0` en el servidor (comandos personalizados globales desactivados).
  - El backend mantiene un mapa `accion_id → scriptid` generado por el *bootstrap*; envía solo
    `scriptid` de ese mapa y **solo** después de que el motor de políticas valida y consume el token.
- Cada llamada = *span* `zabbix.<metodo>` en Langfuse.

## Pendiente de verificar (F1/F4)
- Si `EnableGlobalScripts=0` afecta a los webhooks (la documentación lo liga a scripts de tipo *Script*).
- Tokens: se crean en el *bootstrap*; si no se pueden automatizar, se documenta el paso manual en `infra/zabbix/README.md`.
