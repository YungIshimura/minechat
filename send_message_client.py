import asyncio
import configargparse
from environs import Env
from utils import get_logger
import json


async def send_message_chat_client(host, port, token):
    # Открыли подключение
    reader, writer = await asyncio.open_connection(host, port)
    logger = await get_logger('sender')

    # Вывели стартовое сообщение
    start_message = await reader.readline()
    print(start_message.decode().strip())

    # Отправили ключ
    writer.write(f'{token}\n'.encode())
    await writer.drain()
  
    # Обработали кривой ключ
    received_message = await reader.readline()
    message = received_message.decode().strip()
    if json.loads(message) is None:
        message = 'Неизвестный токен. Проверьте его или зарегистрируйте заново.'
        print(message)
        logger.error(message)
        return

    received_message = await reader.readline()
    message = received_message.decode().strip()
    print(message)

    # Ожидание сообщений
    try:
        while True:
            message = input('Введите сообщение: ') + '\n\n'
            writer.write(message.encode())
            await writer.drain()
    except KeyboardInterrupt:
        logger.debug("\nОтключение от сервера.")
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