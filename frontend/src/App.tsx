import { ReactFlowProvider } from "@xyflow/react";
import { useEffect } from "react";
import { BasicView } from "./basic/BasicView";
import { Canvas } from "./canvas/Canvas";
import { LockBanner } from "./canvas/LockBanner";
import { ProjectBar } from "./canvas/ProjectBar";
import { Sidebar } from "./canvas/Sidebar";
import { HomePage } from "./pages/HomePage";
import { SignInGate } from "./pages/SignIn";
import { collectionHref, homeHref, syncProject, useRoute } from "./router";
import { useCanvas } from "./store/canvas";
import { useShownView } from "./projectView";
import { loadLanguage, useT } from "./i18n";
import { StepPanel } from "./workflow/StepPanel";
import { WorkflowBar } from "./workflow/WorkflowBar";
import { useGenerating, useKeepOpenWarning } from "./workflow/keepOpen";

export function App() {
  return (
    <SignInGate>
      <SignedInApp />
    </SignInGate>
  );
}

function SignedInApp() {
  const route = useRoute();
  // Your last language, as the backend remembers it.
  useEffect(() => void loadLanguage(), []);
  useKeepOpenWarning();
  const projectId = route.page === "project" ? route.projectId : null;

  useEffect(() => {
    void syncProject(projectId ? { page: "project", projectId } : { page: "home" });
  }, [projectId]);

  return route.page === "project" ? <ProjectPage /> : <HomePage route={route} />;
}

function ProjectPage() {
  const t = useT();
  const load = useCanvas((s) => s.load);
  const project = useCanvas((s) => s.project);
  const readOnly = useCanvas((s) => s.lock.status !== "editing");
  const basic = useShownView() === "basic";

  return (
    <ReactFlowProvider>
      <div className="app">
        <ProjectBar />
        {/* The menu runs down the left of all that's under the header. */}
        <div className="app__body">
          {load.status === "ready" && project && (
            <>
              <Sidebar />
              <WorkflowBar />
            </>
          )}
          <main className="app__main">
            {load.status === "error" ? (
              <div className="app__notice app__notice--error">
                <strong>{t("open_error")}</strong>
                <span>{load.message}</span>
                <a className="button" href={project ? collectionHref(project.collection_id) : homeHref}>
                  {t("back_to_projects")}
                </a>
              </div>
            ) : load.status === "loading" || !project ? (
              <div className="app__notice">{t("loading")}</div>
            ) : (
              <>
                <LockBanner />
                {basic ? (
                  // Fences off its own editing controls: moving between steps
                  // stays usable while view-only.
                  <BasicView />
                ) : (
                  // View-only while someone else edits: every control inside
                  // is disabled (the server refuses changes anyway).
                  <fieldset className="readonly-fence" disabled={readOnly}>
                    {/* Remount per project so the saved viewport applies. */}
                    <Canvas key={project.id} />
                    <StepPanel />
                  </fieldset>
                )}
                <Notice />
                <KeepOpenNotice />
              </>
            )}
          </main>
        </div>
      </div>
    </ReactFlowProvider>
  );
}

/** While anything generates, the page must stay open (see keepOpen.ts). */
function KeepOpenNotice() {
  const t = useT();
  const generating = useGenerating();
  if (!generating) return null;
  return (
    <div className="keep-open" role="status">
      <span className="spinner" /> {t("keep_open")}
    </div>
  );
}

/** A passing message about the project (an error, or what Clean up did). */
function Notice() {
  const notice = useCanvas((s) => s.notice);
  if (!notice) return null;
  return (
    <div className={`toast toast--${notice.tone}`} role="status">
      {notice.text}
    </div>
  );
}
