import { ReactFlowProvider } from "@xyflow/react";
import { useEffect } from "react";
import { Canvas } from "./canvas/Canvas";
import { ProjectBar } from "./canvas/ProjectBar";
import { HomePage } from "./pages/HomePage";
import { SignInGate } from "./pages/SignIn";
import { homeHref, syncProject, useRoute } from "./router";
import { useCanvas } from "./store/canvas";
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

  return route.page === "home" ? <HomePage tab={route.tab ?? "projects"} /> : <ProjectPage />;
}

function ProjectPage() {
  const t = useT();
  const load = useCanvas((s) => s.load);
  const project = useCanvas((s) => s.project);

  return (
    <ReactFlowProvider>
      <div className="app">
        <ProjectBar />
        {load.status === "ready" && project && <WorkflowBar />}
        <main className="app__main">
          {load.status === "error" ? (
            <div className="app__notice app__notice--error">
              <strong>{t("open_error")}</strong>
              <span>{load.message}</span>
              <a className="button" href={homeHref}>
                {t("back_to_projects")}
              </a>
            </div>
          ) : load.status === "loading" || !project ? (
            <div className="app__notice">{t("loading")}</div>
          ) : (
            <>
              {/* Remount per project so the saved viewport applies. */}
              <Canvas key={project.id} />
              <StepPanel />
              <KeepOpenNotice />
            </>
          )}
        </main>
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
