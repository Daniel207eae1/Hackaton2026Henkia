"""Ajustes de la aplicación leídos del entorno (.env). Nunca se quema un secreto aquí."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_BACKEND = Path(__file__).resolve().parents[2]


class Ajustes(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    modo_demo: bool = Field(default=False, alias="MODO_DEMO")
    entorno: str = Field(default="local", alias="ENTORNO")

    # Base de datos (P2). Vacía = repositorios en memoria (dobles) mientras P2 entrega.
    database_url: str = Field(default="", alias="DATABASE_URL", repr=False)  # secreto: nunca en logs ni trazas
    database_url_ro: str = Field(default="", alias="DATABASE_URL_RO", repr=False)  # secreto: nunca en logs ni trazas
    checkpointer: Literal["memoria", "postgres"] = Field(default="memoria", alias="CHECKPOINTER")
    # Rol que asume cada sesión (mínimo privilegio; nunca ve `evaluacion`). Ver ADR 0009.
    db_rol_app: str = Field(default="app_rw", alias="DB_ROL_APP")

    # Capa LLM
    modelos_yaml: Path = Field(default=RAIZ_BACKEND / "config" / "modelos.yaml", alias="MODELOS_YAML")
    llm_modo: Literal["real", "fake"] = Field(default="real", alias="LLM_MODO")
    ollama_base_url: str = Field(default="", alias="OLLAMA_BASE_URL")
    openrouter_api_key: str = Field(
        default="", alias="OPENROUTER_API_KEY", repr=False
    )  # secreto: nunca en logs ni trazas
    embedding_model: str = Field(default="qwen3-embedding:0.6b", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=1024, alias="EMBEDDING_DIM")

    # Langfuse
    langfuse_public_key: str = Field(
        default="", alias="LANGFUSE_PUBLIC_KEY", repr=False
    )  # secreto: nunca en logs ni trazas
    langfuse_secret_key: str = Field(
        default="", alias="LANGFUSE_SECRET_KEY", repr=False
    )  # secreto: nunca en logs ni trazas
    langfuse_host: str = Field(default="http://localhost:3000", alias="LANGFUSE_HOST")
    # URL con la que el navegador abre Langfuse (el contenedor puede usar host.docker.internal).
    langfuse_url_publica: str = Field(default="", alias="LANGFUSE_URL_PUBLICA")
    langfuse_etiqueta_prompts: str = Field(default="production", alias="LANGFUSE_ETIQUETA_PROMPTS")

    # Zabbix vía el servidor MCP `zabbix-ofimatica` (ADR 0007). Vacío = sin integración.
    zabbix_mcp_url: str = Field(default="", alias="ZABBIX_MCP_URL")
    zabbix_mcp_token: str = Field(default="", alias="ZABBIX_MCP_TOKEN", repr=False)  # secreto: nunca en logs ni trazas
    zabbix_mcp_timeout_s: float = Field(default=75.0, alias="ZABBIX_MCP_TIMEOUT_S")
    # Equipo de laboratorio a usar cuando el equipo de la persona no existe en Zabbix (solo demo).
    zabbix_equipo_demo: str = Field(default="", alias="ZABBIX_EQUIPO_DEMO")
    # Aprobaciones N2 (API REST del servidor MCP, ADR 0022). La clave vive solo en el servidor.
    n2_url: str = Field(default="", alias="N2_URL")
    n2_api_key: str = Field(default="", alias="N2_API_KEY", repr=False)  # secreto: nunca al navegador ni a logs
    n2_poll_s: int = Field(default=10, alias="N2_POLL_S")
    n2_state_file: Path = Field(default=Path("/var/n2/n2.json"), alias="N2_STATE_FILE")
    n2_sin_ejecutar_min: int = Field(default=30, alias="N2_SIN_EJECUTAR_MIN")

    # Espera del consentimiento en la ventana del equipo dentro de un turno (F4)
    consentimiento_espera_max_s: int = Field(default=150, alias="CONSENTIMIENTO_ESPERA_MAX_S")
    consentimiento_espera_por_consulta_s: int = Field(default=25, alias="CONSENTIMIENTO_ESPERA_POR_CONSULTA_S")

    # Posible masivo: mínimo de equipos con el mismo problema (k, §3.11)
    masivo_min_equipos: int = Field(default=3, alias="MASIVO_MIN_EQUIPOS")
    # Clúster semántico de reportes (F2): ventana, similitud mínima (coseno) y reloj de demostración.
    masivo_ventana_min: int = Field(default=60, alias="MASIVO_VENTANA_MIN")
    masivo_umbral: float = Field(default=0.75, alias="MASIVO_UMBRAL")
    # Solo con MODO_DEMO: «ahora» para el clúster (reproduce los escenarios 3/3b del kit). ISO 8601.
    masivo_reloj_demo: str = Field(default="", alias="MASIVO_RELOJ_DEMO")

    @property
    def masivo_referencia(self) -> str | None:
        return self.masivo_reloj_demo or None if self.modo_demo else None

    # Módulo B (F7): capturas saneadas en disco (volumen propio, nunca servido por HTTP)
    capturas_dir: Path = Field(default=Path("/var/capturas"), alias="CAPTURAS_DIR")
    captura_max_bytes: int = Field(default=5 * 1024 * 1024, alias="CAPTURA_MAX_BYTES")
    capturas_por_mensaje: int = Field(default=3, alias="CAPTURAS_POR_MENSAJE")
    capturas_retencion_dias: int = Field(default=30, alias="CAPTURAS_RETENCION_DIAS")  # 0 = no purgar
    # Límite de solicitudes por persona y minuto (0 = sin límite)
    limite_chat_por_min: int = Field(default=20, alias="LIMITE_CHAT_POR_MIN")
    limite_post_por_min: int = Field(default=60, alias="LIMITE_POST_POR_MIN")

    # F9: reportes de la evaluación (los escribe `python -m evaluacion.ejecutar`; los lee /api/metricas)
    evaluacion_dir: Path = Field(default=Path("/var/evaluacion"), alias="EVALUACION_DIR")

    # Seguridad / límites
    origenes_cors: str = Field(default="http://localhost:5173", alias="ORIGENES_CORS")
    max_caracteres_mensaje: int = Field(default=4000, alias="MAX_CARACTERES_MENSAJE")
    max_turnos_caso: int = Field(default=40, alias="MAX_TURNOS_CASO")

    @property
    def langfuse_activo(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def obtener_ajustes() -> Ajustes:
    return Ajustes()
