import { History, Search } from "lucide-react";
import { useState, type FormEvent } from "react";

import { DetalleCaso } from "@/components/caso/detalle-caso";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EncabezadoVista, EstadoVacio } from "@/components/vista";
import { pedir, type Persona } from "@/lib/api";

interface EstadoCaso {
  case_id: string;
  etapa: string | null;
  turnos: number;
  estado: { linea_tiempo?: { hora: string; etapa: string; detalle: string }[] } & Record<string, unknown>;
}

/** Auditoría del caso (F0: línea de tiempo y estado crudo; F5 completa hipótesis, acciones y tokens). */
export function Auditoria({ persona }: { persona: Persona }) {
  const [caseId, setCaseId] = useState("");
  const [caso, setCaso] = useState<EstadoCaso | null>(null);
  const [error, setError] = useState<string | null>(null);

  const buscar = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setCaso(null);
    try {
      setCaso(await pedir<EstadoCaso>(`/api/casos/${encodeURIComponent(caseId.trim())}`, persona.id));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-5">
      <EncabezadoVista
        titulo="Auditoría del caso"
        icono={History}
        descripcion="Todo lo que pasó en el caso: diagnóstico, hipótesis, acciones con su autorización, conversación y línea de tiempo."
      />
      <form onSubmit={buscar} className="flex max-w-xl gap-2" role="search">
        <label htmlFor="case-id" className="sr-only">
          Id del caso
        </label>
        <Input
          id="case-id"
          value={caseId}
          onChange={(e) => setCaseId(e.target.value)}
          placeholder="Id del caso"
          className="h-9 bg-card font-mono"
        />
        <Button type="submit" size="lg" disabled={!caseId.trim()}>
          <Search aria-hidden /> Buscar
        </Button>
      </form>
      {error && (
        <Alert variant="destructive" className="bg-danger-soft">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!caso && !error && (
        <EstadoVacio icono={Search} titulo="Busca un caso por su id.">
          El id aparece en el panel lateral del chat («Caso: …»).
        </EstadoVacio>
      )}
      {caso && <DetalleCaso caseId={caso.case_id} estado={caso.estado} />}
    </div>
  );
}
