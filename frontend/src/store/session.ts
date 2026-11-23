// This browser tab's edit session: a random ID sent with every request
// (X-Edit-Session), so the server knows which tab holds a project's lock.
// Kept apart from the store so the API client can use it without a cycle.

function randomId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }
}

/** One per tab (per page load): two tabs are two sessions. */
export const EDIT_SESSION = randomId();

type LockLost = (context: Record<string, string>) => void;
let onLockLost: LockLost | null = null;

/** Called by the lock controller (store/lock.ts) while a project is open. */
export function whenLockLost(handler: LockLost | null): void {
  onLockLost = handler;
}

/** The server refused a change: someone else holds the project's lock. */
export function lockLostByServer(context: Record<string, string> = {}): void {
  onLockLost?.(context);
}
