import asyncio
import sys
from datetime import datetime

import aiofiles
import configargparse
from aiofiles.os import wrap
from environs import Env
from utils import get_logger


async def receive_message_chat_client(host, port, history_filepath):
    reader, writer = await asyncio.open_connection(host, port)
    write_stdout = wrap(sys.stdout.write)
    logger = await get_logger('receiver')
    try:
        while True:
            received_message = await reader.readuntil()
            now = datetime.now()

            async with aiofiles.open(history_filepath, mode="a") as handle:
                message = f'[{now.strftime("%d.%m.%Y %H:%M")}] {received_message.decode()}'

                await write_stdout(message)
                await handle.write(message)
    except KeyboardInterrupt:
        logger.debug("\nОтключение от сервера.")
    finally:
        writer.close()
        await writer.wait_closed()

def main():
    env = Env()
    env.read_env()
    host = env.str("HOST")
    port = env.int("READ_PORT")

    history_filepath = "minechat_history.txt"

    p = configargparse.ArgParser()
    p.add("-H", "--host", help="chat host", default=host, required=False)
    p.add("-P", "--port", help="chat port", default=port, required=False)
    p.add(
        "-HF",
        "--history",
        help="chat history filepath",
        default=history_filepath,
        required=False,
    )

    options = p.parse_args()

    asyncio.run(receive_message_chat_client(options.host, options.port, options.history))


if __name__ == "__main__":
    main()
