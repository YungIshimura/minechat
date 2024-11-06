import logging

import aiofiles


async def get_logger(logger_status):
    logging.basicConfig(
        filename="chat_client.log",
        level=logging.DEBUG,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    logger = logging.getLogger(logger_status)

    return logger


async def update_env_file(key, value):
    lines = []

    async with aiofiles.open(".env", mode="r") as file:
        async for line in file:
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}\n")
            else:
                lines.append(line)

    async with aiofiles.open(".env", mode="w") as file:
        await file.writelines(lines)
