/** Línea de tiempo del monitor: agentes con duración y error, marcas de turno y enlace a la traza de Langfuse. */
import { CircleAlert, CircleCheck, ExternalLink, Flag, LoaderCircle, Play, type LucideIcon } from "lucide-react";

import { nombreNodo } from "@/components/monitor/nodos";
import { Badge } from "@/components/ui/badge";
import { urlSegura, type EntradaLinea } from "@/lib/monitor";
import { cn } from "@/lib/utils";

const ESTADO: Record<EntradaLinea["estado"], { icono: LucideIcon; texto: string; clase: string }> = {
  en_curso: { icono: LoaderCircle, texto: "en curso", clase: "text-primary" },
  ok: { icono: CircleCheck, texto: "ok", clase: "text-success" },
  error: { icono: CircleAlert, texto: "error", clase: "text-destructive" },
};

export function hora(ts: number): string {
  return new Date(ts).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function duracion(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "…";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function Entrada({ e }: { e: EntradaLinea }) {
  if (e.clase === "turno_inicio")
    return (
      <li className="flex items-center gap-2 border-t pt-2 text-xs font-medium text-muted-foreground first:border-t-0">
        <Play className="size-3.5" aria-hidden /> Turno iniciado · {hora(e.ts)}
      </li>
    );
  if (e.clase === "turno_fin") {
    const url = urlSegura(e.trazaUrl);
    const est = ESTADO[e.estado];
    return (
      <li className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium">
        <Flag className={cn("size-3.5", est.clase)} aria-hidden />
        <span>
          Turno terminado en {e.etapaFinal ? nombreNodo(e.etapaFinal) : "—"}
          {e.estado === "error" && " (con error)"} · {hora(e.ts)}
        </span>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
          >
            Ver en Langfuse <ExternalLink className="size-3" aria-hidden />
            <span className="sr-only"> (se abre en otra pestaña)</span>
          </a>
        )}
      </li>
    );
  }
  const est = ESTADO[e.estado];
  const Icono = est.icono;
  return (
    <li className="flex items-center gap-2 text-sm">
      <Icono
        className={cn("size-4 shrink-0", est.clase, e.estado === "en_curso" && "motion-safe:animate-spin")}
        aria-hidden
      />
      <span className="min-w-0 flex-1 truncate font-mono text-xs" title={e.agente}>
        {e.agente}
      </span>
      {e.tipoObservacion && (
        <Badge variant="outline" className="hidden text-[0.65rem] sm:inline-flex">
          {e.tipoObservacion}
        </Badge>
      )}
      <span className={cn("w-14 text-right text-xs tabular-nums", est.clase)}>
        {e.estado === "en_curso" ? est.texto : duracion(e.duracionMs)}
      </span>
      <span className="sr-only">{e.estado === "en_curso" ? "" : est.texto}</span>
      {e.estado === "error" && (
        <Badge variant="destructive" className="text-[0.65rem]">
          error
        </Badge>
      )}
    </li>
  );
}

export function LineaTiempo({
  entradas,
  titulo,
  vacio,
  className,
}: {
  entradas: EntradaLinea[];
  titulo: string;
  vacio: string;
  className?: string;
}) {
  const id = `lt-${titulo.replace(/\W+/g, "-").toLowerCase()}`;
  const recientes = [...entradas].reverse(); // lo más nuevo arriba
  return (
    <section aria-labelledby={id} className={cn("flex min-h-0 flex-col gap-2 rounded-xl border bg-card p-3", className)}>
      <h2 id={id} className="text-sm font-semibold">
        {titulo}
      </h2>
      {recientes.length === 0 ? (
        <p className="text-sm text-muted-foreground">{vacio}</p>
      ) : (
        <ol aria-live="polite" aria-relevant="additions" className="flex max-h-[420px] flex-col gap-1.5 overflow-y-auto pr-1">
          {recientes.map((e) => (
            <Entrada key={e.clave} e={e} />
          ))}
        </ol>
      )}
    </section>
  );
}
