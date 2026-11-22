// The landing page. A menu down the left (like the one inside a project)
// switches between full-height pages: Projects (every project as a card,
// plus a tile to start a new one), and the defaults every new project
// starts with: Global assets, the Global instruction and Workflows; and,
// at the bottom, Settings (the language).
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, unwrap } from "../api/client";
import type { components } from "../api/schema";
import { homeTabHref, projectHref, syncProject, type HomeTab } from "../router";
import { GlobalAssets } from "./GlobalAssets";
import { GlobalInstruction } from "./GlobalInstruction";
import { Settings } from "./Settings";
import { WorkflowDesigner } from "./WorkflowDesigner";
import { errorText, useT, type T } from "../i18n";
import type { WorkflowTemplate } from "../api/types";

type ProjectSummary = components["schemas"]["ProjectSummary"];

export function HomePage({ tab }: { tab: HomeTab }) {
  return (
    <div className="home">
      <header className="topbar">
        <span className="topbar__brand">Seedance Canvas</span>
      </header>
      <div className="home__body">
        <HomeRail tab={tab} />
        {tab === "projects" && <ProjectsPage />}
        {tab === "assets" && <GlobalAssets />}
        {tab === "instruction" && <GlobalInstruction />}
        {tab === "workflows" && <WorkflowDesigner />}
        {tab === "settings" && <Settings />}
      </div>
    </div>
  );
}

function HomeRail({ tab }: { tab: HomeTab }) {
  const t = useT();
  const item = (target: HomeTab, label: string, icon: React.ReactNode, title = label) => (
    <a
      className={`rail-button${tab === target ? " is-active" : ""}`}
      href={homeTabHref(target)}
      aria-current={tab === target ? "page" : undefined}
      title={title}
    >
      <svg viewBox="0 0 20 20" aria-hidden="true">
        {icon}
      </svg>
      {label}
    </a>
  );
  return (
    <nav className="sidebar__rail home__rail" aria-label={t("main_menu")}>
      {item(
        "projects",
        t("nav_projects"),
        <>
          <rect x="3" y="3" width="6" height="6" rx="1.5" />
          <rect x="11" y="3" width="6" height="6" rx="1.5" />
          <rect x="3" y="11" width="6" height="6" rx="1.5" />
          <rect x="11" y="11" width="6" height="6" rx="1.5" />
        </>,
      )}
      <span className="home__rail-label" title={t("nav_defaults_hint")}>
        {t("nav_defaults")}
      </span>
      {item(
        "assets",
        t("nav_assets"),
        <>
          <rect x="3" y="4" width="14" height="12" rx="2" />
          <circle cx="7.5" cy="8.5" r="1.4" />
          <path d="m3.5 14 4-4 3 3 2-2 4 4" />
        </>,
        t("nav_assets_hint"),
      )}
      {item(
        "instruction",
        t("nav_instruction"),
        <>
          <path d="M5 2.5h7l3 3v12H5z" />
          <path d="M12 2.5v3h3M7.5 9.5h5M7.5 12.5h5M7.5 15h3" />
        </>,
        t("nav_instruction_hint"),
      )}
      {item(
        "workflows",
        t("nav_workflows"),
        <>
          <circle cx="4.5" cy="5" r="2" />
          <circle cx="15.5" cy="10" r="2" />
          <circle cx="4.5" cy="15" r="2" />
          <path d="M6.5 5h3a2 2 0 0 1 2 2v1.5a1.5 1.5 0 0 0 1.5 1.5h.5M6.5 15h3a2 2 0 0 0 2-2v-1.5" />
        </>,
        t("nav_workflows_hint"),
      )}
      <span className="home__rail-spacer" />
      {item(
        "settings",
        t("nav_settings"),
        <>
          <circle cx="10" cy="10" r="2.5" />
          <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
        </>,
      )}
    </nav>
  );
}

function ProjectsPage() {
  const t = useT();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      // Finish closing (and saving) a project we just left, so its card
      // shows the latest name and counts. Child effects run before App's,
      // so this also starts that close if it hasn't begun.
      await syncProject({ page: "home" });
      setProjects(unwrap(await api.GET("/api/projects")));
      setError("");
    } catch (e) {
      setProjects((current) => current ?? []);
      setError(t("projects_load_error", { error: errorText(e) }));
    }
  }, [t]);

  useEffect(() => {
    document.title = "Seedance Canvas";
    void load();
  }, [load]);

  const remove = async (project: ProjectSummary) => {
    const media = project.image_count + project.video_count;
    const outputs = media ? t.n("project_delete_outputs", media) : "";
    const ok = window.confirm(t("project_delete_confirm", { name: project.name, outputs }));
    if (!ok) return;
    try {
      unwrap(
        await api.DELETE("/api/projects/{project_id}", {
          params: { path: { project_id: project.id } },
        }),
      );
      await load();
    } catch (e) {
      setError(t("delete_failed", { error: errorText(e) }));
    }
  };

  return (
    <main className="home__page">
      <div className="home__inner">
        <h1 className="home__title">{t("projects_title")}</h1>
        <p className="home__help">{t("projects_help")}</p>
        {error && (
          <p className="home__error" role="alert">
            {error}
          </p>
        )}
        {projects === null ? (
          <p className="home__help">{t("loading")}</p>
        ) : (
          <ul className="project-grid" aria-label={t("projects_title")}>
            <li className="pj-item">
              <NewProjectTile onError={setError} />
            </li>
            {projects.map((p) => (
              <li key={p.id} className="pj-item">
                <ProjectCard project={p} />
                <button
                  className="pj-delete"
                  onClick={() => void remove(p)}
                  aria-label={t("delete_project_aria", { name: p.name })}
                >
                  {t("delete")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}

function ProjectCard({ project: p }: { project: ProjectSummary }) {
  const t = useT();
  const video = useRef<HTMLVideoElement>(null);
  const meta = [t.n("count_node", p.node_count)];
  if (p.image_count) meta.push(t.n("count_image", p.image_count));
  if (p.video_count) meta.push(t.n("count_video", p.video_count));
  if (p.running_count) meta.push(t("count_running", { n: p.running_count }));

  return (
    <a
      className="pj-card"
      href={projectHref(p.id)}
      onMouseEnter={() => void video.current?.play().catch(() => {})}
      onMouseLeave={() => video.current?.pause()}
    >
      <div className="pj-cover">
        {p.cover?.kind === "image" && <img src={p.cover.url} alt="" draggable={false} />}
        {p.cover?.kind === "video" && (
          <video ref={video} src={`${p.cover.url}#t=0.1`} muted loop playsInline preload="metadata" />
        )}
        {!p.cover && (
          <svg viewBox="0 0 48 48" aria-hidden="true">
            <rect x="5" y="9" width="16" height="12" rx="3" />
            <rect x="27" y="27" width="16" height="12" rx="3" />
            <path d="M21 15h6a4 4 0 0 1 4 4v8" />
          </svg>
        )}
      </div>
      <span className="pj-name">{p.name}</span>
      <span className="pj-meta">{meta.join(" · ")}</span>
      <span className="pj-when" title={new Date(p.updated_at).toLocaleString()}>
        {t("edited_when", { when: timeAgo(p.updated_at, t) })}
      </span>
    </a>
  );
}

function NewProjectTile({ onError }: { onError: (message: string) => void }) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  // Which workflow the project copies (the default unless picked).
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [template, setTemplate] = useState<string>("");
  useEffect(() => {
    if (!editing) return;
    void api.GET("/api/workflow-templates").then((r) => {
      const list = r.data ?? [];
      setTemplates(list);
      setTemplate((list.find((w) => w.is_default) ?? list[0])?.id ?? "");
    });
  }, [editing]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const project = unwrap(
        await api.POST("/api/projects", {
          body: { name: trimmed, workflow_template_id: template || null },
        }),
      );
      location.hash = projectHref(project.id);
    } catch (e) {
      onError(t("create_failed", { error: errorText(e) }));
      setBusy(false);
    }
  };

  if (!editing) {
    return (
      <button className="pj-new" onClick={() => setEditing(true)}>
        <span className="pj-new__plus" aria-hidden="true">
          +
        </span>
        <span>{t("new_project")}</span>
      </button>
    );
  }
  return (
    <form className="pj-new-form" onSubmit={(e) => void submit(e)}>
      <label htmlFor="new-project-name">{t("project_name")}</label>
      <input
        id="new-project-name"
        autoFocus
        maxLength={200}
        placeholder={t("project_name_placeholder")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setEditing(false);
        }}
      />
      {templates.length > 1 && (
        <>
          <label htmlFor="new-project-workflow">{t("new_project_workflow")}</label>
          <select
            id="new-project-workflow"
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
          >
            {templates.map((w) => (
              <option key={w.id} value={w.id}>
                {w.definition.name}
              </option>
            ))}
          </select>
        </>
      )}
      <div className="pj-new-form__actions">
        <button className="button button--primary" type="submit" disabled={busy || !name.trim()}>
          {t("create")}
        </button>
        <button className="button" type="button" onClick={() => setEditing(false)}>
          {t("cancel")}
        </button>
      </div>
    </form>
  );
}

function timeAgo(iso: string, t: T): string {
  const seconds = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (seconds < 60) return t("time_just_now");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("time_min", { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("time_hours", { n: hours });
  const days = Math.floor(hours / 24);
  if (days < 30) return t.n("time_days", days);
  return new Date(iso).toLocaleDateString(t.language === "zh" ? "zh-CN" : undefined);
}
