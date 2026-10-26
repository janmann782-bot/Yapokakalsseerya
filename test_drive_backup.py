from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from config import Config
from db import Db
from drive_backup import (AdminProgress, DriveBackup, DriveError, DriveSettings,
                          GoogleDrive, fingerprint, make_snapshot, restore_snapshot)
from models import Page


RAW = json.dumps(dict(folder_id="private_folder", client_id="client", client_secret="secret",
                      refresh_token="refresh"))


class MemoryDrive:
    def __init__(self, settings=None, session=None):
        self.settings = settings or DriveSettings.parse(RAW)
        self.files = []
        self.uploaded = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def snapshots(self):
        return self.files

    async def download(self, entry, destination, progress):
        destination.write_bytes(entry["bytes"])
        await progress("скачивание завершено")

    async def upload(self, path):
        self.uploaded.append(path.read_bytes())
        return "new-file"

    async def prune(self):
        pass


class DriveBackupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = Config("fake", self.root, self.root / "bot.db")
        self.db = Db(self.cfg.db_path)
        await self.db.init()
        await self.db.save_page(Page(1, "country", "Кефирстан", data={"title": "Кефирстан", "images": ["media_one.webp"]}, preview_path="obsolete.png"))
        await self.db.add_media(1, "media_one.webp", 20, 20)
        (self.root / "media_one.webp").write_bytes(b"real-media-bytes")
        fonts = self.root / "user_fonts" / "1"
        fonts.mkdir(parents=True)
        (fonts / "my.ttf").write_bytes(b"font-bytes")
        (self.root / ".env").write_text("BOT_TOKEN=do-not-upload")
        (self.root / "bot_runtime_state.json").write_text('{"maintenance":false}')
        self.archive = self.root / "snapshot.zip"

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def test_env_is_validated_without_disclosing_credentials(self):
        settings = DriveSettings.parse(RAW)
        self.assertEqual(settings.interval, 30)
        self.assertNotIn("secret", repr(settings))
        self.assertNotIn("refresh", repr(settings))
        for raw in ('{"refresh_token":"TOP_SECRET"}', "[]", RAW.replace('"private_folder"', '"bad/path"'), RAW[:-1] + ',"initialize_empty":"false"}'):
            with self.assertRaises(DriveError) as error:
                DriveSettings.parse(raw)
            self.assertNotIn("TOP_SECRET", str(error.exception))

    async def test_roundtrip_restores_wal_cards_media_fonts_and_drafts_without_secrets(self):
        await self.db.save_draft(1, {"type": "country", "page_data": {"title": "Черновик"}})
        # Keep WAL open: raw copying of just the DB would miss this committed row.
        with sqlite3.connect(self.cfg.db_path) as connection:
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("UPDATE pages SET title='Из WAL'")
            connection.commit()
            make_snapshot(self.cfg, self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), {"manifest.json", "database.sqlite3", "files/media_one.webp", "files/user_fonts/1/my.ttf"})
        restored_root = self.root / "new-host"
        restored_root.mkdir()
        cfg = Config("fake", restored_root, restored_root / "new.sqlite")
        self.assertEqual(restore_snapshot(cfg, self.archive), 2)
        restored = Db(cfg.db_path)
        pages = await restored.get_user_pages(1)
        self.assertEqual(pages[0].title, "Из WAL")
        self.assertIsNone(pages[0].preview_path)
        self.assertEqual((await restored.get_draft(1))["page_data"]["title"], "Черновик")
        self.assertEqual((restored_root / "media_one.webp").read_bytes(), b"real-media-bytes")
        self.assertEqual((restored_root / "user_fonts/1/my.ttf").read_bytes(), b"font-bytes")

    def test_corrupt_snapshot_leaves_existing_database_untouched(self):
        make_snapshot(self.cfg, self.archive)
        broken = self.root / "broken.zip"
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(broken, "w") as dest:
            for name in source.namelist():
                dest.writestr(name, b"corrupt" if name == "database.sqlite3" else source.read(name))
        original = self.cfg.db_path.read_bytes()
        with self.assertRaises(DriveError):
            restore_snapshot(self.cfg, broken)
        self.assertEqual(self.cfg.db_path.read_bytes(), original)

    def test_traversal_archive_is_rejected(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"format": 1, "files": {"database.sqlite3": "", "files/../../escaped": ""}}))
            archive.writestr("files/../../escaped", b"bad")
            archive.writestr("database.sqlite3", b"bad")
        with self.assertRaises(DriveError):
            restore_snapshot(self.cfg, self.archive)
        self.assertFalse((self.root.parent / "escaped").exists())

    def test_missing_registered_media_prevents_incomplete_backup(self):
        (self.root / "media_one.webp").unlink()
        with self.assertRaises(DriveError):
            make_snapshot(self.cfg, self.archive)

    async def test_existing_local_database_is_not_replaced_by_remote(self):
        drive, progress = MemoryDrive(), AsyncMock()
        drive.files = [{"bytes": b"should not be downloaded"}]
        backup = DriveBackup(self.cfg, drive, progress)
        await backup.restore()
        self.assertEqual((await self.db.get_user_pages(1))[0].title, "Кефирстан")
        self.assertTrue(drive.connected)
        await backup.backup()
        await backup.backup()
        self.assertEqual(len(drive.uploaded), 1)
        await self.db.save_draft(1, {"type": "country"})
        await backup.backup()
        self.assertEqual(len(drive.uploaded), 2)

    async def test_empty_host_downloads_before_initialization_and_keeps_progress(self):
        make_snapshot(self.cfg, self.archive)
        empty = self.root / "ephemeral"
        empty.mkdir()
        cfg = Config("fake", empty, empty / "database.db")
        drive, progress = MemoryDrive(), AsyncMock()
        drive.files = [{"bytes": self.archive.read_bytes()}]
        await DriveBackup(cfg, drive, progress).restore()
        self.assertEqual((await Db(cfg.db_path).get_user_pages(1))[0].title, "Кефирстан")
        messages = [call.args[0] for call in progress.await_args_list]
        self.assertIn("Ищу последнюю", messages[1])
        self.assertIn("восстановление завершено", messages[-1])
        self.assertEqual(drive.uploaded, [])

    async def test_empty_drive_requires_explicit_bootstrap(self):
        cfg = Config("fake", self.root, self.root / "absent.db")
        with self.assertRaises(DriveError):
            await DriveBackup(cfg, MemoryDrive(), AsyncMock()).restore()
        self.assertFalse(cfg.db_path.exists())
        settings = DriveSettings.parse(RAW[:-1] + ',"initialize_empty":true}')
        await DriveBackup(cfg, MemoryDrive(settings), AsyncMock()).restore()
        self.assertFalse(cfg.db_path.exists())  # Db.init is main's next step.

    async def test_backup_failure_does_not_mark_unsaved_changes_as_saved(self):
        drive = MemoryDrive()
        backup = DriveBackup(self.cfg, drive, AsyncMock())
        drive.upload = AsyncMock(side_effect=DriveError("offline"))
        with self.assertRaises(DriveError):
            await backup.backup()
        self.assertIsNone(backup.last_fingerprint)
        drive.upload = AsyncMock(return_value="saved")
        await backup.backup()
        drive.upload.assert_awaited_once()
        self.assertIsNotNone(backup.last_fingerprint)

    async def test_change_during_upload_is_saved_on_next_cycle(self):
        drive = MemoryDrive()
        backup = DriveBackup(self.cfg, drive, AsyncMock())
        async def upload(path):
            await self.db.save_draft(1, {"page_data": {"title": "После снимка"}})
            return "saved"
        drive.upload = AsyncMock(side_effect=upload)
        await backup.backup()
        drive.upload = AsyncMock(return_value="saved-next")
        await backup.backup()
        drive.upload.assert_awaited_once()

    async def test_admin_progress_edits_same_message_and_falls_back_if_deleted(self):
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=7)), edit_message_text=AsyncMock())
        progress = AdminProgress(bot, {1})
        await progress("connecting")
        await progress("downloading")
        bot.send_message.assert_awaited_once()
        bot.edit_message_text.assert_awaited_once_with("downloading", chat_id=1, message_id=7)
        bot.edit_message_text.side_effect = RuntimeError("deleted")
        await progress("ready")
        self.assertEqual(bot.send_message.await_count, 2)

    async def test_main_fails_closed_before_creating_empty_database(self):
        import main
        cfg = Config("fake", self.root, self.root / "must-not-exist.db", google_drive="bad JSON")
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)), edit_message_text=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))
        with patch.object(main, "load_config", return_value=cfg), patch.object(main, "Bot", return_value=bot), patch.object(main, "setup_telegram", new=AsyncMock()), patch.object(main, "make_dispatcher") as dispatcher:
            with self.assertRaises(RuntimeError):
                await main.main()
        dispatcher.assert_not_called()
        self.assertFalse(cfg.db_path.exists())
        self.assertIn("Пустая база не создана", bot.send_message.await_args.args[1])
        bot.session.close.assert_awaited_once()

    async def test_main_without_drive_warns_admin_every_time(self):
        import main
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)), edit_message_text=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))
        dp = SimpleNamespace(start_polling=AsyncMock(), resolve_used_update_types=lambda: [])
        with patch.object(main, "load_config", return_value=self.cfg), patch.object(main, "Bot", return_value=bot), patch.object(main, "setup_telegram", new=AsyncMock()), patch.object(main, "make_dispatcher", return_value=dp):
            await main.main()
            await main.main()
        warnings = [c.args[1] for c in bot.send_message.await_args_list]
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("Диск не подключен" in text and "INFOBOX_GOOGLE_DRIVE" in text for text in warnings))

    async def test_main_restores_before_polling_then_saves_on_shutdown(self):
        import main
        make_snapshot(self.cfg, self.archive)
        root = self.root / "fresh-host"
        root.mkdir()
        cfg = Config("fake", root, root / "restored.db", google_drive=RAW)
        drive = MemoryDrive()
        drive.files = [{"bytes": self.archive.read_bytes()}]
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)), edit_message_text=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))
        session = SimpleNamespace(close=AsyncMock())
        async def polling(*args, **kwargs):
            self.assertEqual((await Db(cfg.db_path).get_user_pages(1))[0].title, "Кефирстан")
            self.assertEqual(len(drive.uploaded), 1)
        dp = SimpleNamespace(start_polling=polling, resolve_used_update_types=lambda: [])
        with patch.object(main, "load_config", return_value=cfg), patch.object(main, "Bot", return_value=bot), patch.object(main, "setup_telegram", new=AsyncMock()), patch.object(main, "make_dispatcher", return_value=dp), patch.object(main, "GoogleDrive", return_value=drive), patch.object(main.aiohttp, "ClientSession", return_value=session):
            await main.main()
        self.assertEqual(len(drive.uploaded), 2)
        self.assertIn("последние изменения сохранены", bot.edit_message_text.await_args.args[0])
        session.close.assert_awaited_once()


class Reply:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload, self.status, self.headers = payload or {}, status, headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.payload


class DriveProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_oauth_refresh_is_reused_and_failures_do_not_echo_secrets(self):
        session = SimpleNamespace(post=Mock(return_value=Reply({"access_token": "access", "expires_in": 3600})))
        drive = GoogleDrive(DriveSettings.parse(RAW), session)
        self.assertEqual((await drive.headers())["Authorization"], "Bearer access")
        await drive.headers()
        session.post.assert_called_once()
        self.assertEqual(session.post.call_args.kwargs["data"]["grant_type"], "refresh_token")
        session.post.return_value = Reply({"error": "secret refresh TOP_SECRET"}, 400)
        drive.expires = 0
        with self.assertRaises(DriveError) as error:
            await drive.headers()
        self.assertNotIn("TOP_SECRET", str(error.exception))

    async def test_listing_paginates_only_our_folder_and_prunes_after_retention(self):
        session = SimpleNamespace(request=Mock(side_effect=[
            Reply({"files": [{"id": "new"}], "nextPageToken": "next"}),
            Reply({"files": [{"id": "middle"}, {"id": "old"}]}),
            Reply(),
        ]))
        drive = GoogleDrive(DriveSettings.parse(RAW[:-1] + ',"keep":2}'), session)
        drive.headers = AsyncMock(return_value={"Authorization": "Bearer fake"})
        await drive.prune()
        query = session.request.call_args_list[0].kwargs["params"]["q"]
        self.assertIn("'private_folder' in parents", query)
        self.assertIn("infobox_backup", query)
        self.assertEqual(session.request.call_args_list[1].kwargs["params"]["pageToken"], "next")
        self.assertTrue(session.request.call_args.args[1].endswith("/old"))
        self.assertEqual(session.request.call_args.kwargs["json"], {"trashed": True})

    async def test_resumable_upload_is_not_complete_until_drive_confirms_file_id(self):
        session = SimpleNamespace(post=Mock(return_value=Reply(headers={"Location": "https://www.googleapis.com/upload/session"})), put=Mock(return_value=Reply({"id": "complete"})))
        drive = GoogleDrive(DriveSettings.parse(RAW), session)
        drive.headers = AsyncMock(return_value={"Authorization": "Bearer fake"})
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "snapshot.zip"
            source.write_bytes(b"snapshot")
            self.assertEqual(await drive.upload(source), "complete")
            self.assertEqual(session.post.call_args.kwargs["params"]["uploadType"], "resumable")
            self.assertEqual(session.post.call_args.kwargs["json"]["parents"], ["private_folder"])
            session.put.return_value = Reply({}, 503)
            with self.assertRaises(DriveError):
                await drive.upload(source)


if __name__ == "__main__":
    unittest.main()
