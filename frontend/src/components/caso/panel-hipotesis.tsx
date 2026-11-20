import { BookOpen } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DatosFuentes, DatosHipotesis, EstadoHipotesis } from "@/lib/mensajes";
import { cn } from "@/lib/utils";

const ESTADO: Record<EstadoHipotesis, { texto: string; clase: string }> = {
  pendiente: { texto: "Por probar", clase: "border-muted-foreground/40 text-muted-foreground" },
  confirmada: { texto: "Confirmada", clase: "border-emerald-700 text-emerald-800" },
  descartada: { texto: "Descartada", clase: "border-muted-foreground/40 text-muted-foreground line-through" },
  no_concluyente: { texto: "No concluyente", clase: "border-amber-700 text-amber-800" },
};

/** Hipótesis del diagnóstico (§3.5): orden por prior del historial, estado y la evidencia que la decidió. */
export function PanelHipotesis({ datos }: { datos: DatosHipotesis | null }) {
  if (!datos || datos.hipotesis.length === 0) return null;
  return (
    <section aria-labelledby="titulo-hipotesis" className="rounded-lg border bg-card p-3">
      <h2 id="titulo-hipotesis" className="text-sm font-medium">
        Posibles causas{datos.categoria ? ` · ${datos.categoria}` : ""}
      </h2>
      <ol className="mt-2 space-y-2 text-sm" aria-live="polite">
        {datos.hipotesis.map((h) => {
          const e = ESTADO[h.estado] ?? ESTADO.pendiente;
          return (
            <li key={h.articulo_id}>
              <div className="flex flex-wrap items-center gap-1">
                <span className={cn(h.estado === "descartada" && "text-muted-foreground line-through")}>{h.hipotesis}</span>
                <Badge variant="outline" className={e.clase}>
                  {e.texto}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {h.articulo_id} · probabilidad previa {Math.round(h.prior * 100)} %
                {h.justificacion && ` · ${h.justificacion}`}
              </p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** Cita de la KB bajo una guía (no invención: los pasos salen de este artículo). */
/** Artículos citados. Tras una guía (la última del caso abierto) pregunta «¿ya te funciona?» con botones. */
export function Fuentes({ datos, onConfirmar }: { datos: DatosFuentes; onConfirmar?: (texto: string) => void }) {
  return (
    <div className="space-y-2">
      <ul aria-label="Fuentes" className="flex flex-wrap gap-2">
        {datos.fuentes.map((f) => (
          <li key={`${f.articulo_id}-${f.seccion}`} className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs">
            <BookOpen className="size-3" aria-hidden /> {f.articulo_id} · {f.titulo}
          </li>
        ))}
      </ul>
      {onConfirmar && (
        <div role="group" aria-label="¿Ya te funciona?" className="flex flex-wrap items-center gap-2 text-sm">
          <span>¿Ya te funciona?</span>
          <Button size="sm" onClick={() => onConfirmar("Sí, ya funciona")}>
            Sí, ya funciona
          </Button>
          <Button size="sm" variant="outline" onClick={() => onConfirmar("No, sigue igual")}>
            No, sigue igual
          </Button>
        </div>
      )}
    </div>
  );
}
