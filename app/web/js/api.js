/*
 * FILE:         app/web/js/api.js
 * WHAT IT DOES: Talks to the backend. Adds the login token to every request and turns
 *               error responses into readable messages.
 * WHERE IT FITS: Phase 10 - every screen calls the API through api().
 *
 * WHERE THE TOKEN LIVES: sessionStorage - it survives a page reload but is deleted when
 * the tab closes, and is never sent anywhere except this server. (A production app might
 * prefer an HttpOnly cookie; the backend never trusts the token's claims anyway - it
 * re-reads the user from the database on every request.)
 */

const TOKEN_KEY = "orbitra.token";

// =============================================================================
// 1. SESSION - the current login token
// =============================================================================
export const session = {
  get token() {
    return sessionStorage.getItem(TOKEN_KEY);
  },
  set(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    sessionStorage.removeItem(TOKEN_KEY);
  },
};

export class ApiError extends Error {
  constructor(status, message, retryAfter) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

// =============================================================================
// 2. api() - one call per request
//    api("/query", {method: "POST", json: {question}})
//    api("/auth/login", {method: "POST", form: {username, password}})
//    api("/admin/documents", {method: "POST", body: formData})   (file upload)
// =============================================================================
export async function api(path, { method = "GET", json, form, body } = {}) {
  const headers = {};
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    body = new URLSearchParams(form); // sent as application/x-www-form-urlencoded
  }

  const response = await fetch(path, { method, headers, body });

  // Token expired / account disabled -> back to the login screen.
  if (response.status === 401 && session.token) {
    session.clear();
    window.dispatchEvent(new Event("auth:expired"));
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(response.status, describe(response, payload),
      Number(response.headers.get("Retry-After")) || null);
  }
  return response.status === 204 ? null : response.json();
}

// Turn FastAPI error bodies into one readable sentence.
function describe(response, payload) {
  if (response.status === 429) {
    const wait = response.headers.get("Retry-After");
    return `Too many requests - please wait ${wait || "a few"} seconds.`;
  }
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
  return `${response.status} ${response.statusText}`;
}
