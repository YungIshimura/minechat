import asyncio
import enum
import logging
import time
from typing import Dict

import aiofiles
from async_timeout import timeout


class ConnectionStatus(enum.Enum):
    ALIVE = "Connection is alive"
    DEAD = "Connection is dead"


class ConnectionSource(enum.Enum):
    NEW_MESSAGE = "Source: New message in chat"
    MESSAGE_SENT = "Source: Message sent"
    TIMEOUT = "Source: 15s timeout is elapsed"
    BEFORE_AUTH = "Source: Prompt before auth"
    AUTH = "Source: Authorization done"


async def get_watchdog_logger() -> logging.Logger:
    logging.basicConfig(
        filename="watchdog.log",
        level=logging.DEBUG,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    logger = logging.getLogger("watchdog_logger")

    return logger


async def update_env_file(key: str, value: str) -> None:
    lines = []

    async with aiofiles.open(".env", mode="r") as file:
        async for line in file:
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}\n")
            else:
                lines.append(line)

    async with aiofiles.open(".env", mode="w") as file:
        await file.writelines(lines)


async def send_message(writer: asyncio.StreamWriter, message: str) -> None:
    writer.write(message.encode())
    await writer.drain()


async def update_messages(
    queues: Dict[str, asyncio.Queue], filepath: str = "minechat_history.txt"
) -> None:
    async with aiofiles.open(filepath, mode="r") as handle:
        queues["messages_queue"].put_nowait(await handle.read())


async def save_message(
    history_queue: asyncio.Queue, message: str, filepath: str = "minechat_history.txt"
) -> None:
    async with aiofiles.open(filepath, mode="a") as handle:
        history_queue.put_nowait(await handle.write(message))


async def watch_for_connection(
    watchdog_queue: asyncio.Queue, status: ConnectionStatus, message: str = None
) -> None:
    logger = await get_watchdog_logger()
    watchdog_queue.put_nowait(await write_log(status, message, logger))


async def write_log(
    connection_status: ConnectionStatus, message: str, logger: logging.Logger
) -> None:
    logger.info(f"{time.time()} {connection_status.value} {message}")


async def get_queues() -> Dict[str, asyncio.Queue]:
    queues = {
        "messages_queue": asyncio.Queue(),
        "sending_queue": asyncio.Queue(),
        "status_updates_queue": asyncio.Queue(),
        "watchdog_queue": asyncio.Queue(),
    }

    return queues


async def ping_server(reader):
    try:
        async with timeout(15):
            response = await reader.readline()
            return response
    except asyncio.TimeoutError:
        return