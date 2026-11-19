import { CheckCircle2, Headset } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { DatosCierre, DatosEscalamiento } from "@/lib/mensajes";

/** Escalamiento a N2: motivo, ANS y siguiente paso (todo construido por el backend desde el estado). */
export function TarjetaEscalamiento({ datos }: { datos: DatosEscalamiento }) {
  return (
    <Alert role="status" className="max-w-xl border-sky-700">
      <Headset aria-hidden />
      <AlertTitle>Tu caso pasó a un técnico de N2</AlertTitle>
      <AlertDescription>
        <dl className="mt-1 grid gap-1 text-sm">
          <div>
            <dt className="inline font-medium">Motivo: </dt>
            <dd className="inline">{datos.motivo}</dd>
          </div>
          <div>
            <dt className="inline font-medium">Plazo de atención: </dt>
            <dd className="inline">
              {datos.plazo} · {datos.prioridad}
            </dd>
          </div>
        </dl>
        <p className="mt-1 text-xs text-muted-foreground">N2 recibe todo lo que revisamos: no tendrás que repetirlo.</p>
      </AlertDescription>
    </Alert>
  );
}

export function TarjetaCierre({ datos }: { datos: DatosCierre }) {
  return (
    <Alert role="status" className="max-w-xl border-emerald-700">
      <CheckCircle2 aria-hidden className="text-emerald-700" />
      <AlertTitle>Caso cerrado como resuelto</AlertTitle>
      <AlertDescription>
        {datos.solucion ? `Solución: ${datos.solucion}.` : "Quedó resuelto."} El registro quedó guardado.
      </AlertDescription>
    </Alert>
  );
}
