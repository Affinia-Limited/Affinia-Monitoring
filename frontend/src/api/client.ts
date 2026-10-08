import axios, { type AxiosError } from "axios";
import type { ApiErrorBody } from "@/types/api";
import { env } from "@/utils/env";
import { acquireApiToken, getMsal, ReauthenticationRequiredError, startReauthentication } from "./auth";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: Record<string, unknown> | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.requestId = body.request_id ?? null;
    this.details = body.details ?? null;
  }
}

/** Authenticated by Entra ID but not (or no longer) an active member of the platform. */
export const ACCESS_DENIED_CODES = ["ACCESS_NOT_GRANTED", "ACCESS_SUSPENDED"] as const;

export function isAccessDenied(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 403 && (ACCESS_DENIED_CODES as readonly string[]).includes(error.code);
}

type AccessDeniedListener = (error: ApiError) => void;
const accessDeniedListeners = new Set<AccessDeniedListener>();

/** Notified when any API call reports that access was refused (e.g. the user was suspended mid-session). */
export function onAccessDenied(listener: AccessDeniedListener): () => void {
  accessDeniedListeners.add(listener);
  return () => accessDeniedListeners.delete(listener);
}

export const api = axios.create({ baseURL: env.apiBaseUrl, timeout: 60_000 });

/** The request was not sent (or was refused) because the user is being signed in again. */
export function isReauthenticating(error: unknown): boolean {
  return error instanceof ApiError && error.code === "REAUTHENTICATING";
}

function reauthenticatingError(): ApiError {
  return new ApiError(401, { code: "REAUTHENTICATING", message: new ReauthenticationRequiredError().message });
}

const REAUTH_KEY = "amp.reauth.at";
const REAUTH_INTERVAL_MS = 2 * 60_000;

/**
 * At most one 401-triggered sign-in per interval. If the API still refuses a fresh token (e.g. a
 * misconfigured audience or a tenant that is not allowed), show the error instead of redirecting in a loop.
 */
function claimReauthAttempt(): boolean {
  try {
    const last = Number(window.sessionStorage.getItem(REAUTH_KEY) ?? 0);
    if (Date.now() - last < REAUTH_INTERVAL_MS) return false;
    window.sessionStorage.setItem(REAUTH_KEY, String(Date.now()));
  } catch {
    // Storage unavailable: still allow the attempt; MSAL's own state prevents parallel redirects.
  }
  return true;
}

api.interceptors.request.use(async (config) => {
  try {
    const token = await acquireApiToken();
    if (token) config.headers.set("Authorization", `Bearer ${token}`);
  } catch (error) {
    if (error instanceof ReauthenticationRequiredError) throw reauthenticatingError();
    throw error;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ error?: ApiErrorBody }> | ApiError) => {
    // Raised by the request interceptor: the request was never sent.
    if (error instanceof ApiError) return Promise.reject(error);
    const status = error.response?.status ?? 0;
    const body = error.response?.data?.error;
    // The API no longer accepts the token (expired or revoked session): sign in again once, rather
    // than leaving every view on an error that a reload cannot fix (MSAL would reuse the cached account).
    if (status === 401 && getMsal() && claimReauthAttempt()) {
      startReauthentication();
      return Promise.reject(reauthenticatingError());
    }
    if (body && typeof body.message === "string") {
      const apiError = new ApiError(status, body);
      if (isAccessDenied(apiError)) accessDeniedListeners.forEach((listener) => listener(apiError));
      return Promise.reject(apiError);
    }
    const requestId = (error.response?.headers?.["x-request-id"] as string | undefined) ?? null;
    const message =
      status === 0
        ? "The monitoring API could not be reached."
        : status >= 500
          ? "The server returned an unexpected error."
          : "The request failed.";
    return Promise.reject(
      new ApiError(status, { code: status === 0 ? "NETWORK_ERROR" : "HTTP_ERROR", message, request_id: requestId }),
    );
  },
);

export function errorMessage(error: unknown): { message: string; requestId: string | null; code: string | null } {
  if (error instanceof ApiError) return { message: error.message, requestId: error.requestId, code: error.code };
  return { message: "Something went wrong.", requestId: null, code: null };
}

function clean(params?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!params) return undefined;
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));
}

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const response = await api.get<T>(url, { params: clean(params) });
  return response.data;
}

export async function send<T>(method: "post" | "put" | "patch" | "delete", url: string, body?: unknown): Promise<T> {
  const response = await api.request<T>({ method, url, data: body });
  return response.data;
}
