"""Teacher files: register an uploaded file, list, delete."""

from uuid import UUID

from app.modules.assets.repository import AssetRepository
from app.modules.assets.schemas import MAX_BYTES, MIME_KIND, AssetList, AssetOut, AssetRegister
from app.shared.errors.exceptions import ConflictError, NotFoundError, ValidationFailedError

ASSET_NOT_FOUND = "الملف غير موجود"


class AssetService:
    def __init__(self, repo: AssetRepository, teacher_id: UUID) -> None:
        self._repo = repo
        self._teacher_id = teacher_id

    async def register(self, data: AssetRegister) -> AssetOut:
        if data.storage_path.split("/", 1)[0] != str(self._teacher_id) or "/" not in data.storage_path:
            raise ValidationFailedError(
                "مسار الملف غير صحيح", details=[{"field": "storage_path", "type": "wrong_folder"}]
            )
        stored = await self._repo.stored_object(data.storage_path)
        if stored is None or stored["size_bytes"] is None:
            raise NotFoundError("ما لقينا الملف المرفوع، ارفعيه مرة ثانية")
        mime = (stored["mime_type"] or "").lower()
        kind = MIME_KIND.get(mime)
        if kind is None:
            raise ValidationFailedError(
                "نوع الملف غير مسموح", details=[{"field": "mime_type", "type": "not_allowed"}]
            )
        if stored["size_bytes"] > MAX_BYTES[kind]:
            raise ValidationFailedError("حجم الملف أكبر من المسموح", details=[{"field": "size", "type": "too_large"}])
        row = await self._repo.create(
            {
                "kind": kind.value,
                "storage_path": data.storage_path,
                "file_name": data.file_name,
                "mime_type": mime,
                "size_bytes": stored["size_bytes"],
                "width": data.width if kind is not kind.pdf else None,
                "height": data.height if kind is not kind.pdf else None,
            }
        )
        if row is None:
            raise ConflictError("الملف مسجّل من قبل")
        return AssetOut(**row)

    async def list(self, kind: str | None, limit: int, offset: int) -> AssetList:
        rows, total = await self._repo.list(kind, limit, offset)
        return AssetList(items=[AssetOut(**r) for r in rows], total=total)

    async def delete(self, asset_id: UUID) -> str:
        path = await self._repo.delete(asset_id)
        if path is None:
            raise NotFoundError(ASSET_NOT_FOUND)
        return path
