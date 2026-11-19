# Zabbix local de respaldo (ADR 0005)

> **El camino por defecto es el servidor MCP `zabbix-ofimatica` (ADR 0007, `ZABBIX_MCP_URL`).** Esta carpeta
> solo sirve si hay que levantar un Zabbix propio sin ese servidor.

Estado: **esqueleto F0**. Zabbix 7.0 LTS (`ubuntu-7.0.32`) con su propia BD, en el perfil `zabbix`.

```powershell
docker compose --profile zabbix up -d zabbix-db zabbix-server zabbix-web
# Web: http://localhost:8080 (usuario inicial Admin / zabbix → CÁMBIALA al entrar)
```

## Pendiente por feature
- **F1:** *bootstrap* idempotente (`bootstrap.py`): grupo `Equipos-Simulados`, hosts `EQ-SIM-xxx`,
  ítems *trapper*, usuario/rol de **solo lectura** y su token → `ZABBIX_TOKEN_LECTURA`. Cargador.
- **F4:** scripts *webhook* de la lista blanca → `equipos-sim`; usuario/rol que solo puede
  `script.execute` sobre `Equipos-Simulados` y su token → `ZABBIX_TOKEN_ACCIONES`. Efectos en `equipos-sim`.

## Cómo obtener los tokens (mientras no exista el bootstrap)
Zabbix web → *Users → API tokens → Create API token* con el usuario correspondiente. Copia el token
en `.env` (nunca en el repo).
