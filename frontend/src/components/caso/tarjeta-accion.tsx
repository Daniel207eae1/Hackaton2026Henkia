import { CheckCircle2, Clock, Monitor, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import type { DatosAccion, EstadoAccion } from "@/lib/mensajes";
import { cn } from "@/lib/utils";

const ESTADO: Record<EstadoAccion, { texto: string; clase: string; icono: typeof Clock }> = {
  propuesta: { texto: "Propuesta", clase: "bg-muted text-foreground", icono: Clock },
  esperando_n2: { texto: "Esperando aprobación de N2", clase: "bg-amber-100 text-amber-900", icono: Clock },
  aprobada_n2: { texto: "Aprobada por N2", clase: "bg-sky-100 text-sky-900", icono: ShieldCheck },
  esperando_consentimiento: { texto: "Esperando tu autorización", clase: "bg-amber-100 text-amber-900", icono: Monitor },
  autorizada: { texto: "Autorizada por ti", clase: "bg-sky-100 text-sky-900", icono: ShieldCheck },
  ejecutando: { texto: "Ejecutando", clase: "bg-sky-100 text-sky-900", icono: Clock },
  ejecutada: { texto: "Ejecutada", clase: "bg-emerald-100 text-emerald-900", icono: CheckCircle2 },
  rechazada: { texto: "Rechazada por ti", clase: "bg-muted text-foreground", icono: XCircle },
  rechazada_n2: { texto: "N2 no la aprobó", clase: "bg-muted text-foreground", icono: XCircle },
  expirada: { texto: "Solicitud vencida", clase: "bg-muted text-foreground", icono: XCircle },
  fallida: { texto: "No se pudo completar", clase: "bg-red-100 text-red-900", icono: ShieldAlert },
};

const RIESGO: Record<string, string> = {
  bajo: "border-emerald-700 text-emerald-800",
  medio: "border-amber-700 text-amber-800",
  alto: "border-red-700 text-red-800",
};

interface Props {
  accion: DatosAccion;
  /** Pide al backend que vuelva a consultar el estado (no autoriza nada: eso solo pasa en la ventana del equipo). */
  onRevisar?: () => void;
  /** Respuesta a «¿ya te funciona?» (solo en la última acción ejecutada). */
  onConfirmar?: (texto: string) => void;
  ocupado?: boolean;
}

/**
 * Tarjeta de consentimiento / aprobación. Todos los textos vienen del backend (catálogo) y se muestran
 * escapados. No tiene botón «Sí»: la autorización real ocurre en la ventana «Soporte TI» del equipo (ADR 0007).
 */
export function TarjetaAccion({ accion, onRevisar, onConfirmar, ocupado }: Props) {
  const estado = ESTADO[accion.estado] ?? ESTADO.propuesta;
  const Icono = estado.icono;
  const esperando = accion.estado === "esperando_consentimiento" || accion.estado === "esperando_n2";

  return (
    <Card className="w-full max-w-xl" role="region" aria-label={`Acción propuesta: ${accion.nombre}`}>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">{accion.nombre}</CardTitle>
          <Badge variant="outline" className={RIESGO[accion.riesgo] ?? ""}>
            Riesgo {accion.riesgo}
          </Badge>
          {accion.politica === "aprobacion_n2" && <Badge variant="outline">Requiere N2</Badge>}
        </div>
        <CardDescription>{accion.descripcion}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <dl className="grid gap-2">
          <div>
            <dt className="font-medium">Qué efecto tiene</dt>
            <dd>{accion.aviso}</dd>
          </div>
          <div>
            <dt className="font-medium">Cómo se revierte</dt>
            <dd>{accion.reversion}</dd>
          </div>
        </dl>
        {accion.estado === "esperando_consentimiento" && (
          <Alert>
            <Monitor aria-hidden />
            <AlertTitle>Autoriza en tu equipo</AlertTitle>
            <AlertDescription>
              Te apareció una ventana «Soporte TI – Solicitud de autorización». Pulsa «Autorizar» si estás de acuerdo o
              «Rechazar» si no. Escribir «sí» en el chat no autoriza nada.
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
      <CardFooter className="flex flex-wrap items-center justify-between gap-2">
        <p role="status" aria-live="polite" className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs", estado.clase)}>
          <Icono className="size-3" aria-hidden /> {estado.texto}
          {accion.mensaje && <span className="sr-only">: {accion.mensaje}</span>}
        </p>
        {accion.estado === "ejecutada" && onConfirmar && (
          <div className="flex gap-2" role="group" aria-label="¿Ya te funciona?">
            <Button size="sm" onClick={() => onConfirmar("Sí, ya funciona")} disabled={ocupado}>
              Sí, ya funciona
            </Button>
            <Button size="sm" variant="outline" onClick={() => onConfirmar("No, sigue igual")} disabled={ocupado}>
              No, sigue igual
            </Button>
          </div>
        )}
        {esperando && onRevisar && (
          <Button variant="outline" size="sm" onClick={onRevisar} disabled={ocupado}>
            {accion.estado === "esperando_n2" ? "Revisar la aprobación" : "Ya respondí la ventana"}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
