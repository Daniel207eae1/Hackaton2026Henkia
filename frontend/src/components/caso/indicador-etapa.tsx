import { ETAPAS } from "@/lib/mensajes";
import { cn } from "@/lib/utils";

/** Indicador de la etapa del grafo (§3.5). La etapa la decide el backend, no el LLM. */
export function IndicadorEtapa({ etapa }: { etapa: string | null }) {
  const actual = ETAPAS.findIndex((e) => e.id === etapa);
  return (
    <nav aria-label="Etapa del caso">
      <ol className="flex flex-wrap gap-1 text-xs">
        {ETAPAS.map((e, i) => (
          <li
            key={e.id}
            aria-current={i === actual ? "step" : undefined}
            className={cn(
              "rounded-full border px-2 py-0.5",
              i === actual && "border-primary bg-primary text-primary-foreground",
              i < actual && "border-primary/40 text-foreground",
              i > actual && "text-muted-foreground",
            )}
          >
            {e.nombre}
          </li>
        ))}
      </ol>
    </nav>
  );
}
