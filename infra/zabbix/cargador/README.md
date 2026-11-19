# Cargador de telemetría → Zabbix (F1)

Lee la semilla del esquema `telemetria` con el rol `zabbix_loader` (P2, `db/CONTRATO_SQL.md`) y la
envía a los ítems *trapper* de cada host `EQ-SIM-xxx` con `zabbix_utils.Sender` (protocolo de
`zabbix_sender`). Se implementa en F1; el mapeo de ítems está en `docs/adr/0005-mapeo-zabbix.md`.
