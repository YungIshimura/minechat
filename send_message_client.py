import asyncio
import json
import os

import configargparse
from environs import Env

from utils import get_logger, update_env_file


async def send_message_chat_client(host, port, token, message):
    reader, writer = await asyncio.open_connection(host, port)

    try:
        logger = await get_logger("sender")
        start_message = await reader.readline()
        print(start_message.decode().strip())

        if token:
            await authorize(writer, reader, token, logger)

        else:
            token = await register(writer, reader, token, logger)
            await update_env_file("TOKEN", token)
            os.system("clear")
            await send_message_chat_client(host, port, token)

        received_message = await reader.readline()
        print(received_message.decode().strip())

        while True:
            if message:
                await send_message(writer, message)
            message = input("Введите сообщение: ") + "\n\n"
    except KeyboardInterrupt:
        logger.debug("\nОтключение от сервера.")
    finally:
        writer.close()
        await writer.wait_closed()


async def send_message(writer, message):
    writer.write(message.encode())
    await writer.drain()


async def authorize(writer, reader, token, logger):
    writer.write(f"{token}\n".encode())
    await writer.drain()

    received_message = await reader.readline()
    message = received_message.decode().strip()

    if json.loads(message) is None:
        message = "Неизвестный токен. Проверьте его или зарегистрируйте заново."
        print(message)
        logger.error(message)

        raise KeyboardInterrupt


async def register(writer, reader, token, logger):
    writer.write(f"{token}\n".encode())
    await writer.drain()

    received_message = await reader.readline()
    message = received_message.decode().strip()
    print(message)

    username = input(
        "Для регистрации введите имя пользователя или нажмите Enter для автоматической генерации: "
    )
    writer.write(f"{username}\n".encode())
    await writer.drain()

    received_message = await reader.readline()
    message = json.loads(received_message.decode().strip())
    print(message)
    token = message["account_hash"]
    print(f"Регистрация прошла успешно. Через 5 секунд консоль будет обновлена.")

    await asyncio.sleep(5)

    return token


def main():
    env = Env()
    env.read_env()
    host = env.str("HOST")
    port = env.int("SEND_PORT")
    token = env.str("TOKEN", "")

    p = configargparse.ArgParser()
    p.add("-H", "--host", help="chat host", default=host, required=False)
    p.add("-P", "--port", help="chat port", default=port, required=False)
    p.add("-T", "--token", help="chat token", default=token, required=False)
    p.add("-M", "--message", help="chat message", required=True)
    options = p.parse_args()

    asyncio.run(
        send_message_chat_client(
            options.host, options.port, token, f"{options.message}\n\n"
        )
    )


if __name__ == "__main__":
    main()
