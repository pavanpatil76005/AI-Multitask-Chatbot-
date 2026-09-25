export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8001";

export class SessionExpiredError extends Error {
  constructor() {
    super("Your session has expired. Please sign in again.");
    this.name = "SessionExpiredError";
  }
}

export async function apiRequest(
  endpoint: string,
  options: RequestInit = {}
) {
  const token =
    typeof window !== "undefined"
      ? localStorage.getItem("access_token")
      : null;

  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${endpoint}`, { ...options, headers });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new Error(`Cannot reach the backend at ${API_URL}. Check that FastAPI is running.`);
  }

  const isSignInRequest = endpoint === "/api/auth/login" || endpoint === "/api/auth/register";
  if (response.status === 401 && !isSignInRequest) {
    // A late response from an old request must not erase a newer login.
    if (typeof window !== "undefined" && localStorage.getItem("access_token") === token) {
      localStorage.removeItem("access_token");
      window.location.replace("/login");
    }
    throw new SessionExpiredError();
  }

  return response;
}

export async function responseError(response: Response, fallback: string): Promise<Error> {
  if (response.status === 404) return new Error(`${fallback}: API route not found. Check the backend URL.`);
  if (response.status >= 500) return new Error(`${fallback}: backend error (HTTP ${response.status}). Check database health and backend logs.`);
  const data = await response.json().catch(() => ({}));
  return new Error(errorDetail(data, `${fallback} (HTTP ${response.status})`));
}

export function errorDetail(data: { detail?: unknown }, fallback: string): string {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map(item => item.msg || "Invalid input").join("; ");
  return fallback;
}
