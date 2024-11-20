import asyncio
import json
import socket
from datetime import datetime
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


async def read_msgs(host: str, port: int, queues: Dict[str, asyncio.Queue]) -> None:
    history_queue = asyncio.Queue()
    status_updates_queue = queues["status_updates_queue"]
    watchdog_queue = queues["watchdog_queue"]
    messages_queue = queues["messages_queue"]


    while True:
        try:
            reader, _ = await asyncio.open_connection(host, port)
            try:
                while True:
                    await ping_server(reader, gui.ReadConnectionStateChanged, status_updates_queue)

                    received_message = await reader.readuntil()
                    status_updates_queue.put_nowait(
                        gui.ReadConnectionStateChanged.ESTABLISHED
                    )
                    await watch_for_connection(
                        watchdog_queue,
                        ConnectionStatus.ALIVE,
                        ConnectionSource.NEW_MESSAGE,
                    )

                    now = datetime.now()
                    message = f'[{now.strftime("%d.%m.%Y %H:%M")}] {received_message.decode()}'
                    messages_queue.put_nowait(message)

                    await save_message(history_queue, message)
            except asyncio.TimeoutError:
                await watch_for_connection(
                    watchdog_queue, ConnectionStatus.ALIVE, ConnectionSource.TIMEOUT
                )
                status_updates_queue.put_nowait(gui.ReadConnectionStateChanged.CLOSED)
        except socket.gaierror:
            status_updates_queue.put_nowait(gui.ReadConnectionStateChanged.INITIATED)


async def send_msgs(
    host: str, port: int, queues: Dict[str, asyncio.Queue], token: str
) -> None:
    is_auth = False
    status_updates_queue = queues["status_updates_queue"]
    watchdog_queue = queues["watchdog_queue"]
    sending_queue = queues["sending_queue"]

    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            try:
                while True:
                    if not is_auth:
                        await watch_for_connection(
                            watchdog_queue,
                            ConnectionStatus.ALIVE,
                            ConnectionSource.BEFORE_AUTH,
                        )
                        nickname = await authorize(reader, writer, token)
                        await ping_server(reader, gui.SendingConnectionStateChanged, status_updates_queue)
                        await watch_for_connection(
                            watchdog_queue,
                            ConnectionStatus.ALIVE,
                            ConnectionSource.AUTH,
                        )
                        nickname_received = gui.NicknameReceived(nickname)
                        status_updates_queue.put_nowait(nickname_received)
                        is_auth = True

                    status_updates_queue.put_nowait(
                        gui.SendingConnectionStateChanged.ESTABLISHED
                    )

                    msg = await sending_queue.get()
                    if msg:
                        await send_message(writer, f"{msg}\n\n")
                        await watch_for_connection(
                            watchdog_queue,
                            ConnectionStatus.ALIVE,
                            ConnectionSource.MESSAGE_SENT,
                        )
            except asyncio.TimeoutError:
                await watch_for_connection(
                    watchdog_queue, ConnectionStatus.ALIVE, ConnectionSource.TIMEOUT
                )
                status_updates_queue.put_nowait(
                    gui.SendingConnectionStateChanged.CLOSED
                )
                is_auth = False
            except InvalidToken:
                is_auth = False
                break
        except socket.gaierror:
            is_auth = False
            status_updates_queue.put_nowait(gui.SendingConnectionStateChanged.INITIATED)


async def ping_server(
    reader: asyncio.StreamReader, gui_class: Any, status_updates_queue: asyncio.Queue
) -> bool:
    start_ping_time = 0

    while start_ping_time < 1800:
        try:
            async with timeout(15) as cm:
                received_message = await reader.readline()
                if received_message:
                    return True
                cm.expired()
        except asyncio.TimeoutError:
            start_ping_time += 15
            status_updates_queue.put_nowait(gui_class.CLOSED)

    raise socket.gaierror


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
