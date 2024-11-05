import logging


async def get_logger(logger_status):
    logging.basicConfig(
        filename='chat_client.log', 
        level=logging.DEBUG,
        format='%(levelname)s:%(name)s:%(message)s'
    )
    logger = logging.getLogger(logger_status)

    return logger