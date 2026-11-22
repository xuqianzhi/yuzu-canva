// The landing page's Settings page: app-wide settings. For now, the
// language of the UI and of every prompt the backend writes for the models.
import { LANGUAGES, useLanguage, useT } from "../i18n";

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
      </div>
    </main>
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
