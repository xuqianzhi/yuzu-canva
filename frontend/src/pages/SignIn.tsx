// Signing in, and the gate in front of the app: nothing else renders (or
// calls the API) until the backend has said this account may use it.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, unwrap } from "../api/client";
import { useAuth, USES_FIREBASE } from "../auth";
import { errorText, useT } from "../i18n";

export function SignInGate({ children }: { children: ReactNode }) {
  const t = useT();
  const state = useAuth((s) => s.state);
  const setAllowed = useAuth((s) => s.setAllowed);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const email = state.status === "signed_in" ? state.email : null;
  const allowed = state.status === "signed_in" ? state.allowed : null;

  useEffect(() => {
    if (email === null || allowed !== null) return;
    let live = true;
    setError("");
    void (async () => {
      try {
        unwrap(await api.GET("/api/me"));
        if (live) setAllowed(true);
      } catch (e) {
        if (!live) return;
        if (e instanceof ApiError && e.status === 403) setAllowed(false);
        else if (!(e instanceof ApiError && e.status === 401)) setError(errorText(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [email, allowed, attempt, setAllowed]);

  if (state.status === "loading") return <Centered>{t("loading")}</Centered>;
  if (state.status === "signed_out") return <SignInPage error={state.error} />;
  if (state.allowed === true) return <>{children}</>;
  if (state.allowed === false) return <NoAccess email={state.email} />;
  return (
    <Centered>
      {error ? (
        <>
          <p className="signin__error" role="alert">
            {error}
          </p>
          <button className="button" onClick={() => setAttempt((n) => n + 1)}>
            {t("try_again")}
          </button>
        </>
      ) : (
        t("loading")
      )}
    </Centered>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <main className="signin">
      <div className="signin__card">{children}</div>
    </main>
  );
}

function SignInPage({ error }: { error?: string }) {
  const t = useT();
  const signIn = useAuth((s) => s.signIn);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    await signIn(email);
    setBusy(false);
  };

  return (
    <Centered>
      <h1 className="signin__brand">Yuzu Canva</h1>
      <p className="signin__help">{t("signin_help")}</p>
      {USES_FIREBASE ? (
        <button
          className="button button--primary signin__google"
          disabled={busy}
          onClick={() => void submit()}
        >
          {t("signin_google")}
        </button>
      ) : (
        <form className="signin__form" onSubmit={(e) => void submit(e)}>
          <input
            type="email"
            required
            autoFocus
            value={email}
            placeholder={t("signin_email_ph")}
            aria-label={t("signin_email_ph")}
            onChange={(e) => setEmail(e.target.value)}
          />
          <button className="button button--primary" disabled={busy || !email.includes("@")}>
            {t("signin_dev")}
          </button>
          <small className="signin__note">{t("signin_dev_note")}</small>
        </form>
      )}
      {error && (
        <p className="signin__error" role="alert">
          {error}
        </p>
      )}
    </Centered>
  );
}

function NoAccess({ email }: { email: string }) {
  const t = useT();
  const signOut = useAuth((s) => s.signOut);
  return (
    <Centered>
      <h1 className="signin__brand">{t("noaccess_title")}</h1>
      <p className="signin__help">{t("noaccess_help", { email })}</p>
      <button className="button" onClick={() => void signOut()}>
        {t("sign_out")}
      </button>
    </Centered>
  );
}
