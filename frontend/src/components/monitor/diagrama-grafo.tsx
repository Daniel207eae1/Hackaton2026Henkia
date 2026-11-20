/**
 * Diagrama del grafo con React Flow. Se carga con `React.lazy` desde la vista del monitor: no pesa en las demás vistas.
 * El estado de cada nodo se muestra con borde, icono Y texto (el color nunca es la única señal).
 */
import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Circle, CircleAlert, CircleCheck, Hourglass, LoaderCircle, type LucideIcon } from "lucide-react";
import { useMemo, useSyncExternalStore } from "react";

import { nombreNodo, posicionNodo, tienePosicion, TEXTO_ESTADO } from "@/components/monitor/nodos";
import { estadoDeNodo, type CasoMonitor, type EstadoNodo, type GrafoMonitor } from "@/lib/monitor";
import { cn } from "@/lib/utils";

type DatosNodo = { etiqueta: string; estado: EstadoNodo; extremo: boolean };
type NodoEtapa = Node<DatosNodo, "etapa">;

const ICONO: Record<EstadoNodo, LucideIcon> = {
  inactivo: Circle,
  activo: LoaderCircle,
  completado: CircleCheck,
  espera: Hourglass,
  error: CircleAlert,
};

const CLASE: Record<EstadoNodo, string> = {
  inactivo: "border-border bg-card text-muted-foreground",
  activo: "border-primary bg-card text-foreground ring-4 ring-primary/30 motion-safe:animate-pulse",
  completado: "border-success bg-success-soft text-foreground",
  espera: "border-warning bg-warning-soft text-foreground ring-4 ring-warning/30",
  error: "border-destructive bg-danger-soft text-foreground",
};

function NodoEtapaVista({ data }: NodeProps<NodoEtapa>) {
  const Icono = ICONO[data.estado];
  return (
    <div
      className={cn(
        "min-w-36 rounded-lg border-2 px-3 py-2 text-xs shadow-sm",
        data.extremo && "min-w-20 rounded-full text-center",
        CLASE[data.estado],
      )}
      data-estado={data.estado}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} className="!opacity-0" />
      <div className="font-medium">{data.etiqueta}</div>
      {!data.extremo && (
        <div className="mt-0.5 flex items-center gap-1 text-[0.7rem]">
          <Icono
            className={cn("size-3", data.estado === "activo" && "motion-safe:animate-spin")}
            aria-hidden
          />
          <span>{TEXTO_ESTADO[data.estado]}</span>
        </div>
      )}
      <Handle type="source" position={Position.Right} isConnectable={false} className="!opacity-0" />
    </div>
  );
}

const TIPOS_NODO = { etapa: NodoEtapaVista };

function suscribirMovimiento(avisar: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener?.("change", avisar);
  return () => mq.removeEventListener?.("change", avisar);
}

function menosMovimiento(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function suscribirTema(avisar: () => void): () => void {
  const obs = new MutationObserver(avisar);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => obs.disconnect();
}

function temaOscuro(): boolean {
  return document.documentElement.classList.contains("dark");
}

export default function DiagramaGrafo({ grafo, caso }: { grafo: GrafoMonitor; caso: CasoMonitor | undefined }) {
  const reducido = useSyncExternalStore(suscribirMovimiento, menosMovimiento);
  const oscuro = useSyncExternalStore(suscribirTema, temaOscuro);

  const nodos = useMemo<NodoEtapa[]>(() => {
    let desconocidos = 0;
    return grafo.nodos.map(({ id }) => {
      const pos = posicionNodo(id, tienePosicion(id) ? 0 : desconocidos++);
      return {
        id,
        type: "etapa",
        position: pos,
        data: { etiqueta: nombreNodo(id), estado: estadoDeNodo(caso, id), extremo: id === "__start__" || id === "__end__" },
        draggable: false,
        connectable: false,
        selectable: false,
      };
    });
  }, [grafo, caso]);

  const aristas = useMemo<Edge[]>(() => {
    const orden = new Map<string, number>();
    caso?.recorrido.forEach(([o, d], i) => orden.set(`${o}->${d}`, i + 1));
    const ultima = caso?.recorrido.length ?? 0;
    const vistas = new Set<string>();
    const lista: Edge[] = [];
    for (const a of grafo.aristas) {
      const id = `${a.origen}->${a.destino}`;
      if (vistas.has(id)) continue;
      vistas.add(id);
      const paso = orden.get(id);
      const recorrida = paso !== undefined;
      lista.push({
        id,
        source: a.origen,
        target: a.destino,
        label: recorrida ? String(paso) : undefined,
        animated: recorrida && paso === ultima && !reducido,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: recorrida
          ? { stroke: "var(--primary)", strokeWidth: 2.5 }
          : { stroke: "var(--border)", strokeWidth: 1, strokeDasharray: a.condicional ? "4 4" : undefined },
        zIndex: recorrida ? 1 : 0,
      });
    }
    return lista;
  }, [grafo, caso, reducido]);

  return (
    <div className="h-[460px] w-full overflow-hidden rounded-xl border bg-background">
      <ReactFlow
        nodes={nodos}
        edges={aristas}
        nodeTypes={TIPOS_NODO}
        colorMode={oscuro ? "dark" : "light"}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        minZoom={0.2}
        aria-label="Diagrama del grafo de agentes"
      >
        <Background gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
