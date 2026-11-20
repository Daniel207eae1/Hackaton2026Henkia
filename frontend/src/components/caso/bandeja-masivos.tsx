import { RadioTower } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Cargando, EstadoVacio, TituloSeccion } from "@/components/vista";

export interface IncidenteMasivo {
  id: string;
  servicio_id: string;
  categoria_id: string | null;
  titulo: string;
  estado: "detectado" | "propuesto" | "publicado" | "descartado" | "resuelto";
  origen: string;
  mensaje_oficial: string | null;
  publicado_en: string | null;
  resuelto_en: string | null;
  confirmado_por: string | null;
  regla: { usuarios_distintos?: number; k?: number; umbral?: number; ventana_min?: number; similitud_max?: number };
  casos_vinculados: number;
}

const MIN_MENSAJE = 15;

/** Fila de la bandeja «Posibles masivos»: confirmar exige mensaje oficial (lo verán los afectados tal cual). */
function FilaMasivo({
  inc,
  onAccion,
}: {
  inc: IncidenteMasivo;
  onAccion: (ruta: string, cuerpo?: object) => Promise<void>;
}) {
  const [mensaje, setMensaje] = useState("");
  const idMensaje = `mensaje-${inc.id}`;
  const r = inc.regla ?? {};
  return (
    <Card className={inc.estado === "propuesto" ? "border-l-4 border-l-warning shadow-sm" : "shadow-sm"}>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="font-mono text-sm font-semibold">{inc.id}</CardTitle>
          <Badge variant={inc.estado === "propuesto" ? "default" : "secondary"}>{inc.estado}</Badge>
          <Badge variant="outline">{inc.origen}</Badge>
          <span className="text-xs text-muted-foreground">{inc.casos_vinculados} caso(s) vinculado(s)</span>
        </div>
        <CardDescription className="text-base text-foreground">{inc.titulo}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {r.usuarios_distintos !== undefined && (
          <p className="rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs text-muted-foreground">
            Regla: {r.usuarios_distintos} usuarios distintos (k = {r.k}) con similitud ≥ {r.umbral} en {r.ventana_min} min
            {r.similitud_max !== undefined && ` · máx. ${r.similitud_max}`}.
          </p>
        )}
        {inc.mensaje_oficial && (
          <blockquote className="border-l-2 border-warning pl-2">
            «{inc.mensaje_oficial}»
            {inc.publicado_en && <span className="block text-xs text-muted-foreground">Publicado: {inc.publicado_en}</span>}
          </blockquote>
        )}
        {inc.estado === "propuesto" && (
          <div className="space-y-1">
            <label htmlFor={idMensaje} className="font-medium">
              Mensaje oficial para los afectados (obligatorio para confirmar)
            </label>
            <textarea
              id={idMensaje}
              className="campo"
              rows={2}
              maxLength={500}
              value={mensaje}
              onChange={(e) => setMensaje(e.currentTarget.value)}
              placeholder="Ej.: «Confirmamos una falla general en Teams; trabajamos en ello. Próxima actualización 15:30.»"
            />
          </div>
        )}
      </CardContent>
      {(inc.estado === "propuesto" || inc.estado === "publicado") && (
        <CardFooter className="flex flex-wrap gap-2 border-t bg-muted/30 py-3">
          {inc.estado === "propuesto" && (
            <>
              <Button
                size="sm"
                disabled={mensaje.trim().length < MIN_MENSAJE}
                onClick={() => void onAccion(`/api/n2/masivos/${inc.id}/confirmar`, { mensaje: mensaje.trim() })}
              >
                Confirmar masivo
              </Button>
              <Button size="sm" variant="outline" onClick={() => void onAccion(`/api/n2/masivos/${inc.id}/descartar`)}>
                Descartar
              </Button>
            </>
          )}
          {inc.estado === "publicado" && (
            <Button size="sm" variant="outline" onClick={() => void onAccion(`/api/n2/masivos/${inc.id}/resolver`)}>
              Marcar resuelto y avisar
            </Button>
          )}
        </CardFooter>
      )}
    </Card>
  );
}

export function BandejaMasivos({
  lista,
  onAccion,
}: {
  lista: IncidenteMasivo[] | null;
  onAccion: (ruta: string, cuerpo?: object) => Promise<void>;
}) {
  return (
    <section aria-labelledby="titulo-masivos" className="space-y-3">
      <TituloSeccion id="titulo-masivos" cuenta={lista?.length}>
        <RadioTower className="size-4 text-muted-foreground" aria-hidden /> Posibles masivos e incidentes generales
      </TituloSeccion>
      {lista === null ? (
        <Cargando />
      ) : lista.length === 0 ? (
        <EstadoVacio icono={RadioTower} titulo="No hay incidentes generales activos." className="py-6" />
      ) : (
        lista.map((inc) => <FilaMasivo key={inc.id} inc={inc} onAccion={onAccion} />)
      )}
    </section>
  );
}
