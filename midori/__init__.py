import os
import logging
import sys
VERSION = "1.0"
CONTEXT_CHANNEL = 1
CONTEXT_PRIVATE = 1 << 1
CONTEXT_ALL = CONTEXT_CHANNEL | CONTEXT_PRIVATE

"""Midori-py root module."""

instance = None
config = None

# init logging
logger = logging.getLogger(__name__)
log_profile = {
    "datefmt": "%H:%M:%S",
    "format": "\033[36m%(asctime)s\033[0m \033[34m[%(name)s] \033[33m[%(levelname)s]\033[0m"
              " | %(message)s",
    "level": logging.INFO,
}

if "__MIDORI_SHOULD_LOG_TO_THIS_FILE__" in os.environ:
    log_profile["filename"] = os.environ["__MIDORI_SHOULD_LOG_TO_THIS_FILE__"]
    os.environ["__MIDORI_DOES_NOT_SUPPORT_CONSOLE_COLOURS__"] = "YES"
if os.environ.get("__MIDORI_DOES_NOT_SUPPORT_CONSOLE_COLOURS__", "NO") == "YES":
    log_profile["format"] = "%(asctime)s [%(name)s] [%(levelname)s] | %(message)s"
logging.basicConfig(**log_profile)
net_send = logging.getLogger("IRC_SEND")
net_recv = logging.getLogger("IRC_RECV")

from midori import core

def init(config_file=None):
    global instance, config
    if not config_file:
        if len(sys.argv) > 1:
            config_file = sys.argv[1]
        else:
            config_file = "config.json"
    instance = core.Midori(config_file)
    config = instance.config

logger.info("Pre-initialization complete: version {0}".format(VERSION))
