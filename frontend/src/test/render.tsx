import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/menu";
import { ToastProvider } from "@/components/ui/toast";
import { FilterProvider } from "@/stores/filters";
import { LiveProvider } from "@/stores/live";
import { ThemeProvider } from "@/stores/theme";

export function renderWithProviders(ui: ReactElement, { route = "/", live = false }: { route?: string; live?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <ThemeProvider>
          <TooltipProvider>
            <ToastProvider>
            <MemoryRouter initialEntries={[route]}>
              <LiveProvider initial={live}>
                <FilterProvider>{ui}</FilterProvider>
              </LiveProvider>
            </MemoryRouter>
            </ToastProvider>
          </TooltipProvider>
        </ThemeProvider>
      </QueryClientProvider>,
    ),
  };
}
