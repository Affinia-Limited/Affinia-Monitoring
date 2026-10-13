import { Suspense, useEffect, useRef, useState } from "react";
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

  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => setMobileOpen(false), [location.pathname]);
  // Only the content area scrolls, so a new page starts at its top.
  useEffect(() => {
    // A statement, not an expression: modern browsers return a Promise from scrollTo, and an
    // effect must not return anything but a clean-up function.
    scroller.current?.scrollTo?.({ top: 0 });
  }, [location.pathname]);

  // App shell: exactly the viewport's height (dynamic height, so mobile browser bars cannot push it
  // around) and never scrolling itself. The sidebar and top bar are fixed parts of the shell; only
  // the content area below the top bar scrolls.
  return (
    <div className="flex h-dvh overflow-hidden">
      <aside
        className={cn(
          "hidden h-full shrink-0 overflow-hidden border-r border-sidebar-border bg-sidebar transition-[width] md:block",
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
      <div className="flex h-full min-w-0 flex-1 flex-col">
        <TopBar onToggleSidebar={() => setCollapsedPref((c) => !c)} onOpenMobileNav={() => setMobileOpen(true)} />
        <div ref={scroller} data-testid="content-scroll" className="min-h-0 flex-1 overflow-y-auto">
          <main className="mx-auto w-full max-w-[1600px] px-4 py-6 md:px-8">
            <ErrorBoundary resetKey={location.pathname}>
              <Suspense fallback={<LoadingBlock label="Loading page" />}>
                <Outlet />
              </Suspense>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </div>
  );
}
