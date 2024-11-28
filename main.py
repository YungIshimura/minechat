import asyncio
import json
import socket
from datetime import datetime
from contextlib import asynccontextmanager
from tkinter import TclError, messagebox
from typing import Any, Dict

import anyio
from async_timeout import timeout
from environs import Env

import gui
from exceptions import InvalidToken
from utils import (
    ConnectionSource,
    ConnectionStatus,
    get_queues,
    save_message,
    send_message,
    update_env_file,
    update_messages,
    watch_for_connection,
)


@asynccontextmanager
async def connection_manager(host: str, port: int, watchdog_queue: asyncio.Queue, source: ConnectionSource):
    try:
        reader, writer = await asyncio.open_connection(host, port)
        await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, source)
        yield reader, writer
    except (socket.gaierror, asyncio.TimeoutError):
        await watch_for_connection(watchdog_queue, ConnectionStatus.DEAD, source)
        raise ConnectionError
    finally:
        writer.close()
        await writer.wait_closed()


async def monitor_connection(
    reader: asyncio.StreamReader, queue: asyncio.Queue, gui_class: Any, watchdog_queue: asyncio.Queue, source: ConnectionSource
) -> None:
    
    try:
        while True:
            async with timeout(15):
                _ = await reader.readline()
                queue.put_nowait(ConnectionStatus.ALIVE)
                await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, source)
    except asyncio.TimeoutError:
        queue.put_nowait(gui_class.CLOSED)
        await watch_for_connection(watchdog_queue, ConnectionStatus.DEAD, source)


async def read_msgs(host: str, port: int, queues: Dict[str, asyncio.Queue]) -> None:
    status_updates_queue = queues["status_updates_queue"]
    messages_queue = queues["messages_queue"]
    watchdog_queue = queues["watchdog_queue"]
    history_queue = asyncio.Queue()

    while True:
        try:
            async with connection_manager(host, port, watchdog_queue, ConnectionSource.NEW_MESSAGE) as (reader, _):
                status_updates_queue.put_nowait(gui.ReadConnectionStateChanged.ESTABLISHED)
                # Так работает
                # asyncio.create_task(
                #     monitor_connection(reader, status_updates_queue, gui.ReadConnectionStateChanged, watchdog_queue, ConnectionSource.NEW_MESSAGE)
                # )
                async with anyio.create_task_group() as tg:
                    tg.start_soon(
                        monitor_connection, reader, status_updates_queue, gui.ReadConnectionStateChanged, watchdog_queue, ConnectionSource.NEW_MESSAGE
                    )
                try:
                    while True:
                        received_message = await reader.readuntil()
                        now = datetime.now()
                        formatted_message = f'[{now.strftime("%d.%m.%Y %H:%M")}] {received_message.decode()}'
                        messages_queue.put_nowait(formatted_message)
                        await save_message(history_queue, formatted_message)
                        await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, ConnectionSource.NEW_MESSAGE)
                except asyncio.TimeoutError:
                    pass
        except ConnectionError:
            status_updates_queue.put_nowait(gui.ReadConnectionStateChanged.CLOSED)


async def send_msgs(host: str, port: int, queues: Dict[str, asyncio.Queue], token: str) -> None:
    status_updates_queue = queues["status_updates_queue"]
    sending_queue = queues["sending_queue"]
    watchdog_queue = queues["watchdog_queue"]

    while True:
        try:
            async with connection_manager(host, port, watchdog_queue, ConnectionSource.BEFORE_AUTH) as (reader, writer):
                nickname = await authorize(reader, writer, token)
                status_updates_queue.put_nowait(gui.NicknameReceived(nickname))
                await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, ConnectionSource.AUTH)
                monitor_task = asyncio.create_task(
                    monitor_connection(reader, status_updates_queue, gui.SendingConnectionStateChanged, watchdog_queue, ConnectionSource.MESSAGE_SENT)
                )
                try:
                    while True:
                        msg = await sending_queue.get()
                        if msg:
                            await send_message(writer, f"{msg}\n\n")
                            await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, ConnectionSource.MESSAGE_SENT)
                            status_updates_queue.put_nowait(gui.SendingConnectionStateChanged.ESTABLISHED)
                finally:
                    monitor_task.cancel()
        except (ConnectionError, InvalidToken):
            status_updates_queue.put_nowait(gui.SendingConnectionStateChanged.CLOSED)


async def authorize(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, token: str
) -> str:
    try:
        if token:
            writer.write(f"{token}\n".encode())
            await writer.drain()

            for _ in range(2):
                received_message = await reader.readline()
                message = received_message.decode().strip()
        else:
            message = await register(reader, writer)

        message_json = json.loads(message)

        if message_json is None:
            raise InvalidToken

        await update_env_file("TOKEN", message_json["account_hash"])
        return message_json["nickname"]

    except InvalidToken:
        messagebox.showinfo("Неверный токен", "Проверьте токен, сервер его не узнал")


async def register(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    nickname = gui.register_nickname()
    writer.write(f"\n".encode())
    await writer.drain()
    for _ in range(2):
        received_message = await reader.readline()
        message = received_message.decode().strip()

    writer.write(f"{nickname}\n".encode())
    await writer.drain()

    received_message = await reader.readline()
    message = received_message.decode().strip()

    return message


async def main() -> None:
    queues = await get_queues()

    env = Env()
    env.read_env()
    host = env.str("HOST")
    read_port = env.int("READ_PORT")
    send_port = env.int("SEND_PORT")
    token = env.str("TOKEN", "")

    async with anyio.create_task_group() as tg:
        tg.start_soon(update_messages, queues)
        tg.start_soon(read_msgs, host, read_port, queues)
        tg.start_soon(send_msgs, host, send_port, queues, token)
        tg.start_soon(gui.draw, queues)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except* (TclError, KeyboardInterrupt):
        pass
