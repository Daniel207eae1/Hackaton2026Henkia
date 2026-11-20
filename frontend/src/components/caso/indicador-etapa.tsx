import { Check } from "lucide-react";
import { useEffect, useRef } from "react";

import { ETAPAS } from "@/lib/mensajes";
import { cn } from "@/lib/utils";

/** Indicador de la etapa del grafo (§3.5). La etapa la decide el backend, no el LLM. */
export function IndicadorEtapa({ etapa }: { etapa: string | null }) {
  const actual = ETAPAS.findIndex((e) => e.id === etapa);
  const avance = actual < 0 ? 0 : Math.round(((actual + 1) / ETAPAS.length) * 100);
  const lista = useRef<HTMLOListElement>(null);

  // Centra la etapa actual en la fila (sin mover la página: solo el desplazamiento horizontal de la lista).
  useEffect(() => {
    const ol = lista.current;
    const li = actual >= 0 ? (ol?.children[actual] as HTMLElement | undefined) : undefined;
    if (!ol || !li || typeof ol.scrollTo !== "function") return;
    ol.scrollTo({ left: li.offsetLeft - ol.clientWidth / 2 + li.offsetWidth / 2, behavior: "smooth" });
  }, [actual]);
  return (
    <nav aria-label="Etapa del caso" className="space-y-1.5">
      <div className="h-1 w-full overflow-hidden rounded-full bg-border" aria-hidden>
        <div className="degradado-marca h-full rounded-full transition-[width] duration-500" style={{ width: `${avance}%` }} />
      </div>
      <ol
        ref={lista}
        className="relative -mx-1 flex gap-1 overflow-x-auto px-1 text-[0.7rem] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {ETAPAS.map((e, i) => (
          <li
            key={e.id}
            aria-current={i === actual ? "step" : undefined}
            className={cn(
              "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 whitespace-nowrap transition-colors",
              i === actual && "border-primary bg-primary font-medium text-primary-foreground shadow-xs",
              i < actual && "border-success/40 bg-success-soft text-success-foreground",
              (actual < 0 || i > actual) && "border-transparent text-muted-foreground",
            )}
          >
            {i < actual && <Check className="size-3" aria-hidden />}
            {e.nombre}
          </li>
        ))}
      </ol>
    </nav>
  );
}
