import asyncio
import aiofiles
from datetime import datetime
from aiofiles.os import wrap
import sys
from environs import Env


async def chat_client(host, port):
    reader, _ = await asyncio.open_connection(
        host, port
    )
    write_stdout = wrap(sys.stdout.write)

    while True:
        received_message = await reader.readuntil()
        now = datetime.now()

        async with aiofiles.open('minechat_history.txt', mode='a',) as handle:
            message = f'[{now.strftime("%d.%m.%Y %H:%M")}] {received_message.decode()}'

            await write_stdout(message)
            await handle.write(message)

        
def main():
    env = Env()
    env.read_env()
    host = env.str('HOST')
    port = env.int('PORT')

    asyncio.run(chat_client(host, port))


if __name__ == "__main__":
    main()