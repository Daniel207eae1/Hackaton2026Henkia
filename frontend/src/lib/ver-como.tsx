/** Contexto «Ver como» (sin login, solo modo demo). El rol lo decide el backend desde la BD. */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { pedir, type Persona } from "@/lib/api";

const CLAVE = "caso5.verComo";

interface ValorVerComo {
  personas: Persona[];
  persona: Persona | null;
  elegir: (id: string) => void;
  error: string | null;
  cargando: boolean;
}

const Contexto = createContext<ValorVerComo | null>(null);

function leerGuardado(): string | null {
  try {
    return window.localStorage.getItem(CLAVE);
  } catch {
    return null;
  }
}

function guardar(id: string) {
  try {
    window.localStorage.setItem(CLAVE, id);
  } catch {
    /* almacenamiento bloqueado: solo se pierde la preferencia */
  }
}

export function VerComoProvider({ children }: { children: ReactNode }) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [id, setId] = useState<string | null>(leerGuardado);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let vigente = true;
    pedir<Persona[]>("/api/personas", null)
      .then((lista) => {
        if (!vigente) return;
        setPersonas(lista);
        setId((actual) => (actual && lista.some((p) => p.id === actual) ? actual : (lista[0]?.id ?? null)));
      })
      .catch((e: Error) => vigente && setError(e.message))
      .finally(() => vigente && setCargando(false));
    return () => {
      vigente = false;
    };
  }, []);

  const valor = useMemo<ValorVerComo>(
    () => ({
      personas,
      persona: personas.find((p) => p.id === id) ?? null,
      elegir: (nuevo: string) => {
        guardar(nuevo);
        setId(nuevo);
      },
      error,
      cargando,
    }),
    [personas, id, error, cargando],
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useVerComo(): ValorVerComo {
  const v = useContext(Contexto);
  if (!v) throw new Error("useVerComo fuera de VerComoProvider");
  return v;
}
