import { BookOpen, Lightbulb } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DatosFuentes, DatosHipotesis, EstadoHipotesis } from "@/lib/mensajes";
import { cn } from "@/lib/utils";

const ESTADO: Record<EstadoHipotesis, { texto: string; clase: string }> = {
  pendiente: { texto: "Por probar", clase: "border-border text-muted-foreground" },
  confirmada: { texto: "Confirmada", clase: "border-success/40 bg-success-soft text-success-foreground" },
  descartada: { texto: "Descartada", clase: "border-border text-muted-foreground line-through" },
  no_concluyente: { texto: "No concluyente", clase: "border-warning/50 bg-warning-soft text-warning-foreground" },
};

/** Hipótesis del diagnóstico (§3.5): orden por prior del historial, estado y la evidencia que la decidió. */
export function PanelHipotesis({ datos }: { datos: DatosHipotesis | null }) {
  if (!datos || datos.hipotesis.length === 0) return null;
  return (
    <section aria-labelledby="titulo-hipotesis" className="rounded-xl border bg-card p-3 shadow-xs">
      <h2 id="titulo-hipotesis" className="flex items-center gap-2 text-sm font-semibold">
        <span className="grid size-7 place-items-center rounded-lg bg-accent text-accent-foreground" aria-hidden>
          <Lightbulb className="size-4" />
        </span>
        Posibles causas{datos.categoria ? ` · ${datos.categoria}` : ""}
      </h2>
      <ol className="mt-3 space-y-2 text-sm" aria-live="polite">
        {datos.hipotesis.map((h) => {
          const e = ESTADO[h.estado] ?? ESTADO.pendiente;
          return (
            <li
              key={h.articulo_id}
              className={cn(
                "rounded-lg border px-2.5 py-2",
                h.estado === "confirmada" ? "border-success/40 bg-success-soft/50" : "border-border/70",
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={cn(h.estado === "descartada" && "text-muted-foreground line-through")}>{h.hipotesis}</span>
                <Badge variant="outline" className={e.clase}>
                  {e.texto}
                </Badge>
              </div>
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted" aria-hidden>
                <div className="h-full rounded-full bg-chart-1" style={{ width: `${Math.round(h.prior * 100)}%` }} />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
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
          <li
            key={`${f.articulo_id}-${f.seccion}`}
            className="inline-flex items-center gap-1 rounded-full border border-info/30 bg-info-soft px-2.5 py-0.5 text-xs text-info-foreground"
          >
            <BookOpen className="size-3" aria-hidden /> {f.articulo_id} · {f.titulo}
          </li>
        ))}
      </ul>
      {onConfirmar && (
        <div
          role="group"
          aria-label="¿Ya te funciona?"
          className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/40 px-3 py-2 text-sm"
        >
          <span className="font-medium">¿Ya te funciona?</span>
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
