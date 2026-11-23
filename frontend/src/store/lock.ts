// The open project's lock: one browser tab at a time may change a project.
//
// - Opening a project takes the lock if it's free (or already this tab's)
//   and renews it every 20 s; it lasts 60 s on the server, so a crashed or
//   sleeping tab lets go within a minute.
// - If someone else holds it (or your own other tab), the project opens
//   view-only: every 5 s the lock is checked and the project reloaded, so you
//   watch their changes arrive; once it's free, "Start editing" takes it.
// - Leaving the project (or closing the tab) releases it right away.
// - Losing it while editing (taken over by your other tab, or a change the
//   server refused) drops this tab to view-only.
import { api, ApiError, unwrap } from "../api/client";
import { authHeader } from "../auth";
import type { ProjectLock } from "../api/types";
import { EDIT_SESSION, whenLockLost } from "./session";
import type { GetState, LockState, SetState } from "./types";

export const RENEW_MS = 20_000;
export const VIEW_POLL_MS = 5_000;

let timer: ReturnType<typeof setInterval> | undefined;
let lockedProject: string | null = null;
// The sign-in, kept for releasing the lock while the page unloads (no time
// to wait for a fresh token then).
let lastAuth: string | null = null;

function viewing(lock: ProjectLock | Record<string, string>): LockState {
  const email = "holder_email" in lock ? (lock.holder_email as string | null) : null;
  const yours = "holder_is_you" in lock ? String(lock.holder_is_you) === "true" : false;
  return { status: "viewing", holderEmail: email ?? null, holderIsYou: yours };
}

/** Ask for the lock. Returns the new lock state. */
async function acquire(projectId: string, takeOver = false): Promise<LockState> {
  lastAuth = await authHeader();
  try {
    const lock = unwrap(
      await api.POST("/api/projects/{project_id}/lock", {
        params: { path: { project_id: projectId } },
        body: { take_over: takeOver },
      }),
    );
    return lock.held ? { status: "editing" } : viewing(lock);
  } catch (error) {
    if (error instanceof ApiError && error.code === "project_locked") {
      return viewing(error.body.error.context);
    }
    throw error;
  }
}

function releaseNow(projectId: string, keepalive = false) {
  const headers: Record<string, string> = { "X-Edit-Session": EDIT_SESSION };
  if (lastAuth) headers.Authorization = lastAuth;
  void fetch(`/api/projects/${encodeURIComponent(projectId)}/lock`, {
    method: "DELETE",
    headers,
    keepalive,
  }).catch(() => {});
}

function onPageHide() {
  if (lockedProject) releaseNow(lockedProject, true);
}

export function createLock(set: SetState, get: GetState) {
  const isOpen = (projectId: string) => get().project?.id === projectId;

  function schedule(projectId: string) {
    clearInterval(timer);
    const editing = get().lock.status === "editing";
    timer = setInterval(() => void tick(projectId), editing ? RENEW_MS : VIEW_POLL_MS);
  }

  function setLock(projectId: string, lock: LockState) {
    if (!isOpen(projectId)) return;
    const changed = get().lock.status !== lock.status;
    set({ lock });
    if (changed) schedule(projectId);
  }

  async function tick(projectId: string) {
    if (!isOpen(projectId)) return;
    if (get().lock.status === "editing") {
      try {
        setLock(projectId, await acquire(projectId));
      } catch {
        // offline: try again next time (the lock lasts a minute)
      }
      return;
    }
    // Viewing: watch the lock, and the other person's changes.
    try {
      const lock = unwrap(
        await api.GET("/api/projects/{project_id}/lock", {
          params: { path: { project_id: projectId } },
        }),
      );
      setLock(projectId, lock.held ? { status: "editing" } : viewing(lock));
    } catch {
      return;
    }
    await get().refreshProject();
  }

  return {
    /** Open: take the lock if possible, then keep it (or keep watching). */
    async start(projectId: string, takeOver = false): Promise<void> {
      lockedProject = projectId;
      whenLockLost((context) => {
        if (isOpen(projectId) && get().lock.status === "editing") {
          setLock(projectId, viewing(context));
        }
      });
      window.addEventListener("pagehide", onPageHide);
      let lock: LockState;
      try {
        lock = await acquire(projectId, takeOver);
      } catch {
        lock = { status: "viewing", holderEmail: null, holderIsYou: false };
      }
      set({ lock });
      schedule(projectId);
    },
    /** Leave: stop renewing and let go. */
    stop(): void {
      clearInterval(timer);
      timer = undefined;
      whenLockLost(null);
      window.removeEventListener("pagehide", onPageHide);
      if (lockedProject && get().lock.status === "editing") releaseNow(lockedProject);
      lockedProject = null;
      set({ lock: { status: "checking" } });
    },
  };
}

export type LockController = ReturnType<typeof createLock>;
