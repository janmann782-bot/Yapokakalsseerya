"""Private Google Drive snapshots. Restore before Db.init; never sync live SQLite."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

import aiohttp

log = logging.getLogger(__name__)
ENV = "INFOBOX_GOOGLE_DRIVE"
API = "https://www.googleapis.com/drive/v3/files"


class DriveError(RuntimeError):
    pass


async def disk_operation(function, *args):
    # Cancellation must wait for a file-writing thread before its temp dir closes.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


@dataclass(frozen=True)
class DriveSettings:
    folder_id: str
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)
    interval: int = 30
    keep: int = 5
    initialize_empty: bool = False

    @classmethod
    def parse(cls, raw):
        try:
            d = json.loads(raw)
            if not isinstance(d, dict):
                raise ValueError
            required = ("folder_id", "client_id", "client_secret", "refresh_token")
            if any(not isinstance(d.get(k), str) or not d[k].strip() for k in required):
                raise ValueError
            if not re.fullmatch(r"[A-Za-z0-9_-]+", d["folder_id"]):
                raise ValueError
            interval, keep = int(d.get("interval", 30)), int(d.get("keep", 5))
            if not 10 <= interval <= 3600 or not 2 <= keep <= 30:
                raise ValueError
            if not isinstance(d.get("initialize_empty", False), bool):
                raise ValueError
            return cls(*(d[k].strip() for k in required), interval, keep, d.get("initialize_empty", False))
        except (ValueError, TypeError, KeyError):
            raise DriveError(f"{ENV}: нужен JSON с folder_id, client_id, client_secret и refresh_token") from None


class AdminProgress:
    """One editable status message per admin, with send fallback."""
    def __init__(self, bot, ids):
        self.bot, self.ids, self.messages = bot, ids, {}

    async def __call__(self, text):
        for aid in sorted(self.ids):
            try:
                previous = self.messages.get(aid)
                if previous:
                    try:
                        await self.bot.edit_message_text(text, chat_id=aid, message_id=previous)
                    except Exception:
                        msg = await self.bot.send_message(aid, text)
                        self.messages[aid] = msg.message_id
                else:
                    msg = await self.bot.send_message(aid, text)
                    self.messages[aid] = msg.message_id
            except Exception:
                # Delivery failure must not interrupt recovery or disclose tokens.
                log.warning("Не удалось обновить статус Диска для админа %s", aid)


def check_database(path):
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DriveError("Проверка SQLite не пройдена")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"users", "pages", "user_settings"} <= tables:
            raise DriveError("Копия не похожа на базу InfoBox")


def storage_files(cfg):
    root = cfg.work_dir.resolve()
    return sorted(p for p in (*root.glob("media_*"), *root.glob("user_fonts/*/*"))
                  if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root))


def fingerprint(cfg):
    paths = [cfg.db_path, Path(str(cfg.db_path) + "-wal"), *storage_files(cfg)]
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths if p.exists())


def make_snapshot(cfg, output):
    """SQLite backup API includes committed WAL data; .env and tokens never enter ZIP."""
    with tempfile.TemporaryDirectory(prefix="infobox_snapshot_") as tmp:
        db_copy = Path(tmp) / "database.sqlite3"
        with closing(sqlite3.connect(f"{cfg.db_path.resolve().as_uri()}?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(db_copy)) as dest:
                src.backup(dest)
        check_database(db_copy)
        with closing(sqlite3.connect(db_copy)) as conn, conn:
            conn.execute("UPDATE pages SET preview_path=NULL")
        files = [("database.sqlite3", db_copy)]
        files += [("files/" + p.relative_to(cfg.work_dir).as_posix(), p) for p in storage_files(cfg)]
        # Do not silently publish a snapshot whose database references absent media.
        with closing(sqlite3.connect(db_copy)) as conn, conn:
            referenced = {Path(r[0]).name for r in conn.execute("SELECT path FROM uploaded_media")}
        available = {p.name for _, p in files}
        if not referenced <= available:
            raise DriveError("Не все картинки базы найдены локально; неполная копия не загружена")
        manifest = {"format": 1, "created": datetime.now(UTC).isoformat(), "files": {}}
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, path in files:
                # Hash the exact bytes in the archive, even if a font changed meanwhile.
                digest = hashlib.sha256()
                with path.open("rb") as source, archive.open(name, "w") as target:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        target.write(chunk)
                manifest["files"][name] = digest.hexdigest()
            archive.writestr("manifest.json", json.dumps(manifest))


def restore_snapshot(cfg, archive_path):
    """Validate all members and hashes in staging before publishing any file."""
    root = cfg.work_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="infobox_restore_") as tmp:
        staging = Path(tmp)
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise DriveError("В архиве повторяются имена файлов")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
                raise DriveError("Неизвестный формат резервной копии")
            entries = manifest["files"]
            if set(names) != set(entries) | {"manifest.json"} or "database.sqlite3" not in entries:
                raise DriveError("Неполная резервная копия")
            for name, expected in entries.items():
                relative = PurePosixPath(name)
                allowed = (name == "database.sqlite3" or
                           (len(relative.parts) == 2 and relative.parts[0] == "files" and relative.name.startswith("media_")) or
                           (len(relative.parts) == 4 and relative.parts[:2] == ("files", "user_fonts")))
                if not allowed or relative.is_absolute() or ".." in relative.parts or "\\" in name:
                    raise DriveError("Недопустимый путь в резервной копии")
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open(name) as source, target.open("wb") as out:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        out.write(chunk)
                if digest.hexdigest() != expected:
                    raise DriveError("Контрольная сумма резервной копии не совпала")
        check_database(staging / "database.sqlite3")
        # Media first, DB last. A killed restore can safely be repeated on startup.
        for name in entries:
            if name == "database.sqlite3":
                continue
            target = root / PurePosixPath(name).relative_to("files")
            if target.is_symlink() or not target.resolve().is_relative_to(root):
                raise DriveError("Недопустимый локальный путь восстановления")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".restore-tmp")
            with (staging / name).open("rb") as source, temporary.open("wb") as out:
                while chunk := source.read(1024 * 1024):
                    out.write(chunk)
            os.replace(temporary, target)
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cfg.db_path.with_name(cfg.db_path.name + ".restore-tmp")
        with (staging / "database.sqlite3").open("rb") as source, temporary.open("wb") as out:
            while chunk := source.read(1024 * 1024):
                out.write(chunk)
        # No SQLite connection has been opened by main yet.
        for suffix in ("-wal", "-shm"):
            Path(str(cfg.db_path) + suffix).unlink(missing_ok=True)
        os.replace(temporary, cfg.db_path)
    return len(entries) - 1


class GoogleDrive:
    def __init__(self, settings, session):
        self.settings, self.session = settings, session
        self.token, self.expires = "", 0

    async def headers(self):
        if time.monotonic() >= self.expires:
            async with self.session.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.settings.client_id, "client_secret": self.settings.client_secret,
                "refresh_token": self.settings.refresh_token, "grant_type": "refresh_token",
            }) as response:
                if response.status != 200:
                    raise DriveError(f"Google OAuth: HTTP {response.status}. Проверь refresh_token и доступ приложения")
                payload = await response.json()
            self.token = payload["access_token"]
            self.expires = time.monotonic() + max(1, int(payload.get("expires_in", 3600)) - 60)
        return {"Authorization": "Bearer " + self.token}

    async def json_request(self, method, url, **kwargs):
        async with self.session.request(method, url, headers=await self.headers(), **kwargs) as response:
            if response.status >= 400:
                raise DriveError(f"Google Диск: HTTP {response.status}. Проверь доступ к папке и свободное место")
            return await response.json() if response.status != 204 else {}

    async def connect(self):
        folder = await self.json_request("GET", API + "/" + self.settings.folder_id,
                                         params={"fields": "mimeType,capabilities(canAddChildren),trashed"})
        if folder.get("trashed") or folder.get("mimeType") != "application/vnd.google-apps.folder" or not folder.get("capabilities", {}).get("canAddChildren"):
            raise DriveError("Папка Google Диска недоступна для записи")

    async def snapshots(self):
        query = (f"'{self.settings.folder_id}' in parents and trashed = false and "
                 "appProperties has { key='infobox_backup' and value='1' }")
        results, cursor = [], None
        while True:
            params = {"q": query, "fields": "files(id,name,size,createdTime),nextPageToken,incompleteSearch",
                      "orderBy": "createdTime desc", "pageSize": "100"}
            if cursor:
                params["pageToken"] = cursor
            payload = await self.json_request("GET", API, params=params)
            if payload.get("incompleteSearch"):
                raise DriveError("Google вернул неполный список копий; запуск остановлен")
            results.extend(payload.get("files", []))
            cursor = payload.get("nextPageToken")
            if not cursor:
                return results

    async def download(self, entry, destination, progress):
        async with self.session.get(API + "/" + entry["id"], params={"alt": "media"}, headers=await self.headers()) as response:
            if response.status != 200:
                raise DriveError(f"Скачивание копии: HTTP {response.status}")
            total, received, last = int(entry.get("size", 0)), 0, 0
            with Path(destination).open("wb") as out:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    out.write(chunk)
                    received += len(chunk)
                    if time.monotonic() - last >= 2:
                        last = time.monotonic()
                        suffix = f" / {total // 1024} КБ" if total else ""
                        await progress(f"Google Диск: скачиваю базу и картинки\n{received // 1024} КБ{suffix}")
            if total and received != total:
                raise DriveError("Копия скачалась не полностью")

    async def upload(self, source):
        name = "infobox-backup-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8] + ".zip"
        headers = await self.headers()
        headers.update({"X-Upload-Content-Type": "application/zip", "X-Upload-Content-Length": str(source.stat().st_size)})
        async with self.session.post("https://www.googleapis.com/upload/drive/v3/files", params={"uploadType": "resumable", "fields": "id"}, headers=headers,
                                     json={"name": name, "parents": [self.settings.folder_id], "appProperties": {"infobox_backup": "1"}}) as response:
            if response.status not in (200, 201):
                raise DriveError(f"Создание копии: HTTP {response.status}")
            location = response.headers.get("Location", "")
        if not location.startswith("https://www.googleapis.com/"):
            raise DriveError("Google не вернул адрес загрузки")
        with source.open("rb") as stream:
            async with self.session.put(location, data=stream, headers={**await self.headers(), "Content-Type": "application/zip", "Content-Length": str(source.stat().st_size)}) as response:
                if response.status not in (200, 201):
                    raise DriveError(f"Загрузка копии: HTTP {response.status}")
                result = await response.json()
        if not result.get("id"):
            raise DriveError("Google не подтвердил сохранение копии")
        return result["id"]

    async def prune(self):
        for entry in (await self.snapshots())[self.settings.keep:]:
            await self.json_request("PATCH", API + "/" + entry["id"], json={"trashed": True})


class DriveBackup:
    def __init__(self, cfg, drive, progress):
        self.cfg, self.drive, self.progress = cfg, drive, progress
        self.last_fingerprint = None
        self.failed = False

    async def restore(self):
        await self.progress("Google Диск: подключаюсь")
        await self.drive.connect()
        await self.progress("Google Диск подключен\nИщу последнюю резервную копию")
        snapshots = await self.drive.snapshots()
        if self.cfg.db_path.exists():
            await asyncio.to_thread(check_database, self.cfg.db_path)
            await self.progress("Google Диск подключен\nЛокальная база есть и прошла проверку. Сохраняю ее, не заменяю старой копией")
            return
        if not snapshots:
            if not self.drive.settings.initialize_empty:
                raise DriveError("На Диске нет копии и локальной базы нет. Для первого чистого запуска добавь initialize_empty: true в env")
            await self.progress("Google Диск подключен\nПустая база разрешена настройкой initialize_empty. Создаю первую копию после запуска")
            return
        with tempfile.TemporaryDirectory(prefix="infobox_download_") as tmp:
            archive = Path(tmp) / "backup.zip"
            await self.drive.download(snapshots[0], archive, self.progress)
            await self.progress("Google Диск: копия скачана\nПроверяю архив и восстанавливаю базу, картинки и пользовательские шрифты")
            count = await disk_operation(restore_snapshot, self.cfg, archive)
        await self.progress(f"Google Диск: восстановление завершено\nБаза проверена, файлов восстановлено: {count}")

    async def backup(self, force=False):
        stamp = await asyncio.to_thread(fingerprint, self.cfg)
        if not force and stamp == self.last_fingerprint:
            return
        with tempfile.TemporaryDirectory(prefix="infobox_upload_") as tmp:
            archive = Path(tmp) / "backup.zip"
            await disk_operation(make_snapshot, self.cfg, archive)
            await self.drive.upload(archive)
        self.last_fingerprint = stamp
        await self.drive.prune()

    async def run(self):
        while True:
            await asyncio.sleep(self.drive.settings.interval)
            try:
                await self.backup()
                if self.failed:
                    await self.progress("Google Диск: резервное сохранение снова работает")
                    self.failed = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Резервная копия Google Диска не сохранена (%s)", type(exc).__name__)
                if not self.failed:
                    await self.progress("Google Диск: резервная копия не сохранена\nЛокальные данные остались. Повторю попытку автоматически. До успешного сохранения не обновляй хостинг")
                    self.failed = True
