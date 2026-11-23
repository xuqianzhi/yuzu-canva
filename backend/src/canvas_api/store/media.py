"""Stored files: materials, uploaded nodes, global assets, outputs.

A project asset's file is "assets/<asset id>.<ext>", a global asset's
"global/<id>.<ext>" (see files.py). Files are written before their rows and
removed again if the row can't be written.
"""

from __future__ import annotations

from pathlib import PurePath

from ..contract import (
    Asset,
    ErrorCode,
    GlobalAsset,
    Material,
    MediaKind,
    Node,
    NodeSource,
    Output,
    Position,
    default_params,
    name_key,
    normalize_name,
)
from ..domain.mentions import (
    ID_RULE,
    is_valid_id,
)
from ..errors import ApiError
from ..files import delete_all
from ..ids import new_id
from .base import (
    Db,
    Row,
    _dt,
    _not_found,
    _ts,
    now,
)


def asset_key(filename: str) -> str:
    return f"assets/{filename}"


def global_key(filename: str) -> str:
    return f"global/{filename}"


def _ext(filename: str) -> str:
    return PurePath(filename).suffix.lstrip(".") or "bin"


class MediaMixin:
    """Stored files: materials, uploaded nodes, global assets, outputs."""

    def _material(self, r: Row) -> Material:
        asset = self._asset(self._one("SELECT * FROM assets WHERE id = ?", r["asset_id"]))
        return Material(
            id=r["id"],
            project_id=r["project_id"],
            name=r["name"],
            asset=asset,
            created_at=_dt(r["created_at"]),
        )

    def _insert_asset(
        self,
        db: Db,
        project_id: str,
        kind: MediaKind,
        mime: str,
        ext: str,
        size: int,
        width: int | None,
        height: int | None,
        duration_s: float | None,
        *,
        data: bytes | None = None,
        copy_from: str | None = None,
    ) -> tuple[str, str]:
        """Store a file (`data`, or a copy of the file `copy_from`) and its
        asset row. Returns (asset id, the file's key)."""
        asset_id = new_id("ast")
        filename = f"{asset_id}.{ext}"
        key = asset_key(filename)
        if copy_from is not None:
            self.files.copy(copy_from, key)
        else:
            self.files.write(key, data or b"", mime)
        db.execute(
            "INSERT INTO assets (id, project_id, kind, mime, filename, bytes, width, "
            "height, duration_s, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                asset_id,
                project_id,
                kind.value,
                mime,
                filename,
                size,
                width,
                height,
                duration_s,
                _ts(now()),
            ),
        )
        return asset_id, key

    def list_materials(self, project_id: str) -> list[Material]:
        self.get_project(project_id)
        rows = self._all(
            "SELECT * FROM materials WHERE project_id = ? ORDER BY created_at DESC, id",
            project_id,
        )
        return [self._material(r) for r in rows]

    def get_material(self, material_id: str) -> Material:
        row = self._one("SELECT * FROM materials WHERE id = ?", material_id)
        if not row:
            raise _not_found("material", material_id)
        return self._material(row)

    def create_material(
        self,
        project_id: str,
        name: str,
        kind: MediaKind,
        data: bytes,
        mime: str,
        ext: str,
        width: int | None = None,
        height: int | None = None,
        duration_s: float | None = None,
    ) -> Material:
        self.get_project(project_id)
        material_id = new_id("mat")
        written: list[str] = []
        try:
            with self._tx() as db:
                asset_id, key = self._insert_asset(
                    db,
                    project_id,
                    kind,
                    mime,
                    ext,
                    len(data),
                    width,
                    height,
                    duration_s,
                    data=data,
                )
                written.append(key)
                db.execute(
                    "INSERT INTO materials (id, project_id, asset_id, name, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (material_id, project_id, asset_id, name, _ts(now())),
                )
        except BaseException:
            delete_all(self.files, written)
            raise
        return self.get_material(material_id)

    def delete_material(self, material_id: str) -> str:
        """Remove it from the library. Nodes placed from it keep their own copy.

        Returns the file to remove.
        """
        material = self.get_material(material_id)
        _, key = self.asset_file(material.asset.id)
        with self._tx() as db:
            db.execute("DELETE FROM assets WHERE id = ?", (material.asset.id,))
        return key

    def _insert_upload_node(
        self,
        db: Db,
        project_id: str,
        kind: MediaKind,
        mime: str,
        ext: str,
        size: int,
        width: int | None,
        height: int | None,
        duration_s: float | None,
        *,
        name: str,
        position: Position,
        data: bytes | None = None,
        copy_from: str | None = None,
    ) -> tuple[str, str]:
        """An uploaded node holding its own copy of the file as its one take,
        already selected. `name` is made unique in the project.

        Returns (node id, the file written), for cleanup if the caller fails.
        """
        node_id, output_id, ts = new_id("nod"), new_id("out"), _ts(now())
        unique = self._unique_name(db, project_id, name[:80], None)
        asset_id, key = self._insert_asset(
            db,
            project_id,
            kind,
            mime,
            ext,
            size,
            width,
            height,
            duration_s,
            data=data,
            copy_from=copy_from,
        )
        db.execute(
            "INSERT INTO nodes (id, project_id, kind, title, position, size, prompt, "
            "params, selected_output_id, created_at, updated_at, source) "
            "VALUES (?, ?, ?, ?, ?, NULL, '', ?, ?, ?, ?, ?)",
            (
                node_id,
                project_id,
                kind.value,
                unique,
                position.model_dump_json(),
                default_params(kind).model_dump_json(),
                output_id,
                ts,
                ts,
                NodeSource.upload.value,
            ),
        )
        db.execute(
            "INSERT INTO outputs (id, node_id, job_id, kind, text, asset_id, "
            "created_at) VALUES (?, ?, NULL, ?, NULL, ?, ?)",
            (output_id, node_id, kind.value, asset_id, ts),
        )
        return node_id, key

    def place_material(self, material_id: str, position: Position) -> Node:
        """Create an uploaded node from a material, with its own copy of the file.

        The node is named after the file (made unique), and its one take is
        the file, already selected, so it can feed other nodes right away.
        """
        material = self.get_material(material_id)
        asset, source = self.asset_file(material.asset.id)
        stem = PurePath(material.name).stem.strip() or asset.kind.value
        written: list[str] = []
        try:
            with self._tx() as db:
                node_id, key = self._insert_upload_node(
                    db,
                    material.project_id,
                    asset.kind,
                    asset.mime,
                    _ext(source),
                    asset.bytes,
                    asset.width,
                    asset.height,
                    asset.duration_s,
                    name=stem,
                    position=position,
                    copy_from=source,
                )
                written.append(key)
                self._touch_project(db, material.project_id)
        except BaseException:
            delete_all(self.files, written)
            raise
        return self.get_node(node_id)

    def _global(self, r: Row) -> GlobalAsset:
        return GlobalAsset(
            id=r["id"],
            name=r["name"],
            kind=r["kind"],
            mime=r["mime"],
            url=self.signer.url("global-assets", r["id"]),
            bytes=r["bytes"],
            width=r["width"],
            height=r["height"],
            duration_s=r["duration_s"],
            created_at=_dt(r["created_at"]),
        )

    def list_global_assets(self, owner: str) -> list[GlobalAsset]:
        rows = self._all(
            "SELECT * FROM global_assets WHERE owner_id = ? ORDER BY created_at, id", owner
        )
        return [self._global(r) for r in rows]

    def get_global_asset(self, asset_id: str) -> GlobalAsset:
        row = self._one("SELECT * FROM global_assets WHERE id = ?", asset_id)
        if not row:
            raise _not_found("global asset", asset_id)
        return self._global(row)

    def global_asset_file(self, asset_id: str) -> tuple[GlobalAsset, str]:
        row = self._one("SELECT * FROM global_assets WHERE id = ?", asset_id)
        if not row:
            raise _not_found("global asset", asset_id)
        return self._global(row), global_key(row["filename"])

    def _global_name(self, db: Db, owner: str, name: str, exclude_id: str | None) -> str:
        """Validate a global asset's name: required, unique (for its owner)
        ignoring case."""
        cleaned = normalize_name(name)
        if not cleaned:
            raise ApiError(422, ErrorCode.validation_error, "a global asset needs an ID")
        if not is_valid_id(cleaned):
            raise ApiError(422, ErrorCode.validation_error, ID_RULE, {"name": cleaned})
        taken = {
            name_key(r["name"])
            for r in db.execute(
                "SELECT id, name FROM global_assets WHERE owner_id = ?", (owner,)
            ).fetchall()
            if r["id"] != exclude_id
        }
        if name_key(cleaned) in taken:
            raise ApiError(
                409,
                ErrorCode.duplicate_name,
                f"another global asset already has the ID “{cleaned}”",
                {"name": cleaned},
            )
        return cleaned

    def create_global_asset(
        self,
        owner: str,
        name: str,
        kind: MediaKind,
        data: bytes,
        mime: str,
        ext: str,
        width: int | None = None,
        height: int | None = None,
        duration_s: float | None = None,
    ) -> GlobalAsset:
        asset_id = new_id("gas")
        filename = f"{asset_id}.{ext}"
        key = global_key(filename)
        with self._tx() as db:  # check the name before writing the file
            cleaned = self._global_name(db, owner, name, None)
        self.files.write(key, data, mime)
        try:
            with self._tx() as db:
                cleaned = self._global_name(db, owner, name, None)
                db.execute(
                    "INSERT INTO global_assets (id, owner_id, name, kind, mime, filename, "
                    "bytes, width, height, duration_s, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        asset_id,
                        owner,
                        cleaned,
                        kind.value,
                        mime,
                        filename,
                        len(data),
                        width,
                        height,
                        duration_s,
                        _ts(now()),
                    ),
                )
        except BaseException:
            delete_all(self.files, [key])
            raise
        return self.get_global_asset(asset_id)

    def rename_global_asset(self, asset_id: str, name: str) -> GlobalAsset:
        owner = self.owner_of("global_asset", asset_id)
        with self._tx() as db:
            cleaned = self._global_name(db, owner, name, asset_id)
            db.execute("UPDATE global_assets SET name = ? WHERE id = ?", (cleaned, asset_id))
        return self.get_global_asset(asset_id)

    def delete_global_asset(self, asset_id: str) -> str:
        """Returns the file to remove. Projects made earlier keep their copies."""
        _, key = self.global_asset_file(asset_id)
        with self._tx() as db:
            db.execute("DELETE FROM global_assets WHERE id = ?", (asset_id,))
        return key

    def list_outputs(self, node_id: str) -> list[Output]:
        self.get_node(node_id)
        rows = self._all("SELECT * FROM outputs WHERE node_id = ? ORDER BY seq DESC", node_id)
        return [self._output(r) for r in rows]

    def get_output(self, output_id: str) -> Output:
        row = self._one("SELECT * FROM outputs WHERE id = ?", output_id)
        if not row:
            raise _not_found("output", output_id)
        return self._output(row)

    def asset_file(self, asset_id: str) -> tuple[Asset, str]:
        """An asset and its file's key."""
        row = self._one("SELECT * FROM assets WHERE id = ?", asset_id)
        if not row:
            raise _not_found("asset", asset_id)
        return self._asset(row), asset_key(row["filename"])
