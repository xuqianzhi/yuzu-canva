// The Settings page: the language of the UI and of every prompt the backend
// writes for the models; your account, and what you pay for today (all that
// was generated in your collections, by you or your editors).
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Me } from "../api/types";
import { useAuth } from "../auth";
import { LANGUAGES, useLanguage, useT } from "../i18n";
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
