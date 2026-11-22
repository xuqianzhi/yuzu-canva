import { ReactFlowProvider } from "@xyflow/react";
import { useEffect } from "react";
import { Canvas } from "./canvas/Canvas";
import { ProjectBar } from "./canvas/ProjectBar";
import { HomePage } from "./pages/HomePage";
import { homeHref, syncProject, useRoute } from "./router";
import { useCanvas } from "./store/canvas";
import { loadLanguage, useT } from "./i18n";
import { StepPanel } from "./workflow/StepPanel";
import { WorkflowBar } from "./workflow/WorkflowBar";

export function App() {
  const route = useRoute();
  // The last language picked, as the backend remembers it.
  useEffect(() => void loadLanguage(), []);
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
            </>
          )}
        </main>
      </div>
    </ReactFlowProvider>
  );
}
