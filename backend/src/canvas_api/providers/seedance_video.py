"""Seedance 2.0 video on Volcengine Ark.

Submit a task, poll it, download the video. Mirrors seedance-ui's client:

- References go inline as base64 data URLs (max 10 MiB each): images as
  ``reference_image``, videos as ``reference_video``.
- The prompt names them 图片1, 图片2 ... and 视频1 ... (numbered per kind, in
  reference order); ``@{node}`` mentions are rewritten to those labels.
- Reference images are shrunk to JPEG (long edge <= 1024 px, quality 80)
  before sending, as for every provider (``RefFile.load``). Every reference goes inline with the
  create request, and from outside China the route to Beijing can run at a
  few KB/s, so a request of a couple of MB takes minutes to upload. 1024 px
  is still well above what a 480p or 720p video draws from a reference, and
  keeps Ark's 300 px minimum side for any aspect ratio it accepts (up to
  2.5:1). The node's own file stays full size.
- One Ark request may take up to SEEDANCE_HTTP_TIMEOUT (900 s by default,
  as in seedance-ui), to allow for that slow upload.
- Every task gets a seed (random unless the node sets one). When a create
  request is lost after it was sent (timeout, dropped connection), Ark may
  have created and will bill the task, so it is never blindly resent: recent
  tasks are listed and the one with this seed is picked up. Only when none
  exists does the job fail, and then generating again is safe.
- Requests that never connected are retried; so are GETs.
- Ark can only cancel a task while it is queued; DELETE on a finished task
  deletes its record (and video URL), so status is checked first.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import time
from typing import Any

import httpx

from ..contract import MediaKind, VideoParams
from .base import GenerationRequest, GenerationResult, ProviderError, RefFile, label_mentions
from .media import mp4_info

log = logging.getLogger(__name__)

TASKS_PATH = "/contents/generations/tasks"
MAX_IMAGES = 9
MAX_VIDEOS = 3
MAX_INLINE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
MAX_SEED = 2**32 - 1
# How far back (seconds) to look for a task a lost create request may have
# made, allowing for clock skew between this machine and Ark.
RECOVERY_SLACK_S = 300
RECOVERY_PAGES = 3


class _MaybeCreated(ProviderError):
    """A POST was sent but its answer was lost: the task may exist."""


class SeedanceVideoGenerator:
    # The worker may hand an interrupted job's task id back via resume_task_id.
    resumable = True

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        poll_interval_s: float = 10,
        poll_timeout_s: float = 1800,
        http_timeout_s: float = 900,
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_s: float = 2,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s
        self._timeout = httpx.Timeout(http_timeout_s, connect=15)
        self._transport = transport
        self._backoff_s = backoff_s

    async def run(self, request: GenerationRequest) -> GenerationResult:
        if not self._api_key:
            raise ProviderError("ARK_API_KEY is not set on the backend")
        params = request.params
        if not isinstance(params, VideoParams):
            raise ProviderError(f"expected video params, got {params.kind}")

        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            task_id = request.resume_task_id
            if task_id is None:
                # Encoding references (JPEG, base64) is CPU work: off the loop.
                body = await asyncio.to_thread(self._body, request, params)
                task_id = await self._submit(client, body)
                if request.on_submitted:
                    request.on_submitted(task_id)
            try:
                url = await self._wait(client, task_id)
            except asyncio.CancelledError:
                # Stop paying for it if it has not started; a running task
                # cannot be stopped on Ark's side.
                await asyncio.shield(self._cancel_if_queued(client, task_id))
                raise
            data = await self._download(client, url)

        duration, width, height = mp4_info(data)
        return GenerationResult(
            kind=MediaKind.video,
            data=data,
            mime="video/mp4",
            ext="mp4",
            width=width,
            height=height,
            duration_s=duration,
        )

    # --- request body ----------------------------------------------------------

    def _body(self, request: GenerationRequest, params: VideoParams) -> dict[str, Any]:
        images = [f for f in request.files if f.kind == MediaKind.image]
        videos = [f for f in request.files if f.kind == MediaKind.video]
        if len(images) > MAX_IMAGES:
            raise ProviderError(f"Seedance takes at most {MAX_IMAGES} reference images")
        if len(videos) > MAX_VIDEOS:
            raise ProviderError(f"Seedance takes at most {MAX_VIDEOS} reference videos")

        prompt = label_mentions(request.prompt, images, lambda n: f"图片{n}")
        prompt = label_mentions(prompt, videos, lambda n: f"视频{n}")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content += [_ref_block(f, "image_url", "reference_image") for f in images]
        content += [_ref_block(f, "video_url", "reference_video") for f in videos]

        body: dict[str, Any] = {
            "model": self._model,
            "content": content,
            "resolution": params.resolution,
            "ratio": params.ratio,
            "duration": params.duration_s,
            "generate_audio": params.generate_audio,
            # Explicitly off, so a server-side default can't turn it on.
            "watermark": False,
        }
        # Always set, so a task whose create answer was lost can be found.
        body["seed"] = params.seed if params.seed is not None else secrets.randbelow(MAX_SEED)
        return body

    # --- Ark calls -------------------------------------------------------------

    async def _submit(self, client: httpx.AsyncClient, body: dict[str, Any]) -> str:
        log.info(
            "creating a Seedance task: %.2f MB request", len(json.dumps(body)) / 1024 / 1024
        )
        started = time.time()
        try:
            task = await self._request(client, "POST", TASKS_PATH, json=body)
        except _MaybeCreated as exc:
            found = await self._find_created(client, body, started)
            if found:
                log.info("recovered Seedance task %s after a lost create answer", found)
                return found
            size_mb = len(json.dumps(body)) / 1024 / 1024
            raise ProviderError(
                f"{exc} while sending the request ({size_mb:.1f} MB). Ark has no new task, "
                "so generating again is safe. If this keeps happening, your upload "
                "speed to Ark (Beijing) is too slow for this many or this large inputs."
            ) from exc
        task_id = task.get("id") or task.get("task_id")
        if not task_id:
            raise ProviderError("Seedance did not return a task id")
        return str(task_id)

    async def _find_created(
        self, client: httpx.AsyncClient, body: dict[str, Any], since: float
    ) -> str | None:
        """The task a lost create request made, matched by seed and settings."""
        want = {k: body[k] for k in ("seed", "duration", "ratio", "resolution")}
        try:
            for page in range(1, RECOVERY_PAGES + 1):
                listing = await self._request(
                    client,
                    "GET",
                    f"{TASKS_PATH}?page_num={page}&page_size=50&filter.model={self._model}",
                )
                items = listing.get("items") or []
                for task in items:  # newest first
                    if (task.get("created_at") or 0) < since - RECOVERY_SLACK_S:
                        return None
                    if all(task.get(k) == v for k, v in want.items()) and task.get("id"):
                        return str(task["id"])
                if len(items) < 50:
                    return None
        except ProviderError as exc:
            raise ProviderError(
                "The request to Seedance was lost and checking whether Ark created the "
                f"task failed too ({exc}). Check the Ark console before generating again, "
                "so you don't pay twice."
            ) from exc
        return None

    async def _status(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
        return await self._request(client, "GET", f"{TASKS_PATH}/{task_id}")

    async def _wait(self, client: httpx.AsyncClient, task_id: str) -> str:
        deadline = time.monotonic() + self._poll_timeout_s
        while True:
            task = await self._status(client, task_id)
            status = str(task.get("status") or "unknown").lower()
            if status == "succeeded":
                url = _video_url(task)
                if not url:
                    raise ProviderError(f"Seedance task {task_id} succeeded without a video")
                return url
            if status in ("failed", "cancelled", "canceled", "expired"):
                error = task.get("error") or {}
                detail = error.get("message") if isinstance(error, dict) else str(error)
                raise ProviderError(f"Seedance task {status}: {detail or 'no detail given'}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError(
                    f"Seedance task {task_id} still {status} after "
                    f"{self._poll_timeout_s:.0f}s; it may still finish on Ark"
                )
            await asyncio.sleep(min(self._poll_interval_s, remaining))

    async def _cancel_if_queued(self, client: httpx.AsyncClient, task_id: str) -> None:
        try:
            async with asyncio.timeout(15):
                task = await self._status(client, task_id)
                if str(task.get("status")).lower() == "queued":
                    await self._request(client, "DELETE", f"{TASKS_PATH}/{task_id}")
        except Exception:  # best effort; the job is cancelled either way
            log.warning("could not cancel Seedance task %s", task_id, exc_info=True)

    async def _download(self, client: httpx.AsyncClient, url: str) -> bytes:
        # A pre-signed storage URL: no Ark credentials go with it.
        try:
            async with client.stream("GET", url, timeout=httpx.Timeout(600, connect=15)) as r:
                if r.status_code >= 400:
                    raise ProviderError(f"downloading the video failed: HTTP {r.status_code}")
                chunks, size = [], 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_VIDEO_BYTES:
                        raise ProviderError("the generated video is unexpectedly large")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise ProviderError(f"downloading the video failed: {exc}") from exc

    async def _request(
        self, client: httpx.AsyncClient, method: str, path: str, json: Any = None
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last = attempt == MAX_ATTEMPTS
            try:
                response = await client.request(method, url, headers=headers, json=json)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Never connected, so nothing was sent: safe to retry any method.
                if last:
                    raise ProviderError(f"could not connect to Seedance: {exc}") from exc
            except httpx.TimeoutException as exc:
                if method == "POST":
                    raise _MaybeCreated("Seedance did not answer in time") from exc
                if last:
                    raise ProviderError("Seedance did not answer in time") from exc
            except httpx.HTTPError as exc:
                if method == "POST":
                    raise _MaybeCreated(f"The connection to Seedance dropped ({exc})") from exc
                if last:
                    raise ProviderError(f"could not reach Seedance: {exc}") from exc
            else:
                if response.status_code < 400:
                    return response.json() if response.content else {}
                # A POST that failed with a 5xx may still have created the task,
                # so only a rate limit (definitely not created) is retried.
                retryable = response.status_code in (
                    {429} if method == "POST" else RETRY_STATUSES
                )
                if not retryable or last:
                    raise ProviderError(_error_message(response))
            await asyncio.sleep(self._backoff_s * 2 ** (attempt - 1))
        raise ProviderError("Seedance request failed")  # unreachable


def _ref_block(ref: RefFile, key: str, role: str) -> dict[str, Any]:
    payload = ref.load()
    if len(payload.data) > MAX_INLINE_BYTES:
        raise ProviderError(
            f"a reference {ref.kind.value} is {len(payload.data) / 1024 / 1024:.1f} MiB; "
            f"Seedance accepts at most {MAX_INLINE_BYTES // 1024 // 1024} MiB inline"
        )
    url = f"data:{payload.mime};base64,{base64.b64encode(payload.data).decode('ascii')}"
    return {"type": key, key: {"url": url}, "role": role}


def _video_url(task: dict[str, Any]) -> str | None:
    """Tolerate `content` being an object or a list of parts."""
    content = task.get("content") or task
    parts = content if isinstance(content, list) else [content]
    for part in parts:
        if not isinstance(part, dict):
            continue
        url = part.get("video_url") or part.get("url")
        if isinstance(url, dict):
            url = url.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json()["error"]
        code, message = error.get("code", ""), error.get("message", "")
        return f"Seedance {response.status_code} {code}: {message}".strip()
    except (ValueError, KeyError, TypeError, AttributeError):
        text = response.text[:300] or response.reason_phrase
        return f"Seedance {response.status_code}: {text}"
