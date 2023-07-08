import logging

__format = "[%(levelname)s] %(asctime)s %(filename)s-%(funcName)s:%(lineno)d  %(message)s"

def get_logger(logger_name, level=logging.INFO):
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    stream_handler = logging.StreamHandler()
    stream_formatter = logging.Formatter(__format)
    stream_handler.setFormatter(stream_formatter)
    logger.addHandler(stream_handler)
    return logger

def test_logger(logger: logging.Logger):
    logger.info(f"Entering testing function")

if __name__ == '__main__':
    lg = get_logger(__name__)
    test_logger(lg)
