// Typed HTTP client for the canvas API. Paths, params, bodies and responses
// are all checked against the generated contract.
import createClient from "openapi-fetch";
import { authHeader, signedOutByServer } from "../auth";
import { EDIT_SESSION, lockLostByServer } from "../store/session";
import type { paths } from "./schema";
import type { ErrorResponse } from "./types";

/** The API origin. The dev server will proxy /api, so same-origin by default. */
export const API_BASE = "";

export const api = createClient<paths>({ baseUrl: API_BASE });

// Every request carries the sign-in and this tab's edit session (see
// store/session.ts); a 401 means the sign-in is gone (back to sign-in), and
// a 409 "project_locked" that someone else now holds the open project.
api.use({
  async onRequest({ request }) {
    const header = await authHeader();
    if (header) request.headers.set("Authorization", header);
    request.headers.set("X-Edit-Session", EDIT_SESSION);
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401) signedOutByServer();
    if (response.status === 409) await noticeLock(response);
    return response;
  },
});

async function noticeLock(response: Response) {
  try {
    const body = (await response.clone().json()) as ErrorResponse;
    if (body.error.code === "project_locked") lockLostByServer(body.error.context);
  } catch {
    // not an error body
  }
}

/** `fetch` with the sign-in, for requests openapi-fetch doesn't make
    (multipart uploads). */
export async function authedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const header = await authHeader();
  if (header) headers.set("Authorization", header);
  headers.set("X-Edit-Session", EDIT_SESSION);
  const response = await fetch(url, { ...init, headers });
  if (response.status === 401) signedOutByServer();
  if (response.status === 409) await noticeLock(response);
  return response;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ErrorResponse,
  ) {
    super(body.error.message);
  }
  get code() {
    return this.body.error.code;
  }
}

/** Unwrap an openapi-fetch result: return data, or throw ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined) {
    throw new ApiError(result.response.status, result.error as ErrorResponse);
  }
  return result.data as T;
}
