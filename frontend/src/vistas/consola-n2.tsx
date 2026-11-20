import { ExternalLink, Headset, Inbox, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Link } from "react-router-dom";

import { BandejaMasivos, type IncidenteMasivo } from "@/components/caso/bandeja-masivos";
import { TablaHipotesis, type HipotesisCaso } from "@/components/caso/detalle-caso";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Cargando, EncabezadoVista, EstadoVacio, TituloSeccion } from "@/components/vista";
import { pedir, type Persona } from "@/lib/api";

interface Ficha {
  motivo: string;
  motivo_texto: string;
  sintoma: Record<string, string | null>;
  contexto_equipo: { equipo: string | null; datos: Record<string, unknown>; consultas_fallidas: string[] };
  acciones: { accion: string; estado: string; consentimiento_id: string | null; aprobacion_id: string | null;
    motivo_fallo: string | null }[];
  banderas_seguridad: string[];
  hipotesis?: HipotesisCaso[];
  siguiente_paso: string;
  ans: { prioridad: string; plazo: string; vence_en: string | null };
  traza_url?: string | null;
}

export interface Escalamiento {
  id: number;
  case_id: string;
  codigo?: string;
  motivo: string;
  estado: "abierto" | "tomado" | "resuelto" | "cerrado";
  asignado_a: string | null;
  completo_sin_repregunta: boolean | null;
  paquete: Ficha;
}

const ETIQUETAS_SINTOMA: Record<string, string> = {
  palabras_del_usuario: "En palabras del usuario",
  aplicacion: "Aplicación",
  tipo_sintoma: "Tipo de síntoma",
  que_ve: "Lo que ve",
  desde_cuando: "Desde cuándo",
};

/** Ficha de diagnóstico §7.2: todo construido desde el estado del caso. Texto siempre escapado (React). */
export function FichaEscalamiento({ ficha }: { ficha: Ficha }) {
  const datos = Object.entries(ficha.contexto_equipo.datos ?? {});
  return (
    <div className="grid gap-3 text-sm md:grid-cols-2 [&>section]:rounded-lg [&>section]:border [&>section]:bg-muted/30 [&>section]:p-3">
      <section>
        <h3 className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">1. Síntoma</h3>
        <dl>
          {Object.entries(ficha.sintoma)
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <div key={k}>
                <dt className="inline text-muted-foreground">{ETIQUETAS_SINTOMA[k] ?? k}: </dt>
                <dd className="inline">{String(v)}</dd>
              </div>
            ))}
        </dl>
      </section>
      <section>
        <h3 className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">2. Contexto del equipo ({ficha.contexto_equipo.equipo ?? "sin equipo"})</h3>
        <ul>
          {datos.map(([k, v]) => (
            <li key={k}>
              <span className="text-muted-foreground">{k}:</span> {String(v)}
            </li>
          ))}
          {ficha.contexto_equipo.consultas_fallidas?.length > 0 && (
            <li className="text-warning-foreground">Consultas fallidas: {ficha.contexto_equipo.consultas_fallidas.join(", ")}</li>
          )}
        </ul>
      </section>
      <section>
        <h3 className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">3–4. Acciones (con autorización y resultado)</h3>
        {ficha.acciones.length === 0 ? (
          <p className="text-muted-foreground">Ninguna acción ejecutada.</p>
        ) : (
          <ul>
            {ficha.acciones.map((a, i) => (
              <li key={i}>
                {a.accion} — <strong>{a.estado}</strong>
                {a.consentimiento_id && ` · consentimiento ${a.consentimiento_id}`}
                {a.aprobacion_id && ` · aprobación ${a.aprobacion_id}`}
                {a.motivo_fallo && <span className="block text-destructive">Fallo: {a.motivo_fallo}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="md:col-span-2">
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Diagnóstico: hipótesis confirmadas, descartadas y por qué
        </h3>
        <TablaHipotesis hipotesis={ficha.hipotesis ?? []} />
      </section>
      <section>
        <h3 className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">5. Banderas de seguridad</h3>
        <p>{ficha.banderas_seguridad.length ? ficha.banderas_seguridad.join(", ") : "Ninguna."}</p>
        <h3 className="mt-3 mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">6. Siguiente paso sugerido</h3>
        <p>{ficha.siguiente_paso}</p>
      </section>
    </div>
  );
}

export function ConsolaN2({ persona }: { persona: Persona }) {
  const [lista, setLista] = useState<Escalamiento[] | null>(null);
  const [masivos, setMasivos] = useState<IncidenteMasivo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const cargar = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let vigente = true;
    Promise.all([
      pedir<Escalamiento[]>("/api/n2/escalamientos", persona.id),
      pedir<IncidenteMasivo[]>("/api/n2/masivos", persona.id),
    ])
      .then(([l, m]) => vigente && (setLista(l), setMasivos(m), setError(null)))
      .catch((e: Error) => vigente && setError(e.message));
    return () => {
      vigente = false;
    };
  }, [persona.id, version]);

  const accion = async (ruta: string, cuerpo?: object) => {
    try {
      await pedir(ruta, persona.id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: cuerpo ? JSON.stringify(cuerpo) : undefined,
      });
      cargar();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="space-y-6">
      <EncabezadoVista
        titulo="Consola N2"
        icono={Headset}
        descripcion="Las aprobaciones de acciones (política aprobacion_n2) se resuelven hoy en el canal del servidor de Zabbix (MCP)."
        acciones={
          <Button variant="outline" size="sm" onClick={() => void cargar()}>
            <RefreshCw aria-hidden /> Actualizar
          </Button>
        }
      />
      {error && (
        <Alert variant="destructive" className="bg-danger-soft">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <BandejaMasivos lista={masivos} onAccion={accion} />
      <section aria-labelledby="titulo-escalamientos" className="space-y-3">
        <TituloSeccion id="titulo-escalamientos" cuenta={lista?.length}>
          <Inbox className="size-4 text-muted-foreground" aria-hidden /> Escalamientos
        </TituloSeccion>
        {lista === null ? (
          <Cargando />
        ) : lista.length === 0 ? (
          <EstadoVacio icono={Inbox} titulo="No hay escalamientos.">
            Cuando el asistente pase un caso a N2, su ficha completa aparecerá aquí.
          </EstadoVacio>
        ) : (
          lista.map((e) => (
            <Card key={e.id} className={e.estado === "abierto" ? "border-l-4 border-l-primary shadow-sm" : "shadow-sm"}>
              <CardHeader>
                <div className="flex flex-wrap items-center gap-2">
                  <CardTitle className="font-mono text-sm font-semibold">{e.codigo ?? e.case_id}</CardTitle>
                  <Badge variant="outline">{e.paquete.motivo_texto}</Badge>
                  <Badge variant={e.estado === "abierto" ? "default" : "secondary"}>{e.estado}</Badge>
                  {e.asignado_a && <span className="text-xs text-muted-foreground">asignado a {e.asignado_a}</span>}
                </div>
                <CardDescription className="font-medium">
                  {e.paquete.ans.prioridad} · {e.paquete.ans.plazo}
                  {e.paquete.ans.vence_en && ` · vence ${e.paquete.ans.vence_en}`}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <FichaEscalamiento ficha={e.paquete} />
              </CardContent>
              <CardFooter className="flex flex-wrap items-center gap-3 border-t bg-muted/30 py-3">
                {e.estado === "abierto" && (
                  <Button size="sm" onClick={() => void accion(`/api/n2/escalamientos/${e.id}/tomar`)}>
                    Tomar el caso
                  </Button>
                )}
                {e.completo_sin_repregunta === null ? (
                  <div role="group" aria-label="¿Podrías continuar sin repreguntar?" className="flex items-center gap-2 text-sm">
                    <span>¿Podrías continuar sin repreguntar?</span>
                    <Button size="sm" variant="outline"
                      onClick={() => void accion(`/api/n2/escalamientos/${e.id}/evaluacion`, { completo: true })}>
                      Sí
                    </Button>
                    <Button size="sm" variant="outline"
                      onClick={() => void accion(`/api/n2/escalamientos/${e.id}/evaluacion`, { completo: false })}>
                      No
                    </Button>
                  </div>
                ) : (
                  <span className="text-sm">Evaluado: {e.completo_sin_repregunta ? "completo, sin repregunta" : "faltó información"}</span>
                )}
                <Link
                  to={`/casos?caso=${encodeURIComponent(e.case_id)}`}
                  className="text-sm font-medium text-primary underline-offset-4 hover:underline"
                >
                  Ver caso completo
                </Link>
                {e.paquete.traza_url && (
                  <a className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline" href={e.paquete.traza_url}
                    target="_blank" rel="noreferrer">
                    Traza en Langfuse <ExternalLink className="size-3" aria-hidden />
                  </a>
                )}
              </CardFooter>
            </Card>
          ))
        )}
      </section>
    </div>
  );
}
