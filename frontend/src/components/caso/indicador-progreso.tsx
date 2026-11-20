import { Shimmer } from "@/components/ai-elements/shimmer";

/** Qué está haciendo el sistema en cada nodo del grafo (lo que el usuario ve mientras espera). */
export const PROGRESO: Record<string, string> = {
  Recepcion: "Leyendo tu mensaje…",
  Captura: "Leyendo tus capturas con cuidado…",
  RespuestaPolitica: "Revisando tu solicitud…",
  Interpretacion: "Entendiendo el problema…",
  Contexto: "Consultando tu equipo…",
  ChequeoMasivo: "Revisando si otros compañeros tienen lo mismo…",
  InformarMasivo: "Revisando el incidente general…",
  Hipotesis: "Evaluando las causas posibles…",
  Guia: "Preparando los pasos de la guía…",
  Decision: "Eligiendo la mejor solución…",
  AprobacionN2: "Esperando la aprobación de un técnico de N2…",
  Consentimiento: "Esperando tu autorización en la ventana «Soporte TI» de tu equipo…",
  Ejecucion: "Aplicando la solución en tu equipo…",
  Verificacion: "Verificando que haya quedado bien…",
  Confirmacion: "Revisando tu respuesta…",
  Aclaracion: "Escribiendo la respuesta…",
  Cierre: "Cerrando tu caso…",
  Escalar: "Preparando el caso para un técnico de N2…",
};

/** Indicador visible durante TODO el turno (no solo antes del primer byte): etapa actual + último hallazgo. */
export function IndicadorProgreso({ etapa, detalle }: { etapa: string | null; detalle?: string | null }) {
  const texto = (etapa && PROGRESO[etapa]) || "Revisando…";
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex max-w-xl items-start gap-3 rounded-xl border border-primary/20 bg-accent/50 px-3 py-2.5 text-sm"
    >
      <span className="relative mt-1 flex size-2.5 shrink-0" aria-hidden>
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-brand-green opacity-60" />
        <span className="relative inline-flex size-2.5 rounded-full bg-brand-green" />
      </span>
      <div className="min-w-0 space-y-0.5">
        <Shimmer>{texto}</Shimmer>
        {detalle && <p className="text-xs text-muted-foreground">{detalle}</p>}
      </div>
    </div>
  );
}
