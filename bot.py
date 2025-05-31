
import asyncio
import logging
import os

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Import Base for database table creation
from models.base import Base

# Import all handlers/routers
from handlers.commands import router as commands_router
from handlers.post_creation import router as post_creation_router
# from handlers.inline_buttons import router as inline_buttons_router # NOTE: Inline buttons handler not provided in reference
from handlers.rss_integration import router as rss_integration_router
from handlers.post_management import router as post_management_router
from handlers.channel_management import router as channel_management_router
from handlers.timezone_management import router as timezone_management_router

# Import service functions and logger setup
from utils.logger import setup_logging # Correctly import setup_logging function
# Assuming db_service.init_db is no longer needed based on ref, using create_db_tables pattern
from services import scheduler_service # Import the entire service module


# Load environment variables from .env file
load_dotenv()

# Setup logging
# Use the setup_logging function from utils.logger
# This will configure the root logger and handlers based on LOG_LEVEL env var
logger = setup_logging()
# Now you can use logger.info, logger.error, etc. in this file

# Get bot token and database URL from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Validate essential environment variables
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN environment variable is not set!")
    exit(1)
if not DATABASE_URL:
    logger.critical("DATABASE_URL environment variable is not set!")
    exit(1)

# Initialize SQLAlchemy Async Engine
engine = create_async_engine(DATABASE_URL)

# Create a session factory
# expire_on_commit=False is often useful when objects might be accessed after commit
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def create_db_tables():
    """Creates database tables based on Base metadata if they don't exist."""
    logger.info("Creating database tables if they do not exist...")
    async with engine.begin() as conn:
        # Assuming Base.metadata contains definitions from all imported models
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables creation check complete.")


async def main():
    """Main asynchronous function to start the bot."""
    logger.info("Starting bot application...")

    # Create database tables if they don't exist
    await create_db_tables()

    # Initialize Bot and Dispatcher
    # parse_mode='HTML' sets the default parse mode for outgoing messages
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    # Dispatcher uses default MemoryStorage if no storage is specified
    dp = Dispatcher()

    # Initialize and start APScheduler with SQLAlchemyJobStore
    # The initialize_scheduler function in scheduler_service handles this setup
    # Pass the sessionmaker factory to the scheduler service init
    scheduler = scheduler_service.initialize_scheduler(DATABASE_URL)
    logger.info("APScheduler initialized.")

    # Restore scheduled jobs from the database on startup
    # Pass the necessary dependencies (scheduler, bot, session_maker factory)
    await scheduler_service.restore_scheduled_jobs(scheduler, bot, async_session_maker)
    logger.info("Scheduled jobs restored from database.")

    # Start the scheduler
    # The scheduler should be started *after* jobs are restored
    scheduler.start()
    logger.info("APScheduler started.")

    # Include routers into the Dispatcher
    # The order of inclusion can matter for handler priority
    # Include general command handler last if it includes a catch-all handler
    dp.include_routers(
        post_creation_router,
        # inline_buttons_router, # NOTE: Inline buttons router commented out as handler not provided
        rss_integration_router,
        post_management_router,
        channel_management_router,
        timezone_management_router,
        commands_router # Include commands router, potentially with fallback, last
    )
    logger.info("All routers included.")

    # Provide dependencies to handlers via workflow_data
    # Handlers can access these via `message.bot.sessionmaker`, `message.bot.scheduler`, etc.
    # Or by receiving them as arguments if using dependency injection middleware
    # aiogram 3.x workflow_data is a standard place to put app-level dependencies
    dp.workflow_data.update({
        'session_maker': async_session_maker, # Pass the session factory
        'scheduler': scheduler,
        'bot': bot # Bot instance is also available via message, but explicit is fine
    })
    logger.info("Dependencies added to workflow_data.")

    # Removed explicit global setting in scheduler_service from here.
    # Dependencies for jobs are passed directly in add_job calls in scheduler_service.
    # Dependencies for services called from handlers are accessed via DI (workflow_data).
    # Dependencies for services called from other services within jobs rely on lazy imports + argument passing within the call chain.


    # Drop pending updates to ignore messages sent while the bot was offline
    # Useful for development, potentially undesirable in production depending on requirements
    logger.info("Deleting webhook and dropping pending updates...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted.")
    except Exception as e:
        logger.warning(f"Failed to delete webhook: {e}", exc_info=True)
        logger.warning("Proceeding without dropping updates.")


    # Start polling
    logger.info("Starting polling...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually via KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"Bot stopped due to a critical error: {e}", exc_info=True)
"""

# Content for models/base.py (from task LmJ0A)
MODELS_BASE_CONTENT = """
from sqlalchemy.orm import declarative_base

Base = declarative_base()
"""

# Content for models/user.py (from task yBWNP)
MODELS_USER_CONTENT = """
from sqlalchemy import Column, Integer, String, DateTime, BigInteger, func
from sqlalchemy.orm import relationship
from typing import TYPE_CHECKING

# Import models for TYPE_CHECKING
if TYPE_CHECKING:
    from .user_channel import UserChannel
    from .rss_feed import RssFeed
    from .post import Post

from .base import Base

class User(Base):
    """
    ORM model for the 'users' table.
    Stores user-specific settings and identifiers.
    """
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    telegram_user_id = Column(BigInteger, unique=True, index=True, nullable=False)
    preferred_mode = Column(String(50), nullable=True)  # 'buttons' or 'commands'
    timezone = Column(String(50), nullable=False, default='Europe/Berlin') # Default timezone set as requested
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Define relationships
    channels: list["UserChannel"] = relationship("UserChannel", back_populates="user")
    rss_feeds: list["RssFeed"] = relationship("RssFeed", back_populates="user")
    posts: list["Post"] = relationship("Post", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_user_id={self.telegram_user_id}, timezone='{self.timezone}')>"
"""

# Content for models/user_channel.py (from task LmJ0A)
MODELS_USER_CHANNEL_CONTENT = """
from sqlalchemy import Column, Integer, String, DateTime, BigInteger, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from typing import TYPE_CHECKING

# Import models for TYPE_CHECKING
if TYPE_CHECKING:
    from .user import User

from .base import Base

class UserChannel(Base):
    """
    SQLAlchemy ORM model for the 'user_channels' table.
    Represents a Telegram channel or group added by a user for posting.
    """
    __tablename__ = 'user_channels'

    id = Column(Integer, primary_key=True, index=True)

    # Foreign key to the 'users' table. user_id stores the Telegram user's ID (matches users.id type).
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)

    # Telegram chat ID. This can be a channel ID or a group ID.
    # Using BigInteger as these IDs can be large.
    chat_id = Column(BigInteger, nullable=False, index=True)

    # Username of the chat (e.g. @my_channel). This is nullable as not all chats have usernames (e.g. private groups, private channels without link).
    # Max length 255 is a common standard and accommodates typical Telegram username lengths.
    chat_username = Column(String(255), nullable=True)

    # Boolean flag indicating if this channel is currently active for the user's posting activities.
    # Defaulting to True means newly added channels are active by default.
    is_active = Column(Boolean, nullable=False, default=True)

    # Timestamp when the user added this channel. Defaults to the current server time using SQLAlchemy's func.now().
    added_at = Column(DateTime, nullable=False, default=func.now())

    # Timestamp when the channel was conceptually removed or deactivated by the user (soft delete).
    # If NULL, the channel is considered active (in conjunction with is_active).
    removed_at = Column(DateTime, nullable=True)

    # Define relationship to the User model.
    user: "User" = relationship("User", back_populates="channels")

    def __repr__(self):
        """Provides a developer-friendly representation of the UserChannel object."""
        return (
            f"<UserChannel(id={self.id}, user_id={self.user_id}, chat_id={self.chat_id}, "
            f"chat_username='{self.chat_username}', is_active={self.is_active}, "
            f"added_at='{self.added_at}', removed_at='{self.removed_at}')>"
        )
"""

# Content for models/post.py (from task LmJ0A)
MODELS_POST_CONTENT = """
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, func, JSON
from sqlalchemy.orm import relationship
from typing import TYPE_CHECKING

# Import models for TYPE_CHECKING
if TYPE_CHECKING:
    from .user import User

from .base import Base

class Post(Base):
    """
    SQLAlchemy ORM модель для таблицы 'posts'.

    Хранит информацию о запланированных, опубликованных или черновиках постов.
    """
    __tablename__ = 'posts'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    chat_ids = Column(JSON, nullable=False, comment="JSON array of Telegram chat_id where posts should be published")
    text = Column(Text, nullable=True)
    media_paths = Column(JSON, nullable=True, comment="JSON array of Telegram file_id or paths to media")
    schedule_type = Column(String(50), nullable=False) # Тип расписания: 'one_time', 'recurring', 'draft', 'now'
    schedule_params = Column(JSON, nullable=True) # Параметры расписания (например, cron string для 'recurring')
    run_date_utc = Column(DateTime, nullable=True) # Для 'one_time': дата и время публикации в UTC
    delete_after_seconds = Column(Integer, nullable=True) # Удалить через N секунд после публикации
    delete_at_utc = Column(DateTime, nullable=True) # Удалить в конкретное время в UTC
    status = Column(String(50), nullable=False, default='scheduled') # Статус поста: 'scheduled', 'sent', 'deleted', 'invalid', 'draft'
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Поля, добавленные по результатам анализа
    sent_message_ids = Column(JSON, nullable=True, default={}, comment="JSON object mapping chat_id to message_id for sent posts")
    published_at_utc = Column(DateTime, nullable=True, comment="Actual UTC time when the post was published")
    parse_mode = Column(String(50), nullable=True, comment="Parse mode for the post text (MarkdownV2, HTML)") # Added parse_mode based on usage

    # Отношение к модели User
    user: "User" = relationship("User", back_populates="posts")

    def __repr__(self):
        return f"<Post(id={self.id}, user_id={self.user_id}, status='{self.status}')>"
"""

# Content for models/rss_feed.py (from task yBWNP)
MODELS_RSS_FEED_CONTENT = """
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from typing import TYPE_CHECKING

# Import models for TYPE_CHECKING
if TYPE_CHECKING:
    from .user import User
    from .rss_item import RssItem # Added for bidirectional relationship

from .base import Base

class RssFeed(Base):
    """
    SQLAlchemy ORM model representing an RSS feed subscription for a user.
    """
    __tablename__ = 'rss_feeds'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    feed_url = Column(String(1024), nullable=False)
    channels = Column(JSON, nullable=False, comment="JSON array of Telegram chat_id where posts should be published")
    filter_keywords = Column(JSON, nullable=True, comment="JSON array of keywords for filtering feed items")
    frequency_minutes = Column(Integer, nullable=False, default=30, comment="How often to check the feed, in minutes")
    next_check_utc = Column(DateTime, nullable=True, comment="UTC time of the next scheduled check")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="Timestamp when the subscription was created")

    # Field added based on analysis
    last_checked_at = Column(DateTime, nullable=True, comment="UTC time when the feed was last checked for new items")
    parse_mode = Column(String(50), nullable=True, comment="Parse mode for RSS item text (MarkdownV2, HTML)") # Added parse_mode

    # Define relationship to the User model
    user: "User" = relationship("User", back_populates="rss_feeds")

    # Define relationship to the RssItem model
    # Added cascade="all, delete-orphan" to automatically delete associated RssItems
    # when an RssFeed is deleted.
    items: list["RssItem"] = relationship("RssItem", back_populates="feed", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<RssFeed(id={self.id}, user_id={self.user_id}, feed_url='{self.feed_url[:50]}...')>"
"""

# Content for models/rss_item.py (from task SrzpQ)
MODELS_RSS_ITEM_CONTENT = """
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from typing import TYPE_CHECKING

# Import models for TYPE_CHECKING
if TYPE_CHECKING:
    from .rss_feed import RssFeed

from .base import Base

class RssItem(Base):
    """
    Модель ORM для хранения информации об элементах RSS-лент,
    которые были опубликованы, для предотвращения дублирования.
    """
    __tablename__ = 'rss_items'

    id = Column(Integer, primary_key=True, index=True)
    feed_id = Column(Integer, ForeignKey('rss_feeds.id'), nullable=False, index=True)
    item_guid = Column(String(1024), nullable=False, unique=True, index=True)
    published_at = Column(DateTime, nullable=True)
    is_posted = Column(Boolean, nullable=False, default=False) # Флаг, указывающий, был ли элемент успешно опубликован
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    # Определение отношения к модели RssFeed (один-ко-многим: одна лента имеет много элементов)
    feed: "RssFeed" = relationship("RssFeed", back_populates="items")

    def __repr__(self):
        return f"<RssItem(id={self.id}, feed_id={self.feed_id}, item_guid='{self.item_guid[:50]}...', published_at={self.published_at}, is_posted={self.is_posted})>"

# Note: The static analysis report mentioned an unused 'BaseModel' import,
# but the provided code reference for models/rss_item.py imports 'Base',
# which is correctly used. No change needed for this specific file based on the reference.
"""

# Content for utils/logger.py (from task Bz47C)
UTILS_LOGGER_CONTENT = """
import logging
import os
import sys

def setup_logging(log_level_env_var: str = 'LOG_LEVEL', default_log_level: str = 'INFO', log_file: str = 'bot.log') -> logging.Logger:
    """
    Настраивает корневой логгер для проекта.

    Получает уровень логирования из переменной окружения, настраивает
    StreamHandler (stdout) и FileHandler, устанавливает формат и уровень.

    Args:
        log_level_env_var: Имя переменной окружения для уровня логирования.
        default_log_level: Уровень логирования по умолчанию (строка).
        log_file: Имя файла для логирования.

    Returns:
        Настроенный корневой логгер.
    """
    # Маппинг строковых уровней логирования к константам
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL,
    }

    # Получение уровня логирования из переменной окружения или использование значения по умолчанию
    # Преобразуем в верхний регистр для регистронезависимого сравнения
    configured_level_str = os.getenv(log_level_env_var, default_log_level).upper()

    # Получаем константу уровня логирования, используя значение по умолчанию при некорректном значении из env
    log_level = level_map.get(configured_level_str, level_map[default_log_level.upper()])

    # Формат логирования
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(module)s:%(lineno)d - %(message)s')

    # Получение корневого логгера
    root_logger = logging.getLogger()

    # Очистка существующих обработчиков, чтобы избежать дублирования при повторной настройке
    # (например, при использовании в тестовой среде или повторном вызове функции)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Настройка StreamHandler для вывода в консоль (stdout)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(log_level) # Устанавливаем уровень для обработчика
    root_logger.addHandler(stream_handler)

    # Настройка FileHandler для записи в файл
    file_handler = logging.FileHandler(log_file, mode='a') # mode='a' для добавления к существующему файлу
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level) # Устанавливаем уровень для обработчика
    root_logger.addHandler(file_handler)

    # Установка общего уровня для корневого логгера
    # Это минимальный уровень для всех сообщений, которые проходят через логгер,
    # прежде чем они будут отправлены обработчикам.
    root_logger.setLevel(log_level)

    # Возвращаем корневой логгер.
    # Другие модули могут получить его либо через импорт `logger`, либо через `logging.getLogger()`.
    return root_logger

# Инициализация и экспорт настроенного логгера
# Этот логгер будет доступен при импорте модуля utils.logger
logger = setup_logging()
"""

# Content for utils/validators.py (from task Bz47C)
UTILS_VALIDATORS_CONTENT = """
import datetime
from typing import Optional, Dict, Any
import re
import pytz

# Константы для валидации
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 МБ
ALLOWED_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'video/mp4',
    'application/pdf',
    'audio/mpeg', # Добавим аудио как часто используемый тип
    'audio/ogg',
    'video/quicktime', # MOV
    'image/webp', # Добавим webp
    'image/tiff', # Добавим tiff
    'image/bmp' # Добавим bmp
}
ALLOWED_WEEK_DAYS = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}

# Регулярное выражение для формата времени HH:MM
TIME_FORMAT_REGEX = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')

# Регулярное выражение для формата дня и месяца DD.MM
DAY_MONTH_FORMAT_REGEX = re.compile(r'^(0[1-9]|[12]\d|3[01])\.(0[1-9]|1[0-2])$')

# Регулярное выражение для базовой валидации URL
URL_REGEX = re.compile(
    r'^(?:http|https)://'  # Схема http или https
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # Доменное имя
    r'localhost|'  # или localhost
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # или IP-адрес
    r'(?::\d+)?'  # Необязательный порт
    r'(?:/?|[/?]\S+)$', re.IGNORECASE)

# Регулярное выражение для валидации юзернейма канала Telegram
# Длина 5-32 символа, латиница, цифры, подчеркивание
CHANNEL_USERNAME_REGEX = re.compile(r'^[a-zA-Z0-9_]{5,32}$')


def validate_iana_timezone(tz_str: str) -> bool:
    """
    Проверяет, является ли строка корректной таймзоной стандарта IANA.

    Args:
        tz_str: Строка для проверки.

    Returns:
        True, если строка является валидной IANA таймзоной, иначе False.
    """
    if not isinstance(tz_str, str):
        return False
    return tz_str in pytz.all_timezones


def validate_datetime_format_and_future(datetime_str: str, user_tz_str: str) -> Optional[datetime.datetime]:
    """
    Валидирует строку даты и времени в формате DD.MM.YYYY HH:MM, проверяет,
    что она находится в будущем относительно текущего UTC времени,
    и возвращает объект datetime в UTC.

    Args:
        datetime_str: Строка даты и времени в формате 'DD.MM.YYYY HH:MM'.
        user_tz_str: Строка таймзоны пользователя (IANA).

    Returns:
        Объект datetime в UTC, если валидация успешна и дата в будущем,
        иначе None.
    """
    if not isinstance(datetime_str, str) or not isinstance(user_tz_str, str):
        return None

    # 1. Валидация таймзоны пользователя
    if not validate_iana_timezone(user_tz_str):
        return None

    # 2. Парсинг строки даты и времени
    try:
        # Сначала парсим как наивное время
        naive_dt = datetime.datetime.strptime(datetime_str, '%d.%m.%Y %H:%M')
    except (ValueError, TypeError):
        # Ошибка формата или некорректная дата/время
        return None

    # 3. Локализация и конвертация в UTC
    try:
        user_tz = pytz.timezone(user_tz_str)
        # Локализуем наивное время в таймзоне пользователя
        localized_dt = user_tz.localize(naive_dt)
        # Конвертируем в UTC
        utc_dt = localized_dt.astimezone(pytz.utc)
    except pytz.UnknownTimeZoneError:
        # Хотя мы уже проверили, это дополнительная страховка
        return None
    except Exception:
        # Прочие ошибки локализации/конвертации
        return None

    # 4. Проверка, что время в будущем
    # Получаем текущее время в UTC
    now_utc = pytz.utc.localize(datetime.datetime.utcnow())

    if utc_dt <= now_utc:
        # Дата и время не в будущем
        return None

    # Все проверки пройдены, возвращаем объект datetime в UTC
    return utc_dt


# Сделаны публичными, убран префикс '_'
def is_valid_time_format(time_str: Any) -> bool:
    """Проверяет формат строки времени HH:MM."""
    if not isinstance(time_str, str):
        return False
    return bool(TIME_FORMAT_REGEX.match(time_str))

# Сделаны публичными, убран префикс '_'
def is_valid_day_month_format(day_month_str: Any) -> bool:
    """Проверяет формат строки дня и месяца DD.MM и базовую корректность."""
    if not isinstance(day_month_str, str):
        return False
    if not DAY_MONTH_FORMAT_REGEX.match(day_month_str):
        return False
    # Дополнительная проверка на корректность даты (например, 31.02)
    try:
        day, month = map(int, day_month_str.split('.'))
        # Создаем дату, чтобы проверить ее корректность. Год не важен, используем 2000 как високосный для 29 февраля.
        datetime.date(2000 if month == 2 and day == 29 else 2001, month, day)
        return True
    except ValueError:
        return False


def validate_cron_params(params: Dict[str, Any], schedule_type: str) -> bool:
    """
    Проверяет корректность словаря параметров для циклической задачи.

    Args:
        params: Словарь параметров задачи.
        schedule_type: Тип расписания ('daily', 'weekly', 'monthly', 'yearly').

    Returns:
        True, если параметры корректны для данного типа, иначе False.
    """
    if not isinstance(params, dict) or not isinstance(schedule_type, str):
        return False

    if schedule_type == 'daily':
        # Требует: 'time' (HH:MM)
        if 'time' not in params or not is_valid_time_format(params['time']): # Используем публичную функцию
            return False

    elif schedule_type == 'weekly':
        # Требует: 'days_of_week' (list[str 'mon'-'sun']) и 'time' (HH:MM)
        if ('days_of_week' not in params or not isinstance(params['days_of_week'], list) or
                not params['days_of_week'] or  # Список не должен быть пустым
                any(day not in ALLOWED_WEEK_DAYS for day in params['days_of_week'])):
            return False
        if 'time' not in params or not is_valid_time_format(params['time']): # Используем публичную функцию
            return False

    elif schedule_type == 'monthly':
        # Требует: 'day_of_month' (int 1-31) и 'time' (HH:MM)
        if ('day_of_month' not in params or not isinstance(params['day_of_month'], int) or
                not (1 <= params['day_of_month'] <= 31)):
            return False
        if 'time' not in params or not is_valid_time_format(params['time']): # Используем публичную функцию
            return False

    elif schedule_type == 'yearly':
        # Требует: 'month_day' (DD.MM) и 'time' (HH:MM)
        if 'month_day' not in params or not is_valid_day_month_format(params['month_day']): # Используем публичную функцию
            return False
        if 'time' not in params or not is_valid_time_format(params['time']): # Используем публичную функцию
            return False

    else:
        # Неизвестный тип расписания
        return False

    # Проверки для конкретного типа пройдены
    return True


def validate_media_properties(file_size: Optional[int] = None, mime_type: Optional[str] = None, url: Optional[str] = None) -> bool:
    """
    Валидирует свойства медиафайла: размер и MIME-тип.
    Добавлена базовая валидация URL для ссылок.

    Args:
        file_size: Размер файла в байтах (необязательно).
        mime_type: MIME-тип файла (необязательно).
        url: URL файла (необязательно, для валидации при загрузке по ссылке).

    Returns:
        True, если все предоставленные параметры валидны, иначе False.
        Если ни один параметр не предоставлен, возвращает True.
    """
    if file_size is not None:
        if not isinstance(file_size, int) or file_size < 0 or file_size > MAX_FILE_SIZE_BYTES:
            return False

    if mime_type is not None:
        # Case-insensitive check for mime type
        if not isinstance(mime_type, str) or mime_type.lower() not in ALLOWED_MIME_TYPES:
            return False

    if url is not None:
        if not validate_url(url): # Use the existing validate_url function
            return False

    # Если ни один параметр не предоставлен или все предоставленные валидны
    return True


def validate_url(url_str: str) -> bool:
    """
    Проверяет, является ли строка корректным HTTP или HTTPS URL.

    Args:
        url_str: Строка для проверки.

    Returns:
        True, если строка является валидным URL с http/https схемой, иначе False.
    """
    if not isinstance(url_str, str):
        return False
    return bool(URL_REGEX.match(url_str))


def validate_channel_username(username_str: str) -> bool:
    """
    Проверяет, соответствует ли строка правилам Telegram для юзернеймов каналов.

    Args:
        username_str: Строка для проверки (может начинаться с '@').

    Returns:
        True, если строка является валидным юзернеймом канала, иначе False.
    """
    if not isinstance(username_str, str):
        return False
    # Удаляем префикс '@', если он есть
    cleaned_username = username_str.lstrip('@')
    return bool(CHANNEL_USERNAME_REGEX.match(cleaned_username))

if __name__ == '__main__':
    # Примеры использования и тесты
    print("--- Тесты validate_iana_timezone ---")
    print(f"Europe/Berlin: {validate_iana_timezone('Europe/Berlin')}") # True
    print(f"Invalid/Timezone: {validate_iana_timezone('Invalid/Timezone')}") # False
    print(f"None: {validate_iana_timezone(None)}") # False
    print(f"'' (empty): {validate_iana_timezone('')}") # False

    print("\n--- Тесты validate_datetime_format_and_future ---")
    # Проверка будущей даты/времени
    # Using datetime.now(pytz.utc) directly for timezone-aware 'now'
    now_utc_test = pytz.utc.localize(datetime.datetime.utcnow())
    future_dt_utc_test = now_utc_test + datetime.timedelta(minutes=5)
    past_dt_utc_test = now_utc_test - datetime.timedelta(minutes=5)

    # Convert UTC test times to Europe/Berlin string for input simulation
    berlin_tz_test = pytz.timezone('Europe/Berlin')
    future_dt_str = future_dt_utc_test.astimezone(berlin_tz_test).strftime('%d.%m.%Y %H:%M')
    past_dt_str = past_dt_utc_test.astimezone(berlin_tz_test).strftime('%d.%m.%Y %H:%M')
    invalid_format_dt_str = "01-01-2023 12:00"
    invalid_date_str = "31.02.2024 12:00" # Февраля 31 нет

    print(f"Будущее время '{future_dt_str}' в 'Europe/Berlin': {validate_datetime_format_and_future(future_dt_str, 'Europe/Berlin') is not None}") # True
    print(f"Прошлое время '{past_dt_str}' в 'Europe/Berlin': {validate_datetime_format_and_future(past_dt_str, 'Europe/Berlin') is not None}") # False
    print(f"Некорректный формат '{invalid_format_dt_str}' в 'Europe/Berlin': {validate_datetime_format_and_future(invalid_format_dt_str, 'Europe/Berlin') is not None}") # False
    print(f"Некорректная дата '{invalid_date_str}' в 'Europe/Berlin': {validate_datetime_format_and_future(invalid_date_str, 'Europe/Berlin') is not None}") # False
    print(f"Будущее время с невалидной таймзоной 'Invalid/TZ': {validate_datetime_format_and_future(future_dt_str, 'Invalid/TZ') is not None}") # False
    print(f"None: {validate_datetime_format_and_future(None, 'Europe/Berlin') is not None}") # False

    print("\n--- Тесты validate_cron_params ---")
    # daily
    print(f"daily valid {{'time': '10:30'}}: {validate_cron_params({'time': '10:30'}, 'daily')}") # True
    print(f"daily missing time: {validate_cron_params({}, 'daily')}") # False
    print(f"daily invalid time {{'time': '25:00'}}: {validate_cron_params({'time': '25:00'}, 'daily')}") # False
    # weekly
    print(f"weekly valid {{'days_of_week': ['mon', 'wed'], 'time': '11:00'}}: {validate_cron_params({'days_of_week': ['mon', 'wed'], 'time': '11:00'}, 'weekly')}") # True
    print(f"weekly invalid day {{'days_of_week': ['funday'], 'time': '11:00'}}: {validate_cron_params({'days_of_week': ['funday'], 'time': '11:00'}, 'weekly')}") # False
    print(f"weekly empty days {{'days_of_week': [], 'time': '11:00'}}: {validate_cron_params({'days_of_week': [], 'time': '11:00'}, 'weekly')}") # False
    print(f"weekly missing time: {validate_cron_params({'days_of_week': ['mon']}, 'weekly')}") # False
    # monthly
    print(f"monthly valid {{'day_of_month': 15, 'time': '12:00'}}: {validate_cron_params({'day_of_month': 15, 'time': '12:00'}, 'monthly')}") # True
    print(f"monthly invalid day {{'day_of_month': 32, 'time': '12:00'}}: {validate_cron_params({'day_of_month': 32, 'time': '12:00'}, 'monthly')}") # False
    print(f"monthly invalid day type {{'day_of_month': '15', 'time': '12:00'}}: {validate_cron_params({'day_of_month': '15', 'time': '12:00'}, 'monthly')}") # False
    print(f"monthly missing time: {validate_cron_params({'day_of_month': 15}, 'monthly')}") # False
    # yearly
    print(f"yearly valid {{'month_day': '25.12', 'time': '13:00'}}: {validate_cron_params({'month_day': '25.12', 'time': '13:00'}, 'yearly')}") # True
    print(f"yearly invalid month_day format {{'month_day': '12/25', 'time': '13:00'}}: {validate_cron_params({'month_day': '12/25', 'time': '13:00'}, 'yearly')}") # False
    print(f"yearly invalid month_day value {{'month_day': '32.13', 'time': '13:00'}}: {validate_cron_params({'month_day': '32.13', 'time': '13:00'}, 'yearly')}") # False
    print(f"yearly missing time: {validate_cron_params({'month_day': '01.01'}, 'yearly')}") # False
    # invalid type
    print(f"invalid schedule_type: {validate_cron_params({}, 'hourly')}") # False

    print("\n--- Тесты validate_media_properties ---")
    print(f"Valid size (1MB): {validate_media_properties(file_size=1024*1024)}") # True
    print(f"Invalid size (21MB): {validate_media_properties(file_size=21*1024*1024)}") # False
    print(f"Valid mime (image/jpeg): {validate_media_properties(mime_type='image/jpeg')}") # True
    print(f"Invalid mime (text/plain): {validate_media_properties(mime_type='text/plain')}") # False
    print(f"Valid size and mime: {validate_media_properties(file_size=5*1024*1024, mime_type='video/mp4')}") # True
    print(f"Valid size, invalid mime: {validate_media_properties(file_size=5*1024*1024, mime_type='application/zip')}") # False
    print(f"Invalid size, valid mime: {validate_media_properties(file_size=30*1024*1024, mime_type='image/png')}") # False
    print(f"Valid URL: {validate_media_properties(url='https://example.com/image.jpg')}") # True
    print(f"Invalid URL: {validate_media_properties(url='invalid-url')}") # False
    print(f"Valid all: {validate_media_properties(file_size=1024, mime_type='image/jpeg', url='https://example.com/image.jpg')}") # True
    print(f"Invalid size, valid mime/url: {validate_media_properties(file_size=30*1024*1024, mime_type='image/png', url='https://example.com/image.png')}") # False
    print(f"No params: {validate_media_properties()}") # True
    print(f"None file_size: {validate_media_properties(file_size=None, mime_type='image/jpeg')}") # True
    print(f"None mime_type: {validate_media_properties(file_size=1024, mime_type=None)}") # True
    print(f"None url: {validate_media_properties(url=None, mime_type='image/jpeg')}") # True


    print("\n--- Тесты validate_url ---")
    print(f"Valid http: {validate_url('http://example.com')}") # True
    print(f"Valid https with path: {validate_url('https://www.google.com/search?q=test')}") # True
    print(f"Valid localhost: {validate_url('http://localhost:8080')}") # True
    print(f"Valid IP: {validate_url('http://192.168.1.1')}") # True
    print(f"Invalid scheme: {validate_url('ftp://example.com')}") # False
    print(f"Missing scheme: {validate_url('www.example.com')}") # False
    print(f"Invalid format: {validate_url('just a string')}") # False
    print(f"None: {validate_url(None)}") # False

    print("\n--- Тесты validate_channel_username ---")
    print(f"Valid: {validate_channel_username('valid_username123')}") # True
    print(f"Valid with @: {validate_channel_username('@another_username')}") # True
    print(f"Too short (4 chars): {validate_channel_username('short')}") # False
    print(f"Too long (33 chars): {validate_channel_username('a_very_long_username_that_is_too_long')}") # False
    print(f"Invalid characters: {validate_channel_username('user-name!')}") # False
    print(f"Empty string: {validate_channel_username('')}") # False
    print(f"None: {validate_channel_username(None)}") # False
"""

# Content for utils/helpers.py (from task Bz47C)
UTILS_HELPERS_CONTENT = """
# -*- coding: utf-8 -*-

"""
Вспомогательные функции для различных операций.
"""

from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any, Union
import json
import pytz
import re
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError


def format_datetime_for_user(dt_utc: datetime, user_tz_str: str) -> Optional[str]:
    """
    Форматирует datetime объект из UTC в таймзону пользователя и возвращает строку DD.MM.YYYY HH:MM.

    :param dt_utc: datetime объект в UTC (должен быть aware).
    :param user_tz_str: Строка таймзоны пользователя (например, 'Europe/Moscow').
    :return: Отформатированная строка или None, если таймзона невалидна или dt_utc наивный.
    """
    if dt_utc is None or dt_utc.tzinfo is None or dt_utc.tzinfo.utcoffset(dt_utc) is None:
        # Должен быть UTC-aware datetime
        return None

    try:
        user_tz = pytz.timezone(user_tz_str)
    except pytz.UnknownTimeZoneError:
        return None

    try:
        dt_user = dt_utc.astimezone(user_tz)
        return dt_user.strftime('%d.%m.%Y %H:%M')
    except Exception:
        # Общий случай для других возможных ошибок конвертации/форматирования
        return None


def parse_time_str(time_str: str) -> Optional[Tuple[int, int]]:
    """
    Парсит строку времени в формате HH:MM.

    :param time_str: Строка времени.
    :return: Кортеж (час, минута) или None, если формат некорректен.
    """
    match = re.match(r'^(\d{2}):(\d{2})$', time_str)
    if not match:
        return None

    try:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
        else:
            return None
    except ValueError:
        # На всякий случай, хотя regex должен предотвратить нечисловые символы
        return None


def safe_serialize_json(data: Any, ensure_ascii: bool = False, indent: Optional[int] = None) -> Optional[str]:
    """
    Безопасно сериализует данные в JSON строку, обрабатывая TypeError.

    :param data: Данные для сериализации.
    :param ensure_ascii: Если False, позволяет использовать не-ASCII символы.
    :param indent: Количество пробелов для отступа.
    :return: JSON строка или None в случае ошибки.
    """
    try:
        return json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    except TypeError:
        return None


def safe_deserialize_json(json_str: str) -> Optional[Any]:
    """
    Безопасно десериализует JSON строку в Python объект, обрабатывая JSONDecodeError.

    :param json_str: JSON строка для десериализации.
    :return: Python объект или None в случае ошибки.
    """
    if not isinstance(json_str, str):
         return None
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def convert_datetime_to_utc(dt_user_naive: datetime, user_tz_str: str) -> Optional[datetime]:
    """
    Конвертирует наивный datetime объект в таймзоне пользователя в UTC-aware datetime.

    :param dt_user_naive: Наивный datetime объект в таймзоне пользователя.
    :param user_tz_str: Строка таймзоны пользователя.
    :return: datetime объект в UTC или None, если таймзона невалидна.
    """
    if dt_user_naive is None or dt_user_naive.tzinfo is not None:
        # Должен быть naive datetime
        return None

    try:
        user_tz = pytz.timezone(user_tz_str)
    except pytz.UnknownTimeZoneError:
        return None

    try:
        dt_user_aware = user_tz.localize(dt_user_naive)
        dt_utc = dt_user_aware.astimezone(pytz.utc)
        return dt_utc
    except Exception:
        # Обработка DST переходов и других возможных ошибок локализации/конвертации
        return None


def convert_datetime_from_utc(dt_utc: datetime, user_tz_str: str) -> Optional[datetime]:
    """
    Конвертирует UTC-aware datetime объект в datetime объект в таймзоне пользователя.

    :param dt_utc: datetime объект в UTC (должен быть aware).
    :param user_tz_str: Строка таймзоны пользователя.
    :return: datetime объект в таймзоне пользователя или None, если таймзона невалидна или dt_utc наивный.
    """
    if dt_utc is None or dt_utc.tzinfo is None or dt_utc.tzinfo.utcoffset(dt_utc) is None:
        # Должен быть UTC-aware datetime
        return None

    try:
        user_tz = pytz.timezone(user_tz_str)
    except pytz.UnknownTimeZoneError:
        return None

    try:
        dt_user = dt_utc.astimezone(user_tz)
        return dt_user
    except Exception:
        # Общий случай для других возможных ошибок конвертации
        return None


async def check_if_user_is_admin(bot: Bot, chat_id: Union[int, str], user_id: int) -> Optional[bool]:
    """
    Проверяет, является ли пользователь администратором или создателем чата.

    :param bot: Экземпляр aiogram.Bot.
    :param chat_id: ID чата.
    :param user_id: ID пользователя.
    :return: True, если пользователь админ/создатель, False если нет, None в случае ошибки API.
    """
    try:
        chat_member = await bot.get_chat_member(chat_id, user_id)
        # Проверяем статус пользователя
        return chat_member.status in ['administrator', 'creator']
    except TelegramAPIError:
        # Обработка ошибок API (например, бот не в чате, чат не найден и т.д.)
        return None
    except Exception:
         # Общая обработка других исключений
        return None


async def check_if_bot_is_admin(bot: Bot, chat_id: Union[int, str]) -> Optional[bool]:
    """
    Проверяет, является ли бот администратором в чате и имеет ли право can_post_messages.

    :param bot: Экземпляр aiogram.Bot.
    :param chat_id: ID чата.
    :return: True, если бот админ с правом can_post_messages, False если нет, None в случае ошибки API.
    """
    try:
        # Получаем информацию о боте как члене чата
        chat_member = await bot.get_chat_member(chat_id, bot.id)

        # Проверяем, является ли статус администратором или создателем
        is_admin_or_creator = chat_member.status in ['administrator', 'creator']

        # Если бот администратор, проверяем право can_post_messages
        # ChatMember object dynamically changes attributes based on status.
        # Use isinstance to check if it has admin-specific attributes.
        if is_admin_or_creator:
             # Check for the specific attribute directly using getattr for safety
            return getattr(chat_member, 'can_post_messages', False) is True
        else:
            # Если статус не администратор/создатель, бот не админ
            return False

    except TelegramAPIError:
        # Обработка ошибок API (например, бот не в чате, чат не найден и т.д.)
        return None
    except Exception:
         # Общая обработка других исключений
        return None
"""

# Content for keyboards/reply_keyboards.py (from task t3xMy)
KEYBOARDS_REPLY_CONTENT = """
# keyboards/reply_keyboards.py

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Определение кнопок для удобства
BTN_NEW_POST = KeyboardButton(text="➕ Новый пост")
BTN_MY_POSTS = KeyboardButton(text="🗂 Мои посты")
BTN_ADD_CHANNEL = KeyboardButton(text="➕ Добавить канал")
BTN_DELETE_CHANNEL = KeyboardButton(text="🗑 Удалить канал")
BTN_MY_CHANNELS = KeyboardButton(text="📋 Мои каналы")
BTN_SET_TIMEZONE = KeyboardButton(text="🕑 Установить часовой пояс")
BTN_ADD_RSS = KeyboardButton(text="📰 Добавить RSS")
BTN_HELP = KeyboardButton(text="❓ Помощь")

BTN_ADD_MEDIA = KeyboardButton(text="Добавить медиа")
BTN_SKIP = KeyboardButton(text="Пропустить")
BTN_CANCEL = KeyboardButton(text="❌ Отменить")

BTN_NEXT = KeyboardButton(text="✅ Далее")
BTN_EDIT_CONTENT = KeyboardButton(text="✏️ Редактировать контент")

BTN_BACK_TO_MAIN = KeyboardButton(text="⬅️ Назад в главное меню")

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Генерирует клавиатуру для главного меню.
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [BTN_NEW_POST, BTN_MY_POSTS],
            [BTN_ADD_CHANNEL, BTN_DELETE_CHANNEL],
            [BTN_MY_CHANNELS, BTN_SET_TIMEZONE],
            [BTN_ADD_RSS, BTN_HELP]
        ],
        resize_keyboard=True # Делает клавиатуру компактной
    )
    return keyboard

def get_post_media_options_keyboard() -> ReplyKeyboardMarkup:
    """
    Генерирует клавиатуру для шага выбора медиа при создании поста.
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [BTN_ADD_MEDIA],
            [BTN_SKIP],
            [BTN_CANCEL]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_post_draft_actions_keyboard() -> ReplyKeyboardMarkup:
    """
    Генерирует клавиатуру для действий с черновиком поста после добавления/пропуска медиа.
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [BTN_NEXT, BTN_EDIT_CONTENT],
            [BTN_CANCEL]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_channel_management_keyboard() -> ReplyKeyboardMarkup:
    """
    Генерирует клавиатуру для меню управления каналами.
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [BTN_ADD_CHANNEL, BTN_DELETE_CHANNEL],
            [BTN_MY_CHANNELS],
            [BTN_BACK_TO_MAIN]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    """
    Генерирует универсальную клавиатуру с кнопкой "Отменить" для FSM.
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [BTN_CANCEL]
        ],
        resize_keyboard=True,
        one_time_keyboard=True # Клавиатура скроется после использования
    )
    return keyboard
"""

# Content for keyboards/inline_keyboards.py (from task t3xMy)
KEYBOARDS_INLINE_CONTENT = """
# keyboards/inline_keyboards.py
# Модуль для генерации Inline-клавиатур бота

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from enum import Enum

# --- CallbackData фабрики ---

# CallbackData для подтверждения/редактирования/отмены создания поста
class ConfirmPostCreationCallback(CallbackData, prefix='confirm_post'):
    action: str # Действие: 'confirm', 'edit', 'cancel'

# CallbackData для опций редактирования черновика поста
class EditDraftOptionsCallback(CallbackData, prefix='edit_draft_opt'):
    action: str # Действие: 'content', 'channels', 'schedule', 'delete'

# CallbackData для выбора типа расписания
class ScheduleTypeCallback(CallbackData, prefix='sched_type'):
    type: str # Тип: 'one_time', 'recurring', 'back'

# CallbackData для выбора типа циклического расписания
class RecurringTypeCallback(CallbackData, prefix='recur_type'):
    type: str # Тип: 'daily', 'weekly', 'monthly', 'yearly', 'back'

# CallbackData для выбора дня недели
class SelectDayOfWeekCallback(CallbackData, prefix='day_select'):
    day: int # Номер дня недели (0 - Пн, 6 - Вс)
    action: str # Действие: 'toggle' (выбрать/снять выбор), 'done', 'back'

# CallbackData для опций удаления поста
class DeleteOptionsCallback(CallbackData, prefix='del_opt'):
    type: str # Тип удаления: 'never', 'hours', 'days', 'date', 'back'

# CallbackData для действий над постом пользователя (список постов)
class UserPostItemActionsCallback(CallbackData, prefix='user_post'):
    post_id: int
    action: str # Действие: 'edit', 'delete'

# CallbackData для подтверждения удаления поста
class ConfirmDeletePostCallback(CallbackData, prefix='confirm_del_post'):
    post_id: int
    confirm: bool # Подтверждение: True/False

# CallbackData для действий над RSS-лентой
class RssFeedItemActionsCallback(CallbackData, prefix='rss_feed'):
    feed_id: int
    action: str # Действие: 'delete'

# CallbackData для выбора канала из списка
class SelectChannelCallback(CallbackData, prefix='sel_ch'):
    channel_id: int
    action: str # Действие: 'toggle' (выбрать/снять выбор)

# CallbackData для кнопок "Готово" и "Отменить" при выборе каналов
class ChannelSelectionControlCallback(CallbackData, prefix='chan_sel_ctrl'):
    action: str # Действие: 'done', 'cancel'

# CallbackData для меню редактирования существующего поста
class EditPostMenuCallback(CallbackData, prefix='edit_post_menu'):
    post_id: int
    action: str # Действие: 'content', 'channels', 'schedule', 'delete', 'back'


# --- Функции генерации клавиатур ---

# Клавиатура для подтверждения создания поста
def get_confirm_post_creation_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=ConfirmPostCreationCallback(action='confirm').pack()
            ),
            InlineKeyboardButton(
                text="✏️ Редактировать",
                callback_data=ConfirmPostCreationCallback(action='edit').pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data=ConfirmPostCreationCallback(action='cancel').pack()
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для опций редактирования черновика поста
def get_edit_draft_options_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="Контент",
                callback_data=EditDraftOptionsCallback(action='content').pack()
            ),
            InlineKeyboardButton(
                text="Каналы",
                callback_data=EditDraftOptionsCallback(action='channels').pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="Расписание",
                callback_data=EditDraftOptionsCallback(action='schedule').pack()
            ),
             InlineKeyboardButton(
                text="Удаление",
                callback_data=EditDraftOptionsCallback(action='delete').pack()
            ),
        ],
         [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=EditDraftOptionsCallback(action='back').pack()
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Клавиатура для выбора типа расписания
def get_schedule_type_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="Разовый",
                callback_data=ScheduleTypeCallback(type='one_time').pack()
            )
        ],
        [
            InlineKeyboardButton(
                text="Циклический",
                callback_data=ScheduleTypeCallback(type='recurring').pack()
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=ScheduleTypeCallback(type='back').pack()
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для выбора типа циклического расписания
def get_recurring_type_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="Ежедневно",
                callback_data=RecurringTypeCallback(type='daily').pack()
            ),
            InlineKeyboardButton(
                text="Еженедельно",
                callback_data=RecurringTypeCallback(type='weekly').pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="Ежемесячно",
                callback_data=RecurringTypeCallback(type='monthly').pack()
            ),
            InlineKeyboardButton(
                text="Ежегодно",
                callback_data=RecurringTypeCallback(type='yearly').pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=RecurringTypeCallback(type='back').pack()
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для выбора дней недели
def get_days_of_week_keyboard(selected_days: list) -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру с днями недели для выбора.
    selected_days - список выбранных номеров дней (0-6).
    """
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    # Кнопки дней недели, отмечаем выбранные
    day_buttons = [
        InlineKeyboardButton(
            text=f"{day_names[i]} {'✅' if i in selected_days else ''}".strip(),
            callback_data=SelectDayOfWeekCallback(day=i, action='toggle').pack()
        ) for i in range(7)
    ]
    # Размещаем дни по 3 в ряд, последний ряд - 1 день
    rows = [day_buttons[i:i+3] for i in range(0, len(day_buttons), 3)]

    # Добавляем кнопки "Готово" и "Назад"
    control_buttons = [
        InlineKeyboardButton(
            text="Готово",
            callback_data=SelectDayOfWeekCallback(day=-1, action='done').pack() # day=-1 т.к. не относится к выбору дня
        ),
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=SelectDayOfWeekCallback(day=-1, action='back').pack() # day=-1
        )
    ]
    rows.append(control_buttons)

    return InlineKeyboardMarkup(inline_keyboard=rows)

# Клавиатура для опций удаления поста
def get_delete_options_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="Не удалять",
                callback_data=DeleteOptionsCallback(type='never').pack()
            )
        ],
         [
            InlineKeyboardButton(
                text="Через часы",
                callback_data=DeleteOptionsCallback(type='hours').pack()
            ),
            InlineKeyboardButton(
                text="Через дни",
                callback_data=DeleteOptionsCallback(type='days').pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="По дате",
                callback_data=DeleteOptionsCallback(type='date').pack()
            )
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=DeleteOptionsCallback(type='back').pack()
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для действий над элементом поста в списке пользователя
def get_user_post_item_actions_keyboard(post_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="✏️ Редактировать",
                callback_data=UserPostItemActionsCallback(post_id=post_id, action='edit').pack()
            ),
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=UserPostItemActionsCallback(post_id=post_id, action='delete').pack()
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для подтверждения удаления поста
def get_confirm_delete_post_keyboard(post_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="Да, удалить",
                callback_data=ConfirmDeletePostCallback(post_id=post_id, confirm=True).pack()
            ),
            InlineKeyboardButton(
                text="Нет",
                callback_data=ConfirmDeletePostCallback(post_id=post_id, confirm=False).pack()
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для действий над элементом RSS-ленты
def get_rss_feed_item_actions_keyboard(feed_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="🗑 Удалить RSS",
                callback_data=RssFeedItemActionsCallback(feed_id=feed_id, action='delete').pack()
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для выбора каналов
def get_select_channels_keyboard(available_channels: list, selected_channel_ids: list) -> InlineKeyboardMarkup:
    """
    Генерирует клавиатуру со списком каналов для выбора.
    available_channels - список кортежей или объектов канала (id, name).
    selected_channel_ids - список выбранных id каналов.
    """
    buttons = []
    for channel_id, channel_name in available_channels:
        # Отмечаем выбранные каналы галочкой
        text = f"{channel_name} {'✅' if channel_id in selected_channel_ids else ''}".strip()
        buttons.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=SelectChannelCallback(channel_id=channel_id, action='toggle').pack()
                )
            ]
        )

    # Добавляем кнопки "Готово" и "Отменить"
    control_buttons = [
        InlineKeyboardButton(
            text="Готово",
            callback_data=ChannelSelectionControlCallback(action='done').pack()
        ),
        InlineKeyboardButton(
            text="Отменить",
            callback_data=ChannelSelectionControlCallback(action='cancel').pack()
        )
    ]
    buttons.append(control_buttons)

    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для меню редактирования существующего поста
def get_edit_post_menu_keyboard(post_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="Контент",
                callback_data=EditPostMenuCallback(post_id=post_id, action='content').pack()
            ),
            InlineKeyboardButton(
                text="Каналы",
                callback_data=EditPostMenuCallback(post_id=post_id, action='channels').pack()
            ),
        ],
        [
            InlineKeyboardButton(
                text="Расписание",
                callback_data=EditPostMenuCallback(post_id=post_id, action='schedule').pack()
            ),
             InlineKeyboardButton(
                text="Удаление",
                callback_data=EditPostMenuCallback(post_id=post_id, action='delete').pack()
            ),
        ],
         [
            InlineKeyboardButton(
                text="⬅️ Назад", # Кнопка "Назад" из меню редактирования
                callback_data=EditPostMenuCallback(post_id=post_id, action='back').pack()
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
"""

# Content for services/db_service.py (from task SrzpQ)
SERVICES_DB_CONTENT = """
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError # Import IntegrityError for specific handling

# Assuming models are defined in a 'models' directory
from models.user import User
from models.user_channel import UserChannel
from models.post import Post
from models.rss_feed import RssFeed
from models.rss_item import RssItem

# Assuming logger is configured in utils/logger.py
try:
    from utils.logger import logger
except ImportError as e:
    logging.error(f"Failed to import logger: {e}. Using basic logging.", exc_info=True)
    logger = logging.getLogger(__name__) # Fallback to basic logger

# Use logger for this service
service_logger = logging.getLogger(__name__)
service_logger.setLevel(logger.level if 'logger' in globals() else logging.INFO)


async def get_or_create_user(session: AsyncSession, telegram_user_id: int) -> User:
    """
    Получает пользователя по Telegram ID или создает нового, если не найден.
    Handles unique constraint violation gracefully. Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        telegram_user_id: Telegram ID пользователя.

    Returns:
        Объект User.
    Raises:
        Exception: If user creation fails after retry.
    """
    stmt = select(User).where(User.telegram_user_id == telegram_user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        service_logger.info(f"Attempting to create new user with Telegram ID: {telegram_user_id}")
        try:
            user = User(telegram_user_id=telegram_user_id)
            session.add(user)
            # No commit here. Caller manages transaction.
            # session.add marks the object as pending. It will be created on session commit.
            service_logger.debug(f"Staged new user {telegram_user_id}. Awaiting commit.")
            # await session.refresh(user) # Refresh requires flush/commit first, handled by caller if needed

        except IntegrityError:
            # This could happen in a race condition if another transaction
            # created the user after the initial select().
            # Rollback the pending state of the current session for safety,
            # although session management by caller should handle rollback on exceptions.
            # await session.rollback() # Removed explicit rollback - caller's responsibility
            service_logger.warning(f"IntegrityError during user creation for {telegram_user_id}. Likely race condition.")
            # Re-fetch the existing user
            stmt_retry = select(User).where(User.telegram_user_id == telegram_user_id)
            result_retry = await session.execute(stmt_retry)
            user = result_retry.scalar_one_or_none()
            if user:
                service_logger.info(f"Retrieved existing user {user.id} after IntegrityError.")
            else:
                 # If still None, something is seriously wrong (e.g., different DB error)
                 service_logger.error(f"Failed to retrieve user {telegram_user_id} after IntegrityError during creation.")
                 raise # Re-raise if user doesn't exist after handling IntegrityError

        except Exception as e:
            # await session.rollback() # Removed explicit rollback
            service_logger.error(f"Unexpected error creating user {telegram_user_id}: {e}", exc_info=True)
            raise # Re-raise other exceptions


    return user # Return staged or retrieved user


async def set_user_timezone(session: AsyncSession, user_id: int, timezone_str: str) -> Optional[User]:
    """
    Устанавливает таймзону пользователя по ID. Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя (из БД).
        timezone_str: Строка таймзоны (IANA).

    Returns:
        Обновленный объект User or None, if user not found.
        Returning the updated object requires commit/flush by the caller before accessing attributes not in update values.
    Raises:
        Exception: If staging fails.
    """
    try:
        # Use returning() to get the updated object *after* the caller commits
        stmt = update(User).where(User.id == user_id).values(timezone=timezone_str).returning(User)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none() # Object available *after* caller commits/flushes
        if user:
            service_logger.debug(f"Staged timezone update for user {user_id} to {timezone_str}. Awaiting commit.")
        else:
            service_logger.warning(f"User {user_id} not found for timezone update staging.")
        return user # Return the staged object

    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging timezone update for user {user_id}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def get_user_timezone(session: AsyncSession, user_id: int) -> Optional[str]:
    """
    Получает таймзону пользователя по ID.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя (из БД).

    Returns:
        Строка таймзоны или None, если пользователь не найден.
    """
    stmt = select(User.timezone).where(User.id == user_id)
    result = await session.execute(stmt)
    timezone = result.scalar_one_or_none()
    service_logger.debug(f"Retrieved timezone for user {user_id}: {timezone}")
    return timezone


async def add_user_channel(session: AsyncSession, user_id: int, chat_id: int, chat_username: Optional[str]) -> Optional[UserChannel]:
    """
    Добавляет канал/группу для пользователя. Проверяет на дублирование.
    If channel already exists for this user by chat_id, returns the existing one.
    If soft-deleted, reactivates it. Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя.
        chat_id: ID чата Telegram.
        chat_username: Юзернейм чата Telegram (опционально).

    Returns:
        Созданный или существующий объект UserChannel, или None в случае ошибки.
    Raises:
        Exception: If staging fails (excluding IntegrityError if using ON CONFLICT).
    """
    # Check if channel already exists for this user by chat_id
    stmt = select(UserChannel).where(
        UserChannel.user_id == user_id,
        UserChannel.chat_id == chat_id
    )
    result = await session.execute(stmt)
    existing_channel = result.scalar_one_or_none()

    if existing_channel:
        service_logger.warning(f"Channel {chat_id} already exists for user {user_id}. Returning existing.")
        # Optional: reactivate if it was soft-deleted
        if not existing_channel.is_active:
            existing_channel.is_active = True
            existing_channel.removed_at = None
            # No commit here. Caller manages transaction.
            session.add(existing_channel) # Mark for update
            service_logger.info(f"Staged reactivation of channel {existing_channel.id} (chat_id: {chat_id}) for user {user_id}. Awaiting commit.")

        return existing_channel # Return existing channel object

    try:
        channel = UserChannel(user_id=user_id, chat_id=chat_id, chat_username=chat_username, is_active=True)
        session.add(channel)
        # No commit here. Caller manages transaction.
        service_logger.info(f"Staged new channel (chat_id: {chat_id}) for user {user_id}. Awaiting commit.")
        return channel # Return staged new channel object

    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging channel add (chat_id: {chat_id}) for user {user_id}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def remove_user_channel(session: AsyncSession, user_id: int, channel_id: int) -> Optional[UserChannel]:
    """
    Удаляет (деактивирует) канал/группу пользователя по внутреннему ID канала.
    Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя.
        channel_id: Внутренний ID канала (из таблицы user_channels).

    Returns:
        Удаленный (деактивированный) объект UserChannel or None, if not found.
        Returning the updated object requires commit/flush by the caller.
    Raises:
        Exception: If staging fails.
    """
    # Soft delete by setting is_active=False and removed_at
    try:
        stmt = update(UserChannel)\
            .where(UserChannel.user_id == user_id, UserChannel.id == channel_id)\
            .values(is_active=False, removed_at=func.now())\
            .returning(UserChannel) # Keep returning to get the object
        result = await session.execute(stmt)
        # No commit here. Caller manages transaction.
        channel = result.scalar_one_or_none() # Object available *after* caller commits
        if channel:
            service_logger.info(f"Staged removal (deactivation) of channel {channel_id} for user {user_id}. Awaiting commit.")
        else:
            service_logger.warning(f"Channel {channel_id} not found for user {user_id} during removal attempt.")
        return channel
    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging channel removal {channel_id} for user {user_id}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def get_user_channels(session: AsyncSession, user_id: int, active_only: bool = True) -> List[UserChannel]:
    """
    Получает список каналов/групп для пользователя.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя.
        active_only: Если True, возвращает только активные каналы.

    Returns:
        Список объектов UserChannel.
    """
    stmt = select(UserChannel).where(UserChannel.user_id == user_id)
    # Fix PEP 8 warning: Use `is True` or omit `== True` for boolean comparisons
    if active_only:
        stmt = stmt.where(UserChannel.is_active.is_(True)) # Use is_() for explicit boolean comparison
    result = await session.execute(stmt)
    channels = result.scalars().all()
    service_logger.debug(f"Retrieved {len(channels)} channels for user {user_id} (active_only={active_only})")
    return channels


async def get_user_channel_by_username(session: AsyncSession, user_id: int, chat_username: str) -> Optional[UserChannel]:
    """
    Получает канал/группу пользователя по юзернейму.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя.
        chat_username: Юзернейм чата Telegram (начинается с @).

    Returns:
        Объект UserChannel или None, если не найден.
    """
    cleaned_username = chat_username.lstrip('@')
    stmt = select(UserChannel).where(
        UserChannel.user_id == user_id,
        UserChannel.chat_username == cleaned_username,
        UserChannel.is_active.is_(True) # Fix PEP 8 warning
    )
    result = await session.execute(stmt)
    channel = result.scalar_one_or_none()
    service_logger.debug(f"Retrieved channel by username '{chat_username}' for user {user_id}: {channel is not None}")
    return channel


async def get_user_channel_by_chat_id(session: AsyncSession, user_id: int, chat_id: int) -> Optional[UserChannel]:
    """
    Получает канал/группу пользователя по Telegram chat ID.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя.
        chat_id: Telegram ID чата.

    Returns:
        Объект UserChannel или None, если не найден.
    """
    stmt = select(UserChannel).where(
        UserChannel.user_id == user_id,
        UserChannel.chat_id == chat_id,
        UserChannel.is_active.is_(True) # Fix PEP 8 warning
    )
    result = await session.execute(stmt)
    channel = result.scalar_one_or_none()
    service_logger.debug(f"Retrieved channel by chat_id '{chat_id}' for user {user_id}: {channel is not None}")
    return channel


async def create_post(session: AsyncSession, **kwargs: Any) -> Optional[Post]:
    """
    Создает новый пост. Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        **kwargs: Параметры поста (user_id, chat_ids, text, media_paths, schedule_type, etc.).

    Returns:
        Созданный объект Post or None in case of error (excluding IntegrityError which might be handled by caller).
    Raises:
        Exception: If staging fails.
    """
    try:
        post = Post(**kwargs)
        session.add(post)
        # No commit/refresh here. Caller manages transaction.
        service_logger.info(f"Staged new post for user {kwargs.get('user_id')}. Status: {kwargs.get('status')}. Awaiting commit.")
        return post # Return staged object
    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging post creation for user {kwargs.get('user_id')}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def get_post_by_id(session: AsyncSession, post_id: int) -> Optional[Post]:
    """
    Получает пост по его внутреннему ID.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        post_id: Внутренний ID поста.

    Returns:
        Объект Post или None, если не найден.
    """
    stmt = select(Post).where(Post.id == post_id)
    result = await session.execute(stmt)
    post = result.scalar_one_or_none()
    service_logger.debug(f"Retrieved post {post_id}: {post is not None}")
    return post


async def get_user_posts(session: AsyncSession, user_id: int, status: Optional[str] = None) -> List[Post]:
    """
    Получает список постов пользователя, возможно, фильтруя по статусу.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя.
        status: Статус поста ('scheduled', 'sent', 'deleted', 'invalid', 'draft').

    Returns:
        Список объектов Post.
    """
    stmt = select(Post).where(Post.user_id == user_id)
    if status:
        stmt = stmt.where(Post.status == status)
    # Order by creation date
    stmt = stmt.order_by(Post.created_at.desc())
    result = await session.execute(stmt)
    posts = result.scalars().all()
    service_logger.debug(f"Retrieved {len(posts)} posts for user {user_id} (status='{status}')")
    return posts


async def get_all_scheduled_posts(session: AsyncSession) -> List[Post]:
    """
    Получает все посты со статусом 'scheduled'.

    Args:
        session: Асинхронная сессия SQLAlchemy.

    Returns:
        Список объектов Post.
    """
    stmt = select(Post).where(Post.status == 'scheduled')
    result = await session.execute(stmt)
    posts = result.scalars().all()
    service_logger.debug(f"Retrieved {len(posts)} posts with status 'scheduled'")
    return posts


async def update_post_data(session: AsyncSession, post_id: int, **kwargs: Any) -> Optional[Post]:
    """
    Обновляет данные поста по его ID. Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        post_id: Внутренний ID поста.
        **kwargs: Данные для обновления.

    Returns:
        Обновленный объект Post or None if not found.
    Raises:
        Exception: If staging fails.
    """
    try:
        # Ensure updated_at is updated implicitly by the model's default or explicitly
        # if 'updated_at' not in kwargs:
        #      kwargs['updated_at'] = func.now() # Model's onupdate handles this

        stmt = update(Post).where(Post.id == post_id).values(**kwargs).returning(Post) # Keep returning
        result = await session.execute(stmt)
        # No commit here. Caller manages transaction.
        post = result.scalar_one_or_none() # Object available *after* caller commits
        if post:
            service_logger.info(f"Staged update for post {post_id}. New status: {kwargs.get('status', post.status)}. Awaiting commit.")
        else:
            service_logger.warning(f"Post {post_id} not found during update attempt.")
        return post
    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging update for post {post_id}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def delete_post_by_id(session: AsyncSession, post_id: int) -> Optional[Post]:
    """
    Удаляет пост по его ID (мягкое удаление). Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        post_id: Внутренний ID поста.

    Returns:
        Удаленный (деактивированный) объект Post or None if not found.
    Raises:
        Exception: If staging fails.
    """
    # Soft delete by setting status to 'deleted'
    try:
        # Use update instead of delete for soft deletion
        stmt = update(Post).where(Post.id == post_id).values(status='deleted', updated_at=func.now()).returning(Post) # Keep returning
        result = await session.execute(stmt)
        # No commit here. Caller manages transaction.
        post = result.scalar_one_or_none() # Object available *after* caller commits
        if post:
            service_logger.info(f"Staged soft-delete for post {post_id}. Awaiting commit.")
        else:
            service_logger.warning(f"Post {post_id} not found during soft-delete attempt.")
        return post
    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging soft-delete for post {post_id}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def add_rss_feed(session: AsyncSession, **kwargs: Any) -> Optional[RssFeed]:
    """
    Добавляет новую RSS-ленту для пользователя.
    If feed already exists for the user and URL, returns the existing one.
    Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        **kwargs: Параметры ленты (user_id, feed_url, channels, frequency_minutes, filter_keywords).

    Returns:
        Созданный или существующий объект RssFeed, или None в случае ошибки.
    Raises:
        Exception: If staging fails (excluding unique constraint handled by caller).
    """
    # Check for existing feed for the same user and URL if needed
    # This check can be done before calling this function, or handle IntegrityError here.
    # Let's handle the check before calling this function in handlers for user feedback.
    # So, this function assumes it's being called to add a potentially new feed.

    try:
        feed = RssFeed(**kwargs)
        session.add(feed)
        # No commit here. Caller manages transaction.
        service_logger.info(f"Staged new RSS feed for user {feed.user_id}, url {feed.feed_url}. Awaiting commit.")
        return feed # Return staged object

    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging RSS feed creation for user {kwargs.get('user_id')}, url {kwargs.get('feed_url')}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def get_rss_feed_by_id(session: AsyncSession, feed_id: int) -> Optional[RssFeed]:
    """
    Получает RSS-ленту по ее ID.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        feed_id: Внутренний ID ленты.

    Returns:
        Объект RssFeed или None, если не найден.
    """
    stmt = select(RssFeed).where(RssFeed.id == feed_id)
    result = await session.execute(stmt)
    feed = result.scalar_one_or_none()
    service_logger.debug(f"Retrieved RSS feed {feed_id}: {feed is not None}")
    return feed


async def get_user_rss_feeds(session: AsyncSession, user_id: int) -> List[RssFeed]:
    """
    Получает список RSS-лент пользователя.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        user_id: Внутренний ID пользователя.

    Returns:
        Список объектов RssFeed.
    """
    stmt = select(RssFeed).where(RssFeed.user_id == user_id)
    # Optional: Add filtering for active feeds if model supports it
    # stmt = stmt.where(RssFeed.is_active.is_(True)) # If RssFeed model had is_active
    result = await session.execute(stmt)
    feeds = result.scalars().all()
    service_logger.debug(f"Retrieved {len(feeds)} RSS feeds for user {user_id}")
    return feeds


async def get_all_active_rss_feeds(session: AsyncSession) -> List[RssFeed]:
    """
    Получает все активные RSS-ленты. Предполагая, что нет флага is_active
    и все записи в таблице 'rss_feeds' считаются активными.
    Если требуется флаг активности, модель RssFeed должна быть обновлена.

    Args:
        session: Асинхронная сессия SQLAlchemy.

    Returns:
        Список объектов RssFeed.
    """
    # Assuming all entries are active. Add filtering if needed.
    stmt = select(RssFeed)
    result = await session.execute(stmt)
    feeds = result.scalars().all()
    service_logger.debug(f"Retrieved {len(feeds)} active RSS feeds.")
    return feeds


async def update_rss_feed(session: AsyncSession, feed_id: int, **kwargs: Any) -> Optional[RssFeed]:
    """
    Обновляет данные RSS-ленты по ее ID. Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        feed_id: Внутренний ID ленты.
        **kwargs: Данные для обновления.

    Returns:
        Обновленный объект RssFeed or None if not found.
    Raises:
        Exception: If staging fails.
    """
    try:
        stmt = update(RssFeed).where(RssFeed.id == feed_id).values(**kwargs).returning(RssFeed) # Keep returning
        result = await session.execute(stmt)
        # No commit here. Caller manages transaction.
        feed = result.scalar_one_or_none() # Object available *after* caller commits
        if feed:
            service_logger.info(f"Staged update for RSS feed {feed_id}. Awaiting commit.")
        else:
            service_logger.warning(f"RSS feed {feed_id} not found during update attempt.")
        return feed
    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging update for RSS feed {feed_id}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def remove_rss_feed_by_id(session: AsyncSession, feed_id: int) -> Optional[RssFeed]:
    """
    Удаляет RSS-ленту по ее ID. Does NOT commit the session.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        feed_id: Внутренний ID ленты.

    Returns:
        Удаленный объект RssFeed or None if not found.
    Raises:
        Exception: If staging fails.
    """
    try:
        # Consider soft-delete for RSS feeds if needed, similar to UserChannel
        # Current implementation is hard delete
        stmt = delete(RssFeed).where(RssFeed.id == feed_id).returning(RssFeed) # Keep returning
        result = await session.execute(stmt)
        # No commit here. Caller manages transaction.
        feed = result.scalar_one_or_none() # Object available *after* caller commits
        if feed:
            service_logger.info(f"Staged deletion of RSS feed {feed_id}. Awaiting commit.")
        else:
            service_logger.warning(f"RSS feed {feed_id} not found during delete attempt.")
        return feed
    except Exception as e:
        # await session.rollback() # Removed explicit rollback
        service_logger.error(f"Error staging delete for RSS feed {feed_id}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def add_rss_item(session: AsyncSession, feed_id: int, item_guid: str, published_at: Optional[datetime]) -> Optional[RssItem]:
    """
    Добавляет информацию об обработанном элементе RSS-ленты.
    Returns the RssItem object if it was added/already exists. Does NOT commit.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        feed_id: Внутренний ID RSS-ленты.
        item_guid: Уникальный идентификатор элемента.
        published_at: Дата публикации элемента (может быть None), в UTC.

    Returns:
        The RssItem object if found or successfully staged, or None in case of unexpected error.
        Returns the existing object if item_guid already exists.
    """
    # Check if the item already exists by GUID first (more database-agnostic than ON CONFLICT)
    # Using a separate query here ensures we get the existing object if it's already there.
    existing_item = await get_rss_item_by_guid(session, item_guid)
    if existing_item:
        service_logger.debug(f"RSS item {item_guid} already exists. Returning existing item.")
        return existing_item

    # If not exists, attempt insertion
    try:
        rss_item = RssItem(
            feed_id=feed_id,
            item_guid=item_guid,
            published_at=published_at, # This should be UTC
            is_posted=False, # Initially False
        )
        session.add(rss_item)
        # No commit here, let the caller manage the session transaction.
        # await session.refresh(rss_item) # Removed explicit refresh, caller can refresh if needed after commit

        service_logger.debug(f"Staged new RSS item {item_guid} for feed {feed_id}. Awaiting commit.")
        return rss_item # Return the object, it will be saved on session commit

    except IntegrityError:
        # Handle race condition: item was added by another transaction between exists check and add
        service_logger.warning(f"IntegrityError staging RSS item {item_guid} for feed {feed_id}. Likely race condition.")
        # Rollback is handled by caller. Re-fetch the existing item.
        existing_item_after_error = await get_rss_item_by_guid(session, item_guid)
        if existing_item_after_error:
             service_logger.info(f"Retrieved existing RSS item {item_guid} after IntegrityError.")
             return existing_item_after_error
        else:
             # This is unexpected - IntegrityError but item not found after re-fetch
             service_logger.error(f"IntegrityError staging RSS item {item_guid} but item not found after re-fetch.", exc_info=True)
             raise # Re-raise if item doesn't exist

    except Exception as e:
        # Rollback is done by the caller's session management (e.g., async with session:)
        # await session.rollback() # Removed explicit rollback here
        service_logger.error(f"Error staging RSS item {item_guid} for feed {feed_id}: {e}", exc_info=True)
        raise # Re-raise for caller transaction management


async def get_rss_item_by_guid(session: AsyncSession, item_guid: str) -> Optional[RssItem]:
    """
    Проверяет, существует ли элемент RSS с данным GUID и возвращает его.

    Args:
        session: Асинхронная сессия SQLAlchemy.
        item_guid: Уникальный идентификатор элемента.

    Returns:
        Объект RssItem, если найден, иначе None.
    """
    stmt = select(RssItem).where(RssItem.item_guid == item_guid)
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    # service_logger.debug(f"Checked if RSS item {item_guid} exists: {item is not None}") # Too noisy
    return item

# Helper to mark an RSS item as posted after successful Telegram publication
async def mark_rss_item_as_posted(session: AsyncSession, item_guid: str) -> Optional[RssItem]:
     """
     Marks an RSS item as posted based on its GUID. Does NOT commit the session.

     Args:
         session: Асинхронная сессия SQLAlchemy.
         item_guid: The unique identifier of the RSS item.

     Returns:
         The updated RssItem object or None if not found.
     Raises:
        Exception: If staging fails.
     """
     try:
         # Find the item by GUID first
         item_to_update = await get_rss_item_by_guid(session, item_guid)

         if item_to_update:
              item_to_update.is_posted = True
              session.add(item_to_update) # Mark object as dirty
              service_logger.debug(f"Staged RSS item {item_guid} as posted. Awaiting commit.")
              return item_to_update # Return staged object
         else:
              service_logger.warning(f"RSS item {item_guid} not found when trying to mark as posted.")
              return None # Indicate item not found

     except Exception as e:
         # Rollback is done by the caller's session management
         # await session.rollback() # Removed explicit rollback here
         service_logger.error(f"Error staging RSS item {item_guid} as posted: {e}", exc_info=True)
         raise # Re-raise for caller transaction management
"""

# Content for services/scheduler_service.py (from task yBWNP)
SERVICES_SCHEDULER_CONTENT = """
import logging
import datetime
from typing import Optional, List, Dict, Any, Union
from functools import partial
import pytz # For UTC timezone
import os
import shutil # For cleanup
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job_states import STATE_ERROR, STATE_MISSED, STATE_EXECUTING
from apscheduler.job import Job # Import Job type for type hints

# Need a way to get the sessionmaker factory and bot instance.
# These should be passed to the scheduler initialization and job functions.
# Global placeholders are used here following the reference, but dependency injection
# via application startup/context is the preferred pattern.
async_sessionmaker = None # Must be set by the application startup
bot = None # Must be set by the application startup

# Assuming logger is configured in utils/logger.py
try:
    from utils.logger import logger
except ImportError as e:
    logging.error(f"Failed to import logger: {e}. Using basic logging.", exc_info=True)
    logger = logging.getLogger(__name__) # Fallback

service_logger = logging.getLogger(__name__)
service_logger.setLevel(logger.level if 'logger' in globals() else logging.INFO)


# Import services needed within job functions - Deferred import to potentially avoid circular issues
# These will be imported via _lazy_import_services inside job functions
db_service = None
telegram_api_service = None
content_manager_service = None
rss_service = None

def _lazy_import_services():
    """Helper to lazily import services within a function scope."""
    global db_service, telegram_api_service, content_manager_service, rss_service
    if db_service is None:
        try:
            # Assuming services are in a package 'services' relative to the bot root
            from services import db_service as imported_db_service
            from services import telegram_api_service as imported_telegram_api_service
            from services import content_manager_service as imported_content_manager_service
            from services import rss_service as imported_rss_service
            db_service = imported_db_service
            telegram_api_service = imported_telegram_api_service
            content_manager_service = imported_content_manager_service
            rss_service = imported_rss_service
            service_logger.debug("Services lazily imported in scheduler job.")
        except ImportError as e:
            service_logger.error(f"Failed to import services within scheduler job function: {e}", exc_info=True)
            # Set to None to indicate failure
            db_service = telegram_api_service = content_manager_service = rss_service = None


# --- Job Functions ---
# These functions are executed by APScheduler. They must be self-contained or accept
# necessary dependencies as arguments.

async def _post_publication_job(scheduler_instance: AsyncIOScheduler, bot_instance: Any, db_session_maker_factory: Any, post_id: int):
    """
    Задача планировщика: Опубликовать пост.
    Принимает scheduler_instance для возможности планирования задач удаления.
    """
    _lazy_import_services()
    if not bot_instance or not db_session_maker_factory or not db_service or not telegram_api_service or not content_manager_service:
        service_logger.error(f"Scheduler job _post_publication_job for post {post_id}: Dependencies not provided or imported.")
        # Attempt to mark post as invalid if DB service is available
        if db_service and db_session_maker_factory:
            try:
                 async with db_session_maker_factory() as session:
                      post_to_update = await db_service.get_post_by_id(session, post_id)
                      if post_to_update and post_to_update.status != 'deleted':
                           # update_post_data doesn't commit, need to commit the session here
                           await db_service.update_post_data(session, post_id, status='invalid')
                           await session.commit()
            except Exception as e_db:
                 service_logger.error(f"Failed to mark post {post_id} invalid due to missing deps: {e_db}", exc_info=True)
        return # Cannot proceed without essential dependencies

    service_logger.info(f"Executing post publication job for post ID: {post_id}")

    async with db_session_maker_factory() as session:
        try:
            post = await db_service.get_post_by_id(session, post_id)
            if not post or post.status != 'scheduled':
                status = post.status if post else 'None'
                service_logger.warning(f"Post {post_id} not found or not in 'scheduled' status ({status}). Skipping publication.")
                # If status is something else, maybe mark as invalid?
                if post and post.status == 'sent':
                     service_logger.info(f"Post {post_id} already sent, skipping.")
                elif post and post.status not in ['deleted', 'invalid']: # Avoid overwriting deleted/invalid
                     # update_post_data doesn't commit, need to commit the session here
                     await db_service.update_post_data(session, post_id, status='invalid')
                     await session.commit()
                return

            # Prepare media items if any
            prepared_media_objects = []
            if post.media_paths:
                try:
                    # post.media_paths is assumed to be a list of dicts like [{'type': 'photo', 'path': Path('...')}, ...]
                    # Ensure paths are strings for prepare_media_for_sending if needed
                    media_records_with_str_paths = [{'type': rec['type'], 'file_id': rec.get('file_id'), 'path': str(rec['path']) if rec.get('path') else None} for rec in post.media_paths]
                    prepared_media_objects = content_manager_service.prepare_media_for_sending(media_records_with_str_paths)
                except Exception as e:
                     service_logger.error(f"Error preparing media for post {post_id}: {e}", exc_info=True)
                     # Mark post as invalid and commit
                     await db_service.update_post_data(session, post_id, status='invalid')
                     await session.commit()
                     # Clean up temp files even on preparation error if they were downloaded
                     if post.user_id and post.id:
                         content_manager_service.cleanup_temporary_media_for_draft(post.user_id, post.id)
                     return # Cannot send without media

            # Send the post to each channel
            sent_message_ids = {} # {str(chat_id): message_id or list of message_ids}
            success = True
            sent_to_any_channel = False # Track if send was attempted for at least one channel

            for chat_id in post.chat_ids:
                sent_to_any_channel = True
                try:
                    message_info = await telegram_api_service.send_post_to_channel(
                        bot_instance,
                        chat_id,
                        post.text,
                        prepared_media_objects if prepared_media_objects else None, # Pass prepared media if exists
                        post.parse_mode # Assuming post model has parse_mode or use a default
                    )
                    if message_info:
                         # message_info is expected to be a Message object or a list of Message objects for media groups
                         # Store the message_id(s). For a media group, storing just the first ID might be sufficient for basic tracking,
                         # but a list is more accurate if deletion needs to delete all messages in the group.
                         # Telegram's deleteMessage works per message_id. For a media group, delete the first message,
                         # Telegram might handle deleting the rest automatically if they are part of the same group.
                         # Let's store the first message_id for now.
                         if isinstance(message_info, list) and message_info:
                              if message_info: # Check if list is not empty
                                   # Ensure message_info[0] is actually a Message object before accessing message_id
                                   if hasattr(message_info[0], 'message_id'):
                                        sent_message_ids[str(chat_id)] = message_info[0].message_id
                                   else:
                                        service_logger.warning(f"Post {post_id} sent media group to {chat_id}, but first item has no message_id.")
                                        success = False # Consider failure if we can't track for deletion
                              else:
                                service_logger.warning(f"Post {post_id} send media group to {chat_id} returned empty list.")
                                success = False # Consider failure if empty list returned
                         elif message_info and hasattr(message_info, 'message_id'): # Single message
                              sent_message_ids[str(chat_id)] = message_info.message_id
                         else:
                              service_logger.warning(f"Post {post_id} sent message to {chat_id}, but response has no message_id.")
                              success = False # Consider failure if we can't track for deletion


                         service_logger.info(f"Post {post_id} sent to chat {chat_id}. Message ID: {sent_message_ids.get(str(chat_id), 'N/A')}")
                    else:
                         service_logger.warning(f"Post {post_id} failed to send to chat {chat_id} (send_post_to_channel returned None).")
                         success = False # Consider the whole post send failed if any channel fails

                except Exception as e:
                    service_logger.error(f"Error sending post {post_id} to chat {chat_id}: {e}", exc_info=True)
                    success = False

            # Check if sending was even attempted if chat_ids were present
            if not sent_to_any_channel and post.chat_ids:
                 service_logger.warning(f"Post {post_id} has chat_ids {post.chat_ids}, but sending was not attempted. Likely an issue before the loop.")
                 success = False # If no channels were attempted but channels exist, consider it a failure
            elif sent_to_any_channel and not sent_message_ids:
                 # Sending was attempted, but no message IDs were recorded for ANY channel.
                 # This could be a total failure or an issue getting responses.
                 service_logger.warning(f"Post {post_id} sending attempted, but no message_ids were recorded for any channel. Sending may have partially failed or response parsing issue.")
                 success = False # If attempted but no message IDs, consider failure or partial failure

            # Mark item as posted *if* it was successfully sent to Telegram
            if success and sent_message_ids: # Ensure message_ids were actually recorded for deletion
                # Update post status to sent and store sent message IDs
                update_fields = {
                    'status': 'sent',
                    'sent_message_ids': sent_message_ids, # Use the populated dict
                    'published_at_utc': pytz.utc.localize(datetime.utcnow()) # Record publication time
                }

                # update_post_data doesn't commit, need to commit the session here
                await db_service.update_post_data(
                    session,
                    post_id,
                    **update_fields
                )
                await session.commit() # Commit the status update
                service_logger.info(f"Post {post_id} successfully sent to all channels. Status updated to 'sent'.")


                # Schedule deletion if delete_after_seconds or delete_at_utc is set
                if scheduler_instance:
                    now_utc = pytz.utc.localize(datetime.utcnow())
                    delete_time_utc = None

                    # Prioritize delete_at_utc if set and in the future
                    if post.delete_at_utc is not None and post.delete_at_utc.tzinfo is not None and post.delete_at_utc > now_utc:
                        delete_time_utc = post.delete_at_utc
                        service_logger.info(f"Scheduling deletion for post {post_id} at specific time: {delete_time_utc}.")
                    # Otherwise, use delete_after_seconds if set and positive
                    elif post.delete_after_seconds is not None and post.delete_after_seconds > 0:
                         # Ensure published_at_utc is set and timezone-aware
                         published_time = update_fields.get('published_at_utc') # Use the time recorded during this job
                         if published_time and published_time.tzinfo is not None:
                             delete_time_utc = published_time + datetime.timedelta(seconds=post.delete_after_seconds)
                             service_logger.info(f"Scheduling deletion for post {post_id} after delay: {post.delete_after_seconds} seconds from {published_time}.")
                         else:
                             service_logger.warning(f"Cannot schedule deletion for post {post_id} using seconds: published_at_utc is missing or naive.")


                    if delete_time_utc:
                         # Schedule a deletion job for *each* message sent (one job per chat+message)
                         for chat_id_str, message_id in sent_message_ids.items():
                              # Ensure message_id is valid before scheduling deletion
                              if message_id:
                                   try:
                                        await schedule_post_deletion(
                                            scheduler_instance,
                                            bot_instance,
                                            db_session_maker_factory, # Pass session maker (optional for job but good practice)
                                            int(chat_id_str),
                                            message_id,
                                            delete_time_utc
                                        )
                                   except Exception as schedule_del_e:
                                        service_logger.error(f"Error scheduling deletion for message {message_id} in chat {chat_id_str} for post {post_id}: {schedule_del_e}", exc_info=True)
                              else:
                                   service_logger.warning(f"Post {post_id}: Cannot schedule deletion for chat {chat_id_str} - no valid message_id.")
                else:
                    service_logger.warning(f"Scheduler instance not available in _post_publication_job for post {post_id}. Cannot schedule deletion.")

                # Clean up temporary media files after successful send
                if post.user_id and post.id and content_manager_service:
                     content_manager_service.cleanup_temporary_media_for_draft(post.user_id, post.id) # Use post.id as entity_id for temporary path structure

            else:
                # If sending failed or no message IDs were recorded, mark post as invalid
                # unless it was already deleted.
                if post and post.status != 'deleted':
                    # update_post_data doesn't commit, need to commit the session here
                    await db_service.update_post_data(session, post_id, status='invalid')
                    await session.commit() # Commit the status update
                    service_logger.error(f"Post {post_id} failed to send or record message IDs. Status set to 'invalid'.")
                else:
                    service_logger.warning(f"Post {post_id} sending failed, but status was {post.status if post else 'None'}. Not marking as invalid.")

                # Clean up temporary media files even on failed send attempt
                if post and post.user_id and post.id and content_manager_service:
                     content_manager_service.cleanup_temporary_media_for_draft(post.user_id, post.id)


        except Exception as e:
            service_logger.error(f"Unhandled error in _post_publication_job for post {post_id}: {e}", exc_info=True)
            # Attempt to mark as invalid even if something went wrong inside the job
            if db_service and db_session_maker_factory:
                try:
                    # Need to fetch post again in case session was rolled back or closed
                    async with db_session_maker_factory() as session_err:
                         post_to_update = await db_service.get_post_by_id(session_err, post_id)
                         if post_to_update and post_to_update.status not in ['deleted', 'invalid']: # Don't overwrite
                             # update_post_data doesn't commit, need to commit the session here
                             await db_service.update_post_data(session_err, post_id, status='invalid')
                             await session_err.commit()
                except Exception as inner_e:
                     service_logger.error(f"Failed to mark post {post_id} as invalid after job error: {inner_e}", exc_info=True)
            # Clean up temp files on error
            if post and post.user_id and post.id and content_manager_service:
                 content_manager_service.cleanup_temporary_media_for_draft(post.user_id, post.id)


async def _post_deletion_job(bot_instance: Any, chat_id: int, message_id: int):
    """
    Задача планировщика: Удалить опубликованное сообщение.
    Removed db_session_maker_factory as it was unused.
    """
    _lazy_import_services()
    if not bot_instance or not telegram_api_service:
        service_logger.error(f"Scheduler job _post_deletion_job for message {message_id} in chat {chat_id}: bot or telegram_api_service not provided.")
        return

    service_logger.info(f"Executing post deletion job for message {message_id} in chat {chat_id}")

    try:
        await telegram_api_service.delete_message_from_channel(bot_instance, chat_id, message_id)
        # telegram_api_service.delete_message_from_channel logs success/failure internally
    except Exception as e:
        service_logger.error(f"Unhandled error in _post_deletion_job for message {message_id} in chat {chat_id}: {e}", exc_info=True)
        # Log the error. The job failed successfully in that it *tried* to delete.


async def _rss_check_job(bot_instance: Any, db_session_maker_factory: Any, feed_id: int):
    """
    Задача планировщика: Проверить одну RSS-ленту.
    """
    _lazy_import_services()
    if not bot_instance or not db_session_maker_factory or not db_service or not rss_service:
        service_logger.error(f"Scheduler job _rss_check_job for feed {feed_id}: Dependencies not provided or imported.")
        return

    service_logger.info(f"Executing RSS feed check job for feed ID: {feed_id}")

    try:
        async with db_session_maker_factory() as session:
            feed = await db_service.get_rss_feed_by_id(session, feed_id)
            if not feed:
                service_logger.warning(f"RSS feed {feed_id} not found. Skipping check and attempting job removal.")
                # Remove the job from the scheduler if the feed no longer exists
                scheduler_instance = globals().get('scheduler') # Access global placeholder for removal
                if scheduler_instance:
                    try:
                         remove_scheduled_rss_job(scheduler_instance, feed_id)
                         service_logger.info(f"Removed job for deleted RSS feed {feed_id}.")
                    except Exception as remove_e:
                         service_logger.error(f"Failed to remove job for feed {feed_id}: {remove_e}")
                return

            # Pass the bot instance and session maker factory to process_single_feed
            # process_single_feed handles its own session management internally
            await rss_service.process_single_feed(bot_instance, db_session_maker_factory, feed)
            service_logger.info(f"Finished processing RSS feed {feed.id}.")
            
    except Exception as e:
        service_logger.error(f"Unhandled error in _rss_check_job for feed {feed_id}: {e}", exc_info=True)
            # Log the error. process_single_feed should handle updating last_checked_at even on error.


# --- Scheduling Functions ---

# APScheduler instance (needs to be initialized and started in the main application)
# Use a global placeholder as per implicit structure, but dependency injection is better.
scheduler: Optional[AsyncIOScheduler] = None

def initialize_scheduler(jobstore_url: str):
    """Initializes and returns the APScheduler instance."""
    global scheduler

    if scheduler is not None:
        service_logger.warning("Scheduler already initialized.")
        return scheduler

    # async_sessionmaker is needed by SQLAlchemyJobStore if using engine directly,
    # or if the JobStore itself needs it for some reason (less common).
    # The job functions definitely need the session maker factory.
    # Check if the placeholder is set.
    # Note: SQLAlchemyJobStore >= 3.6 supports async directly via 'url'.
    # If using an async engine object, initialize like SQLAlchemyJobStore(engine=...)
    # The current placeholder approach requires the URL.
    if not jobstore_url:
        service_logger.error("jobstore_url is not provided. Cannot initialize scheduler with SQLAlchemyJobStore.")
        # In a real application, you would raise an error or exit.
        raise ValueError("jobstore_url must be provided to initialize scheduler.")


    jobstores = {
        'default': SQLAlchemyJobStore(url=jobstore_url)
    }
    executors = {
        'default': {'type': 'asyncio', 'max_workers': 20} # Adjust max_workers based on workload
    }
    job_defaults = {
        'coalesce': True, # Don't run multiple missed jobs if the scheduler is down
        'max_instances': 1, # Prevent multiple instances of the same job ID running concurrently
        'timezone': pytz.utc # Store and interpret job times in UTC by default
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone=pytz.utc # Scheduler's own timezone for display and internal calculations
    )
    service_logger.info("APScheduler initialized with SQLAlchemyJobStore.")
    return scheduler


async def schedule_one_time_post(
    scheduler_instance: AsyncIOScheduler,
    bot_instance: Any,
    db_session_maker_factory: Any,
    post_id: int,
    run_date_utc: datetime,
):
    """
    Планирует одноразовую публикацию поста.
    Removed redundant post data args as job fetches from DB.

    Args:
        scheduler_instance: Экземпляр APScheduler.
        bot_instance: Экземпляр aiogram.Bot.
        db_session_maker_factory: Фабрика асинхронных сессий SQLAlchemy.
        post_id: Внутренний ID поста.
        run_date_utc: Дата и время публикации в UTC (timezone-aware).
    """
    job_id = f"post_publish_{post_id}"

    now_utc = pytz.utc.localize(datetime.utcnow())
    # Ensure run_date_utc is timezone-aware and in the future
    if run_date_utc.tzinfo is None:
         service_logger.warning(f"Run date for post {post_id} is naive. Assuming UTC: {run_date_utc}.")
         run_date_utc = pytz.utc.localize(run_date_utc)

    if run_date_utc <= now_utc:
        service_logger.warning(f"Run date {run_date_utc} for post {post_id} is in the past or now. Cannot schedule one-time job.")
        # Consider marking post as invalid or handling differently
        _lazy_import_services()
        if db_service and db_session_maker_factory:
            try:
                 async with db_session_maker_factory() as session:
                      post_to_update = await db_service.get_post_by_id(session, post_id)
                      if post_to_update and post_to_update.status != 'deleted':
                           # update_post_data doesn't commit, need to commit the session here
                           await db_service.update_post_data(session, post_id, status='invalid')
                           await session.commit()
            except Exception as e_db:
                 service_logger.error(f"Failed to mark post {post_id} invalid after scheduling failed: {e_db}")
        return

    try:
        scheduler_instance.add_job(
            func=_post_publication_job,
            trigger=DateTrigger(run_date=run_date_utc),
            args=[scheduler_instance, bot_instance, db_session_maker_factory, post_id], # Pass necessary dependencies and post ID
            id=job_id,
            replace_existing=True, # Replace if a job with this ID already exists (e.g., rescheduling)
            misfire_grace_time=600 # Allow job to run up to 10 minutes late
        )
        service_logger.info(f"Scheduled one-time publication job for post {post_id} at {run_date_utc} (UTC) with job_id: {job_id}")

    except Exception as e:
        service_logger.error(f"Error scheduling one-time post {post_id}: {e}", exc_info=True)
        # Mark post as invalid in DB?
        _lazy_import_services()
        if db_service and db_session_maker_factory:
            try:
                 async with db_session_maker_factory() as session:
                      # update_post_data doesn't commit, need to commit the session here
                      await db_service.update_post_data(session, post_id, status='invalid')
                      await session.commit()
            except Exception as e_db:
                 service_logger.error(f"Failed to mark post {post_id} invalid after scheduling failed: {e_db}")


async def schedule_recurring_post(
    scheduler_instance: AsyncIOScheduler,
    bot_instance: Any,
    db_session_maker_factory: Any,
    post_id: int,
    schedule_params_utc: Dict[str, Any], # Parameters for CronTrigger
    start_date_utc: Optional[datetime], # Start date in UTC (timezone-aware)
    end_date_utc: Optional[datetime], # End date in UTC (timezone-aware)
    # Delete params handled in the job
):
    """
    Планирует циклическую публикацию поста.
    Removed redundant post data args as job fetches from DB.

    Args:
        scheduler_instance: Экземпляр APScheduler.
        bot_instance: Экземпляр aiogram.Bot.
        db_session_maker_factory: Фабрика асинхронных сессий SQLAlchemy.
        post_id: Внутренний ID поста.
        schedule_params_utc: Параметры для CronTrigger (e.g., {'hour': '10', 'minute': '0', 'day_of_week': 'mon,wed'}).
        start_date_utc: Дата начала (опционально, в UTC, timezone-aware).
        end_date_utc: Дата окончания (опционально, в UTC, timezone-aware).
    """
    job_id = f"post_recurring_publish_{post_id}"

    # Basic validation for recurring params
    if not isinstance(schedule_params_utc, dict) or not schedule_params_utc:
        service_logger.error(f"Cannot schedule recurring post {post_id}: Invalid or empty schedule_params_utc.")
        _lazy_import_services()
        if db_service and db_session_maker_factory:
            try:
                 async with db_session_maker_factory() as session:
                      # update_post_data doesn't commit, need to commit session
                      await db_service.update_post_data(session, post_id, status='invalid')
                      await session.commit()
            except Exception as e_db:
                 service_logger.error(f"Failed to mark post {post_id} invalid after scheduling failed: {e_db}")
        return

    # Ensure start_date is timezone-aware and in the future if provided
    now_utc = pytz.utc.localize(datetime.utcnow())
    if start_date_utc:
        if start_date_utc.tzinfo is None:
             service_logger.warning(f"Recurring post {post_id}: start_date_utc is naive. Assuming UTC: {start_date_utc}.")
             start_date_utc = pytz.utc.localize(start_date_utc)

        # Adjust start date to be slightly in the future if it's in the past/now
        # (CronTrigger starts from the first match *after* start_date, but ensuring it's future avoids confusion)
        if start_date_utc <= now_utc:
             service_logger.warning(f"Recurring post {post_id}: start_date_utc {start_date_utc} is in the past/now. Adjusting to start in 5 seconds.")
             start_date_utc = now_utc + datetime.timedelta(seconds=5) # Start 5 secs from now

    # Ensure end_date is timezone-aware if provided
    if end_date_utc and end_date_utc.tzinfo is None:
         service_logger.warning(f"Recurring post {post_id}: end_date_utc is naive. Assuming UTC: {end_date_utc}.")
         end_date_utc = pytz.utc.localize(end_date_utc)


    # Convert schedule_params_utc dict to CronTrigger arguments
    cron_kwargs = {}
    # Map your specific schedule_params format to CronTrigger kwargs
    # Example mapping based on common schedule settings (daily time, days of week, specific month/day)
    if 'time' in schedule_params_utc:
        try:
            # Assuming 'time' is 'HH:MM' string
            hour, minute = map(int, schedule_params_utc['time'].split(':'))
            cron_kwargs['hour'] = hour
            cron_kwargs['minute'] = minute
        except (ValueError, AttributeError):
            service_logger.error(f"Recurring post {post_id}: Invalid time format in schedule_params_utc['time'].")
            _lazy_import_services()
            if db_service and db_session_maker_factory:
                 try:
                      async with db_session_maker_factory() as session:
                           # update_post_data doesn't commit, need to commit session
                           await db_service.update_post_data(session, post_id, status='invalid')
                           await session.commit()
                 except Exception as e_db:
                      service_logger.error(f"Failed to mark post {post_id} invalid after scheduling failed: {e_db}")
            return
    if 'days_of_week' in schedule_params_utc and isinstance(schedule_params_utc['days_of_week'], list):
         # CronTrigger expects a string like 'mon,wed,fri'
        cron_kwargs['day_of_week'] = ','.join(schedule_params_utc['days_of_week'])
    if 'day_of_month' in schedule_params_utc and isinstance(schedule_params_utc['day_of_month'], int):
         cron_kwargs['day'] = schedule_params_utc['day_of_month']
    if 'month_day' in schedule_params_utc:
         # Assuming 'month_day' is 'DD.MM' string
         try:
              day, month = map(int, schedule_params_utc['month_day'].split('.'))
              cron_kwargs['day'] = day
              cron_kwargs['month'] = month
         except (ValueError, AttributeError):
            service_logger.error(f"Recurring post {post_id}: Invalid date format in schedule_params_utc['month_day'].")
            _lazy_import_services()
            if db_service and db_session_maker_factory:
                 try:
                      async with db_session_maker_factory() as session:
                           # update_post_data doesn't commit, need to commit session
                           await db_service.update_post_data(session, post_id, status='invalid')
                           await session.commit()
                 except Exception as e_db:
                      service_logger.error(f"Failed to mark post {post_id} invalid after scheduling failed: {e_db}")
            return
    # Add other cron parameters if necessary (e.g., year, week, day_of_year)

    # Ensure necessary cron parts are present for the trigger to be valid
    if not cron_kwargs:
        service_logger.error(f"Recurring post {post_id}: No valid cron parameters derived from schedule_params_utc.")
        _lazy_import_services()
        if db_service and db_session_maker_factory:
            try:
                 async with db_session_maker_factory() as session:
                      # update_post_data doesn't commit, need to commit session
                      await db_service.update_post_data(session, post_id, status='invalid')
                      await session.commit()
            except Exception as e_db:
                 service_logger.error(f"Failed to mark post {post_id} invalid after scheduling failed: {e_db}")
        return

    try:
        scheduler_instance.add_job(
            func=_post_publication_job,
            trigger=CronTrigger(
                start_date=start_date_utc, # Should be timezone-aware UTC
                end_date=end_date_utc,     # Should be timezone-aware UTC
                timezone=pytz.utc,         # Trigger operates in UTC
                **cron_kwargs              # Pass converted parameters
            ),
             args=[scheduler_instance, bot_instance, db_session_maker_factory, post_id], # Pass dependencies and post ID
            id=job_id,
            replace_existing=True,
            misfire_grace_time=600
        )
        service_logger.info(f"Scheduled recurring publication job for post {post_id} with params {cron_kwargs}, start: {start_date_utc}, end: {end_date_utc}, job_id: {job_id}")

    except Exception as e:
        service_logger.error(f"Error scheduling recurring post {post_id}: {e}", exc_info=True)
        # Mark post as invalid in DB?
        _lazy_import_services()
        if db_service and db_session_maker_factory:
            try:
                 async with db_session_maker_factory() as session:
                      # update_post_data doesn't commit, need to commit session
                      await db_service.update_post_data(session, post_id, status='invalid')
                      await session.commit()
            except Exception as e_db:
                 service_logger.error(f"Failed to mark post {post_id} invalid after scheduling failed: {e_db}")


async def schedule_post_deletion(
    scheduler_instance: AsyncIOScheduler,
    bot_instance: Any,
    db_session_maker_factory: Any, # Kept for consistency, though not used by the job itself
    chat_id: int,
    message_id: int,
    delete_time_utc: datetime
):
    """
    Планирует удаление опубликованного сообщения в конкретное время.

    Args:
        scheduler_instance: Экземпляр APScheduler.
        bot_instance: Экземпляр aiogram.Bot.
        db_session_maker_factory: Фабрика асинхронных сессий SQLAlchemy (optional for this job func).
        chat_id: ID чата Telegram.
        message_id: ID сообщения Telegram.
        delete_time_utc: Время удаления в UTC (timezone-aware).
    """
    # Job ID should be unique per deletion task. Using chat_id and message_id is a good approach.
    job_id = f"post_delete_{chat_id}_{message_id}"

    # Check if the deletion time is in the future
    now_utc = pytz.utc.localize(datetime.utcnow())
    # Ensure delete_time_utc is timezone-aware
    if delete_time_utc.tzinfo is None:
         service_logger.warning(f"Deletion time for message {message_id} in chat {chat_id} is naive. Assuming UTC: {delete_time_utc}.")
         delete_time_utc = pytz.utc.localize(delete_time_utc)

    if delete_time_utc <= now_utc:
        service_logger.warning(f"Deletion time for message {message_id} in chat {chat_id} is in the past or now ({delete_time_utc}). Skipping scheduling.")
        # Optional: try to delete it immediately?
        # asyncio.create_task(_post_deletion_job(bot_instance, chat_id, message_id)) # Pass correct args
        return

    try:
        scheduler_instance.add_job(
            func=_post_deletion_job,
            trigger=DateTrigger(run_date=delete_time_utc),
             args=[bot_instance, chat_id, message_id], # Pass correct args: bot, chat_id, message_id
            id=job_id,
            replace_existing=True,
            misfire_grace_time=60 # Allow job to run up to 1 minute late
        )
        service_logger.info(f"Scheduled deletion job for message {message_id} in chat {chat_id} at {delete_time_utc} (UTC) with job_id: {job_id}")

    except Exception as e:
        service_logger.error(f"Error scheduling deletion job for message {message_id} in chat {chat_id}: {e}", exc_info=True)


async def schedule_rss_feed_check(
    scheduler_instance: AsyncIOScheduler,
    bot_instance: Any,
    db_session_maker_factory: Any,
    feed_id: int,
    frequency_minutes: int
):
    """
    Планирует циклическую проверку RSS-ленты.

    Args:
        scheduler_instance: Экземпляр APScheduler.
        bot_instance: Экземпляр aiogram.Bot.
        db_session_maker_factory: Фабрика асинхронных сессий SQLAlchemy.
        feed_id: Внутренний ID RSS-ленты.
        frequency_minutes: Частота проверки в минутах.
    """
    job_id = f"rss_check_{feed_id}"

    # Check frequency
    if frequency_minutes <= 0:
        service_logger.warning(f"Invalid frequency_minutes ({frequency_minutes}) for RSS feed {feed_id}. Skipping scheduling.")
        # Optional: Mark feed inactive or remove?
        return

    try:
        # If frequency is very low (e.g., < 1 minute), interval might not be suitable or reliable.
        # Let's assume frequency_minutes >= 1 for simplicity.
        if frequency_minutes < 1:
             service_logger.warning(f"Frequency for RSS feed {feed_id} is less than 1 minute ({frequency_minutes}). Setting to 1 minute.")
             frequency_minutes = 1

        scheduler_instance.add_job(
            func=_rss_check_job,
            trigger='interval', # Use interval trigger for simple frequency
            minutes=frequency_minutes,
            args=[bot_instance, db_session_maker_factory, feed_id], # Pass dependencies and feed ID
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300 # Allow job to run up to 5 minutes late
        )
        service_logger.info(f"Scheduled RSS feed check job for feed {feed_id} every {frequency_minutes} minutes with job_id: {job_id}")

    except Exception as e:
        service_logger.error(f"Error scheduling RSS feed check job for feed {feed_id}: {e}", exc_info=True)


def remove_scheduled_jobs_for_post(scheduler_instance: AsyncIOScheduler, post_id: int):
    """
    Удаляет все запланированные задачи (публикацию), связанные с постом.
    Note: Deletion jobs are identified by chat_id and message_id, not post_id.
    This function primarily removes publication jobs. Removing deletion jobs
    would require querying the job store's job arguments, which is less direct.

    Args:
        scheduler_instance: Экземпляр APScheduler.
        post_id: Внутренний ID поста.
    """
    publish_job_id_one_time = f"post_publish_{post_id}"
    publish_job_id_recurring = f"post_recurring_publish_{post_id}" # Use a different prefix for recurring

    removed_count = 0
    try:
        if scheduler_instance.get_job(publish_job_id_one_time):
            scheduler_instance.remove_job(publish_job_id_one_time)
            service_logger.info(f"Removed one-time publication job {publish_job_id_one_time} for post {post_id}.")
            removed_count += 1
    except Exception as e:
         service_logger.warning(f"Failed to remove one-time job {publish_job_id_one_time} for post {post_id}: {e}")

    try:
        if scheduler_instance.get_job(publish_job_id_recurring):
            scheduler_instance.remove_job(publish_job_id_recurring)
            service_logger.info(f"Removed recurring publication job {publish_job_id_recurring} for post {post_id}.")
            removed_count += 1
    except Exception as e:
         service_logger.warning(f"Failed to remove recurring job {publish_job_id_recurring} for post {post_id}: {e}")

    if removed_count == 0:
        service_logger.debug(f"No scheduled publication jobs found for post {post_id} to remove.")

    # Note: Removing associated deletion jobs here is complex as they are identified by chat_id and message_id.
    # A better approach would be to either query the job store for jobs whose args contain the post_id
    # (if the job args included it, which _post_deletion_job currently doesn't),
    # or store deletion job IDs in the Post model (e.g., in sent_message_ids or a separate field).
    # As per analysis, this is a known limitation in the current structure.


def remove_scheduled_rss_job(scheduler_instance: AsyncIOScheduler, feed_id: int):
    """
    Удаляет запланированную задачу проверки RSS-ленты.

    Args:
        scheduler_instance: Экземпляр APScheduler.
        feed_id: Внутренний ID RSS-ленты.
    """
    job_id = f"rss_check_{feed_id}"
    try:
        if scheduler_instance.get_job(job_id):
            scheduler_instance.remove_job(job_id)
            service_logger.info(f"Removed RSS check job {job_id} for feed {feed_id}.")
        else:
            service_logger.warning(f"No scheduled RSS check job found for feed {feed_id} to remove.")
    except Exception as e:
        service_logger.error(f"Error removing RSS check job for feed {feed_id}: {e}", exc_info=True)


async def reschedule_post(
    scheduler_instance: AsyncIOScheduler,
    bot_instance: Any,
    db_session_maker_factory: Any,
    post_id: int,
    new_post_data: Dict[str, Any] # Contains data like schedule_type, run_date_utc, schedule_params etc.
):
    """
    Удаляет старые задачи для поста и создает новые на основе обновленных данных.
    Handles updating the post data and scheduling in a single flow.

    Args:
        scheduler_instance: Экземпляр APScheduler.
        bot_instance: Экземпляр aiogram.Bot.
        db_session_maker_factory: Фабрика асинхронных сессий SQLAlchemy.
        post_id: Внутренний ID поста.
        new_post_data: Словарь с обновленными данными поста, включая новое расписание.
                       Must contain 'schedule_type' and relevant schedule parameters.
    """
    _lazy_import_services()
    if not db_service:
        service_logger.error("Cannot reschedule post: db_service not available.")
        return

    service_logger.info(f"Attempting to reschedule post {post_id}.")

    # 1. Remove existing publication jobs for this post
    remove_scheduled_jobs_for_post(scheduler_instance, post_id)

    # 2. Update the post data in the DB
    # Use a separate session for the update to ensure atomicity of the update itself
    # even if scheduling fails later.
    async with db_session_maker_factory() as session:
         # update_post_data doesn't commit, need to commit session here
         updated_post_obj = await db_service.update_post_data(session, post_id, **new_post_data)
         await session.commit() # Commit the update

    if not updated_post_obj:
        service_logger.error(f"Failed to update post {post_id} data. Cannot reschedule.")
        return # Stop if DB update failed

    # 3. Schedule new jobs based on the updated data
    schedule_type = updated_post_obj.schedule_type # Use data from the updated object

    if schedule_type == 'one_time':
        run_date_utc = updated_post_obj.run_date_utc
        if not isinstance(run_date_utc, datetime) or run_date_utc.tzinfo is None:
             service_logger.error(f"Cannot reschedule post {post_id} (one_time): Invalid or missing timezone-aware run_date_utc in updated data.")
             # Mark post as invalid? Already logged error.
             return # Do not schedule if datetime is invalid

        # schedule_one_time_post checks if date is in past and marks invalid if needed
        await schedule_one_time_post(
            scheduler_instance,
            bot_instance,
            db_session_maker_factory,
            post_id,
            run_date_utc # Pass the timezone-aware date
        )
        # Status is updated inside schedule_one_time_post if successful, or marked invalid.
        # No extra status update needed here.


    elif schedule_type == 'recurring':
         schedule_params_utc = updated_post_obj.schedule_params
         # Assuming start/end date columns exist on Post model for recurring if needed by CronTrigger
         start_date_utc = getattr(updated_post_obj, 'start_date_utc', None)
         end_date_utc = getattr(updated_post_obj, 'end_date_utc', None)

         # schedule_recurring_post handles validation and scheduling
         await schedule_recurring_post(
             scheduler_instance,
             bot_instance,
             db_session_maker_factory,
             post_id,
             schedule_params_utc, # Should contain CronTrigger parameters
             start_date_utc, # Should be timezone-aware UTC or None
             end_date_utc,   # Should be timezone-aware UTC or None
         )
         # Status is updated inside schedule_recurring_post if successful, or marked invalid.
         # No extra status update needed here.

    elif schedule_type in ['draft', 'sent', 'deleted', 'invalid']:
        # If status is updated to non-scheduled, jobs were already removed.
        service_logger.info(f"Post {post_id} updated to status '{schedule_type}', no APScheduler job needed.")
        pass # No job to schedule

    else:
        service_logger.error(f"Unknown schedule_type '{schedule_type}' for post {post_id} in updated data. Cannot reschedule.")
        # Mark post as invalid?
        async with db_session_maker_factory() as session:
             if db_service:
                 try:
                     # update_post_data doesn't commit, need to commit session
                     await db_service.update_post_data(session, post_id, status='invalid')
                     await session.commit()
                 except Exception as e_db:
                      service_logger.error(f"Failed to mark post {post_id} invalid after rescheduling failed: {e_db}")


async def restore_scheduled_jobs(scheduler_instance: AsyncIOScheduler, bot_instance: Any, db_session_maker_factory: Any):
    """
    Загружает все активные посты и RSS-ленты из БД и восстанавливает их задачи в APScheduler.
    Вызывается при старте приложения.
    Note: APScheduler's SQLAlchemyJobStore automatically loads persisted jobs on startup.
    This function provides an explicit way to ensure DB-managed schedules are reflected in APScheduler,
    handling cases where DB state might be inconsistent with the job store or for dynamically scheduled jobs like RSS.

    Args:
        scheduler_instance: Экземпляр APScheduler.
        bot_instance: Экземпляр aiogram.Bot.
        db_session_maker_factory: Фабрика асинхронных сессий SQLAlchemy.
    """
    _lazy_import_services()
    if not db_service:
        service_logger.error("Cannot restore jobs: db_service not available.")
        return

    service_logger.info("Restoring scheduled jobs from database...")

    # Fetch data needed for restoration in a single session
    async with db_session_maker_factory() as session:
        try:
            scheduled_posts = await db_service.get_all_scheduled_posts(session)
            active_rss_feeds = await db_service.get_all_active_rss_feeds(session)
        except Exception as e:
             service_logger.error(f"Failed to fetch data for job restoration: {e}", exc_info=True)
             # Cannot proceed without data
             return


    service_logger.info(f"Found {len(scheduled_posts)} scheduled posts and {len(active_rss_feeds)} active RSS feeds to restore.")

    # Restore scheduled posts
    for post in scheduled_posts:
        try:
            # Use reschedule_post logic to ensure jobs are correctly added based on status and type
            # reschedule_post will fetch the necessary data again within its own session context for robustness.
            # Pass enough info to reschedule_post to identify the post and initiate scheduling.
            # The actual schedule data is read from the post object inside reschedule_post.
            await reschedule_post(scheduler_instance, bot_instance, db_session_maker_factory, post.id, {'schedule_type': post.schedule_type})
            service_logger.info(f"Successfully attempted restore for post {post.id}.")

        except Exception as e:
            # Log error for THIS specific post, but continue with the next ones
            service_logger.error(f"Failed to restore job for post {post.id}: {e}", exc_info=True)
            # Optionally update post status to 'invalid' if restoring failed
            # This is already attempted inside reschedule_post and schedule_*_post functions
            # if scheduling fails after data update.
            # A separate catch here might double-log or try to update already updated status.
            # Let's trust the inner functions to mark invalid if scheduling itself fails.
            pass # Continue to next post


    # Restore active RSS feed check jobs
    # These jobs might not be automatically reloaded by APScheduler's SQLAlchemyJobStore
    # if they were added dynamically (e.g. via schedule_rss_feed_check).
    # Explicitly scheduling them ensures they run, and replace_existing=True prevents duplicates
    # if the job store *did* load them.
    for feed in active_rss_feeds:
        try:
            # Ensure frequency is valid before scheduling
            if feed.frequency_minutes is None or feed.frequency_minutes <= 0:
                service_logger.warning(f"Invalid or missing frequency ({feed.frequency_minutes}) for RSS feed {feed.id}. Skipping scheduling.")
                continue # Skip this feed if frequency is invalid

            # Remove existing job first, just in case APScheduler did load it or it's a duplicate
            remove_scheduled_rss_job(scheduler_instance, feed.id)
            # Schedule the job
            await schedule_rss_feed_check(
                scheduler_instance,
                bot_instance,
                db_session_maker_factory,
                feed.id,
                feed.frequency_minutes
            )
            service_logger.info(f"Successfully attempted restore for RSS feed {feed.id}.")

        except Exception as e:
            # Log error for THIS specific feed, but continue with the next ones
            service_logger.error(f"Failed to restore job for RSS feed {feed.id}: {e}", exc_info=True)
            pass # Continue to next feed


    service_logger.info("Finished restoring scheduled jobs.")

# How to set global placeholders in your main application file (e.g., bot.py):
# import scheduler_service
# from bot.db.database import async_sessionmaker as my_async_sessionmaker # Replace with actual import
# from bot.main import bot as my_bot_instance # Replace with actual import
#
# scheduler_service.async_sessionmaker = my_async_sessionmaker
# scheduler_service.bot = my_bot_instance
#
# # Then initialize and start the scheduler
# job_store_url = "sqlite:///jobs.sqlite" # Or your actual DB URL
# scheduler_instance = scheduler_service.initialize_scheduler(job_store_url)
#
# async def main():
#     scheduler_instance.start()
#     await scheduler_service.restore_scheduled_jobs(scheduler_instance, my_bot_instance, my_async_sessionmaker)
#     # ... rest of your bot startup (dispatcher.start_polling etc.)
#
# asyncio.run(main())
"""

# Content for services/telegram_api_service.py (from task 7Vr0g)
SERVICES_TELEGRAM_API_CONTENT = """
import logging
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument, Message, FSInputFile
from aiogram.exceptions import TelegramAPIError, AiogramError # Import relevant exceptions

# Assuming logger is configured in utils/logger.py
try:
    from utils.logger import logger
except ImportError as e:
    logging.error(f"Failed to import logger: {e}. Using basic logging.", exc_info=True)
    logger = logging.getLogger(__name__) # Fallback

service_logger = logging.getLogger(__name__)
service_logger.setLevel(logger.level if 'logger' in globals() else logging.INFO)

# Max caption length for photos, videos, and other media (docs, audio) is 1024 characters.
# Max text length for a message (no media) is 4096 characters.
# We should use the smaller limit (1024) if media is present.
CAPTION_MAX_LENGTH = 1024


async def send_post_to_channel(
    bot: Bot,
    chat_id: Union[int, str],
    text: Optional[str] = None,
    media_items: Optional[List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]]] = None,
    parse_mode: Optional[str] = None
) -> Optional[Union[Message, List[Message]]]:
    """
    Отправляет пост в канал/группу Telegram. Поддерживает текст и медиагруппу.

    Args:
        bot: Экземпляр aiogram.Bot.
        chat_id: ID чата или юзернейм (@channelusername).
        text: Текст сообщения.
        media_items: Список объектов InputMedia*. These should have `media` set to file_id, bytes, or FSInputFile. URLs work only for single photo/video sends, not media groups with local files/file_ids consistently.
        parse_mode: Режим парсинга текста (MarkdownV2, HTML, None).

    Returns:
        Объект Message (для текста) или список Message (для медиагруппы),
        или None в случае ошибки.
    """
    if not text and not media_items:
        service_logger.warning(f"Attempted to send empty post to chat {chat_id}. Skipping.")
        return None

    try:
        if media_items:
            # For media_group, the caption/parse_mode should generally be on the first item.
            # Aiogram's send_media_group docs confirm caption applies to the first element
            # unless overridden by an individual InputMedia object's caption.
            # Let's ensure the main post text is used as the caption for the first item.
            caption_text_for_media = text # Use the main text as caption
            # Truncate caption if it exceeds limit
            if caption_text_for_media and len(caption_text_for_media) > CAPTION_MAX_LENGTH:
                 service_logger.warning(f"Post text exceeds caption limit ({len(caption_text_for_media)} > {CAPTION_MAX_LENGTH}). Truncating.")
                 # Truncate carefully to not break Markdown formatting mid-tag/escape sequence.
                 # Simple truncation might cut off escapes. A more complex approach needed for perfect truncation.
                 # Basic truncation:
                 truncated_text = caption_text_for_media[:CAPTION_MAX_LENGTH - 3].rstrip() # Reserve space for ellipsis
                 # Ensure truncation doesn't end mid-escape sequence like '\\'
                 if truncated_text.endswith('\\'):
                      truncated_text = truncated_text[:-1].rstrip()
                 caption_text_for_media = truncated_text + "..." # Truncate and add ellipsis


            # Apply caption and parse_mode to the first media item if available and supported
            if media_items:
                 first_item = media_items[0]
                 # Check if the item type supports caption (most InputMedia types do, but good to be safe)
                 # and if a caption isn't already explicitly set on the item (unlikely in this flow).
                 if hasattr(first_item, 'caption'):
                     first_item.caption = caption_text_for_media
                     first_item.parse_mode = parse_mode
                     # send_text_separately = False # Text is now the caption (removed unused variable)
                 else:
                      service_logger.warning(f"First media item type {type(first_item).__name__} does not support caption. Text will not be sent with media group.")
                      # send_text_separately = False # Cannot send text with this media group type easily (removed unused variable)


            # Send media group
            sent_messages = await bot.send_media_group(
                chat_id=chat_id,
                media=media_items,
                # caption and parse_mode are set on the InputMedia object directly
            )
            # sent_messages is a list of Message objects
            service_logger.info(f"Sent media group post to chat {chat_id}. Received {len(sent_messages)} message objects.")
            return sent_messages # Return the list of message objects

        elif text:
            # Send text-only message
            # Ensure text does not exceed message limit (4096)
            if len(text) > 4096: # Check against message text limit
                 service_logger.warning(f"Post text exceeds message limit ({len(text)} > 4096). Truncating.")
                 text = text[:4096] # Truncate

            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode
            )
            # sent_message is a single Message object
            service_logger.info(f"Sent text-only post to chat {chat_id}. Message ID: {sent_message.message_id}.")
            return sent_message # Return the single message object

        else:
            # Should not happen due to initial check, but as a fallback
            service_logger.warning(f"Attempted to send post to {chat_id} but neither text nor media_items were valid for sending.")
            return None

    except TelegramAPIError as e:
        service_logger.error(f"Telegram API error sending post to chat {chat_id}: {e}", exc_info=True)
        return None
    except AiogramError as e:
         service_logger.error(f"Aiogram error sending post to chat {chat_id}: {e}", exc_info=True)
         return None
    except Exception as e:
        service_logger.error(f"Unexpected error sending post to chat {chat_id}: {e}", exc_info=True)
        return None


async def delete_message_from_channel(bot: Bot, chat_id: Union[int, str], message_id: int) -> bool:
    """
    Удаляет сообщение из канала/группы.

    Args:
        bot: Экземпляр aiogram.Bot.
        chat_id: ID чата или юзернейм (@channelusername).
        message_id: ID сообщения.

    Returns:
        True, если сообщение успешно удалено, иначе False.
    """
    try:
        # deleteMessage method returns True on success
        result = await bot.delete_message(chat_id=chat_id, message_id=message_id)
        # Telegram API docs state deleteMessage returns True on success, False if message is not found.
        # Aiogram might raise an exception instead for certain errors (like bot not admin).
        service_logger.info(f"Attempted to delete message {message_id} from chat {chat_id}. Result: {result}")
        return result # delete_message returns bool

    except TelegramAPIError as e:
        # Common errors: message already deleted (MessageToDeleteNotFound), message_id invalid,
        # bot not admin with delete rights (NotEnoughRights).
        # Log warning for known API errors, return False.
        service_logger.warning(f"Telegram API error deleting message {message_id} from chat {chat_id}: {e}")
        return False
    except AiogramError as e:
         # Catch other aiogram specific errors
         service_logger.error(f"Aiogram error deleting message {message_id} from chat {chat_id}: {e}", exc_info=True)
         return False
    except Exception as e:
        service_logger.error(f"Unexpected error deleting message {message_id} from chat {chat_id}: {e}", exc_info=True)
        return False


async def get_chat_member_status(bot: Bot, chat_id: Union[int, str], user_id: int) -> Optional[str]:
    """
    Получает статус участника в чате.

    Args:
        bot: Экземпляр aiogram.Bot.
        chat_id: ID чата.
        user_id: ID пользователя.

    Returns:
        Статус участника ('creator', 'administrator', 'member', 'restricted',
        'left', 'banned') или None в случае ошибки API (e.g. chat not found, user not found).
    """
    try:
        chat_member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        service_logger.debug(f"Got chat member status for user {user_id} in chat {chat_id}: {chat_member.status}")
        return chat_member.status
    except TelegramAPIError as e:
        # Common errors: chat not found (ChatNotFound), user not in chat (UserNotFound, although Aiogram might raise TelegramBadRequest)
        # Log warning for known API errors, return None.
        service_logger.warning(f"Telegram API error getting status for user {user_id} in chat {chat_id}: {e}")
        return None
    except AiogramError as e:
         service_logger.error(f"Aiogram error getting status for user {user_id} in chat {chat_id}: {e}", exc_info=True)
         return None
    except Exception as e:
        service_logger.error(f"Unexpected error getting status for user {user_id} in chat {chat_id}: {e}", exc_info=True)
        return None


async def check_bot_permissions_in_channel(bot: Bot, chat_id: Union[int, str]) -> Dict[str, Union[bool, str]]:
    """
    Проверяет, является ли бот администратором в канале и имеет ли нужные права.

    Args:
        bot: Экземпляр aiogram.Bot.
        chat_id: ID чата.

    Returns:
        Словарь с правами бота (is_admin, can_post_messages, can_delete_messages),
        возвращает False для всех, если бот не адmin или произошла ошибка.
        Includes an 'error' key indicating if an API error occurred.
    """
    result: Dict[str, Union[bool, str]] = {
        'is_admin': False,
        'can_post_messages': False,
        'can_delete_messages': False,
        'error': False, # Indicate if an API error occurred
        'status': 'unknown' # Bot's status in the chat
    }
    try:
        # Get chat member info for the bot itself
        chat_member = await bot.get_chat_member(chat_id=chat_id, user_id=bot.id)
        result['status'] = chat_member.status

        # Check if bot is creator or administrator
        if chat_member.status in ['administrator', 'creator']:
            result['is_admin'] = True
            # Check specific permissions if bot is admin
            # These attributes are available on ChatMemberAdministrator/ChatMemberOwner,
            # which are subclasses of ChatMember. Aiogram objects should have these if status is admin/creator.
            # Use getattr with a default of False to be safe if the object structure changes slightly.
            result['can_post_messages'] = getattr(chat_member, 'can_post_messages', False)
            result['can_delete_messages'] = getattr(chat_member, 'can_delete_messages', False)
            service_logger.debug(f"Bot permissions in chat {chat_id}: {result}")
        else:
            service_logger.debug(f"Bot is not an administrator or creator in chat {chat_id}. Status: {chat_member.status}")
            # Status is not admin/creator, so permissions are False (initialized that way)


    except TelegramAPIError as e:
        # Common errors: chat not found (ChatNotFound), bot not in chat (UserNotFound/TelegramBadRequest).
        # These are API errors preventing the check.
        service_logger.warning(f"Telegram API error checking bot permissions in chat {chat_id}: {e}")
        result['error'] = True # Indicate API error
        result['status'] = 'api_error' # Indicate status couldn't be determined due to API error
    except AiogramError as e:
         service_logger.error(f"Aiogram error checking bot permissions in chat {chat_id}: {e}", exc_info=True)
         result['error'] = True
         result['status'] = 'aiogram_error'
    except Exception as e:
        service_logger.error(f"Unexpected error checking bot permissions in chat {chat_id}: {e}", exc_info=True)
        result['error'] = True
        result['status'] = 'unexpected_error'


    return result
"""

# Content for services/content_manager_service.py (from task yBWNP)
SERVICES_CONTENT_MANAGER_CONTENT = """
import logging
import os
import shutil
import uuid
from typing import Optional, List, Dict, Any, Union
from pathlib import Path
import aiohttp # Keep aiohttp for URL downloads
import aiofiles # Keep aiofiles for async file writing

from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument, Message, FSInputFile
from aiogram.exceptions import TelegramAPIError, AiogramError, DownloadTelegramObjectError, TelegramBadRequest

# Assuming validators and logger are configured in utils/
try:
    from utils.logger import logger
    # Assuming validate_media_properties is defined in utils.validators
    from utils.validators import validate_media_properties # Example: check file size/type
except ImportError as e:
    logging.error(f"Failed to import utils: {e}. Using basic logging and dummy validator.", exc_info=True)
    logger = logging.getLogger(__name__)
    # Dummy validator fallback
    def validate_media_properties(*args, **kwargs):
        service_logger.warning("Using dummy validate_media_properties. Real validation missing.")
        return True

service_logger = logging.getLogger(__name__)
service_logger.setLevel(logger.level if 'logger' in globals() else logging.INFO)

# Configuration for temporary media storage
TEMP_MEDIA_DIR = Path("media_temp")
MAX_TEXT_LENGTH = 4096 # Telegram limit for message text
MAX_CAPTION_LENGTH = 1024 # Telegram limit for media caption


def validate_post_text(text: Optional[str]) -> bool:
    """
    Проверяет текст поста на базовые ограничения (например, максимальная длина).

    Args:
        text: Текст поста.

    Returns:
        True, если текст валиден (or None), иначе False.
    """
    if text is None:
        return True # Empty text is allowed (e.g., media-only post)
    if not isinstance(text, str):
        service_logger.warning(f"Post text is not a string: {type(text)}. Invalid.")
        return False
    if len(text) > MAX_TEXT_LENGTH:
        service_logger.warning(f"Post text exceeds max length ({len(text)} > {MAX_TEXT_LENGTH}).")
        return False

    # Basic tag validation could be added here, but it's complex
    # depending on allowed Markdown/HTML modes. Skipping for basic validation.

    return True

async def download_and_save_media_by_file_id(
    bot: Bot,
    file_id: str,
    user_id: int,
    entity_id: int # Use a unique ID for grouping temporary files (e.g., draft_id, post_id, rss_feed_id)
) -> Optional[Path]:
    """
    Загружает медиафайл по file_id во временную директорию пользователя/сущности
    и возвращает локальный путь к сохраненному файлу.

    Args:
        bot: Экземпляр aiogram.Bot.
        file_id: Telegram file_id медиафайла.
        user_id: Внутренний ID пользователя (из БД).
        entity_id: ID сущности (черновика, поста, ленты) для организации файлов.

    Returns:
        Локальный путь к сохраненному файлу (Path object) или None в случае ошибки.
    """
    temp_dir = TEMP_MEDIA_DIR / str(user_id) / str(entity_id)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Get file info to construct filename and validate properties
        file = await bot.get_file(file_id)
        if not file or not file.file_path:
            service_logger.error(f"Failed to get file info for file_id {file_id}.")
            return None

        # Construct a safe filename. Use original filename if available from context (not on File object),
        # or file_unique_id + extension.
        # Telegram's File object's file_path is like "documents/file_unique_id.ext", not the original filename.
        file_extension = Path(file.file_path).suffix if file.file_path else ".tmp"
        # Using file.file_unique_id ensures a unique and safe base name
        safe_filename = f"{file.file_unique_id}{file_extension}"

        local_path = temp_dir / safe_filename

        # Validate file properties before downloading if available (e.g. file.file_size)
        if file.file_size is not None:
             if not validate_media_properties(file_size=file.file_size):
                  service_logger.warning(f"File {file_id} failed size validation ({file.file_size} bytes). Skipping download.")
                  return None

        # Download the file
        await bot.download_file(file.file_path, destination=local_path)

        service_logger.info(f"Downloaded file_id {file_id} to {local_path}")
        return local_path

    except (DownloadTelegramObjectError, TelegramAPIError, AiogramError) as e:
        service_logger.error(f"Error processing or downloading file_id {file_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        service_logger.error(f"Unexpected error downloading file_id {file_id}: {e}", exc_info=True)
        return None

async def download_url_to_temp(
    url: str,
    user_id: int,
    entity_id: int,
    filename: Optional[str] = None # Optional suggested filename
) -> Optional[Path]:
    """
    Загружает файл по URL во временную директорию пользователя/сущности
    и возвращает локальный путь к сохраненному файлу.

    Args:
        url: URL файла.
        user_id: Внутренний ID пользователя (из БД).
        entity_id: ID сущности (черновика, поста, ленты) для организации файлов.
        filename: Optional filename suggestion.

    Returns:
        Локальный путь к сохраненному файлу (Path object) или None в случае ошибки.
    """
    temp_dir = TEMP_MEDIA_DIR / str(user_id) / str(entity_id)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Determine filename and sanitize it to prevent path traversal and invalid characters
    if filename:
        # Simple sanitization: allow only alphanumeric, dot, underscore, hyphen
        # Use os.path.basename to strip any path components just in case filename includes them
        safe_filename = os.path.basename(filename)
        safe_filename = "".join(c for c in safe_filename if c.isalnum() or c in ('.', '_', '-')).rstrip('.')
        # Ensure it's not empty after sanitization
        if not safe_filename:
             safe_filename = f"download_{uuid.uuid4()}" # Fallback to a unique name

    else:
        # Generate a unique filename based on UUID and original URL path name
        safe_filename = f"download_{uuid.uuid4()}_{os.path.basename(Path(url).name)}"
        # Sanitize the generated name
        safe_filename = "".join(c for c in safe_filename if c.isalnum() or c in ('.', '_', '-')).rstrip('.')
        if not safe_filename:
             safe_filename = f"download_{uuid.uuid4()}"


    local_path = temp_dir / safe_filename

    # Basic validation (URL, size limits if possible via headers)
    # This could be more complex, e.g., checking content-type.
    if not validate_media_properties(url=url): # Assuming validator can handle URL checks
         service_logger.warning(f"URL {url} failed validation. Skipping download.")
         return None


    try:
        # Use aiohttp for async download
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

                # Optional: Check Content-Length header against size limits
                content_length = response.headers.get('Content-Length')
                if content_length and not validate_media_properties(file_size=int(content_length)):
                     service_logger.warning(f"File at URL {url} failed size validation ({content_length} bytes). Skipping download.")
                     return None

                # Optional: Check Content-Type header against allowed types
                content_type = response.headers.get('Content-Type')
                if content_type and not validate_media_properties(mime_type=content_type):
                     service_logger.warning(f"File at URL {url} failed type validation ({content_type}). Skipping download.")
                     return None


                # Save the content asynchronously
                async with aiofiles.open(local_path, 'wb') as f:
                    await f.write(await response.read())

        service_logger.info(f"Downloaded URL {url} to {local_path}")
        return local_path

    except aiohttp.ClientResponseError as e:
        service_logger.error(f"HTTP error downloading URL {url}: {e}", exc_info=True)
        return None
    except aiohttp.ClientConnectionError as e:
        service_logger.error(f"Connection error downloading URL {url}: {e}", exc_info=True)
        return None
    except Exception as e:
        service_logger.error(f"Unexpected error downloading URL {url}: {e}", exc_info=True)
        return None


def prepare_media_for_sending(media_records: List[Dict]) -> List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]]:
    """
    Конвертирует список записей о медиа (с локальными путями или file_id)
    в список объектов InputMedia* для send_media_group.

    Args:
        media_records: Список словарей, описывающих медиафайлы.
                       Формат: [{'type': 'photo', 'file_id': '...'},
                                 {'type': 'video', 'path': Path(...)},
                                 {'type': 'document', 'file_id': '...'}, ...]
                       Records should contain EITHER 'file_id' (string) OR 'path' (Path object or string).
                       Caption/parse_mode should ideally be handled on the first item in the calling service
                       or passed here if needed per item. This function focuses on the media source.

    Returns:
        Список объектов InputMediaPhoto, InputMediaVideo, InputMediaDocument.
    """
    prepared_media = []
    for record in media_records:
        media_type = record.get('type')
        file_id = record.get('file_id')
        local_path = record.get('path')
        # Caption and parse_mode can be passed here if needed per item, but typically set on the first.
        caption = record.get('caption')
        parse_mode = record.get('parse_mode')


        if not media_type or (file_id is None and local_path is None):
            service_logger.warning(f"Skipping invalid media record (missing type, file_id or path): {record}")
            continue

        # Media source is either file_id or a local file (FSInputFile)
        media_source = None
        if file_id:
            media_source = file_id # Use file_id string directly
        elif local_path and (isinstance(local_path, Path) or os.path.exists(str(local_path))):
            media_source = FSInputFile(str(local_path)) # Use FSInputFile for local paths
        else:
            service_logger.warning(f"Skipping media record with invalid or missing path: {record}. Path exists? {os.path.exists(str(local_path)) if local_path else 'N/A'}")
            continue


        try:
            if media_type == 'photo':
                 media_obj = InputMediaPhoto(media=media_source, caption=caption, parse_mode=parse_mode)
            elif media_type == 'video':
                 media_obj = InputMediaVideo(media=media_source, caption=caption, parse_mode=parse_mode)
                 # Optional: Add thumbnail support if available in record
                 thumbnail_path = record.get('thumbnail_path')
                 if thumbnail_path and (isinstance(thumbnail_path, Path) or os.path.exists(str(thumbnail_path))):
                      media_obj.thumbnail = FSInputFile(str(thumbnail_path))
                 elif thumbnail_path:
                      service_logger.warning(f"Thumbnail path not found or invalid: {thumbnail_path}")

            elif media_type == 'document':
                 media_obj = InputMediaDocument(media=media_source, caption=caption, parse_mode=parse_mode)
            # Add other types like audio if needed

            else:
                service_logger.warning(f"Unsupported media type '{media_type}' in record: {record}. Skipping.")
                continue

            prepared_media.append(media_obj)

        except Exception as e:
            service_logger.error(f"Error preparing media item {record}: {e}", exc_info=True)
            continue

    service_logger.debug(f"Prepared {len(prepared_media)} media items from {len(media_records)} records.")
    return prepared_media


def cleanup_temporary_media_for_draft(user_id: int, entity_id: int):
    """
    Удаляет временную директорию с медиафайлами для конкретного черновика/поста/RSS-ленты пользователя.

    Args:
        user_id: Внутренний ID пользователя (из БД).
        entity_id: ID сущности (черновика, поста, RSS-ленты).
    """
    temp_dir = TEMP_MEDIA_DIR / str(user_id) / str(entity_id)
    if temp_dir.exists():
        try:
            shutil.rmtree(temp_dir)
            service_logger.info(f"Cleaned up temporary media directory: {temp_dir}")
        except Exception as e:
            service_logger.error(f"Error cleaning up temporary media directory {temp_dir}: {e}", exc_info=True)
    else:
        service_logger.debug(f"Temporary media directory not found for cleanup: {temp_dir}")

# Note: You might need different cleanup functions or logic depending on when you want cleanup to happen.
# e.g., cleanup after draft is saved as post, after post is sent, after RSS feed is processed.
# This generic cleanup function can be called from different places.
"""

# Content for services/rss_service.py (from task SrzpQ)
SERVICES_RSS_CONTENT = """
import logging
import datetime
import pytz
import feedparser
import asyncio
import time # For mktime conversion
import re # For keyword filtering
from typing import Optional, List, Dict, Any

# Assuming models, db_session_maker_factory, bot instance, and other services are available
# These should be passed as arguments or via dependency injection, not accessed globally.
# Global placeholders below follow the implicit structure of the reference, but should be avoided.
async_sessionmaker = None # Placeholder: REPLACE THIS WITH YOUR ACTUAL SESSIONMAKER FACTORY
bot = None # Placeholder: REPLACE THIS WITH YOUR ACTUAL BOT INSTANCE

# Assuming logger, validators, helpers are configured in utils/
try:
    from utils.logger import logger
    from utils.validators import validate_url # Assuming this exists for feed_url validation
    # Assuming validate_media_properties exists for image URL validation
    from utils.validators import validate_media_properties # Used for image URL validation
    # Assuming convert_datetime_to_utc exists (though pytz is used directly now)
    # from utils.helpers import convert_datetime_to_utc
except ImportError as e:
    logging.error(f"Failed to import utils: {e}. Using basic logging and dummy utils.", exc_info=True)
    logger = logging.getLogger(__name__)
    # Dummy utils fallback
    def validate_url(url):
        service_logger.warning("Using dummy validate_url.")
        return True
    def validate_media_properties(*args, **kwargs):
        service_logger.warning("Using dummy validate_media_properties.")
        return True


service_logger = logging.getLogger(__name__)
service_logger.setLevel(logger.level if 'logger' in globals() else logging.INFO)

# Import services needed within rss processing - Deferred import
# These will be imported via _lazy_import_services inside the functions
db_service = None
telegram_api_service = None
content_manager_service = None

def _lazy_import_services():
    """Helper to lazily import services within a function scope."""
    global db_service, telegram_api_service, content_manager_service
    if db_service is None:
        try:
            # Assuming services are in a package 'services' relative to the bot root
            from services import db_service as imported_db_service
            from services import telegram_api_service as imported_telegram_api_service
            from services import content_manager_service as imported_content_manager_service
            db_service = imported_db_service
            telegram_api_service = imported_telegram_api_service
            content_manager_service = imported_content_manager_service
            service_logger.debug("RSS services lazily imported.")
        except ImportError as e:
            service_logger.error(f"Failed to import services within RSS processing: {e}", exc_info=True)
            # Set to None to indicate failure
            db_service = telegram_api_service = content_manager_service = None


async def check_all_active_feeds(bot_instance: Any, db_session_maker_factory: Any):
    """
    Получает все активные RSS-ленты из БД и для каждой вызывает process_single_feed.
    Предназначена для запуска либо при старте приложения, либо как часть управления.
    Note: If scheduler jobs check single feeds (_rss_check_job), this function is for
    initial population or full sweeps, not the primary scheduled check mechanism.
    """
    _lazy_import_services()
    if not db_service or not bot_instance or not db_session_maker_factory:
        service_logger.error("Cannot check all feeds: Dependencies not available.")
        return

    service_logger.info("Checking all active RSS feeds...")

    # Use a single session for fetching feeds, but process each feed in a separate task
    # or manage sessions within each task if processing is long.
    # The current design passes the session factory, so process_single_feed manages its own session.
    # Fetching feeds needs a session.
    try:
        async with db_session_maker_factory() as session:
             active_feeds = await db_service.get_all_active_rss_feeds(session)
    except Exception as e:
        service_logger.error(f"Error fetching active RSS feeds: {e}", exc_info=True)
        return # Cannot proceed if fetching fails


    tasks = []
    for feed in active_feeds:
        # Create a task for each feed check to run them concurrently
        # Pass the bot instance and session factory
        tasks.append(asyncio.create_task(
            process_single_feed(bot_instance, db_session_maker_factory, feed)
        ))

    # Wait for all tasks to complete
    await asyncio.gather(*tasks)

    service_logger.info("Finished checking all active RSS feeds.")


async def process_single_feed(bot_instance: Any, db_session_maker_factory: Any, feed_db_obj: Any):
    """
    Парсит одну RSS-ленту, обрабатывает новые элементы и публикует их.

    Args:
        bot_instance: Экземпляр aiogram.Bot.
        db_session_maker_factory: Фабрика асинхронных сессий SQLAlchemy.
        feed_db_obj: Объект модели RssFeed из БД.
    """
    _lazy_import_services()
    if not db_service or not telegram_api_service or not content_manager_service or not bot_instance or not db_session_maker_factory:
        service_logger.error(f"Cannot process feed {feed_db_obj.id} (URL: {feed_db_obj.feed_url}): Dependencies not available.")
        # Attempt to update last_checked_at even on dependency error
        # Use a new session for this quick update
        try:
            async with db_session_maker_factory() as session_update:
                 # update_rss_feed does not commit, need to commit session here
                 await db_service.update_rss_feed(session_update, feed_db_obj.id, last_checked_at=pytz.utc.localize(datetime.datetime.utcnow()))
                 await session_update.commit() # Commit the update immediately
        except Exception as update_e:
             service_logger.error(f"Error updating last_checked_at for feed {feed_db_obj.id} after deps error: {update_e}", exc_info=True)

        return # Cannot proceed without essential dependencies


    feed_url = feed_db_obj.feed_url
    service_logger.info(f"Processing RSS feed {feed_db_obj.id} from URL: {feed_url}")

    if not validate_url(feed_url):
        service_logger.error(f"Invalid URL for RSS feed {feed_db_obj.id}: {feed_url}. Skipping.")
        # Mark feed as invalid in DB? For now, just skip processing.
        # Update last checked even on invalid URL? Debatable. Let's not, as it wasn't a successful check.
        return

    feed_data = None
    try:
        # Run synchronous feedparser.parse in a thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        feed_data = await loop.run_in_executor(None, feedparser.parse, feed_url)

        if feed_data.bozo:
            service_logger.warning(f"Feed {feed_db_obj.id} URL {feed_url} parse error: {feed_data.bozo_exception}")
            # Decide how to handle parse errors (skip, retry, mark invalid).
            # If no entries are found, and there's a parse error, it's likely invalid.
            if not feed_data.entries:
                service_logger.warning(f"Feed {feed_db_obj.id} has parse error and no entries. Skipping processing.")
                # Still update last checked? Yes, attempted check.
                await _update_feed_last_checked(db_session_maker_factory, feed_db_obj.id)
                return

    except Exception as e:
        service_logger.error(f"Error fetching or parsing RSS feed {feed_db_obj.id} from URL {feed_url}: {e}", exc_info=True)
        await _update_feed_last_checked(db_session_maker_factory, feed_db_obj.id) # Update last checked even on fetch/parse error
        return # Stop processing this feed if fetch/parse failed

    new_items_count = 0
    published_count = 0 # Count items successfully sent to Telegram

    # Process entries within a single session transaction
    # Use a try...except block around the session for rollback on error
    async with db_session_maker_factory() as session:
        try:
            for entry in feed_data.entries:
                # Use GUID as unique identifier if available, otherwise use link
                item_guid = entry.get('id') or entry.get('link')
                if not item_guid:
                    service_logger.warning(f"Feed {feed_db_obj.id}: Skipping entry with no GUID or link: {entry.get('title', 'No title')}")
                    continue

                # Check if item already processed (using db_service).
                # check_rss_item_exists queries based on the unique item_guid.
                # We should get the item object to check if it's already posted.
                rss_item_obj = await db_service.get_rss_item_by_guid(session, item_guid)

                if rss_item_obj and rss_item_obj.is_posted:
                    service_logger.debug(f"Feed {feed_db_obj.id}: Item {item_guid} already posted. Skipping.")
                    continue
                elif rss_item_obj and not rss_item_obj.is_posted:
                     # Item exists but was not marked as posted (e.g., previous send failed)
                     service_logger.info(f"Feed {feed_db_obj.id}: Item {item_guid} exists but was not marked posted. Attempting publication again.")
                     # Continue to publication logic below

                # Apply keyword filter if specified (only for items not already in DB, or items in DB but not posted?)
                # Let's apply filter only to items not yet seen in the DB at all.
                # If an item exists but wasn't posted, we *should* re-attempt based on current filters.
                # This means filter should apply to items where is_posted is False or item does not exist.
                if not rss_item_obj: # Only filter items not previously seen in DB
                    filter_keywords = feed_db_obj.filter_keywords
                    if filter_keywords and isinstance(filter_keywords, list) and filter_keywords:
                        entry_text_for_filter = f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('content', '')}".lower()
                        if not any(keyword.strip().lower() in entry_text_for_filter for keyword in filter_keywords if keyword and isinstance(keyword, str)):
                            service_logger.info(f"Feed {feed_db_obj.id}: Item {item_guid} does not match filter keywords. Skipping.")
                            # IMPORTANT: Add filtered item to DB *immediately* with is_posted=False (or a 'filtered' status if model supported)
                            # This prevents re-checking this item against filters on subsequent runs.
                            # Since RssItem only has is_posted, we add it with is_posted=False. The fact it exists prevents re-adding.
                            # Its presence means it's been 'processed' (filtered).
                            # Need to add it before continuing, so the check at the start of the loop works next time.
                            published_dt_utc_filtered = None
                            if 'published_parsed' in entry and entry.published_parsed:
                                 try:
                                      published_dt_utc_filtered = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=pytz.utc)
                                 except Exception: pass # Ignore date parsing errors for filtered items
                            # Add item with is_posted=False. add_rss_item handles existence check/returns existing.
                            # add_rss_item doesn't commit, so stage it here and commit later.
                            try:
                                added_or_existing_filtered_item = await db_service.add_rss_item(session, feed_db_obj.id, item_guid, published_dt_utc_filtered)
                                if added_or_existing_filtered_item:
                                     service_logger.debug(f"Feed {feed_db_obj.id}: Item {item_guid} staged in DB with is_posted=False after filtering.")
                                # Do not process further for sending.
                            except Exception as db_add_e:
                                service_logger.error(f"Feed {feed_db_obj.id}: Error staging filtered RSS item {item_guid} to DB: {db_add_e}", exc_info=True)
                            continue # Skip processing this entry if it was filtered out


                service_logger.info(f"Feed {feed_db_obj.id}: Found new or unposted item: {entry.get('title', 'No title')}")


                # --- Prepare Post Content ---
                # Format post text
                title = entry.get('title', 'Без заголовка')
                link = entry.get('link', feed_url) # Fallback to feed URL if no item link
                summary = entry.get('summary', '').strip()
                # Fallback to content if summary is empty
                if not summary:
                    content_parts = entry.get('content', [])
                    if content_parts:
                         # Take the value of the first content part
                         summary = content_parts[0].get('value', '').strip()

                # Clean up HTML tags from summary/content if present (basic regex)
                summary = re.sub(r'<.*?>', '', summary)
                # Decode HTML entities if needed (feedparser often handles this, but sometimes not fully)
                # import html # html.unescape(summary)

                # Construct the main text with Markdown V2 formatting
                # Escaping necessary Markdown V2 characters: `_ * [ ] ( ) ~ ` > # + - = | { } . !`
                # Simple escape for now, a dedicated markdown escape helper is better.
                def escape_mdv2(text: str) -> str:
                    if text is None: return ""
                    # Escape characters that have special meaning in MarkdownV2
                    # List of characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
                    # Escaping '.' is needed for lists/urls etc, but might look weird elsewhere.
                    # Escaping '-' needed for list items, etc.
                    # Escaping '|' for tables.
                    # Let's escape the minimum required for basic formatting and links/bold/italic.
                    # Characters that *must* be escaped if not used for formatting: _ * [ ] ( ) ~ ` > # + - = | { } . !
                    # A simpler set of chars that are *always* potentially problematic in text: _ * [ ] ( ) ~ ` > # | { }
                    # Let's use a more complete set that needs care: _ * [ ] ( ) ~ ` > # + - = | { } . !
                    # Example: "a _ b * c [ d ] ( e ) ~ f ` g > h # i + j - k = l | m { n } o . p ! q"
                    chars_to_escape = r'_*[]()~`>#+-=|{}.!'
                    # Prepend '\' to each character in chars_to_escape if it appears in the text
                    # Use a lambda function in replace for more control if needed, but re.sub is usually fine.
                    escaped_text = text
                    # Escape \ first!
                    escaped_text = escaped_text.replace('\\', '\\\\')
                    for char in '_*[]()~`>#+-=|{}.!':
                         # Only escape if not part of a valid MDV2 sequence? Too complex here.
                         # Escape all occurrences. This might break some intended formatting.
                         # A robust MDV2 escape needs context. Basic escape for safety.
                         if char in text:
                             escaped_text = escaped_text.replace(char, f'\\{char}')

                    # Correct escape for numbers at start of line for lists (e.g. "1. Item")
                    # This needs line awareness. Skipping for basic escape.

                    return escaped_text


                escaped_title = escape_mdv2(title)
                escaped_summary = escape_mdv2(summary)
                # Link in MarkdownV2 format: [Text](URL)
                link_text = escape_mdv2("Читать далее") # Text for the link

                post_text_parts = [f"*{escaped_title}*", "\n\n"] # Title bolded
                if escaped_summary:
                    post_text_parts.append(f"{escaped_summary}\n\n")
                # Add link separately using the original, unescaped URL for the link target
                # The URL itself doesn't need escaping, but the parentheses *around* it might if they appear in the URL itself.
                # Telegram API docs say: "Parentheses `()` around URLs in links must be escaped: `[example](https://example.com\))`"
                # This means *if* the URL contains `)`, it needs escaping.
                # For simplicity, let's assume basic URLs or rely on Telegram API handling.
                if link:
                     # Check for unescaped ')' in link and escape it for MDV2 link format
                     escaped_link = link.replace(')', '\\)')
                     post_text_parts.append(f"[{link_text}]({escaped_link})")

                post_text = "".join(post_text_parts)

                # Ensure text does not exceed Telegram caption limit (1024) if media will be used,
                # or message text limit (4096) if text only.
                # Assume for RSS items, we prefer media with caption if possible.
                # Max length for caption is 1024. Truncate if necessary.
                # We don't know yet if media will be successfully attached.
                # Let's prepare the text assuming it might be a caption, so truncate to 1024.
                if len(post_text) > content_manager_service.MAX_CAPTION_LENGTH:
                     # Truncate carefully to not break Markdown formatting mid-tag/escape sequence.
                     # Simple truncation might cut off escapes. A more complex approach needed for perfect truncation.
                     # Basic truncation:
                     truncated_text = post_text[:content_manager_service.MAX_CAPTION_LENGTH - 20].rstrip() # Reserve space for ellipsis
                     # Ensure truncation doesn't end mid-escape sequence like '\\'
                     if truncated_text.endswith('\\'):
                          truncated_text = truncated_text[:-1].rstrip()
                     post_text = truncated_text + "..." # Truncate and add ellipsis

                # Handle media (find image URL in entry and download it)
                media_records = []
                image_url = None

                # Check standard places for image URLs
                # 1. media_content (from media RSS module)
                if 'media_content' in entry and entry['media_content']:
                    for media in entry['media_content']:
                        # Check for type and URL
                        media_type = media.get('type', '')
                        media_url = media.get('url')
                        # Prioritize image types
                        if media_url and media_type.startswith('image/'):
                            image_url = media_url
                            break # Found an image, take the first
                # 2. enclosures
                if not image_url and 'enclosures' in entry and entry['enclosures']:
                     for enc in entry['enclosures']:
                          # Check for type and URL
                          enc_type = enc.get('type', '')
                          enc_url = enc.get('url')
                          if enc_url and enc_type.startswith('image/'):
                               image_url = enc_url
                               break # Found an image, take the first

                # 3. img tag in summary or content (less reliable, depends on feed quality)
                if not image_url:
                     # Check first content part or summary
                     content_to_search = entry.get('content', [{'value':''}])[0].get('value', '') or entry.get('summary', '')
                     # Use BeautifulSoup for robust HTML parsing if complex feeds expected
                     # from bs4 import BeautifulSoup
                     # soup = BeautifulSoup(content_to_search, 'html.parser')
                     # img_tag = soup.find('img')
                     # if img_tag and 'src' in img_tag.attrs:
                     #      image_url = img_tag['src']
                     # Basic regex fallback if no BeautifulSoup
                     if isinstance(content_to_search, str):
                         match = re.search(r'<img.*?src=["\'](.*?)["\']', content_to_search)
                         if match:
                              image_url = match.group(1)


                local_media_path = None
                # Check if image_url is valid before attempting download
                if image_url and validate_url(image_url) and content_manager_service:
                    service_logger.debug(f"Feed {feed_db_obj.id}: Found image URL: {image_url}. Attempting download.")
                    try:
                         # Download the image URL to a temporary file
                         local_media_path = await content_manager_service.download_url_to_temp(
                             image_url,
                             feed_db_obj.user_id,
                             feed_db_obj.id # Use feed ID as entity ID for temp files
                         )
                         if local_media_path:
                              service_logger.info(f"Feed {feed_db_obj.id}: Downloaded image for item {item_guid} to {local_media_path}")
                              # Add the downloaded file path to media_records
                              # The type is assumed 'photo' based on finding an image URL.
                              media_records.append({'type': 'photo', 'path': local_media_path})
                              # The main post_text will be used as the caption for the first media item.
                              # Do NOT set caption here, let send_post_to_channel handle it on the first item.

                         else:
                              service_logger.warning(f"Feed {feed_db_obj.id}: Failed to download image from URL: {image_url}")
                              # Continue without media
                    except Exception as e:
                         service_logger.error(f"Error downloading image URL {image_url} for feed {feed_db_obj.id}: {e}", exc_info=True)
                         # Continue without media if image failed
                elif image_url:
                    # Image URL exists but is invalid format or content_manager_service not available
                    service_logger.warning(f"Feed {feed_db_obj.id}: Image URL '{image_url}' is invalid or content_manager_service unavailable. Skipping image download.")


                # Prepare media objects for sending if any were found and downloaded
                prepared_media_objects = []
                if media_records and content_manager_service:
                     # prepare_media_for_sending takes local paths and returns InputMedia objects
                     prepared_media_objects = content_manager_service.prepare_media_for_sending(media_records)
                     if prepared_media_objects:
                         service_logger.debug(f"Prepared {len(prepared_media_objects)} media objects for sending.")
                         # The first item in prepared_media_objects will get the post_text as its caption
                         # in the telegram_api_service.send_post_to_channel function.
                         # Clear post_text if it's being used as a caption.
                         # No, the send function handles this. Just pass both text and media.
                     else:
                          service_logger.warning(f"Feed {feed_db_obj.id}: No media objects prepared despite records. Skipping media send.")
                          media_records = [] # Clear records if preparation failed


                # Publish post to channels (using telegram_api_service)
                success = True
                sent_message_ids = {} # Track for potential future deletion (unlikely for RSS items)
                if feed_db_obj.channels and telegram_api_service:
                     # Ensure there's actually something to send (text or media)
                     if not prepared_media_objects and not post_text:
                          service_logger.warning(f"Feed {feed_db_obj.id}: Item {item_guid} has no text or media to send. Skipping publication.")
                          success = False # Nothing to send
                     else:
                          for chat_id in feed_db_obj.channels:
                               try:
                                     # Pass the bot instance to the service function
                                     message_info = await telegram_api_service.send_post_to_channel(
                                          bot_instance, # Pass bot instance
                                          chat_id,
                                          post_text, # Text (might be used as caption)
                                          prepared_media_objects, # Prepared media objects
                                          feed_db_obj.parse_mode # Use parse mode from feed settings
                                     )
                                     if message_info:
                                         # Get message_id(s)
                                         # telegram_api_service returns Message or List[Message]
                                         if isinstance(message_info, list) and message_info:
                                             if message_info: # Check if list is not empty
                                                 if hasattr(message_info[0], 'message_id'):
                                                     # Store the first message_id of the media group
                                                     sent_message_ids[str(chat_id)] = message_info[0].message_id
                                                 else:
                                                     service_logger.warning(f"Feed {feed_db_obj.id}: Sent media group to {chat_id}, but first item has no message_id.")
                                         elif message_info and hasattr(message_info, 'message_id'):
                                             # Single message
                                             sent_message_ids[str(chat_id)] = message_info.message_id
                                         else:
                                             service_logger.warning(f"Feed {feed_db_obj.id}: Sent message to {chat_id}, but response has no message_id.")

                                         service_logger.info(f"Feed {feed_db_obj.id}: Item {item_guid} sent to chat {chat_id}. Message ID: {sent_message_ids.get(str(chat_id), 'N/A')}")
                                     else:
                                         service_logger.warning(f"Feed {feed_db_obj.id}: Item {item_guid} failed to send to chat {chat_id}.")
                                         success = False # If sending to any channel fails
                               except Exception as e:
                                    service_logger.error(f"Feed {feed_db_obj.id}: Error sending item {item_guid} to chat {chat_id}: {e}", exc_info=True)
                                    success = False # If sending to any channel fails
                else:
                     service_logger.warning(f"Feed {feed_db_obj.id}: No channels specified or telegram_api_service not available. Item {item_guid} not published.")
                     success = False # Consider it not published if no channels


                # Save information about the processed item in rss_items (using db_service)
                # Add to rss_items table regardless of send success initially, then mark as posted if successful.
                # This ensures we record that we *tried* to process this item GUID.
                # Check if item already exists in *this* session (handle duplicates from feedparser)
                # If item_guid already exists in the DB (checked at the start of the loop), we don't add again.
                # We only add if it's a completely new item GUID.
                if not rss_item_obj: # Only add if it didn't exist in DB before this check
                     published_dt_utc = None
                     if 'published_parsed' in entry and entry.published_parsed:
                          try:
                               # feedparser parses 'published_parsed' into a UTC time.struct_time
                               # Convert struct_time to timezone-aware UTC datetime
                                published_dt_utc = datetime.datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=pytz.utc)
                          except Exception as date_e:
                               service_logger.warning(f"Feed {feed_db_obj.id}: Could not parse published date '{entry.get('published_parsed')}': {date_e}")
                               published_dt_utc = None # Keep as None if parsing fails

                     # Add the item record. add_rss_item handles existence check.
                     # add_rss_item doesn't commit, it stages the item.
                     try:
                         added_or_existing_item = await db_service.add_rss_item(session, feed_db_obj.id, item_guid, published_dt_utc)
                         if added_or_existing_item and not rss_item_obj: # Count only truly new items added (added_or_existing_item will be the new item object if not duplicate)
                             new_items_count += 1
                         rss_item_obj = added_or_existing_item # Update rss_item_obj reference, might be None if duplicate

                     except Exception as db_add_e:
                         service_logger.error(f"Feed {feed_db_obj.id}: Error staging RSS item {item_guid} to DB: {db_add_e}", exc_info=True)
                         # Cannot proceed if DB fails to record item. Mark send as failed or skip mark as posted.
                         success = False # Treat DB error as failure to process item fully


                # Mark item as posted *if* it was successfully sent to Telegram
                # This call happens *after* the send attempt and inside the loop for the current item.
                if success and rss_item_obj: # Ensure we have an item object to mark
                     try:
                         # mark_rss_item_as_posted stages the update, doesn't commit.
                         # It finds the item by GUID and updates its is_posted flag.
                         marked_posted_item = await db_service.mark_rss_item_as_posted(session, item_guid)
                         if marked_posted_item: # marked_posted_item is the item object if found and staged
                              service_logger.debug(f"Item {item_guid} staged as posted in DB.")
                              published_count += 1 # Count items successfully SENT and STAGED to be marked as posted
                         else:
                              service_logger.warning(f"Item {item_guid} not found to stage as posted, despite send success. (This is unexpected after adding/getting).")
                     except Exception as db_mark_e:
                          service_logger.error(f"Feed {feed_db_obj.id}: Error staging RSS item {item_guid} as posted: {db_mark_e}", exc_info=True)
                          # Log error, continue to next item. The item status might be incorrect in DB.


            # Commit the session after processing all entries that were staged
            # This commits all adds (new items, filtered items) and updates (mark as posted) in this batch.
            await session.commit()
            service_logger.info(f"Feed {feed_db_obj.id}: Session committed. {new_items_count} potentially new items processed, {published_count} items successfully published and marked.")

        except Exception as e:
             # Rollback the session if any error occurred during entry processing
             await session.rollback()
             service_logger.error(f"Unhandled error processing entries for RSS feed {feed_db_obj.id}: {e}", exc_info=True)
             # Do NOT re-raise, process next feed.

    # Update feed's last_checked_at timestamp regardless of whether new items were found or errors occurred during entry processing
    await _update_feed_last_checked(db_session_maker_factory, feed_db_obj.id)

    # Clean up temporary media files for this feed
    if content_manager_service:
         content_manager_service.cleanup_temporary_media_for_draft(feed_db_obj.user_id, feed_db_obj.id) # Use feed ID as entity ID

    service_logger.info(f"Feed {feed_db_obj.id}: Processing finished. Published {published_count} items.")


async def _update_feed_last_checked(db_session_maker_factory: Any, feed_id: int):
    """Helper to update the last_checked_at timestamp for a feed."""
    _lazy_import_services()
    if not db_service or not db_session_maker_factory:
        service_logger.error("Cannot update feed last checked: Dependencies not available.")
        return
    try:
        async with db_session_maker_factory() as session:
            # Pass timezone-aware UTC datetime
            # update_rss_feed does NOT commit, so need to commit the session here
            await db_service.update_rss_feed(
                session,
                feed_id,
                last_checked_at=pytz.utc.localize(datetime.datetime.utcnow()) # Add last_checked_at to RssFeed model
            )
            # Commit the helper session immediately
            await session.commit()
            service_logger.debug(f"Updated last_checked_at for feed {feed_id}.")
        except Exception as e:
            # This is a helper, log error but don't raise
            # Rollback if commit fails, though less critical for this specific update
            # The `async with session` block handles the rollback on exit if an exception occurs within it.
            service_logger.error(f"Error updating last_checked_at for feed {feed_id}: {e}", exc_info=True)

# How to set global placeholders in your main application file (e.g., bot.py):
# import rss_service
# from bot.db.database import async_sessionmaker as my_async_sessionmaker # Replace with actual import
# from bot.main import bot as my_bot_instance # Replace with actual import
#
# rss_service.async_sessionmaker = my_async_sessionmaker
# rss_service.bot = my_bot_instance
#
# # Then when running checks (e.g., from scheduler job _rss_check_job):
# # Call rss_service.process_single_feed(bot_instance, db_session_maker_factory, feed_object)
"""

# Content for handlers/commands.py (from task SrzpQ)
HANDLERS_COMMANDS_CONTENT = """
import logging
from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, Text, StateFilter
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler # Import for type hint

# Импорт сервисов
from services import db_service
# Удален неиспользуемый импорт scheduler_service

# Импорт клавиатур
from keyboards import reply_keyboards as rk
from keyboards import inline_keyboards as ik

# Импорт утилит
from utils.logger import logger
# Удален неиспользуемый импорт check_if_user_is_admin
# Удалены неиспользуемые импорты валидаторов
# from utils.validators import validate_channel_username, validate_iana_timezone, validate_url # Используется в других хендлерах

# Импорт FSM состояний и хелперов из других модулей
from handlers.post_creation import PostCreationStates # Для /newpost
# from handlers.channel_management import ChannelManagementStates # Если нужно FSM для add/remove
# from handlers.timezone_management import TimezoneManagementStates # Если нужно FSM для settimezone
# from handlers.rss_integration import RssIntegrationStates # Если нужно FSM для addrss

# Импорт обработчиков для делегирования команд (используем локальный импорт в функциях для избежания циклических зависимостей)
# from handlers import post_management
# from handlers import channel_management
# from handlers import timezone_management
# from handlers import rss_integration


router = Router()
command_logger = logging.getLogger(__name__)

# Зависимости, которые будут внедрены при регистрации роутера
# async def register_handlers(router: Router, sessionmaker, scheduler, bot):
#     router.message.register(...)
#     router.callback_query.register(...)
#     router["sessionmaker"] = sessionmaker # Пример передачи зависимости
#     router["scheduler"] = scheduler
#     router["bot"] = bot # Bot instance is also available via Message/CallbackQuery

# Получение зависимостей внутри хендлера (предполагая, что они переданы в filter_data или message.bot.workflow_data)
# async def my_handler(message: Message):
#    sessionmaker = message.bot.workflow_data.get('session_maker')
#    scheduler = message.bot.workflow_data.get('scheduler')
#    bot = message.bot # Bot instance
#    async with sessionmaker() as session: ...
#    scheduler.add_job(...)

# Более чистый способ: получать через аргументы, если настроен DI middleware
# async def my_handler(message: Message, session: AsyncSession, scheduler: AsyncIOScheduler, bot: Bot):
#     # session здесь - это уже инстанс сессии, открытый middleware
#     # Для scheduler и bot, если они не предоставляются middleware автоматически,
#     # можно либо получить из message.bot.workflow_data, либо использовать middleware для их внедрения.
#     pass # В текущей структуре, session, scheduler, bot передаются через аргументы хендлеров там, где они нужны.


@router.message(Command("start"))
async def handle_start_command(message: Message, session: AsyncSession):
    """Обработчик команды /start."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} sent /start")

    try:
        # Получение или создание пользователя в БД
        # db_service.get_or_create_user no longer commits, relying on caller session.
        # Wrap in transaction.
        async with session.begin():
             user = await db_service.get_or_create_user(session, user_id)
        # After commit, user object is persistent and usable.


        # Приветственное сообщение
        greeting_text = f"Привет, {message.from_user.full_name}!\n"
        greeting_text += "Я твой помощник для планирования постов в Telegram каналы и группы.\n"
        greeting_text += "Используй меню ниже для навигации или отправь /help для списка команд."

        # Отправка главного меню
        await message.answer(
            greeting_text,
            reply_markup=rk.get_main_menu_keyboard()
        )
        command_logger.debug(f"Sent start message and main menu to user {user_id}")

    except Exception as e:
        command_logger.error(f"Error handling /start for user {user_id}: {e}", exc_info=True)
        # No explicit rollback needed here because using async with session.begin() handles it.
        await message.answer("Произошла ошибка при подготовке к работе. Пожалуйста, попробуйте позже.")


@router.message(Command("help"))
async def handle_help_command(message: Message): # session не используется, убран из сигнатуры
    """Обработчик команды /help."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} sent /help")

    # Текст справки (согласно ТЗ разделы 5.1 и 7)
    help_text = """
    *Справка по боту PostPlanner:*

    Я могу помочь вам автоматизировать публикацию сообщений в ваших Telegram каналах и группах.

    *Основные функции:*
    - Создание постов с текстом и медиа (фото, видео, документы).
    - Планирование постов на определенную дату и время (разовые).
    - Настройка повторяющихся публикаций по расписанию (ежедневно, еженедельно, ежемесячно, ежегодно).
    - Возможность автоматического удаления постов через заданное время или по дате.
    - Управление списком каналов и групп для постинга.
    - Интеграция с RSS-лентами для автоматической публикации новостей.
    - Установка вашего часового пояса для удобства планирования.

    *Доступные команды:*
    /start - Начать взаимодействие с ботом и показать главное меню.
    /help - Показать эту справку.
    /newpost - Начать создание нового поста (запускает пошаговый диалог).
    /myposts - Показать список ваших запланированных, отправленных и черновиков постов.
    /editpost <ID> [раздел] - Редактировать существующий пост по ID. Разделы: `content`, `channels`, `schedule`, `delete`. Если раздел не указан, предложит выбор.
    /addchannel <username или id> - Добавить канал или группу для постинга. Если без аргумента, запросит username.
    /removechannel <username или id> - Удалить канал или группу из списка. Если без аргумента, предложит выбрать.
    /listchannels - Показать список всех добавленных вами каналов и групп.
    /settimezone <IANA Timezone> - Установить ваш часовой пояс (например, `Europe/Berlin`). Если без аргумента, запросит ввод.
    /addrss <URL> - Добавить RSS-ленту. Если без аргументов, запустит диалог.
    /removerss <ID или URL> - Удалить RSS-ленту. Если без аргумента, предложит выбрать.
    /listrss - Показать список ваших RSS-лент.
    /cancel - Отменить текущее действие (например, создание/редактирование поста).

    *Работа с меню:*
    Большинство действий доступны через кнопки главного меню, которые дублируют команды.

    *Часовой пояс:*
    Все время, которое вы вводите, будет интерпретироваться согласно вашему установленному часовому поясу. По умолчанию используется Europe/Berlin. Пожалуйста, установите свой часовой пояс с помощью /settimezone для корректной работы расписания.

    Для работы с ботом добавьте меня в ваш канал/группу как администратора с правами на публикацию сообщений и, если требуется автоудаление, на удаление сообщений.
    """
    await message.answer(help_text, parse_mode="MarkdownV2", reply_markup=rk.get_main_menu_keyboard()) # Можно использовать ту же клавиатуру
    command_logger.debug(f"Sent help message to user {user_id}")


# --- Обработчики команд, дублирующих кнопки меню ---
# Эти обработчики перенаправляют выполнение в соответствующие модули/FSM

@router.message(Command("newpost") | Text(rk.BTN_NEW_POST.text))
async def handle_newpost_command(message: Message, session: AsyncSession, state: FSMContext): # Add session for creating draft
    """Запуск FSM для создания нового поста."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} starting new post creation.")

    # Create a draft post immediately to get an ID for temporary file grouping
    # This is done here instead of in process_media_upload
    try:
        user_db = await db_service.get_or_create_user(session, user_id) # Ensure user exists

        # Create a minimal draft post entry just to get an ID for file grouping
        # Status 'draft' indicates it's not ready for scheduling yet.
        # Need dummy chat_ids and schedule_type to create the Post object minimally
        # Default parse_mode for new posts could be set here
        async with session.begin(): # Wrap creation in a transaction
             draft_post = await db_service.create_post(session, user_id=user_db.id, chat_ids=[], schedule_type='draft', status='draft', parse_mode='MarkdownV2') # Assuming MarkdownV2 as default

        if draft_post:
             await state.update_data(draft_post_id=draft_post.id)
             command_logger.debug(f"Created draft post {draft_post.id} for user {user_id} to start creation FSM.")
        else:
             command_logger.error(f"Failed to create initial draft post for user {user_id}.")
             await message.answer("Произошла ошибка при подготовке к созданию поста. Пожалуйста, попробуйте позже.")
             await state.clear() # Ensure no FSM state is set if draft creation fails
             return

    except Exception as e:
         command_logger.error(f"Error creating initial draft for user {user_id}: {e}", exc_info=True)
         await message.answer("Произошла ошибка при подготовке к созданию поста. Пожалуйста, попробуйте позже.")
         await state.clear()
         return


    # Переход в начальное состояние FSM post_creation
    await state.set_state(PostCreationStates.waiting_for_text)
    await message.answer(
        "Начнем создание нового поста. Отправьте текст поста.",
        reply_markup=rk.get_cancel_reply_keyboard() # Предлагаем отмену
    )
    command_logger.debug(f"User {user_id} transitioned to PostCreationStates.waiting_for_text")


# Добавлена аннотация типа для session
@router.message(Command("myposts") | Text(rk.BTN_MY_POSTS.text))
async def handle_myposts_command(message: Message, session: AsyncSession):
    """Запуск обработчика для отображения постов пользователя."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} requested my posts.")
    # Делегируем обработку соответствующему модулю
    from handlers import post_management # Импортируем здесь для избежания циклических зависимостей
    await post_management.handle_my_posts(message, session)


# Добавлены аннотации типов для session, state, command
@router.message(Command("addchannel") | Text(rk.BTN_ADD_CHANNEL.text))
async def handle_addchannel_command(message: Message, session: AsyncSession, state: FSMContext, command: CommandObject = None):
    """Запуск диалога добавления канала или обработка команды с аргументом."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} initiated add channel.")
    from handlers import channel_management # Импортируем здесь
    await channel_management.handle_add_channel(message, session, state, command=command)


# Добавлены аннотации типов для session, state, command
@router.message(Command("removechannel") | Text(rk.BTN_DELETE_CHANNEL.text))
async def handle_removechannel_command(message: Message, session: AsyncSession, state: FSMContext, command: CommandObject = None):
    """Запуск диалога удаления канала или обработка команды с аргументом."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} initiated remove channel.")
    from handlers import channel_management # Импортируем здесь
    await channel_management.handle_remove_channel(message, session, state, command=command)


# Добавлена аннотация типа для session
@router.message(Command("listchannels") | Text(rk.BTN_MY_CHANNELS.text))
async def handle_listchannels_command(message: Message, session: AsyncSession):
    """Запуск обработчика для отображения списка каналов."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} requested list channels.")
    from handlers import channel_management # Импортируем здесь
    await channel_management.handle_list_channels(message, session)


# Добавлены аннотации типов для session, state, command
@router.message(Command("settimezone") | Text(rk.BTN_SET_TIMEZONE.text))
async def handle_settimezone_command(message: Message, session: AsyncSession, state: FSMContext, command: CommandObject = None):
    """Запуск диалога установки часового пояса или обработка команды с аргументом."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} initiated set timezone.")
    from handlers import timezone_management # Импортируем здесь
    await timezone_management.handle_set_timezone(message, session, state, command=command)

# Добавлены аннотации типов для session, state, command
@router.message(Command("addrss") | Text(rk.BTN_ADD_RSS.text))
async def handle_addrss_command(message: Message, session: AsyncSession, state: FSMContext, command: CommandObject = None):
    """Запуск диалога добавления RSS-ленты или обработка команды с аргументами."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} initiated add RSS feed.")
    from handlers import rss_integration # Импортируем здесь
    await rss_integration.handle_add_rss_command(message, session, state, command=command)

# Добавлены аннотации типов для session, command
@router.message(Command("removerss"))
async def handle_removerss_command(message: Message, session: AsyncSession, command: CommandObject = None):
    """Обработка команды удаления RSS-ленты."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} initiated remove RSS feed.")
    from handlers import rss_integration # Импортируем здесь
    await rss_integration.handle_removerss_command(message, session, command=command)

# Добавлена аннотация типа для session
@router.message(Command("listrss"))
async def handle_listrss_command(message: Message, session: AsyncSession):
    """Обработка команды списка RSS-лент."""
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} requested list RSS feeds.")
    from handlers import rss_integration # Импортируем здесь
    await rss_integration.handle_list_rss_command(message, session)

# Added handler for /editpost command
@router.message(Command("editpost"))
async def handle_editpost_command(message: Message, session: AsyncSession, state: FSMContext, command: CommandObject):
     """Обработка команды /editpost <ID> [section]."""
     user_id = message.from_user.id
     command_logger.info(f"User {user_id} used /editpost command.")
     from handlers import post_management # Import here to avoid circular dependency
     await post_management.handle_editpost_command(message, session, state, command)


# Команда для отмены текущего FSM диалога (может быть переопределена внутри FSM handlers)
# This handler catches /cancel if it's not handled by a more specific FSM handler.
@router.message(Command("cancel") | Text(rk.BTN_CANCEL.text))
async def handle_cancel_command(message: Message, state: FSMContext):
    """Отмена текущего действия/FSM."""
    current_state = await state.get_state()
    user_id = message.from_user.id
    command_logger.info(f"User {user_id} sent /cancel. Current state: {current_state}")

    if current_state is None:
        await message.answer(
            "Сейчас нет активных действий для отмены.",
            reply_markup=rk.get_main_menu_keyboard()
        )
        return

    # If the FSM is one of the post creation/editing states, call the cleanup handler
    if current_state and current_state.split(':')[0] == 'PostCreationStates':
         command_logger.debug(f"Cancelling PostCreation FSM for user {user_id}.")
         from handlers.post_creation import handle_cancelpost_command_fsm # Local import
         await handle_cancelpost_command_fsm(message, state) # Delegate to post creation cancel handler
         return # Handler already answered and cleared state

    # If the FSM is one of the channel management states, call the cancel handler
    if current_state and current_state.split(':')[0] == 'ChannelManagementStates':
         command_logger.debug(f"Cancelling ChannelManagement FSM for user {user_id}.")
         from handlers.channel_management import handle_cancel_channel_management_fsm # Local import
         await handle_cancel_channel_management_fsm(message, state) # Delegate
         return # Handler already answered and cleared state

     # If the FSM is one of the timezone management states, call the cancel handler
    if current_state and current_state.split(':')[0] == 'TimezoneManagementStates':
         command_logger.debug(f"Cancelling TimezoneManagement FSM for user {user_id}.")
         from handlers.timezone_management import handle_cancel_timezone_management_fsm # Local import
         await handle_cancel_timezone_management_fsm(message, state) # Delegate
         return # Handler already answered and cleared state

     # If the FSM is one of the RSS integration states, call the cancel handler
    if current_state and current_state.split(':')[0] == 'RssIntegrationStates':
         command_logger.debug(f"Cancelling RssIntegration FSM for user {user_id}.")
         from handlers.rss_integration import handle_cancel_rss_integration_fsm # Local import
         await handle_cancel_rss_integration_fsm(message, state) # Delegate
         return # Handler already answered and cleared state


    # For any other FSM state not explicitly handled above, just clear state
    command_logger.warning(f"User {user_id} cancelled unknown FSM state: {current_state}. Clearing state.")
    await state.clear()
    await message.answer(
        "Действие отменено.",
        reply_markup=rk.get_main_menu_keyboard()
    )
"""

# Content for handlers/post_creation.py (from task yBWNP)
HANDLERS_POST_CREATION_CONTENT = """
import logging
from typing import List, Dict, Any, Optional, Union
from datetime import datetime, timedelta

from aiogram import Router, Bot, F # Добавлен F для фильтров
from aiogram.filters import Command, Text, StateFilter, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ContentType, InlineKeyboardMarkup, CallbackQuery
# Удален неиспользуемый импорт InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
import pytz # Для работы с таймзонами

# Импорт сервисов
from services import db_service
from services import scheduler_service
from services import content_manager_service
# Удален неиспользуемый импорт telegram_api_service # Не нужен напрямую здесь

# Импорт клавиатур
from keyboards import reply_keyboards as rk
from keyboards import inline_keyboards as ik
from keyboards.inline_keyboards import (
    ConfirmPostCreationCallback, EditDraftOptionsCallback, ScheduleTypeCallback,
    RecurringTypeCallback, SelectDayOfWeekCallback, DeleteOptionsCallback,
    SelectChannelCallback, ChannelSelectionControlCallback
)

# Импорт утилит
from utils.logger import logger
from utils import validators # Импортируем весь модуль для доступа к валидаторам и константам
from utils.helpers import format_datetime_for_user # get_user_timezone не определен в helpers, используется db_service


router = Router()
post_creation_logger = logging.getLogger(__name__)

# --- FSM States ---
class PostCreationStates(StatesGroup):
    """Состояния для процесса создания/редактирования поста."""
    waiting_for_text = State()
    waiting_for_media = State()
    waiting_for_channels = State()
    waiting_for_schedule_type = State()
    waiting_for_onetime_datetime = State()
    waiting_for_recurring_type = State()
    waiting_for_recurring_daily_time = State()
    waiting_for_recurring_weekly_days = State()
    waiting_for_recurring_weekly_time = State()
    waiting_for_recurring_monthly_day = State()
    waiting_for_recurring_monthly_time = State()
    waiting_for_recurring_yearly_date = State()
    waiting_for_recurring_yearly_time = State()
    waiting_for_delete_option = State()
    waiting_for_delete_hours = State()
    waiting_for_delete_days = State()
    waiting_for_delete_datetime = State()
    confirm_post = State()
    # Состояния для редактирования (можно использовать те же, но могут быть нюансы)
    # editing_content = State()
    # editing_channels = State()
    # editing_schedule = State()
    # editing_delete_options = State()


# --- Helper functions for FSM ---

async def cleanup_post_creation_draft(user_id: int, draft_id: int):
    """Очищает временные файлы для черновика поста."""
    post_creation_logger.debug(f"Cleaning up draft {draft_id} temporary media for user {user_id}")
    content_manager_service.cleanup_temporary_media_for_draft
"""

# Map file paths to their content
file_contents = {
    "requirements.txt": REQUIREMENTS_CONTENT,
    ".env.example": DOTENV_EXAMPLE_CONTENT,
    "Procfile": PROCFILE_CONTENT,
    "README.md": README_CONTENT,
    "bot.py": BOT_PY_CONTENT,
    "models/base.py": MODELS_BASE_CONTENT,
    "models/user.py": MODELS_USER_CONTENT,
    "models/user_channel.py": MODELS_USER_CHANNEL_CONTENT,
    "models/post.py": MODELS_POST_CONTENT,
    "models/rss_feed.py": MODELS_RSS_FEED_CONTENT,
    "models/rss_item.py": MODELS_RSS_ITEM_CONTENT,
    "utils/logger.py": UTILS_LOGGER_CONTENT,
    "utils/validators.py": UTILS_VALIDATORS_CONTENT,
    "utils/helpers.py": UTILS_HELPERS_CONTENT,
    "keyboards/reply_keyboards.py": KEYBOARDS_REPLY_CONTENT,
    "keyboards/inline_keyboards.py": KEYBOARDS_INLINE_CONTENT,
    "services/db_service.py": SERVICES_DB_CONTENT,
    "services/scheduler_service.py": SERVICES_SCHEDULER_CONTENT,
    "services/telegram_api_service.py": SERVICES_TELEGRAM_API_CONTENT,
    "services/content_manager_service.py": SERVICES_CONTENT_MANAGER_CONTENT,
    "services/rss_service.py": SERVICES_RSS_CONTENT,
    "handlers/commands.py": HANDLERS_COMMANDS_CONTENT,
    "handlers/post_creation.py": HANDLERS_POST_CREATION_CONTENT,
    # Placeholders for other handlers - content not provided in prompt
    "handlers/post_management.py": "# Content for post_management.py (not provided in reference)\n",
    "handlers/channel_management.py": "# Content for channel_management.py (not provided in reference)\n",
    "handlers/timezone_management.py": "# Content for timezone_management.py (not provided in reference)\n",
    "handlers/rss_integration.py": "# Content for rss_integration.py (not provided in reference)\n",
}

# Content for project_generator.py itself
GENERATOR_SCRIPT_CONTENT = f"""
import os
from pathlib import Path

# Define the content of each file as a multi-line string

REQUIREMENTS_CONTENT = \"\"\"
{REQUIREMENTS_CONTENT.strip()}
\"\"\"

DOTENV_EXAMPLE_CONTENT = \"\"\"
{DOTENV_EXAMPLE_CONTENT.strip()}
\"\"\"

PROCFILE_CONTENT = \"\"\"
{PROCFILE_CONTENT.strip()}
\"\"\"

README_CONTENT = \"\"\"
{README_CONTENT.strip()}
\"\"\"

BOT_PY_CONTENT = \"\"\"
{BOT_PY_CONTENT.strip()}
\"\"\"

MODELS_BASE_CONTENT = \"\"\"
{MODELS_BASE_CONTENT.strip()}
\"\"\"

MODELS_USER_CONTENT = \"\"\"
{MODELS_USER_CONTENT.strip()}
\"\"\"

MODELS_USER_CHANNEL_CONTENT = \"\"\"
{MODELS_USER_CHANNEL_CONTENT.strip()}
\"\"\"

MODELS_POST_CONTENT = \"\"\"
{MODELS_POST_CONTENT.strip()}
\"\"\"

MODELS_RSS_FEED_CONTENT = \"\"\"
{MODELS_RSS_FEED_CONTENT.strip()}
\"\"\"

MODELS_RSS_ITEM_CONTENT = \"\"\"
{MODELS_RSS_ITEM_CONTENT.strip()}
\"\"\"

UTILS_LOGGER_CONTENT = \"\"\"
{UTILS_LOGGER_CONTENT.strip()}
\"\"\"

UTILS_VALIDATORS_CONTENT = \"\"\"
{UTILS_VALIDATORS_CONTENT.strip()}
\"\"\"

UTILS_HELPERS_CONTENT = \"\"\"
{UTILS_HELPERS_CONTENT.strip()}
\"\"\"

KEYBOARDS_REPLY_CONTENT = \"\"\"
{KEYBOARDS_REPLY_CONTENT.strip()}
\"\"\"

KEYBOARDS_INLINE_CONTENT = \"\"\"
{KEYBOARDS_INLINE_CONTENT.strip()}
\"\"\"

SERVICES_DB_CONTENT = \"\"\"
{SERVICES_DB_CONTENT.strip()}
\"\"\"

SERVICES_SCHEDULER_CONTENT = \"\"\"
{SERVICES_SCHEDULER_CONTENT.strip()}
\"\"\"

SERVICES_TELEGRAM_API_CONTENT = \"\"\"
{SERVICES_TELEGRAM_API_CONTENT.strip()}
\"\"\"

SERVICES_CONTENT_MANAGER_CONTENT = \"\"\"
{SERVICES_CONTENT_MANAGER_CONTENT.strip()}
\"\"\"

SERVICES_RSS_CONTENT = \"\"\"
{SERVICES_RSS_CONTENT.strip()}
\"\"\"

# Add content for handlers that were not fully provided in the reference
# Provide minimal content to avoid syntax errors
HANDLERS_POST_MANAGEMENT_CONTENT = \"\"\"
import logging
from aiogram import Router
# Minimal content for handlers/post_management.py
router = Router()
post_management_logger = logging.getLogger(__name__)

async def handle_my_posts(message, session):
    post_management_logger.warning("handle_my_posts not fully implemented based on provided reference.")
    await message.answer("Список постов (не реализовано в демо)")

async def handle_editpost_command(message, session, state, command):
    post_management_logger.warning("handle_editpost_command not fully implemented based on provided reference.")
    await message.answer("Редактирование поста (не реализовано в демо)")
\"\"\"

HANDLERS_CHANNEL_MANAGEMENT_CONTENT = \"\"\"
import logging
from aiogram import Router
# Minimal content for handlers/channel_management.py
router = Router()
channel_management_logger = logging.getLogger(__name__)

async def handle_add_channel(message, session, state, command):
    channel_management_logger.warning("handle_add_channel not fully implemented based on provided reference.")
    await message.answer("Добавление канала (не реализовано в демо)")

async def handle_remove_channel(message, session, state, command):
     channel_management_logger.warning("handle_remove_channel not fully implemented based on provided reference.")
     await message.answer("Удаление канала (не реализовано в демо)")

async def handle_list_channels(message, session):
     channel_management_logger.warning("handle_list_channels not fully implemented based on provided reference.")
     await message.answer("Список каналов (не реализовано в демо)")

async def handle_cancel_channel_management_fsm(message, state):
     await state.clear()
     await message.answer("Действие отменено.", reply_markup=None) # Assuming reply markup is handled elsewhere
\"\"\"

HANDLERS_TIMEZONE_MANAGEMENT_CONTENT = \"\"\"
import logging
from aiogram import Router
# Minimal content for handlers/timezone_management.py
router = Router()
timezone_management_logger = logging.getLogger(__name__)

async def handle_set_timezone(message, session, state, command):
    timezone_management_logger.warning("handle_set_timezone not fully implemented based on provided reference.")
    await message.answer("Установка таймзоны (не реализовано в демо)")

async def handle_cancel_timezone_management_fsm(message, state):
     await state.clear()
     await message.answer("Действие отменено.", reply_markup=None) # Assuming reply markup is handled elsewhere
\"\"\"

HANDLERS_RSS_INTEGRATION_CONTENT = \"\"\"
import logging
from aiogram import Router
# Minimal content for handlers/rss_integration.py
router = Router()
rss_integration_logger = logging.getLogger(__name__)

async def handle_add_rss_command(message, session, state, command):
     rss_integration_logger.warning("handle_add_rss_command not fully implemented based on provided reference.")
     await message.answer("Добавление RSS (не реализовано в демо)")

async def handle_removerss_command(message, session, command):
     rss_integration_logger.warning("handle_removerss_command not fully implemented based on provided reference.")
     await message.answer("Удаление RSS (не реализовано в демо)")

async def handle_list_rss_command(message, session):
     rss_integration_logger.warning("handle_list_rss_command not fully implemented based on provided reference.")
     await message.answer("Список RSS (не реализовано в демо)")

async def handle_cancel_rss_integration_fsm(message, state):
     await state.clear()
     await message.answer("Действие отменено.", reply_markup=None) # Assuming reply markup is handled elsewhere
\"\"\"

# Map file paths to their content
file_contents = {
    "requirements.txt": REQUIREMENTS_CONTENT,
    ".env.example": DOTENV_EXAMPLE_CONTENT,
    "Procfile": PROCFILE_CONTENT,
    "README.md": README_CONTENT,
    "bot.py": BOT_PY_CONTENT,
    "models/base.py": MODELS_BASE_CONTENT,
    "models/user.py": MODELS_USER_CONTENT,
    "models/user_channel.py": MODELS_USER_CHANNEL_CONTENT,
    "models/post.py": MODELS_POST_CONTENT,
    "models/rss_feed.py": MODELS_RSS_FEED_CONTENT,
    "models/rss_item.py": MODELS_RSS_ITEM_CONTENT,
    "utils/logger.py": UTILS_LOGGER_CONTENT,
    "utils/validators.py": UTILS_VALIDATORS_CONTENT,
    "utils/helpers.py": UTILS_HELPERS_CONTENT,
    "keyboards/reply_keyboards.py": KEYBOARDS_REPLY_CONTENT,
    "keyboards/inline_keyboards.py": KEYBOARDS_INLINE_CONTENT,
    "services/db_service.py": SERVICES_DB_CONTENT,
    "services/scheduler_service.py": SERVICES_SCHEDULER_CONTENT,
    "services/telegram_api_service.py": SERVICES_TELEGRAM_API_CONTENT,
    "services/content_manager_service.py": SERVICES_CONTENT_MANAGER_CONTENT,
    "services/rss_service.py": SERVICES_RSS_CONTENT,
    "handlers/commands.py": HANDLERS_COMMANDS_CONTENT,
    "handlers/post_creation.py": HANDLERS_POST_CREATION_CONTENT,
    # Add the generated minimal content for other handlers
    "handlers/post_management.py": HANDLERS_POST_MANAGEMENT_CONTENT,
    "handlers/channel_management.py": HANDLERS_CHANNEL_MANAGEMENT_CONTENT,
    "handlers/timezone_management.py": HANDLERS_TIMEZONE_MANAGEMENT_CONTENT,
    "handlers/rss_integration.py": HANDLERS_RSS_INTEGRATION_CONTENT,
}

def create_project_structure(base_path="."):
    """
    Creates the project directory structure and files.

    Args:
        base_path: The base directory to create the project in.
    """
    base_dir = Path(base_path)
    print(f"Creating project structure in {base_dir.resolve()}")

    # Create directories
    dirs_to_create = [
        "models",
        "utils",
        "services",
        "handlers",
        "keyboards",
        "media_temp" # Directory for temporary media files
    ]

    for dirname in dirs_to_create:
        path = base_dir / dirname
        path.mkdir(parents=True, exist_ok=True)
        # Create __init__.py in packages
        if dirname in ["models", "utils", "services", "handlers", "keyboards"]:
             (path / "__init__.py").touch(exist_ok=True)
             print(f"Created directory {path} and {path / '__init__.py'}")
        else:
            print(f"Created directory {path}")


    # Create files with content
    for filepath, content in file_contents.items():
        path = base_dir / filepath
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Created file: {path}")
        except Exception as e:
            print(f"Error creating file {path}: {e}")


if __name__ == "__main__":
    create_project_structure()
    print("\nProject structure and files created.")
    print("Please refer to README.md for further instructions on setup and running the bot.")
"""

print(GENERATOR_SCRIPT_CONTENT)
