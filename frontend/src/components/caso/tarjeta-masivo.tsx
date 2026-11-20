import { Megaphone, RadioTower } from "lucide-react";
import { useEffect, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { pedir } from "@/lib/api";
import type { DatosMasivo } from "@/lib/mensajes";

/** Cita del estado oficial TAL CUAL (texto escapado por React) o aviso de posible masivo. */
export function TarjetaMasivo({ datos }: { datos: DatosMasivo }) {
  const resuelto = datos.incidente_estado === "resuelto";
  const confirmado = datos.estado === "masivo_confirmado" && !resuelto;
  return (
    <Alert role="status" className="max-w-xl border-warning/50 bg-warning-soft p-3 shadow-xs">
      <Megaphone aria-hidden className="text-warning-foreground" />
      <AlertTitle className="font-semibold">
        {resuelto ? "Incidente general resuelto" : confirmado ? "Incidente general confirmado" : "Posible incidente general"}
        {datos.incidente_id && <span className="ml-1 font-normal text-muted-foreground">· {datos.incidente_id}</span>}
      </AlertTitle>
      <AlertDescription>
        {confirmado && datos.mensaje_oficial ? (
          <blockquote className="border-l-2 border-warning pl-2 text-sm text-foreground">
            «{datos.mensaje_oficial}»
            {datos.hora_oficial && <span className="block text-xs text-muted-foreground">Publicado: {datos.hora_oficial}</span>}
          </blockquote>
        ) : resuelto ? (
          <p className="text-sm">Cuéntame si ya te funciona.</p>
        ) : (
          <p className="text-sm">
            {datos.usuarios_similares
              ? `${datos.usuarios_similares} compañeros reportaron algo parecido. N2 lo está validando.`
              : "N2 lo está validando."}
          </p>
        )}
        <p className="mt-1 text-xs text-muted-foreground">No hace falta que cambies nada en tu equipo: te avisamos aquí.</p>
      </AlertDescription>
    </Alert>
  );
}

export interface NovedadMasivo {
  vinculado: boolean;
  incidente_id?: string;
  estado_caso?: string;
  incidente_estado?: string;
  servicio_nombre?: string | null;
  mensaje_oficial?: string | null;
  hora_oficial?: string | null;
  resuelto_en?: string | null;
}

const TEXTO_ESTADO: Record<string, string> = {
  propuesto: "N2 está validando si es un incidente general.",
  publicado: "Incidente general confirmado. Te avisamos al resolverse.",
  descartado: "N2 revisó: no es un incidente general. Escríbeme y reviso tu equipo.",
  resuelto: "El incidente general se resolvió.",
};

/** Seguimiento en vivo del incidente vinculado (consulta periódica; el usuario no tiene que escribir). */
export function SeguimientoMasivo({
  caseId,
  verComo,
  activo,
  ocupado,
  onResponder,
  intervaloMs = 15000,
}: {
  caseId: string;
  verComo: string;
  activo: boolean;
  ocupado: boolean;
  onResponder: (texto: string) => void;
  intervaloMs?: number;
}) {
  const [nov, setNov] = useState<NovedadMasivo | null>(null);

  useEffect(() => {
    if (!activo) return;
    let vigente = true;
    const consultar = () =>
      pedir<NovedadMasivo>(`/api/casos/${caseId}/masivo`, verComo)
        .then((n) => vigente && setNov(n))
        .catch(() => undefined);
    void consultar();
    const t = setInterval(consultar, intervaloMs);
    return () => {
      vigente = false;
      clearInterval(t);
    };
  }, [caseId, verComo, activo, intervaloMs]);

  if (!activo || !nov?.vinculado || !nov.incidente_estado) return null;
  const resuelto = nov.incidente_estado === "resuelto";
  return (
    <section
      aria-label="Incidente general"
      aria-live="polite"
      className="rounded-xl border border-warning/50 bg-warning-soft p-3 text-sm shadow-xs"
    >
      <h2 className="flex items-center gap-2 font-semibold">
        <RadioTower className="size-4 text-warning-foreground" aria-hidden /> Incidente general · {nov.incidente_id}
      </h2>
      <p className="mt-1">{TEXTO_ESTADO[nov.incidente_estado] ?? nov.incidente_estado}</p>
      {nov.incidente_estado === "publicado" && nov.mensaje_oficial && (
        <blockquote className="mt-1 border-l-2 border-warning pl-2 text-xs">
          «{nov.mensaje_oficial}»{nov.hora_oficial && ` (${nov.hora_oficial})`}
        </blockquote>
      )}
      {resuelto && (
        <div role="group" aria-label="¿Ya te funciona?" className="mt-2 flex flex-wrap items-center gap-2">
          <span>¿Ya te funciona?</span>
          <Button size="sm" disabled={ocupado} onClick={() => onResponder("Sí, ya me funciona")}>
            Sí
          </Button>
          <Button size="sm" variant="outline" disabled={ocupado} onClick={() => onResponder("No, sigue fallando")}>
            No, sigue fallando
          </Button>
        </div>
      )}
    </section>
  );
}
