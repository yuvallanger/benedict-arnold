import logging
import json
import re
import os
import sys
import time
from collections import defaultdict

import midori
import midori.api
import midori.extloader
import midori.workers

try:
    import queue
except ImportError:
    import Queue as queue

logger = logging.getLogger(__name__)

if sys.version_info.major == 2:
    fix_log_string = lambda s: s.encode("utf8")
else:
    fix_log_string = lambda s: s

class Midori(object):
    """A modular, non-blocking IRC bot."""
    def __init__(self, config_file="config.json"):
        self.basedir = os.path.realpath(".")
        with open(os.path.join(self.basedir, config_file)) as fp:
            self._config = json.load(fp)
        self.api = midori.api.API(self)
        self.loaded_extensions = 0
        self.net_thread = None
        self.read_queue = queue.Queue()
        self.write_queue = queue.Queue()
        self.observers = defaultdict(lambda: [])
        self.workers = midori.workers.ThreadPool(self._config.get("workers_size", 2))

    def load_extensions(self):
        ext_settings = self.config("extension", {})
        self.ext_manager = midori.extloader.ExtensionManager(
            search_dirs=[os.path.join(os.path.dirname(__file__), "base_exts"),
                         os.path.join(self.basedir, "extensions")],
            blacklist=self.config("extension_blacklist", []),
        )
        self.ext_manager.load_extensions(lambda mod: (self.api, ext_settings.get(mod.__identifier__, {})))
        logger.info("I have {0} extensions loaded.".format(self.ext_manager.count()))

    def run(self):
        self.irc_nick = self.config("identity.nick", "")
        self.irc_user = self.config("identity.user", "")
        self.irc_host = self.config("server.host", "")
        self.irc_port = self.config("server.port", 0)
        self.irc_realname = self.config("identity.real_name", "")
        self.api.nick = self.irc_nick
        if not self.loaded_extensions:
            self.load_extensions()
        for cf in ("irc_nick", "irc_user", "irc_host", "irc_port", "irc_realname"):
            if not getattr(self, cf):
                raise ConfigurationError("Mis-configured key: {0}. Please check.".format(cf))
        self.use_ssl = self.config("server.use_ssl", -1)
        if self.use_ssl not in (0, 1):
            raise ConfigurationError("Mis-configured key: use_ssl.")
        while 1:
            self.net_thread = midori.workers.NetworkThread(self, self.irc_host,
                                                           self.irc_port, self.use_ssl,
                                                           self.read_queue, self.write_queue)
            self.net_thread.start()
            self.handshake()
            while self.net_thread.is_alive():
                try:
                    cmd = self.read_queue.get(timeout=300)
                except queue.Empty:
                    self.api.send_raw("PING :{0}".format(self.irc_nick))
                if not cmd:
                    break
                midori.net_recv.info("\033[32m{0}\033[0m".format(fix_log_string(cmd.string_rep)))
                for callback, predicate in self.observers[cmd.kind]:
                    if predicate(cmd):
                        self.workers.dispatch(callback, args=(cmd,))
            logger.error("Disconnected from IRC. Trying again in 360 seconds...")
            time.sleep(360)

    def config(self, key, default=None, rtype=lambda x: x):
        value = self._config
        # so you can use . in key for drilling into subobjects
        for i in key.split("."):
            if i in value:
                value = value[i]
            else:
                # call for key in global config, or return caller's default
                return default
        return rtype(value)

    def handshake(self):
        pass_ = self.config("server.password", "")
        if pass_:
            self.api.send_raw("PASS {0}".format(pass_))
        self.api.send_raw("NICK {0}".format(self.irc_nick))
        self.api.send_raw("USER {0} * 8 :{1}".format(self.irc_user, self.irc_realname))

    def exit(self):
        logger.warn("Shutting down. Bye bye!")
        self.workers.stop()
        if self.net_thread:
            self.net_thread.stopping = 1
            logger.info("Waiting for network thread to die...")
            self.net_thread.join()
        return 0

class Command(object):
    """high-level IRC command"""
    def __init__(self, command):
        self.string_rep = command
        if " :" in command:
            left, self.message = command.split(" :", 1)
        else:
            left, self.message = command, None
        self.args = left.split()
        self.sender = None
        if self.args[0].startswith(":"):
            user = re.split(r"[!@]", self.args.pop(0)[1:])
            if len(user) != 3:
                self.sender = (None, None, user[0])
            else:
                self.sender = tuple(user)
        self.kind = self.args.pop(0)

    def __repr__(self):
        return "<midori.core.Command({0})>".format(self.string_rep)

    def __str__(self):
        return self.string_rep

class ConfigurationError(Exception):
    """Raised when Midori is not configured correctly"""
