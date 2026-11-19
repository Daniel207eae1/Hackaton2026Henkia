import { AlertTriangle, CheckCircle2, CircleDashed, XCircle } from "lucide-react";

import { Task, TaskContent, TaskItem, TaskTrigger } from "@/components/ai-elements/task";
import type { DatosRevisando, EstadoRevision } from "@/lib/mensajes";

const ICONO: Record<EstadoRevision, { icono: typeof CheckCircle2; etiqueta: string; clase: string }> = {
  ok: { icono: CheckCircle2, etiqueta: "Consulta correcta, nada anormal", clase: "text-emerald-700" },
  anomalia: { icono: XCircle, etiqueta: "Consulta correcta, con una anomalía", clase: "text-red-700" },
  fallo: { icono: AlertTriangle, etiqueta: "La consulta falló", clase: "text-amber-700" },
  pendiente: { icono: CircleDashed, etiqueta: "Pendiente", clase: "text-muted-foreground" },
};

/** Panel «Lo que estoy revisando». El texto se muestra escapado (React), nunca como HTML. */
export function PanelRevisando({ lineas }: { lineas: DatosRevisando[] }) {
  return (
    <section aria-labelledby="titulo-revisando" className="rounded-lg border bg-card p-3">
      <h2 id="titulo-revisando" className="sr-only">
        Lo que estoy revisando
      </h2>
      <Task defaultOpen>
        <TaskTrigger title="Lo que estoy revisando" />
        <TaskContent>
          {lineas.length === 0 ? (
            <TaskItem>Aún no he consultado nada.</TaskItem>
          ) : (
            <ul className="space-y-2" aria-live="polite">
              {lineas.map((l) => {
                const { icono: Icono, etiqueta, clase } = ICONO[l.estado] ?? ICONO.pendiente;
                return (
                  <li key={l.id} className="flex items-start gap-2 text-sm">
                    <Icono className={`mt-0.5 size-4 shrink-0 ${clase}`} aria-label={etiqueta} role="img" />
                    <span>{l.texto}</span>
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
