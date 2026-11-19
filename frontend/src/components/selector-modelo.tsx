import { Cpu } from "lucide-react";
import { useEffect, useState } from "react";

import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { pedir } from "@/lib/api";

export interface ModeloChat {
  alias: string;
  etiqueta: string;
  proveedor: string;
  id: string;
  capacidades: string[];
  licencia: string;
  disponible: boolean;
  precio_referencia: { entrada_usd_1m: number | null; salida_usd_1m: number | null };
}

const AUTOMATICO = "__cadena__";
const CLAVE = "caso5.modelo";
const NOMBRE_PROVEEDOR: Record<string, string> = {
  huggingface: "Hugging Face",
  openrouter: "OpenRouter",
  ollama: "Local (Ollama)",
};

export function leerModeloGuardado(): string {
  try {
    return window.localStorage.getItem(CLAVE) ?? "";
  } catch {
    return "";
  }
}

function guardar(alias: string) {
  try {
    window.localStorage.setItem(CLAVE, alias);
  } catch {
    /* almacenamiento bloqueado: solo se pierde la preferencia */
  }
}

/**
 * Selector de modelo SOLO para pruebas (modo demo). «Automático» = la cadena configurada por agente.
 * El modelo elegido va primero en la cadena de cada agente que pueda usarlo (el backend valida capacidades).
 */
export function SelectorModelo({ valor, onCambio }: { valor: string; onCambio: (alias: string) => void }) {
  const [modelos, setModelos] = useState<ModeloChat[]>([]);

  useEffect(() => {
    let vigente = true;
    pedir<{ modelos: ModeloChat[] }>("/api/modelos", null)
      .then((r) => vigente && setModelos(r.modelos))
      .catch(() => vigente && setModelos([]));
    return () => {
      vigente = false;
    };
  }, []);

  const proveedores = [...new Set(modelos.map((m) => m.proveedor))];
  const elegir = (v: string) => {
    const alias = v === AUTOMATICO ? "" : v;
    guardar(alias);
    onCambio(alias);
  };

  return (
    <div className="flex items-center gap-1">
      <Cpu className="size-4 text-muted-foreground" aria-hidden />
      <label htmlFor="selector-modelo" className="sr-only">
        Modelo de IA (pruebas)
      </label>
      <Select value={valor || AUTOMATICO} onValueChange={elegir}>
        <SelectTrigger id="selector-modelo" size="sm" className="w-56" title="Modelo de IA (solo pruebas)">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={AUTOMATICO}>Automático (cadena por agente)</SelectItem>
          {proveedores.map((p) => (
            <SelectGroup key={p}>
              <SelectLabel>{NOMBRE_PROVEEDOR[p] ?? p}</SelectLabel>
              {modelos
                .filter((m) => m.proveedor === p)
                .map((m) => (
                  <SelectItem key={m.alias} value={m.alias} disabled={!m.disponible}>
                    {m.etiqueta}
                    {!m.disponible && " · sin clave"}
                    {m.capacidades.includes("vision") && " · visión"}
                  </SelectItem>
                ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
