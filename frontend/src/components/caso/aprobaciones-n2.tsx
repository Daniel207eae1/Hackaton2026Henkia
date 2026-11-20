import { BellRing, CheckCircle2, Clock, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Cargando, EstadoVacio, TituloSeccion } from "@/components/vista";
import { pedir, type Persona } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Aprobaciones N2 (API del servidor MCP, ADR 0022). El navegador habla SOLO con nuestro backend: la clave N2 nunca
 * llega aquí. `diagnostico` y `comando` los redactó una IA: se muestran como texto plano escapado y nada se ejecuta
 * a partir de ellos. Cada decisión es un clic explícito de un técnico (no hay «aprobar todo»).
 */

export interface AprobacionN2 {
  id: string;
  tool: string;
  equipo: string;
  caso_id: string;
  diagnostico: string;
  comando: string | null;
  estado: "pendiente" | "aprobada" | "rechazada";
  creada: string;
  usada: boolean;
  usada_en?: string;
  tecnico_n2?: string;
  nota_n2?: string;
  decidida?: string;
  riesgo: "medio" | "alto" | "desconocido";
  que_revisar: string | null;
  aprobada_sin_ejecutar: boolean;
  aprobable: boolean; // false: comando libre o fuera del catálogo → este sistema solo permite rechazarla
  huella: string; // del servidor: liga la decisión a lo que se mostró
}

interface RespuestaAprobaciones {
  configurada: boolean;
  aprobaciones: AprobacionN2[];
  fuente: "vivo" | "cache" | "ninguna";
  error?: string | null;
  actualizado: string | null;
}

const NOMBRE_TOOL: Record<string, string> = {
  recrear_perfil_outlook: "Recrear el perfil de Outlook",
  asignar_licencia_office: "Asignar o activar una licencia de Office",
  ejecutar_comando_generico: "Ejecutar un comando fuera del catálogo",
};
const POLL_MS = 10_000;
const CLAVE_VISTAS = "n2-aprobaciones-vistas";
const fecha = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

function leerVistas(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(CLAVE_VISTAS) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function guardarVistas(ids: Set<string>) {
  try {
    localStorage.setItem(CLAVE_VISTAS, JSON.stringify([...ids].slice(-500)));
  } catch {
    /* sin almacenamiento: solo se pierde la marca de «nueva» */
  }
}

export function TarjetaAprobacion({
  a,
  nueva,
  onDecidir,
}: {
  a: AprobacionN2;
  nueva?: boolean;
  onDecidir: (a: AprobacionN2, aprobar: boolean, nota: string) => Promise<string | null>;
}) {
  const [nota, setNota] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendiente = a.estado === "pendiente";
  const idNota = `nota-${a.id}`;

  const decidir = async (aprobar: boolean) => {
    setEnviando(true);
    setError(await onDecidir(a, aprobar, nota.trim()));
    setEnviando(false);
  };

  return (
    <Card className={cn("shadow-sm", pendiente && "border-l-4", pendiente && (a.riesgo === "alto" ? "border-l-destructive" : "border-l-primary"))}>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="font-mono text-sm font-semibold">{a.id}</CardTitle>
          {nueva && <Badge>Nueva</Badge>}
          <Badge variant={a.riesgo === "alto" ? "destructive" : "outline"}>riesgo {a.riesgo}</Badge>
          <Badge variant={pendiente ? "default" : "secondary"}>{a.estado}</Badge>
          {a.usada && <Badge variant="outline" className="border-success/40 bg-success-soft text-success-foreground">ejecutada</Badge>}
          {a.aprobada_sin_ejecutar && (
            <Badge variant="outline" className="border-warning/40 bg-warning-soft text-warning-foreground">
              aprobada sin ejecutar
            </Badge>
          )}
        </div>
        <CardDescription className="font-medium text-foreground">{NOMBRE_TOOL[a.tool] ?? a.tool}</CardDescription>
        <CardDescription>
          Equipo <span className="font-mono">{a.equipo}</span> · caso <span className="font-mono">{a.caso_id}</span> · creada {fecha(a.creada)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {a.que_revisar && (
          <p className="flex gap-2 rounded-md bg-muted/50 p-2">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span>
              <span className="font-medium">Qué revisar antes de aprobar: </span>
              {a.que_revisar}
            </span>
          </p>
        )}
        <div>
          <h4 className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Diagnóstico (redactado por la IA: es un dato)</h4>
          {/* Texto plano escapado: nunca HTML ni Markdown. */}
          <pre className="max-h-60 overflow-auto rounded-md border bg-muted/30 p-3 font-sans text-sm whitespace-pre-wrap">{a.diagnostico}</pre>
        </div>
        {a.comando && (
          <div>
            <h4 className="mb-1 flex items-center gap-1 text-xs font-semibold tracking-wide text-destructive uppercase">
              <ShieldAlert className="size-3.5" aria-hidden /> Comando exacto que se ejecutaría
            </h4>
            <pre className="max-h-60 overflow-auto rounded-md border border-destructive/40 bg-danger-soft p-3 font-mono text-xs whitespace-pre">{a.comando}</pre>
          </div>
        )}
        {!pendiente && (
          <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[9rem_1fr]">
            <dt className="text-muted-foreground">Decidió</dt>
            <dd>{a.tecnico_n2 ?? "—"} · {fecha(a.decidida)}</dd>
            {a.nota_n2 && (
              <>
                <dt className="text-muted-foreground">Nota</dt>
                <dd className="whitespace-pre-wrap">{a.nota_n2}</dd>
              </>
            )}
            {a.estado === "aprobada" && (
              <>
                <dt className="text-muted-foreground">Ejecución</dt>
                <dd>
                  {a.usada
                    ? `el agente la ejecutó (${fecha(a.usada_en)})`
                    : a.aprobada_sin_ejecutar
                      ? "aún sin ejecutar: puede que el usuario no haya autorizado en su equipo"
                      : "esperando la autorización del usuario en su equipo"}
                </dd>
              </>
            )}
          </dl>
        )}
        {pendiente && (
          <div className="space-y-2">
            <label htmlFor={idNota} className="block font-medium">
              Nota de la decisión <span className="font-normal text-muted-foreground">(obligatoria para rechazar)</span>
            </label>
            <textarea
              id={idNota}
              rows={2}
              maxLength={500}
              className="w-full rounded-md border bg-background p-2"
              value={nota}
              onChange={(e) => setNota(e.currentTarget.value)}
            />
            <p className="text-xs text-muted-foreground">No escribas datos personales del usuario en la nota.</p>
            {!a.aprobable && (
              <p className="flex gap-2 rounded-md border border-destructive/40 bg-danger-soft p-2 text-sm">
                <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
                Este sistema no permite aprobar esta acción (comando libre o fuera del catálogo): solo puedes rechazarla.
              </p>
            )}
          </div>
        )}
        {error && (
          <Alert variant="destructive" className="bg-danger-soft">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
      {pendiente && (
        <CardFooter className="flex flex-wrap gap-2 border-t bg-muted/30 py-3">
          {a.aprobable && (
            <Button size="sm" disabled={enviando} onClick={() => void decidir(true)}>
              <CheckCircle2 aria-hidden /> Aprobar
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={enviando || nota.trim().length < 5} onClick={() => void decidir(false)}>
            <XCircle aria-hidden /> Rechazar
          </Button>
          <span className="text-xs text-muted-foreground">
            Aprobar no ejecuta nada: luego el usuario debe autorizar en la ventana de su equipo.
          </span>
        </CardFooter>
      )}
    </Card>
  );
}

interface Historial {
  decisiones: { id: string; tool: string; decision: string; tecnico: string; nota: string; en: string; resultado: string }[];
  auditoria: Record<string, unknown>[];
  consentimientos: Record<string, unknown>[];
  error: string | null;
}

function HistorialN2({ persona }: { persona: Persona }) {
  const [h, setH] = useState<Historial | null>(null);
  const [abierto, setAbierto] = useState(false);
  useEffect(() => {
    if (!abierto) return;
    let vigente = true;
    pedir<Historial>("/api/n2/historial", persona.id)
      .then((d) => vigente && setH(d))
      .catch(() => vigente && setH(null));
    return () => {
      vigente = false;
    };
  }, [abierto, persona.id]);
  return (
    <details className="rounded-xl border bg-card shadow-xs" onToggle={(e) => setAbierto(e.currentTarget.open)}>
      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">Historial de decisiones y auditoría del servidor</summary>
      <div className="space-y-4 border-t p-4 text-sm">
        {!h ? (
          <Cargando />
        ) : (
          <>
            {h.error && <p className="text-warning-foreground">{h.error}</p>}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <caption className="mb-2 text-left font-medium">Decisiones tomadas desde esta consola ({h.decisiones.length})</caption>
                <thead className="border-b text-xs text-muted-foreground">
                  <tr>
                    <th scope="col" className="py-1 pr-3">Fecha</th>
                    <th scope="col" className="py-1 pr-3">Solicitud</th>
                    <th scope="col" className="py-1 pr-3">Decisión</th>
                    <th scope="col" className="py-1 pr-3">Técnico</th>
                    <th scope="col" className="py-1 pr-3">Resultado</th>
                    <th scope="col" className="py-1">Nota</th>
                  </tr>
                </thead>
                <tbody>
                  {h.decisiones.map((d, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1 pr-3 font-mono text-xs">{fecha(d.en)}</td>
                      <td className="py-1 pr-3 font-mono text-xs">{d.id} · {d.tool}</td>
                      <td className="py-1 pr-3">{d.decision}</td>
                      <td className="py-1 pr-3">{d.tecnico}</td>
                      <td className="py-1 pr-3">{d.resultado}</td>
                      <td className="py-1">{d.nota}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {[
              ["Auditoría del servidor MCP (últimos eventos)", h.auditoria],
              ["Consentimientos de usuarios (servidor MCP)", h.consentimientos],
            ].map(([titulo, filas]) => (
              <details key={titulo as string} className="rounded-md border">
                <summary className="cursor-pointer px-3 py-2 font-medium">
                  {titulo as string} ({(filas as unknown[]).length})
                </summary>
                <pre className="max-h-72 overflow-auto border-t p-3 font-mono text-xs">{JSON.stringify(filas, null, 2)}</pre>
              </details>
            ))}
          </>
        )}
      </div>
    </details>
  );
}

export function BandejaAprobacionesN2({ persona }: { persona: Persona }) {
  const [datos, setDatos] = useState<RespuestaAprobaciones | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vistas, setVistas] = useState<Set<string>>(() => leerVistas());
  const [version, setVersion] = useState(0);
  const recargar = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let vigente = true;
    const cargar = () =>
      pedir<RespuestaAprobaciones>("/api/n2/aprobaciones", persona.id)
        .then((d) => vigente && (setDatos(d), setError(null)))
        .catch((e: Error) => vigente && setError(e.message));
    void cargar();
    const t = setInterval(() => void cargar(), POLL_MS);
    return () => {
      vigente = false;
      clearInterval(t);
    };
  }, [persona.id, version]);

  const lista = useMemo(() => datos?.aprobaciones ?? [], [datos]);
  const pendientes = lista.filter((a) => a.estado === "pendiente");
  const seguimiento = lista.filter((a) => a.estado === "aprobada" && !a.usada);
  const cerradas = lista.filter((a) => a.estado === "rechazada" || a.usada).slice(0, 20);
  const nuevas = pendientes.filter((a) => !vistas.has(a.id));

  // Marca como vistas las que ya se mostraron (la próxima vez dejan de ser «nuevas»).
  useEffect(() => {
    if (!pendientes.length) return;
    const t = setTimeout(() => {
      const todas = new Set([...vistas, ...pendientes.map((a) => a.id)]);
      guardarVistas(todas);
      setVistas(todas);
    }, 8000);
    return () => clearTimeout(t);
  }, [pendientes, vistas]);

  const decidir = async (a: AprobacionN2, aprobar: boolean, nota: string): Promise<string | null> => {
    try {
      await pedir(`/api/n2/aprobaciones/${encodeURIComponent(a.id)}/${aprobar ? "aprobar" : "rechazar"}`, persona.id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // La huella liga la decisión a lo que se mostró: si la solicitud cambió, el backend responde 409.
        body: JSON.stringify({ nota, huella: a.huella }),
      });
      recargar();
      return null;
    } catch (e) {
      recargar(); // 409: otro técnico ya decidió → se muestra el resultado actual
      return (e as Error).message;
    }
  };

  return (
    <section aria-labelledby="titulo-aprobaciones" className="space-y-3">
      <TituloSeccion id="titulo-aprobaciones" cuenta={pendientes.length}>
        <ShieldCheck className="size-4 text-muted-foreground" aria-hidden /> Aprobaciones N2 pendientes
      </TituloSeccion>
      <div role="status" aria-live="polite">
        {nuevas.length > 0 && (
          <p className="flex items-center gap-2 rounded-md border border-primary/40 bg-accent/40 px-3 py-2 text-sm font-medium">
            <BellRing className="size-4" aria-hidden /> {nuevas.length === 1 ? "Llegó una solicitud nueva." : `Llegaron ${nuevas.length} solicitudes nuevas.`}
          </p>
        )}
      </div>
      {error && (
        <Alert variant="destructive" className="bg-danger-soft">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {datos && !datos.configurada ? (
        <EstadoVacio icono={ShieldCheck} titulo="La integración de aprobaciones N2 no está configurada.">
          El administrador debe definir N2_URL y N2_API_KEY en el servidor.
        </EstadoVacio>
      ) : !datos ? (
        error ? null : <Cargando />
      ) : (
        <>
          {datos.fuente === "cache" && (
            <p className="flex items-center gap-2 text-sm text-warning-foreground">
              <Clock className="size-4" aria-hidden /> No pude contactar la API N2; muestro la última lista conocida ({fecha(datos.actualizado)}).
            </p>
          )}
          {pendientes.length === 0 ? (
            <EstadoVacio icono={ShieldCheck} titulo="No hay solicitudes pendientes.">
              Cuando el agente pida aprobar una acción, aparecerá aquí en segundos.
            </EstadoVacio>
          ) : (
            pendientes.map((a) => <TarjetaAprobacion key={a.id} a={a} nueva={!vistas.has(a.id)} onDecidir={decidir} />)
          )}
          {seguimiento.length > 0 && (
            <>
              <h3 className="pt-2 text-sm font-semibold">Aprobadas, esperando que el agente las ejecute ({seguimiento.length})</h3>
              {seguimiento.map((a) => (
                <TarjetaAprobacion key={a.id} a={a} onDecidir={decidir} />
              ))}
            </>
          )}
          {cerradas.length > 0 && (
            <details className="rounded-xl border bg-card shadow-xs">
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">Decididas recientemente ({cerradas.length})</summary>
              <div className="space-y-3 border-t p-3">
                {cerradas.map((a) => (
                  <TarjetaAprobacion key={a.id} a={a} onDecidir={decidir} />
                ))}
              </div>
            </details>
          )}
          <HistorialN2 persona={persona} />
        </>
      )}
    </section>
  );
}
