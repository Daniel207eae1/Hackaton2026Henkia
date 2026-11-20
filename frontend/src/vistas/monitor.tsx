/**
 * Monitor de agentes (ADR 0023): nodos del grafo y agentes en vivo mientras se atiende un caso. Solo N2 y revisor KB.
 * Solo metadatos (nunca el texto de la conversación). El diagrama (React Flow) se carga aparte con `React.lazy`.
 */
import { Pause, Play, Wifi, WifiOff, Workflow, RefreshCw, type LucideIcon } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useReducer, useRef, useState } from "react";

import { LineaTiempo, hora } from "@/components/monitor/linea-tiempo";
import { nombreNodo } from "@/components/monitor/nodos";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Cargando, EncabezadoVista, EstadoVacio } from "@/components/vista";
import { pedir, type Persona } from "@/lib/api";
import {
  conectarMonitor,
  ESTADO_INICIAL,
  reducir,
  type CasoMonitor,
  type EstadoConexion,
  type EstadoMonitor,
  type EventoMonitor,
  type GrafoMonitor,
} from "@/lib/monitor";
import { cn } from "@/lib/utils";

const DiagramaGrafo = lazy(() => import("@/components/monitor/diagrama-grafo"));

const AUTO = "__auto__";
const MAX_PENDIENTES = 2000;

const CONEXION: Record<EstadoConexion, { icono: LucideIcon; texto: string; clase: string }> = {
  conectando: { icono: RefreshCw, texto: "Conectando…", clase: "border-border text-muted-foreground" },
  conectado: { icono: Wifi, texto: "Conectado", clase: "border-success text-success" },
  reconectando: { icono: RefreshCw, texto: "Reconectando…", clase: "border-warning text-warning-foreground" },
  desconectado: { icono: WifiOff, texto: "Desconectado", clase: "border-destructive text-destructive" },
};

function reducirLote(estado: EstadoMonitor, eventos: EventoMonitor[]): EstadoMonitor {
  return eventos.reduce(reducir, estado);
}

export function EstadoConexionVista({ estado, detalle }: { estado: EstadoConexion; detalle?: string }) {
  const c = CONEXION[estado];
  const Icono = c.icono;
  return (
    <span
      role="status"
      className={cn("inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium", c.clase)}
    >
      <Icono className={cn("size-3.5", estado !== "conectado" && estado !== "desconectado" && "motion-safe:animate-spin")} aria-hidden />
      {c.texto}
      {detalle && <span className="font-normal text-muted-foreground">· {detalle}</span>}
    </span>
  );
}

function resumenCaso(caso: CasoMonitor | undefined): string {
  if (!caso) return "Sin actividad todavía.";
  if (caso.errorNodo) return `Error en ${nombreNodo(caso.errorNodo)}.`;
  if (caso.espera) return `En espera humana: ${nombreNodo(caso.espera)}.`;
  if (caso.nodoActivo) return `Nodo activo: ${nombreNodo(caso.nodoActivo)}.`;
  return caso.enCurso ? "Turno en curso." : "Turno terminado.";
}

export function Monitor({ persona }: { persona: Persona }) {
  const [grafo, setGrafo] = useState<GrafoMonitor | null>(null);
  const [errorGrafo, setErrorGrafo] = useState<string | null>(null);
  const [estado, despachar] = useReducer(reducirLote, ESTADO_INICIAL);
  const [conexion, setConexion] = useState<{ estado: EstadoConexion; detalle?: string }>({ estado: "conectando" });
  const [pausado, setPausado] = useState(false);
  const [seleccion, setSeleccion] = useState<string>(AUTO);
  const pausadoRef = useRef(false);
  const pendientes = useRef<EventoMonitor[]>([]);

  useEffect(() => {
    let vigente = true;
    pedir<GrafoMonitor>("/api/monitor/grafo", persona.id)
      .then((g) => vigente && setGrafo(g))
      .catch((e: Error) => vigente && setErrorGrafo(e.message));
    return () => {
      vigente = false;
    };
  }, [persona.id]);

  useEffect(() => {
    const ctrl = new AbortController();
    void conectarMonitor({
      verComo: persona.id,
      senal: ctrl.signal,
      alEvento: (ev) => {
        if (pausadoRef.current) {
          pendientes.current.push(ev);
          if (pendientes.current.length > MAX_PENDIENTES) pendientes.current.shift();
        } else {
          despachar([ev]);
        }
      },
      alEstado: (e, detalle) => setConexion({ estado: e, detalle }),
    });
    return () => ctrl.abort(); // cerrar o cambiar de persona corta la conexión (el chat no se entera)
  }, [persona.id]);

  const alternarPausa = useCallback(() => {
    const nuevo = !pausadoRef.current;
    pausadoRef.current = nuevo;
    setPausado(nuevo);
    if (!nuevo && pendientes.current.length) {
      despachar(pendientes.current);
      pendientes.current = [];
    }
  }, []);

  const casoId = seleccion === AUTO ? estado.orden[0] : seleccion;
  const caso = casoId ? estado.casos[casoId] : undefined;

  return (
    <div className="space-y-4">
      <EncabezadoVista
        titulo="Monitor de agentes"
        icono={Workflow}
        descripcion="Qué nodos del grafo y qué agentes se activan mientras se atiende un caso, en tiempo real. Solo metadatos: nunca el texto de la conversación."
        acciones={
          <>
            <EstadoConexionVista estado={conexion.estado} detalle={conexion.detalle} />
            <Button variant="outline" onClick={alternarPausa} aria-pressed={pausado}>
              {pausado ? <Play aria-hidden /> : <Pause aria-hidden />}
              {pausado ? "Reanudar" : "Pausar"}
            </Button>
          </>
        }
      />

      {pausado && (
        <Alert>
          <AlertDescription>
            Pausado: los eventos nuevos se guardan y se muestran al reanudar.
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="monitor-caso" className="text-sm font-medium">
          Caso
        </label>
        <Select value={seleccion} onValueChange={setSeleccion}>
          <SelectTrigger id="monitor-caso" className="w-full sm:w-80" aria-label="Caso a mostrar">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={AUTO}>Seguir el caso más reciente</SelectItem>
            {estado.orden.map((id) => {
              const c = estado.casos[id];
              return (
                <SelectItem key={id} value={id}>
                  {id.slice(0, 12)}… · {hora(c.ultimoTs)}
                  {c.enCurso ? " · en curso" : ""}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
        <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
          {resumenCaso(caso)}
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-2">
          {errorGrafo ? (
            <Alert variant="destructive">
              <AlertDescription>No pude cargar el grafo: {errorGrafo}</AlertDescription>
            </Alert>
          ) : !grafo ? (
            <Cargando texto="Cargando el grafo…" />
          ) : (
            <Suspense fallback={<Cargando texto="Cargando el diagrama…" />}>
              <DiagramaGrafo grafo={grafo} caso={caso} />
            </Suspense>
          )}
          <Leyenda />
        </div>
        {caso ? (
          <LineaTiempo
            titulo={`Línea de tiempo · ${caso.id.slice(0, 12)}…`}
            entradas={caso.linea}
            vacio="Aún no hay agentes en este caso."
          />
        ) : (
          <EstadoVacio icono={Workflow} titulo="Esperando actividad">
            Abre el chat como colaborador en otra ventana y escribe un problema: aquí verás cada nodo y agente.
          </EstadoVacio>
        )}
      </div>

      <LineaTiempo
        titulo="Procesos de fondo"
        entradas={estado.fondo}
        vacio="Sin procesos de fondo. «Ejecutar lote ahora» en Revisor de KB corre el curador_kb y aparece aquí."
      />
    </div>
  );
}

function Leyenda() {
  const items: { texto: string; clase: string }[] = [
    { texto: "Activo", clase: "border-primary ring-2 ring-primary/30" },
    { texto: "Completado", clase: "border-success bg-success-soft" },
    { texto: "En espera humana", clase: "border-warning bg-warning-soft" },
    { texto: "Error", clase: "border-destructive bg-danger-soft" },
    { texto: "Inactivo", clase: "border-border" },
  ];
  return (
    <ul aria-label="Leyenda de estados" className="flex flex-wrap gap-3 text-xs text-muted-foreground">
      {items.map((i) => (
        <li key={i.texto} className="flex items-center gap-1.5">
          <span aria-hidden className={cn("inline-block size-3 rounded border-2", i.clase)} />
          {i.texto}
        </li>
      ))}
      <li>Las flechas resaltadas y numeradas son el recorrido del turno.</li>
    </ul>
  );
}
