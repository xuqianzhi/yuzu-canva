// Typed HTTP client for the canvas API. Paths, params, bodies and responses
// are all checked against the generated contract.
import createClient from "openapi-fetch";
import type { paths } from "./schema";
import type { ErrorResponse } from "./types";

/** The API origin. The dev server will proxy /api, so same-origin by default. */
export const API_BASE = "";

export const api = createClient<paths>({ baseUrl: API_BASE });

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
