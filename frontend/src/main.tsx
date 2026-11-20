import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "@/App";
import { TooltipProvider } from "@/components/ui/tooltip";
import { VerComoProvider } from "@/lib/ver-como";
import "@/index.css";
import { aplicarTema, leerTema } from "@/lib/tema";

// Antes del primer render, para no mostrar un destello del tema equivocado.
aplicarTema(leerTema());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <TooltipProvider>
        <VerComoProvider>
          <App />
        </VerComoProvider>
      </TooltipProvider>
    </BrowserRouter>
  </StrictMode>,
);
