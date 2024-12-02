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
from consts import INITIATED_TIME
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
async def connection_manager(host: str, port: int, queues: Dict[str, asyncio.Queue], source: ConnectionSource):
    watchdog_queue = queues["watchdog_queue"]
    
    try:
        reader, writer = await asyncio.open_connection(host, port)
        await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, source)
        yield reader, writer
    except asyncio.TimeoutError:
        await watch_for_connection(watchdog_queue, ConnectionStatus.DEAD, source)
        raise ConnectionError
    except socket.gaierror:
        status_updates_queue = queues["status_updates_queue"]
        status_updates_queue.put_nowait(gui.ReadConnectionStateChanged.INITIATED)
        status_updates_queue.put_nowait(gui.SendingConnectionStateChanged.INITIATED)


async def monitor_connection(
    host: str,
    port: int,
    gui_class: Any,
    queues: Dict[str, asyncio.Queue],
    source: ConnectionSource
) -> None:
    status_updates_queue = queues["status_updates_queue"]
    watchdog_queue = queues["watchdog_queue"]
    start_ping_time = 0

    while True:
        try:
            async with connection_manager(host, port, queues, source) as (reader, _):
                status_updates_queue.put_nowait(gui_class.ESTABLISHED)
                while True:
                    response = await ping_server(reader)
                    if response:
                        await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, source)
                    else:
                        status_updates_queue.put_nowait(gui_class.CLOSED)
                        await watch_for_connection(watchdog_queue, ConnectionStatus.DEAD, source)
                        break
        except ConnectionError:
            status_updates_queue.put_nowait(gui_class.CLOSED)
        except socket.gaierror:
            response = await ping_server(reader)
            start_ping_time = start_ping_time + 5 if not response else 0
            
            if start_ping_time >= INITIATED_TIME:
                status_updates_queue.put_nowait(gui_class.INITIATED)
        except RuntimeError:
            pass


async def ping_server(reader):
    try:
        async with timeout(15):
            response = await reader.readline()
            return response
    except asyncio.TimeoutError:
        return


async def read_msgs(host: str, port: int, queues: Dict[str, asyncio.Queue]) -> None:
    status_updates_queue = queues["status_updates_queue"]
    messages_queue = queues["messages_queue"]
    watchdog_queue = queues["watchdog_queue"]
    history_queue = asyncio.Queue()

    while True:
        try:
            async with connection_manager(host, port, queues, ConnectionSource.NEW_MESSAGE) as (reader, _):
                status_updates_queue.put_nowait(gui.ReadConnectionStateChanged.ESTABLISHED)
                while True:
                    received_message = await reader.readuntil()
                    now = datetime.now()
                    formatted_message = f'[{now.strftime("%d.%m.%Y %H:%M")}] {received_message.decode()}'
                    messages_queue.put_nowait(formatted_message)
                    await save_message(history_queue, formatted_message)
                    await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, ConnectionSource.NEW_MESSAGE)
        except RuntimeError:
            pass


async def send_msgs(host: str, port: int, queues: Dict[str, asyncio.Queue], token: str) -> None:
    status_updates_queue = queues["status_updates_queue"]
    sending_queue = queues["sending_queue"]
    watchdog_queue = queues["watchdog_queue"]

    while True:
        try:
            async with connection_manager(host, port, queues, ConnectionSource.BEFORE_AUTH) as (reader, writer):
                nickname = await authorize(reader, writer, token)
                status_updates_queue.put_nowait(gui.NicknameReceived(nickname))
                await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, ConnectionSource.AUTH)
                while True:
                    msg = await sending_queue.get()
                    if msg:
                        await send_message(writer, f"{msg}\n\n")
                        await watch_for_connection(watchdog_queue, ConnectionStatus.ALIVE, ConnectionSource.MESSAGE_SENT)
                        status_updates_queue.put_nowait(gui.SendingConnectionStateChanged.ESTABLISHED)
        except InvalidToken:
            status_updates_queue.put_nowait(gui.SendingConnectionStateChanged.CLOSED)
        except RuntimeError:
            pass


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
        tg.start_soon(
            monitor_connection,
            host,
            read_port,
            gui.ReadConnectionStateChanged,
            queues,
            ConnectionSource.NEW_MESSAGE,
        )
        tg.start_soon(
            monitor_connection,
            host,
            send_port,
            gui.SendingConnectionStateChanged,
            queues,
            ConnectionSource.MESSAGE_SENT,
        )
        tg.start_soon(read_msgs, host, read_port, queues)
        tg.start_soon(send_msgs, host, send_port, queues, token)
        tg.start_soon(gui.draw, queues)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (TclError, KeyboardInterrupt):
        pass
