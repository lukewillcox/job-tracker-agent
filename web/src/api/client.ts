/**
 * Typed API client. Mirrors the HTTP API in design.md. The session cookie is
 * sent automatically (httpOnly, Secure, SameSite=Lax), so requests use
 * `credentials: "include"`. Only a slice of endpoints is typed here; the rest
 * are added alongside the pages that use them (tasks 14-16).
 */

export interface Me {
  user_id: string;
  email: string;
  name: string | null;
  status: "active" | "paused" | "needs_reconnect";
}

export interface ApiError {
  status: number;
  message: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "X-Requested-With": "fetch", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const err: ApiError = { status: res.status, message: res.statusText };
    throw err;
  }
  return (await res.json()) as T;
}

export const getMe = () => request<Me>("/api/me");
