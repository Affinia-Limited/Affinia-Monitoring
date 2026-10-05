import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { signOut } from "@/api/auth";

/** Clears every cached API response (protected data) before ending the Entra session. */
export function useSignOut(): () => Promise<void> {
  const qc = useQueryClient();
  return useCallback(async () => {
    await qc.cancelQueries();
    qc.clear();
    await signOut();
  }, [qc]);
}
