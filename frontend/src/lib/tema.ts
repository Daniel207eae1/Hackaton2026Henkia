import { useCallback, useEffect, useState } from "react";

/** Preferencia de tema: «sistema» sigue a `prefers-color-scheme`. Solo presentación (localStorage con try/catch). */
export type Tema = "claro" | "oscuro" | "sistema";

const CLAVE = "caso5.tema";
const ORDEN: Tema[] = ["sistema", "claro", "oscuro"];

export function leerTema(): Tema {
  try {
    const v = window.localStorage.getItem(CLAVE);
    return v === "claro" || v === "oscuro" ? v : "sistema";
  } catch {
    return "sistema";
  }
}

function sistemaOscuro(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Aplica la clase `dark` en `<html>` (la usa el `@custom-variant dark` de Tailwind). */
export function aplicarTema(tema: Tema): void {
  const oscuro = tema === "oscuro" || (tema === "sistema" && sistemaOscuro());
  document.documentElement.classList.toggle("dark", oscuro);
}

export function useTema() {
  const [tema, setTema] = useState<Tema>(leerTema);

  useEffect(() => {
    aplicarTema(tema);
    if (tema !== "sistema" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const alCambiar = () => aplicarTema("sistema");
    mq.addEventListener("change", alCambiar);
    return () => mq.removeEventListener("change", alCambiar);
  }, [tema]);

  const siguiente = useCallback(() => {
    setTema((t) => {
      const n = ORDEN[(ORDEN.indexOf(t) + 1) % ORDEN.length];
      try {
        window.localStorage.setItem(CLAVE, n);
      } catch {
        /* almacenamiento bloqueado: el tema vale solo en esta pestaña */
      }
      return n;
    });
  }, []);

  return { tema, siguiente };
}
