from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import aiohttp

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.types import BotCommand

from bot import make_dispatcher
from config import load_config
from db import Db
from version import __version__
from drive_backup import AdminProgress, DriveBackup, DriveSettings, GoogleDrive, DriveError, ENV

log = logging.getLogger("infobox")


async def setup_telegram(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="create", description="Создать страницу"),
        BotCommand(command="my_pages", description="Мои страницы"),
        BotCommand(command="stats", description="Статистика генераций"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
    ]

    try:
        await bot.set_my_commands(commands)
    except TelegramUnauthorizedError as e:
        raise RuntimeError(
            "Telegram отклонил BOT_TOKEN. Проверь токен в переменных окружения BotHost "
            "и при необходимости выпусти новый через @BotFather."
        ) from e
    except TelegramAPIError as e:
        log.warning("Не удалось установить меню команд, продолжаю запуск: %s", e)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except TelegramUnauthorizedError as e:
        raise RuntimeError(
            "Telegram отклонил BOT_TOKEN. Проверь токен в переменных окружения BotHost "
            "и при необходимости выпусти новый через @BotFather."
        ) from e
    except TelegramAPIError as e:
        # polling сам повторяет запросы после временных сетевых ошибок
        log.warning("Не удалось проверить webhook, перехожу к polling: %s", e)


async def main() -> None:
    from admin import admin_ids, set_maintenance

    cfg = load_config()
    cfg.work_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # при каждом запуске - техработы
    set_maintenance(cfg, True)
    log.info("InfoBox Bot %s | Maintenance ON (default on startup)", __version__)

    bot = Bot(cfg.bot_token)
    progress = AdminProgress(bot, admin_ids())
    drive_session = None
    backup = None
    worker = None
    ready = False
    try:
        await setup_telegram(bot)
        if not cfg.google_drive:
            await progress(
                "Админ, ты долбаеб: Google Диск не подключен\n"
                f"Добавь {ENV} в переменные окружения хостинга\n"
                "Работаю с локальной базой без резервного сохранения. После обновления она может пропасть\n"
                "Техработы включены, выключить: /maint_off"
            )
        else:
            try:
                settings = DriveSettings.parse(cfg.google_drive)
                drive_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600, connect=15, sock_read=60))
                backup = DriveBackup(cfg, GoogleDrive(settings, drive_session), progress)
                await backup.restore()
            except Exception as exc:
                detail = str(exc) if isinstance(exc, DriveError) else type(exc).__name__
                await progress("Google Диск: запуск остановлен\n" + detail + "\nПустая база не создана, копия на Диске не перезаписана")
                raise RuntimeError("Восстановление Google Диска не завершено; запуск остановлен") from None
        # Must happen after restore: Db.init creates a new empty file otherwise.
        db = Db(cfg.db_path)
        try:
            await db.init()
        except Exception as exc:
            await progress("Запуск остановлен: не удалось открыть локальную базу\n" + type(exc).__name__ + "\nКопия на Диске не перезаписана")
            raise
        if backup:
            try:
                await progress("Google Диск: база готова\nСохраняю проверенную резервную копию")
                await backup.backup(force=True)
            except Exception as exc:
                detail = str(exc) if isinstance(exc, DriveError) else type(exc).__name__
                await progress("Google Диск: сохранение не удалось\n" + detail + "\nЗапуск остановлен. Локальная база сохранена")
                raise RuntimeError("Первая резервная копия не сохранена; запуск остановлен") from None
            ready = True
            worker = asyncio.create_task(backup.run(), name="google-drive-backup")
            await progress(
                f"Google Диск: готово\nБаза и файлы сохранены\n"
                f"Проверяю изменения каждые {backup.drive.settings.interval} сек. Храню {backup.drive.settings.keep} копий\n"
                "Техработы включены, выключить: /maint_off"
            )
        dp = make_dispatcher(db, cfg)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        if backup and ready:
            try:
                await progress("Google Диск: бот останавливается\nСохраняю последние изменения")
                await backup.backup(force=True)
                await progress("Google Диск: последние изменения сохранены\nБот остановлен")
            except Exception:
                await progress("Google Диск: последняя копия не сохранена перед остановкой\nНа Диске осталась предыдущая копия")
        if drive_session:
            await drive_session.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
