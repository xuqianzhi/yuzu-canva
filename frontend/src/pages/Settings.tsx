// The landing page's Settings page: the language of the UI and of every
// prompt the backend writes for the models; your account and today's usage.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { components } from "../api/schema";
import { useAuth } from "../auth";
import { LANGUAGES, useLanguage, useT } from "../i18n";
import { homeHref } from "../router";

type Me = components["schemas"]["Me"];

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
