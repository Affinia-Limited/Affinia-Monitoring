import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter } from "react-router-dom";
import { ApiError } from "@/api/client";
import { AuthGate } from "@/AuthGate";
import { TooltipProvider } from "@/components/ui/menu";
import { ToastProvider } from "@/components/ui/toast";
import { AppRoutes } from "@/routes/AppRoutes";
import { FilterProvider } from "@/stores/filters";
import { ThemeProvider } from "@/stores/theme";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // Never retry client errors (401/403/404/422); retry transient failures twice.
        retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      },
    },
  });
}

export function App() {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <TooltipProvider>
          <ToastProvider>
          <BrowserRouter>
            <FilterProvider>
              <AuthGate>
                <AppRoutes />
              </AuthGate>
            </FilterProvider>
          </BrowserRouter>
          </ToastProvider>
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
