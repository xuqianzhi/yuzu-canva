// A collection's Assets page: named images and videos that every new project
// in the collection starts with, as nodes down the left side of its canvas.
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { api, API_BASE, authedFetch, unwrap } from "../api/client";
import { isValidId, nameKey, normalizeName, toValidId, type CollectionAsset } from "../api/types";
import { errorText, t as tr, useT } from "../i18n";
import type { CollectionView } from "./HomePage";

type GlobalAsset = CollectionAsset;

const ACCEPT = "image/png,image/jpeg,image/webp,video/mp4,video/quicktime";

/** A file being uploaded right now. */
interface Uploading {
  key: number;
  file: File;
  preview: string;
  name: string;
}

let uploadKey = 0;

/** `wanted`, or `wanted 2`, `wanted 3`... whichever is not in `taken`. */
function uniqueName(wanted: string, taken: Set<string>): string {
  let candidate = wanted;
  for (let n = 2; taken.has(nameKey(candidate)); n++) candidate = `${wanted}_${n}`;
  return candidate;
}

export function CollectionAssets({ view }: { view: CollectionView }) {
  const t = useT();
  const collectionId = view.collection.id;
  const [assets, setAssets] = useState<GlobalAsset[] | null>(null);
  const [uploading, setUploading] = useState<Uploading[]>([]);
  const [error, setError] = useState("");
  const [dropping, setDropping] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setAssets(
        unwrap(
          await api.GET("/api/collections/{collection_id}/assets", {
            params: { path: { collection_id: collectionId } },
          }),
        ),
      );
    } catch (e) {
      setAssets((current) => current ?? []);
      setError(tr("ga_load_error", { error: errorText(e) }));
    }
  }, [collectionId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Latest list, for naming files uploaded one after another.
  const assetsRef = useRef(assets);
  assetsRef.current = assets;

  /** Upload each file straight away, named after it (made unique). One at a
      time, so names given within one batch can't clash. */
  const addFiles = async (files: File[]) => {
    const items = files.map((file) => ({
      key: ++uploadKey,
      file,
      preview: URL.createObjectURL(file),
      name: toValidId(file.name.replace(/\.[^.]+$/, "")),
    }));
    setUploading((current) => [...current, ...items]);
    const failures: string[] = [];
    for (const item of items) {
      const taken = new Set((assetsRef.current ?? []).map((a) => nameKey(a.name)));
      const name = uniqueName(item.name.slice(0, 76), taken);
      try {
        const form = new FormData();
        form.append("file", item.file, item.file.name);
        form.append("name", name);
        const url = `${API_BASE}/api/collections/${encodeURIComponent(collectionId)}/assets`;
        const response = await authedFetch(url, {
          method: "POST",
          body: form,
        });
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(body?.error?.message ?? `HTTP ${response.status}`);
        const added = body as GlobalAsset;
        assetsRef.current = [...(assetsRef.current ?? []), added];
        setAssets(assetsRef.current);
      } catch (e) {
        failures.push(`${item.file.name}: ${(e as Error).message}`);
      } finally {
        URL.revokeObjectURL(item.preview);
        setUploading((current) => current.filter((u) => u.key !== item.key));
      }
    }
    setError(failures.length ? tr("upload_failed", { list: failures.join("; ") }) : "");
  };

  const remove = async (asset: GlobalAsset) => {
    const ok = window.confirm(tr("ga_delete_confirm", { name: asset.name }));
    if (!ok) return;
    try {
      unwrap(
        await api.DELETE("/api/collection-assets/{asset_id}", {
          params: { path: { asset_id: asset.id } },
        }),
      );
      setAssets((current) => (current ?? []).filter((a) => a.id !== asset.id));
    } catch (e) {
      setError(tr("delete_failed", { error: errorText(e) }));
    }
  };

  const onDrop = (event: DragEvent) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setDropping(false);
    void addFiles([...event.dataTransfer.files]);
  };

  return (
    <main
      className={`home__page home__globals${dropping ? " home__globals--dropping" : ""}`}
      aria-labelledby="global-assets-title"
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        setDropping(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropping(false);
      }}
      onDrop={onDrop}
    >
      <div className="home__inner">
        <header className="globals__head">
          <div>
            <h1 id="global-assets-title" className="home__title">
              {t("ga_title")}
            </h1>
            <p className="home__help">
              {t("ga_help")}
            </p>
          </div>
          <button className="button button--primary" onClick={() => input.current?.click()}>
            {t("upload")}
          </button>
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            multiple
            hidden
            onChange={(e) => {
              void addFiles([...(e.target.files ?? [])]);
              e.target.value = "";
            }}
          />
        </header>
        {error && (
          <p className="home__error" role="alert">
            {error}
          </p>
        )}
        <ul className="globals__grid" aria-label={t("ga_title")}>
          {assets?.map((asset) => (
            <GlobalCard
              key={asset.id}
              asset={asset}
              taken={assets.filter((a) => a.id !== asset.id).map((a) => nameKey(a.name))}
              onRenamed={(renamed) =>
                setAssets((current) => (current ?? []).map((a) => (a.id === renamed.id ? renamed : a)))
              }
              onDelete={() => void remove(asset)}
            />
          ))}
          {uploading.map((item) => (
            <li key={item.key} className="global-card global-card--uploading" aria-busy="true">
              <Thumb kind={item.file.type.startsWith("video/") ? "video" : "image"} url={item.preview} />
              <span className="global-card__meta">
                <span className="spinner" /> {t("uploading")}
              </span>
            </li>
          ))}
          {assets?.length === 0 && uploading.length === 0 && (
            <li className="globals__empty-item">
              <button className="globals__empty" onClick={() => input.current?.click()}>
                {t("ga_empty")}
              </button>
            </li>
          )}
        </ul>
      </div>
      {dropping && <div className="globals__drop">{t("ga_drop")}</div>}
    </main>
  );
}

function GlobalCard({
  asset,
  taken,
  onRenamed,
  onDelete,
}: {
  asset: GlobalAsset;
  taken: string[];
  onRenamed: (asset: GlobalAsset) => void;
  onDelete: () => void;
}) {
  const t = useT();
  const [name, setName] = useState(asset.name);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setName(asset.name), [asset.name]);

  const save = async () => {
    const cleaned = normalizeName(name);
    if (cleaned === asset.name) return setError(null);
    const problem = !cleaned
      ? t("ga_needs_id")
      : !isValidId(cleaned)
        ? t("id_rule")
        : taken.includes(nameKey(cleaned))
          ? t("id_taken", { id: cleaned })
          : null;
    if (problem) {
      setError(problem);
      setName(asset.name);
      return;
    }
    try {
      const renamed = unwrap(
        await api.PATCH("/api/collection-assets/{asset_id}", {
          params: { path: { asset_id: asset.id } },
          body: { name: cleaned! },
        }),
      );
      setError(null);
      onRenamed(renamed);
    } catch (e) {
      setError(errorText(e));
      setName(asset.name);
    }
  };

  const details =
    asset.kind === "video" && asset.duration_s
      ? t("video_seconds", { n: Math.round(asset.duration_s) })
      : asset.width && asset.height
        ? `${asset.width}×${asset.height}`
        : t(`kind_${asset.kind}`);

  return (
    <li className="global-card">
      <Thumb kind={asset.kind} url={asset.url} />
      <input
        className={`global-card__name${error ? " is-invalid" : ""}`}
        value={name}
        maxLength={80}
        aria-label={t("ga_id_aria")}
        spellCheck={false}
        onChange={(e) => {
          setName(e.target.value);
          setError(null);
        }}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            setName(asset.name);
            setError(null);
            e.currentTarget.blur();
          }
        }}
      />
      {error ? (
        <span className="global-card__error">{error}</span>
      ) : (
        <span className="global-card__meta">{details}</span>
      )}
      <button
        className="global-card__delete"
        onClick={onDelete}
        aria-label={t("ga_delete_aria", { name: asset.name })}
        title={t("ga_delete_title")}
      >
        ×
      </button>
    </li>
  );
}

function Thumb({ kind, url }: { kind: string; url: string }) {
  return (
    <div className="global-card__thumb">
      {kind === "video" ? (
        <video src={`${url}#t=0.1`} muted playsInline preload="metadata" />
      ) : (
        <img src={url} alt="" draggable={false} />
      )}
    </div>
  );
}
