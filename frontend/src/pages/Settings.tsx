// The Settings page: the language of the UI and of every prompt the backend
// writes for the models; your account, and what you pay for today (all that
// was generated in your collections, by you or your editors); for admins,
// which collections have no daily limit.
import { useCallback, useEffect, useState } from "react";
import { api, unwrap } from "../api/client";
import type { CollectionSummary, Me } from "../api/types";
import { useAuth } from "../auth";
import { errorText, LANGUAGES, useLanguage, useT } from "../i18n";
import { homeHref } from "../router";

export function Settings() {
  const t = useT();
  return (
    <main className="home__page">
      <div className="home__inner">
        <h1 className="home__title">{t("settings_title")}</h1>
        <section className="settings__row">
          <div>
            <h2 className="settings__label">{t("language")}</h2>
            <p className="home__help">{t("settings_language_help")}</p>
          </div>
          <LanguagePicker />
        </section>
        <Account />
      </div>
    </main>
  );
}

/** Who you're signed in as, today's usage against the limits, sign out. */
function Account() {
  const t = useT();
  const signOut = useAuth((s) => s.signOut);
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    let live = true;
    void api.GET("/api/me").then((result) => {
      if (live && result.data) setMe(result.data);
    });
    return () => {
      live = false;
    };
  }, []);

  const count = (kind: keyof Me["used_today"]) => {
    if (!me) return "…";
    const used = me.used_today[kind];
    const limit = me.daily_limits[kind];
    return limit ? t("usage_of", { used, limit }) : t("usage_unlimited", { used });
  };

  return (
    <>
      <section className="settings__row">
        <div>
          <h2 className="settings__label">{t("account")}</h2>
          <p className="home__help">{me ? t("account_help", { email: me.email }) : t("loading")}</p>
        </div>
        <button
          className="button"
          onClick={() => {
            location.hash = homeHref;
            void signOut();
          }}
        >
          {t("sign_out")}
        </button>
      </section>
      <section className="settings__row">
        <div>
          <h2 className="settings__label">{t("usage_title")}</h2>
          <p className="home__help">{t("usage_help")}</p>
        </div>
        <dl className="settings__usage">
          <dt>{t("usage_text")}</dt>
          <dd>{count("text")}</dd>
          <dt>{t("usage_image")}</dt>
          <dd>{count("image")}</dd>
          <dt>{t("usage_video")}</dt>
          <dd>{count("video")}</dd>
        </dl>
      </section>
      {me?.admin && <DailyLimits />}
      {me && me.breakdown.length > 0 && (
        <section className="settings__row settings__row--stack">
          <h2 className="settings__label">{t("usage_breakdown")}</h2>
          <table className="usage-table">
            <thead>
              <tr>
                <th>{t("usage_collection")}</th>
                <th>{t("usage_who")}</th>
                <th>{t("usage_image")}</th>
                <th>{t("usage_video")}</th>
                <th>{t("usage_text")}</th>
              </tr>
            </thead>
            <tbody>
              {me.breakdown.map((line, i) => (
                <tr key={i}>
                  <td>{line.collection_name ?? t("usage_deleted_collection")}</td>
                  <td>{line.email === me.email ? t("share_you") : (line.email ?? "—")}</td>
                  <td>{line.used.image}</td>
                  <td>{line.used.video}</td>
                  <td>{line.used.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}

/** Admins only: lift the daily limits for what's generated in a collection.
    Saved at once (with the collection's version). */
function DailyLimits() {
  const t = useT();
  const [collections, setCollections] = useState<CollectionSummary[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setCollections(unwrap(await api.GET("/api/collections")));
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => void load(), [load]);

  const save = async (collection: CollectionSummary, no_daily_limit: boolean) => {
    setBusy(true);
    setError("");
    try {
      unwrap(
        await api.PATCH("/api/collections/{collection_id}", {
          params: { path: { collection_id: collection.id } },
          body: { version: collection.version, no_daily_limit },
        }),
      );
    } catch (e) {
      setError(t("save_error", { error: errorText(e) }));
    }
    await load();
    setBusy(false);
  };

  return (
    <section className="settings__row settings__row--stack" aria-label={t("limit_title")}>
      <div>
        <h2 className="settings__label">{t("limit_title")}</h2>
        <p className="home__help">{t("no_daily_limit_help")}</p>
      </div>
      {collections === null ? (
        !error && <p className="home__help">{t("loading")}</p>
      ) : collections.length === 0 ? (
        <p className="home__help">{t("limit_no_collections")}</p>
      ) : (
        collections.map((c) => (
          <label className="panel__switch" key={c.id}>
            <input
              type="checkbox"
              role="switch"
              checked={c.no_daily_limit}
              disabled={busy}
              onChange={(e) => void save(c, e.target.checked)}
            />
            <span>{c.name}</span>
          </label>
        ))
      )}
      {error && (
        <p className="home__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** English / 中文. Remembered (on the backend) until changed. */
function LanguagePicker() {
  const t = useT();
  const language = useLanguage((s) => s.language);
  const setLanguage = useLanguage((s) => s.setLanguage);
  return (
    <div className="lang-picker" role="radiogroup" aria-label={t("language")}>
      {LANGUAGES.map((option) => (
        <button
          key={option.code}
          role="radio"
          aria-checked={language === option.code}
          className={language === option.code ? "is-active" : ""}
          onClick={() => setLanguage(option.code)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
