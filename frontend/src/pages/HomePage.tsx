// The landing pages. A menu down the left (like the one inside a project)
// switches between full-height pages:
// - Collections: every collection you're in, invitations to accept, and a
//   tile to start a new one;
// - inside a collection: its Projects, and what its projects share (Assets,
//   Instruction, Workflows) and Share (members and invites);
// - at the bottom, Settings (language, account, usage).
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, unwrap } from "../api/client";
import type { Collection, CollectionSummary, Invitation, ProjectSummary } from "../api/types";
import {
  collectionHref,
  homeHref,
  projectHref,
  settingsHref,
  syncProject,
  type CollectionTab,
  type Route,
} from "../router";
import { CollectionAssets } from "./CollectionAssets";
import { CollectionInstruction } from "./CollectionInstruction";
import { Settings } from "./Settings";
import { Share } from "./Share";
import { WorkflowDesigner } from "./WorkflowDesigner";
import { errorText, useT, type T } from "../i18n";

type HomeRoute = Exclude<Route, { page: "project" }>;

/** A collection, loaded for its pages; `reload` after changing it. */
export interface CollectionView {
  collection: Collection;
  reload: () => Promise<void>;
}

function useCollection(collectionId: string | null) {
  const [collection, setCollection] = useState<Collection | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    if (!collectionId) return;
    try {
      setCollection(
        unwrap(
          await api.GET("/api/collections/{collection_id}", {
            params: { path: { collection_id: collectionId } },
          }),
        ),
      );
      setError("");
    } catch (e) {
      setError(errorText(e));
    }
  }, [collectionId]);
  useEffect(() => {
    setCollection(null);
    setError("");
    void reload();
  }, [reload]);
  return { collection: collection?.id === collectionId ? collection : null, error, reload };
}

export function HomePage({ route }: { route: HomeRoute }) {
  const t = useT();
  const collectionId = route.page === "collection" ? route.collectionId : null;
  const { collection, error, reload } = useCollection(collectionId);

  useEffect(() => {
    document.title = collection ? `${collection.name} · Yuzu Canva` : "Yuzu Canva";
  }, [collection]);

  let page: React.ReactNode;
  if (route.page === "home") page = <CollectionsPage />;
  else if (route.page === "settings") page = <Settings />;
  else if (error) {
    page = (
      <main className="home__page">
        <div className="home__inner">
          <p className="home__error" role="alert">
            {t("collection_open_error", { error })}
          </p>
          <a className="button" href={homeHref}>
            {t("back_to_collections")}
          </a>
        </div>
      </main>
    );
  } else if (!collection) {
    page = (
      <main className="home__page">
        <p className="home__help">{t("loading")}</p>
      </main>
    );
  } else {
    const view = { collection, reload };
    page = {
      projects: <ProjectsPage view={view} />,
      assets: <CollectionAssets view={view} />,
      instruction: <CollectionInstruction view={view} />,
      workflows: <WorkflowDesigner view={view} />,
      share: <Share view={view} />,
    }[route.tab];
  }

  return (
    <div className="home">
      <header className="topbar">
        <span className="topbar__brand">Yuzu Canva</span>
      </header>
      <div className="home__body">
        <HomeRail route={route} collection={collection} />
        {page}
      </div>
    </div>
  );
}

function HomeRail({ route, collection }: { route: HomeRoute; collection: Collection | null }) {
  const t = useT();
  const item = (
    href: string,
    active: boolean,
    label: string,
    icon: React.ReactNode,
    title = label,
  ) => (
    <a
      key={href}
      className={`rail-button${active ? " is-active" : ""}`}
      href={href}
      aria-current={active ? "page" : undefined}
      title={title}
    >
      <svg viewBox="0 0 20 20" aria-hidden="true">
        {icon}
      </svg>
      {label}
    </a>
  );
  const tab = route.page === "collection" ? route.tab : null;
  const section = (target: CollectionTab, label: string, icon: React.ReactNode, title?: string) =>
    collection && item(collectionHref(collection.id, target), tab === target, label, icon, title);

  return (
    <nav className="sidebar__rail home__rail" aria-label={t("main_menu")}>
      {item(
        homeHref,
        route.page === "home",
        t("nav_collections"),
        <>
          <path d="M3 6.5h14v9a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 15.5z" />
          <path d="M3 6.5V5A1.5 1.5 0 0 1 4.5 3.5h3.5l1.5 1.5H17" />
        </>,
      )}
      {collection && (
        <span className="home__rail-label" title={collection.name}>
          {collection.name}
        </span>
      )}
      {section(
        "projects",
        t("nav_projects"),
        <>
          <rect x="3" y="3" width="6" height="6" rx="1.5" />
          <rect x="11" y="3" width="6" height="6" rx="1.5" />
          <rect x="3" y="11" width="6" height="6" rx="1.5" />
          <rect x="11" y="11" width="6" height="6" rx="1.5" />
        </>,
      )}
      {section(
        "assets",
        t("nav_assets"),
        <>
          <rect x="3" y="4" width="14" height="12" rx="2" />
          <circle cx="7.5" cy="8.5" r="1.4" />
          <path d="m3.5 14 4-4 3 3 2-2 4 4" />
        </>,
        t("nav_assets_hint"),
      )}
      {section(
        "instruction",
        t("nav_instruction"),
        <>
          <path d="M5 2.5h7l3 3v12H5z" />
          <path d="M12 2.5v3h3M7.5 9.5h5M7.5 12.5h5M7.5 15h3" />
        </>,
        t("nav_instruction_hint"),
      )}
      {section(
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
      {section(
        "share",
        t("nav_share"),
        <>
          <circle cx="7.5" cy="7" r="2.5" />
          <path d="M3 16a4.5 4.5 0 0 1 9 0M13 5.5a2.2 2.2 0 1 1 0 4.4M14.5 12.5A4 4 0 0 1 17 16" />
        </>,
        t("nav_share_hint"),
      )}
      <span className="home__rail-spacer" />
      {item(
        settingsHref,
        route.page === "settings",
        t("nav_settings"),
        <>
          <circle cx="10" cy="10" r="2.5" />
          <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
        </>,
      )}
    </nav>
  );
}

// --- collections -------------------------------------------------------------------

function CollectionsPage() {
  const t = useT();
  const [collections, setCollections] = useState<CollectionSummary[] | null>(null);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      await syncProject({ page: "home" });
      const [mine, invited] = await Promise.all([
        api.GET("/api/collections").then(unwrap),
        api.GET("/api/invitations").then(unwrap),
      ]);
      setCollections(mine);
      setInvitations(invited);
      setError("");
    } catch (e) {
      setCollections((current) => current ?? []);
      setError(t("collections_load_error", { error: errorText(e) }));
    }
  }, [t]);

  useEffect(() => void load(), [load]);

  const answer = async (invitation: Invitation, accept: boolean) => {
    try {
      const path = { params: { path: { invite_id: invitation.id } } };
      if (accept) {
        unwrap(await api.POST("/api/invitations/{invite_id}/accept", path));
        location.hash = collectionHref(invitation.collection_id);
      } else {
        unwrap(await api.POST("/api/invitations/{invite_id}/decline", path));
        await load();
      }
    } catch (e) {
      setError(errorText(e));
      await load();
    }
  };

  return (
    <main className="home__page">
      <div className="home__inner">
        <h1 className="home__title">{t("collections_title")}</h1>
        <p className="home__help">{t("collections_help")}</p>
        {error && (
          <p className="home__error" role="alert">
            {error}
          </p>
        )}
        {invitations.length > 0 && (
          <section className="invitations" aria-label={t("invitations_title")}>
            <h2 className="settings__label">{t("invitations_title")}</h2>
            <ul>
              {invitations.map((invitation) => (
                <li key={invitation.id} className="invitation">
                  <span>
                    {t("invitation_text", {
                      who: invitation.invited_by_email,
                      name: invitation.collection_name,
                    })}
                  </span>
                  <span className="take__spacer" />
                  <button
                    className="button button--primary button--small"
                    onClick={() => void answer(invitation, true)}
                  >
                    {t("invitation_accept")}
                  </button>
                  <button
                    className="button button--small"
                    onClick={() => void answer(invitation, false)}
                  >
                    {t("invitation_decline")}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        {collections === null ? (
          <p className="home__help">{t("loading")}</p>
        ) : (
          <ul className="project-grid" aria-label={t("collections_title")}>
            <li className="pj-item">
              <NewCollectionTile onError={setError} />
            </li>
            {collections.map((c) => (
              <li key={c.id} className="pj-item">
                <CollectionCard collection={c} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}

function CollectionCard({ collection: c }: { collection: CollectionSummary }) {
  const t = useT();
  const meta = [t.n("count_project", c.project_count)];
  if (c.member_count > 1) meta.push(t.n("count_member", c.member_count));
  return (
    <a className="pj-card collection-card" href={collectionHref(c.id)}>
      <div className="pj-cover collection-card__cover">
        <svg viewBox="0 0 48 48" aria-hidden="true">
          <path d="M7 15h34v21a3 3 0 0 1-3 3H10a3 3 0 0 1-3-3z" />
          <path d="M7 15v-3a3 3 0 0 1 3-3h9l3 3h16a3 3 0 0 1 3 3" />
        </svg>
        {c.your_role === "editor" && <span className="role-pill">{t("role_editor")}</span>}
      </div>
      <span className="pj-name">{c.name}</span>
      <span className="pj-meta">{meta.join(" · ")}</span>
      <span className="pj-when">
        {c.your_role === "owner" ? t("collection_yours") : t("collection_of", { email: c.owner_email })}
      </span>
    </a>
  );
}

function NewCollectionTile({ onError }: { onError: (message: string) => void }) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const made = unwrap(await api.POST("/api/collections", { body: { name: trimmed } }));
      location.hash = collectionHref(made.id);
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
        <span>{t("new_collection")}</span>
      </button>
    );
  }
  return (
    <form className="pj-new-form" onSubmit={(e) => void submit(e)}>
      <label htmlFor="new-collection-name">{t("collection_name")}</label>
      <input
        id="new-collection-name"
        autoFocus
        maxLength={200}
        placeholder={t("collection_name_placeholder")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setEditing(false);
        }}
      />
      <p className="home__help">{t("new_collection_help")}</p>
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

// --- a collection's projects ---------------------------------------------------------

function ProjectsPage({ view }: { view: CollectionView }) {
  const t = useT();
  const { collection } = view;
  const owner = collection.your_role === "owner";
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      // Finish closing (and saving) a project we just left, so its card
      // shows the latest name and counts. Child effects run before App's,
      // so this also starts that close if it hasn't begun.
      await syncProject({ page: "home" });
      setProjects(
        unwrap(
          await api.GET("/api/collections/{collection_id}/projects", {
            params: { path: { collection_id: collection.id } },
          }),
        ),
      );
      setError("");
    } catch (e) {
      setProjects((current) => current ?? []);
      setError(t("projects_load_error", { error: errorText(e) }));
    }
  }, [t, collection.id]);

  useEffect(() => void load(), [load]);

  const remove = async (project: ProjectSummary) => {
    const media = project.image_count + project.video_count;
    const outputs = media ? t.n("project_delete_outputs", media) : "";
    const editing = project.editing_by
      ? t("project_delete_editing", { email: project.editing_by })
      : "";
    const ok = window.confirm(
      t("project_delete_confirm", { name: project.name, outputs }) + editing,
    );
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

  const removeCollection = async () => {
    const typed = window.prompt(
      t("collection_delete_confirm", { name: collection.name, n: projects?.length ?? 0 }),
    );
    if (typed === null) return;
    if (typed.trim() !== collection.name.trim()) {
      setError(t("collection_delete_mismatch"));
      return;
    }
    try {
      unwrap(
        await api.DELETE("/api/collections/{collection_id}", {
          params: { path: { collection_id: collection.id } },
        }),
      );
      location.hash = homeHref;
    } catch (e) {
      setError(t("delete_failed", { error: errorText(e) }));
    }
  };

  return (
    <main className="home__page">
      <div className="home__inner">
        <div className="collection__head">
          <div>
            <h1 className="home__title">{collection.name}</h1>
            <p className="home__help">
              {owner
                ? t("projects_help")
                : t("projects_help_editor", { email: collection.owner_email })}
            </p>
          </div>
          {owner && (
            <button className="button button--danger-ghost" onClick={() => void removeCollection()}>
              {t("collection_delete")}
            </button>
          )}
        </div>
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
              <NewProjectTile collectionId={collection.id} onError={setError} />
            </li>
            {projects.map((p) => (
              <li key={p.id} className="pj-item">
                <ProjectCard project={p} />
                {owner && (
                  <button
                    className="pj-delete"
                    onClick={() => void remove(p)}
                    aria-label={t("delete_project_aria", { name: p.name })}
                  >
                    {t("delete")}
                  </button>
                )}
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
        {p.editing_by && (
          <span className="role-pill role-pill--editing">
            {t("editing_now", { email: p.editing_by })}
          </span>
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

function NewProjectTile({
  collectionId,
  onError,
}: {
  collectionId: string;
  onError: (message: string) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const project = unwrap(
        await api.POST("/api/collections/{collection_id}/projects", {
          params: { path: { collection_id: collectionId } },
          body: { name: trimmed },
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

export function timeAgo(iso: string, t: T): string {
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
