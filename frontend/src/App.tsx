import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/app-shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Cargando } from "@/components/vista";
import type { Persona, Rol } from "@/lib/api";
import { useVerComo } from "@/lib/ver-como";
import { Auditoria } from "@/vistas/auditoria";
import { BaseConocimiento } from "@/vistas/base-conocimiento";
import { Casos } from "@/vistas/casos";
import { ChatColaborador } from "@/vistas/chat-colaborador";
import { ConsolaN2 } from "@/vistas/consola-n2";
import { Metricas } from "@/vistas/metricas";
import { RevisorKB } from "@/vistas/revisor-kb";

const INICIO: Record<Rol, string> = { colaborador: "/", n2: "/n2", revisor_kb: "/kb" };

/** Guarda de UI por rol. La autorización real la hace el backend con el rol de la BD. */
function ConRol({ roles, persona, children }: { roles: Rol[]; persona: Persona; children: ReactNode }) {
  return roles.includes(persona.rol) ? children : <Navigate to={INICIO[persona.rol]} replace />;
}

export default function App() {
  const { persona, error, cargando } = useVerComo();

  let contenido: ReactNode;
  if (cargando)
    contenido = <Cargando className="py-10" />;
  else if (error || !persona)
    contenido = (
      <Alert variant="destructive">
        <AlertDescription>No pude cargar las personas de «Ver como»: {error ?? "lista vacía"}.</AlertDescription>
      </Alert>
    );
  else
    contenido = (
      <Routes>
        <Route path="/" element={<ConRol roles={["colaborador"]} persona={persona}><ChatColaborador persona={persona} /></ConRol>} />
        <Route path="/n2" element={<ConRol roles={["n2"]} persona={persona}><ConsolaN2 persona={persona} /></ConRol>} />
        <Route
          path="/kb"
          element={
            <ConRol roles={["revisor_kb"]} persona={persona}>
              <RevisorKB persona={persona} />
            </ConRol>
          }
        />
        <Route path="/casos" element={<ConRol roles={["n2"]} persona={persona}><Casos persona={persona} /></ConRol>} />
        <Route
          path="/base-conocimiento"
          element={
            <ConRol roles={["n2", "revisor_kb"]} persona={persona}>
              <BaseConocimiento persona={persona} />
            </ConRol>
          }
        />
        <Route path="/auditoria" element={<ConRol roles={["colaborador", "n2"]} persona={persona}><Auditoria persona={persona} /></ConRol>} />
        <Route
          path="/metricas"
          element={
            <ConRol roles={["n2", "revisor_kb"]} persona={persona}>
              <Metricas persona={persona} />
            </ConRol>
          }
        />
        <Route path="*" element={<Navigate to={INICIO[persona.rol]} replace />} />
      </Routes>
    );

  return <AppShell>{contenido}</AppShell>;
}
