// The project's uploaded files (assets) and placing them as nodes.
import { api, API_BASE, authedFetch, unwrap } from "../../api/client";
import { t } from "../../i18n";
import { type Material, type Node } from "../../api/types";
import type { CanvasState, GetState, SetState } from "../types";
import { message } from "../core";
import type { Core } from "../core";

export function mediaActions(
  set: SetState,
  get: GetState,
  core: Core,
): Pick<CanvasState, "uploadFiles" | "deleteMaterial" | "placeMaterial"> {
  const { record, addLocal, apiRestore, deleteNow, refreshLinks } = core;
  return {
  async uploadFiles(files) {
    const project = get().project;
    if (!project || !files.length) return [];
    set((s) => ({ uploading: s.uploading + files.length }));
    const uploaded: Material[] = [];
    const failures: string[] = [];
    await Promise.all(
      files.map(async (file) => {
        try {
          // Multipart: openapi-fetch's JSON client doesn't fit, so plain fetch.
          const form = new FormData();
          form.append("file", file, file.name);
          const response = await authedFetch(
            `${API_BASE}/api/projects/${encodeURIComponent(project.id)}/materials`,
            { method: "POST", body: form },
          );
          const body = await response.json().catch(() => null);
          if (!response.ok) {
            throw new Error(body?.error?.message ?? `HTTP ${response.status}`);
          }
          uploaded.push(body as Material);
        } catch (error) {
          failures.push(`${file.name}: ${message(error)}`);
        } finally {
          set((s) => ({ uploading: s.uploading - 1 }));
        }
      }),
    );
    if (get().project?.id === project.id && uploaded.length) {
      set((s) => ({ materials: [...uploaded.reverse(), ...s.materials] }));
    }
    if (failures.length) get().showNotice(t("upload_failed", { list: failures.join("; ") }));
    return uploaded;
  },

  async deleteMaterial(materialId) {
    const before = get().materials;
    set({ materials: before.filter((m) => m.id !== materialId) });
    try {
      unwrap(
        await api.DELETE("/api/materials/{material_id}", {
          params: { path: { material_id: materialId } },
        }),
      );
    } catch (error) {
      set({ materials: before });
      get().showNotice(t("delete_failed", { error: message(error) }));
    }
  },

  async placeMaterial(materialId, position) {
    let node: Node;
    try {
      node = unwrap(
        await api.POST("/api/materials/{material_id}/place", {
          params: { path: { material_id: materialId } },
          body: { position },
        }),
      );
    } catch (error) {
      get().showNotice(t("add_failed", { error: message(error) }));
      return;
    }
    const outputs = unwrap(
      await api.GET("/api/nodes/{node_id}/outputs", { params: { path: { node_id: node.id } } }),
    );
    addLocal([node], [], outputs);
    set((s) => ({
      flowNodes: s.flowNodes.map((n) => ({ ...n, selected: n.id === node.id })),
    }));
    record({
      label: "h_add",
      undo: async () => void (await deleteNow([node.id], [])),
      redo: () => apiRestore([node.id], []),
    });
    await refreshLinks(); // prompts that already name it are now linked
  },
  };
}
