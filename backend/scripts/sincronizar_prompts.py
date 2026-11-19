"""Sube los prompts embebidos (app/agentes/prompts/*.md) a Langfuse Prompt Management.

Uso (dentro del contenedor de la API):
    docker compose exec api python scripts/sincronizar_prompts.py            # etiqueta staging
    docker compose exec api python scripts/sincronizar_prompts.py --production

- Solo crea una versión nueva si el texto cambió respecto a la última con esa etiqueta.
- `production` solo se asigna con --production (regla: pasar a production tras la regresión, CLAUDE.md).
- No contiene secretos: lee LANGFUSE_* del entorno.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from langfuse import Langfuse

from app.config.ajustes import obtener_ajustes

DIR_PROMPTS = Path(__file__).resolve().parents[1] / "app" / "agentes" / "prompts"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true", help="asigna también la etiqueta production")
    args = parser.parse_args()
    etiquetas = ["staging", "production"] if args.production else ["staging"]

    a = obtener_ajustes()
    if not a.langfuse_activo:
        raise SystemExit("Faltan LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY")
    lf = Langfuse(public_key=a.langfuse_public_key, secret_key=a.langfuse_secret_key, base_url=a.langfuse_host)

    def vigente(nombre: str, etiqueta: str):
        try:
            p = lf.get_prompt(nombre, label=etiqueta, type="text", cache_ttl_seconds=0)
        except Exception:  # noqa: BLE001 - no existe todavía
            return None
        return None if getattr(p, "is_fallback", False) else p

    for ruta in sorted(DIR_PROMPTS.glob("*.md")):
        nombre, texto = ruta.stem, ruta.read_text(encoding="utf-8")
        actual = vigente(nombre, etiquetas[-1])
        if actual is not None and actual.prompt == texto:
            print(f"= {nombre}: sin cambios (v{actual.version}, {etiquetas[-1]})")
            continue
        staging = vigente(nombre, "staging") if args.production else None
        if staging is not None and staging.prompt == texto:
            # Promueve la misma versión probada en staging: no se duplica.
            lf.update_prompt(name=nombre, version=staging.version, new_labels=["production"])
            print(f"↑ {nombre}: v{staging.version} → production")
            continue
        nuevo = lf.create_prompt(
            name=nombre,
            prompt=texto,
            type="text",
            labels=etiquetas,
            tags=["caso5", "agente"],
            commit_message="Sincronizado desde app/agentes/prompts",
        )
        print(f"+ {nombre}: v{nuevo.version} {etiquetas}")
    lf.flush()


if __name__ == "__main__":
    main()
