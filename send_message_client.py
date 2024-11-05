import asyncio

import configargparse
from environs import Env


async def send_message_chat_client(host, port, token):
    reader, writer = await asyncio.open_connection(host, port)

    writer.write(f'{token}\n'.encode())
    await writer.drain()

    try:
        for _ in range(3):
            received_message = await reader.readline()
            print(received_message.decode().strip())

        while True:
            message = input('Введите сообщение: ') + '\n\n'
            writer.write(message.encode())
            await writer.drain()
    except KeyboardInterrupt:
        print("\nОтключение от сервера.")
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    env = Env()
    env.read_env()
    host = env.str("HOST")
    port = env.int("SEND_PORT")
    token = env.str("TOKEN")

    p = configargparse.ArgParser()
    p.add("-H", "--host", help="chat host", default=host, required=False)
    p.add("-P", "--port", help="chat port", default=port, required=False)

    options = p.parse_args()

    asyncio.run(send_message_chat_client(options.host, options.port, token))


if __name__ == '__main__':
    main()