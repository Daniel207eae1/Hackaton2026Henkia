import { AlertTriangle, CheckCircle2, ChevronDown, CircleDashed, CircleMinus, ScanSearch, XCircle } from "lucide-react";

import { Task, TaskContent, TaskItem, TaskTrigger } from "@/components/ai-elements/task";
import type { DatosRevisando, EstadoRevision } from "@/lib/mensajes";
import { cn } from "@/lib/utils";

const ICONO: Record<EstadoRevision, { icono: typeof CheckCircle2; etiqueta: string; clase: string }> = {
  ok: { icono: CheckCircle2, etiqueta: "Consulta correcta, nada anormal", clase: "text-success" },
  anomalia: { icono: XCircle, etiqueta: "Consulta correcta, con una anomalía", clase: "text-destructive" },
  fallo: { icono: AlertTriangle, etiqueta: "La consulta falló", clase: "text-warning-foreground" },
  pendiente: { icono: CircleDashed, etiqueta: "Pendiente", clase: "text-muted-foreground" },
  no_disponible: { icono: CircleMinus, etiqueta: "Lectura no disponible para este equipo", clase: "text-muted-foreground" },
};

/** Panel «Lo que estoy revisando». El texto se muestra escapado (React), nunca como HTML. */
export function PanelRevisando({ lineas }: { lineas: DatosRevisando[] }) {
  return (
    <section aria-labelledby="titulo-revisando" className="rounded-xl border bg-card p-3 shadow-xs">
      <h2 id="titulo-revisando" className="sr-only">
        Lo que estoy revisando
      </h2>
      <Task defaultOpen>
        <TaskTrigger title="Lo que estoy revisando">
          {/* Botón real (no un div) para que se pueda abrir y cerrar con el teclado. */}
          <button
            type="button"
            className="group flex w-full items-center gap-2 rounded-md text-left text-sm font-semibold text-foreground"
          >
            <span className="grid size-7 place-items-center rounded-lg bg-accent text-accent-foreground">
              <ScanSearch className="size-4" aria-hidden />
            </span>
            <span className="flex-1">Lo que estoy revisando</span>
            {lineas.length > 0 && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground tabular-nums">
                {lineas.length}
              </span>
            )}
            <ChevronDown
              className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180"
              aria-hidden
            />
          </button>
        </TaskTrigger>
        <TaskContent className="mt-3">
          {lineas.length === 0 ? (
            <TaskItem className="text-muted-foreground">Aún no he consultado nada.</TaskItem>
          ) : (
            <ul className="space-y-1" aria-live="polite">
              {lineas.map((l) => {
                const { icono: Icono, etiqueta, clase } = ICONO[l.estado] ?? ICONO.pendiente;
                return (
                  <li key={l.id} className="flex items-start gap-2 rounded-md px-1.5 py-1 text-sm odd:bg-muted/40">
                    <Icono className={cn("mt-0.5 size-4 shrink-0", clase)} aria-label={etiqueta} role="img" />
                    <span className="min-w-0 break-words">{l.texto}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </TaskContent>
      </Task>
    </section>
  );
}
