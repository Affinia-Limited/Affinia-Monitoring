import axios, { type AxiosError } from "axios";
import type { ApiErrorBody } from "@/types/api";
import { env } from "@/utils/env";
import { acquireApiToken } from "./auth";

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

api.interceptors.request.use(async (config) => {
  const token = await acquireApiToken();
  if (token) config.headers.set("Authorization", `Bearer ${token}`);
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ error?: ApiErrorBody }>) => {
    const status = error.response?.status ?? 0;
    const body = error.response?.data?.error;
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
