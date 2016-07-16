import logging
import midori.api

class IRCBase(object):
    def __init__(self, api, nil):
        self.api = api
        self.hooks = []
        self.api.hook_raw("PING", self.on_ping)
        self.api.hook_raw("001", self.on_ready)
        self.api.hook_raw("PRIVMSG", self.delegate_msg)
        self.api.hook_raw("JOIN", self.on_join)
        self.api.hook_raw("PART", self.on_part)
        self.api.hook_raw("KICK", self.on_kick)
        self.api.hook_raw("QUIT", self.on_quit)
        self.api.hook_raw("353", self.on_names)
        self.api.hook_raw("MODE", self.on_mode)
        # self.api.hook_raw("376", self.on_mode)
        self.api.hook_raw("NICK", self.on_nick)
        self.is_waiting_for_mode_r = 0
        logger.info("Core hooks installed.")
        api.hook_command = self.hook_privcommand
        api.unhook_command = self.unhook_privcommand
        api.hook_command(midori.CONTEXT_PRIVATE, self.return_version,
                         lambda cmd: cmd.message.startswith("\x01VERSION")
                                     and cmd.message.endswith("\x01"))

    def hook_privcommand(self, context, callback, predicate=lambda cmd: 1):
        self.hooks.append({
            "ctx": context,
            "call": callback,
            "predicate": predicate
        })

    def unhook_privcommand(self, context, callback):
        caught = None
        for i in self.hooks:
            if i["ctx"] == context and i["call"] == callback:
                caught = i
                break
        if caught:
            logger.info("Removing PRIVMSG hook for {0} in context {1}".format(callback, context))
            self.hooks.remove(caught)

    def delegate_msg(self, command):
        user = self.api.users.get(command.sender[0], command.sender)
        if user is None:
            logger.info("User not known, command discarded.")
            return
        user.user_name = command.sender[1]
        user.hostmask = command.sender[2]
        if command.args[0] == self.api.nick:
            channel = None
            ctxmode = midori.CONTEXT_PRIVATE
        else:
            channel = self.api.channels.get(command.args[0])
            channel.buffer.append({
                "sender": command.args[0],
                "message": command.message,
            })
            ctxmode = midori.CONTEXT_CHANNEL
        if not isinstance(user, midori.api.TransientUser):
            user.buffer.append({
                "sender": command.args[0],
                "channel": channel,
                "message": command.message,
            })
        cmd = midori.api.PrivateMessage(user, channel, ctxmode, command.message)
        for passing in filter(lambda x: x["ctx"] & ctxmode, self.hooks):
            if passing["predicate"](cmd):
                passing["call"](cmd)

    def on_ping(self, command):
        self.api.send_raw("PONG :{0}".format(command.message))

    def on_ready(self, command):
        modes = self.api.get_instance().config("modes", "+wpsC")
        if modes:
            self.api.mode(self.api.nick, modes)

        password = self.api.get_instance().config("nickserv_password", 0)
        if password:
            self.is_waiting_for_mode_r = 1
            self.api.privmsg(self.api.get_instance().config("nickserv", "NickServ"),
                             "IDENTIFY {0}".format(password))
            # we're going to wait for nickserv identification before autojoin.
        else:
            self.is_waiting_for_mode_r = 0
            for channel in self.api.get_instance().config("channels", []):
                self.api.join(channel)

    def on_join(self, command):
        cname = command.message or command.args[0]
        if command.sender[0] == self.api.nick:
            self.api.channels[cname] = midori.api.Channel(cname)
        else:
            try:
                user = self.api.users[command.sender[0]]
            except KeyError:
                user = midori.api.User(command.sender)
                self.api.users[command.sender[0]] = user
            channel = self.api.channels.get(cname)
            if channel:
                channel.users.add(user)
            else:
                logger.warn("JOIN message dropped because we aren't subscribed to the target channel.")

    def on_part(self, command):
        try:
            user = self.api.users[command.sender[0]]
        except KeyError:
            return
        channel = self.api.channels.get(command.args[0])
        if channel:
            channel.users.remove(user)
        else:
            logger.warn("PART message dropped because we aren't subscribed to the target channel.")

    def on_kick(self, command):
        if command.args[1] == self.api.nick:
            self.api.channels.remove(command.args[0])
        else:
            try:
                user = self.api.users[command.args[1]]
            except KeyError:
                return
            channel = self.api.channels.get(command.args[0])
            if channel:
                channel.users.remove(user)
            else:
                logger.warn("KICK message dropped because we aren't subscribed to the target channel.")

    def on_quit(self, command):
        try:
            user = self.api.users[command.sender[0]]
        except KeyError:
            return
        for channel in self.api.channels:
            try:
                self.api.channels[channel].users.remove(user)
            except KeyError:
                pass

    def on_names(self, command):
        for name in command.message.split(" "):
            name = name.lstrip("!~&@%+")
            if name == self.api.nick:
                continue
            try:
                user = self.api.users[name]
            except KeyError:
                user = midori.api.User((name, "(unknown)", "(unknown)"))
                self.api.users[name] = user
            channel = self.api.channels.get(command.args[2])
            if channel:
                channel.users.add(user)
            else:
                logger.warn("NAMES message dropped because we aren't subscribed to the target channel.")

    def on_nick(self, command):
        if command.sender[0] == self.api.nick:
            self.api.nick = command.args[0]
        else:
            try:
                user = self.api.users[command.sender[0]]
            except KeyError:
                return
            user.nick = command.message
            del self.api.users[command.sender[0]]
            self.api.users[user.nick] = user

    def on_mode(self, command):
        # it is more reliable to check for the registered flag instead of
        # arbitrary messages from NickServ (which may change between services)
        if command.args[0] != self.api.nick or not self.is_waiting_for_mode_r:
            return

        added_modes = []
        deleted_modes = []
        is_deleting = 0
        for ch in command.message:
            if ch == "+":
                is_deleting = 0
                continue
            elif ch == "-":
                is_deleting = 1
                continue
            else:
                (deleted_modes if is_deleting else added_modes).append(ch)

        if "r" in added_modes:
            for channel in self.api.get_instance().config("channels", []):
                self.api.join(channel)
            self.is_waiting_for_mode_r = 0

    def return_version(self, command):
        self.api.notice(command.sender, "\x01VERSION Stolen NASA Satellite 1.0001something-AA\x01")

__identifier__ = "midori.base"
__dependencies__ = []
__version__ = midori.VERSION
__ext_class__ = IRCBase
logger = logging.getLogger(__identifier__)
