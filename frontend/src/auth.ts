// Who is signed in, and the token every API request carries.
//
// - With the Firebase web config set (VITE_FIREBASE_*), sign-in is Google
//   through Firebase Auth; requests carry the Firebase ID token, refreshed by
//   the SDK as it nears expiry.
// - Without it, or on the dev server (see USES_FIREBASE), you sign in by
//   typing an email: requests carry "dev:<email>", which only a backend
//   with CANVAS_DEV_AUTH=1 (local only) accepts.
//
// The backend decides who gets in (its allowlist): after signing in, the app
// asks /api/me, and a 403 shows "no access" instead of the app.
import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  getAuth,
  onIdTokenChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
  type Auth,
} from "firebase/auth";
import { create } from "zustand";

const env = import.meta.env;
const firebaseConfig = {
  apiKey: env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  storageBucket: env.VITE_FIREBASE_STORAGE_BUCKET as string | undefined,
  messagingSenderId: env.VITE_FIREBASE_MESSAGING_SENDER_ID as string | undefined,
  appId: env.VITE_FIREBASE_APP_ID as string | undefined,
};

/** Google sign-in through Firebase; otherwise the local dev sign-in. The
    dev server (`npm run dev`) uses the dev sign-in unless
    VITE_FIREBASE_IN_DEV=1, so local work needs no Firebase setup in the
    backend; production builds always use Firebase. */
export const USES_FIREBASE =
  Boolean(firebaseConfig.apiKey) && (!env.DEV || env.VITE_FIREBASE_IN_DEV === "1");

const DEV_KEY = "yuzu-canva.dev-email";

export type AuthState =
  /** Finding out whether a sign-in is remembered. */
  | { status: "loading" }
  | { status: "signed_out"; error?: string }
  /** Signed in; `allowed` once /api/me has said yes (false: no access). */
  | { status: "signed_in"; email: string; allowed: boolean | null };

interface AuthStore {
  state: AuthState;
  signIn(devEmail?: string): Promise<void>;
  signOut(): Promise<void>;
  setAllowed(allowed: boolean): void;
}

let firebaseAuth: Auth | null = null;
let devEmail: string | null = null;

export const useAuth = create<AuthStore>()((set, get) => ({
  state: { status: "loading" },
  async signIn(email) {
    if (firebaseAuth) {
      try {
        await signInWithPopup(firebaseAuth, new GoogleAuthProvider());
      } catch (error) {
        const code = (error as { code?: string }).code ?? "";
        // Closing the popup isn't an error worth showing.
        if (code !== "auth/popup-closed-by-user" && code !== "auth/cancelled-popup-request") {
          set({ state: { status: "signed_out", error: (error as Error).message } });
        }
      }
      return;
    }
    const cleaned = (email ?? "").trim().toLowerCase();
    if (!cleaned.includes("@")) return;
    devEmail = cleaned;
    try {
      localStorage.setItem(DEV_KEY, cleaned);
    } catch {
      // only a convenience
    }
    set({ state: { status: "signed_in", email: cleaned, allowed: null } });
  },
  async signOut() {
    document.title = "Yuzu Canva";
    if (firebaseAuth) {
      await firebaseSignOut(firebaseAuth);
    } else {
      devEmail = null;
      try {
        localStorage.removeItem(DEV_KEY);
      } catch {
        // only a convenience
      }
      set({ state: { status: "signed_out" } });
    }
  },
  setAllowed(allowed) {
    const state = get().state;
    if (state.status === "signed_in") set({ state: { ...state, allowed } });
  },
}));

/** The Authorization header value for an API request, or null if signed out. */
export async function authHeader(): Promise<string | null> {
  if (firebaseAuth) {
    const user = firebaseAuth.currentUser;
    return user ? `Bearer ${await user.getIdToken()}` : null;
  }
  return devEmail ? `Bearer dev:${devEmail}` : null;
}

/** The API said the sign-in is no longer valid: back to the sign-in page. */
export function signedOutByServer(): void {
  const { state } = useAuth.getState();
  if (state.status !== "signed_in") return;
  void useAuth.getState().signOut();
}

/** Start listening for the remembered sign-in (once, before rendering). */
export function startAuth(): void {
  if (USES_FIREBASE) {
    firebaseAuth = getAuth(initializeApp(firebaseConfig));
    onIdTokenChanged(firebaseAuth, (user) => {
      const current = useAuth.getState().state;
      if (!user) {
        useAuth.setState({ state: { status: "signed_out" } });
      } else if (current.status !== "signed_in" || current.email !== user.email) {
        useAuth.setState({
          state: { status: "signed_in", email: user.email ?? "", allowed: null },
        });
      }
    });
    return;
  }
  try {
    devEmail = localStorage.getItem(DEV_KEY);
  } catch {
    devEmail = null;
  }
  useAuth.setState({
    state: devEmail
      ? { status: "signed_in", email: devEmail, allowed: null }
      : { status: "signed_out" },
  });
}
