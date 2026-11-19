import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "@/App";
import { TooltipProvider } from "@/components/ui/tooltip";
import { VerComoProvider } from "@/lib/ver-como";
import "@/index.css";

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
