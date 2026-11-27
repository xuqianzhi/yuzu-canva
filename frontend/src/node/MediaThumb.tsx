// A small look at an image or video file: thumbnails, lists and chips.
import type { MediaKind } from "../api/types";

export function MediaThumb({ kind, url }: { kind: MediaKind; url: string }) {
  if (kind === "video") {
    // #t=0.1 makes browsers paint the first frame.
    return <video src={`${url}#t=0.1`} muted playsInline preload="metadata" />;
  }
  return <img src={url} alt="" draggable={false} />;
}
