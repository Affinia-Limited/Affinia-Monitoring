import { Suspense, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { LoadingBlock } from "@/components/ui/states";
import { cn } from "@/utils/cn";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

function useIsNarrow(query: string): boolean {
  const [match, setMatch] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const listener = (e: MediaQueryListEvent) => setMatch(e.matches);
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, [query]);
  return match;
}

export function AppLayout() {
  const narrow = useIsNarrow("(max-width: 1023px)");
  const [collapsedPref, setCollapsedPref] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const collapsed = narrow || collapsedPref;

  useEffect(() => setMobileOpen(false), [location.pathname]);

  return (
    <div className="flex h-full min-h-screen">
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 border-r border-border bg-sidebar transition-[width] md:block",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <Sidebar collapsed={collapsed} />
      </aside>
      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        {mobileOpen ? (
          <DialogContent title="Navigation" side="left" className="p-0">
            <Sidebar collapsed={false} />
          </DialogContent>
        ) : null}
      </Dialog>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onToggleSidebar={() => setCollapsedPref((c) => !c)} onOpenMobileNav={() => setMobileOpen(true)} />
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 md:px-8">
          <Suspense fallback={<LoadingBlock label="Loading page" />}>
            <ErrorBoundary resetKey={location.pathname}>
            <Suspense fallback={<LoadingBlock label="Loading page" />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
