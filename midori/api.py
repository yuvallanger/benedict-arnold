from __future__ import unicode_literals
import weakref
from collections import deque
import re
"""
Midori API definitions.
This module should not be imported directly, instead, your extension should have
saved the API object passed to its __init__.
"""

class API(object):
    """Extension API."""
    def __init__(self, instance):
        self.instance = instance
        self.nick = ""
        self.channels = {}
        self.users = MidoriUserDictionary()

    def get_instance(self):
        """Return the midori.core.Midori instance associated with this API
           object."""
        return self.instance

    def get_stats(self):
        buffer_count = 0
        total_buffer_containment = 0
        for user_name in self.users:
            buffer_count += 1
            total_buffer_containment += len(self.users[user_name].buffer)
        for channel in self.channels:
            buffer_count += 1
            total_buffer_containment += len(self.channels[channel].buffer)
        return {
            "buffer_count": buffer_count,
            "total_buffer_containment": total_buffer_containment
        }

    def hook_raw(self, kind, callback, predicate=lambda cmd: 1):
        """Register a callback for the IRC numeric represented by kind.
           If predicate returns true for the midori.core.Command object passed
           to it, callback will be called using the same Command object.
           Predicates will be run on the main thread, so make sure they do
           not take too long.

        Arguments:
            kind [string]: IRC numeric you are registering for. example: 001, PRIVMSG
            callback [callable]: The callback you are registering. Callbacks are not
                                 guaranteed to run in order, or even on the same thread.
            predicate [callable]: A short function that is used to filter what messages
                                  are passed to the callback.
        """
        self.instance.observers[kind].append((callback, predicate))

    def send_raw(self, command_str):
        """Send a command to IRC.
        
        Arguments:
            command_str [unicode!]: Command to send, as a unicode string.
                                    Do not include the trailing CRLF."""
        self.instance.write_queue.put("{0}\r\n".format(command_str).encode("utf-8"))

    def join(self, channel):
        """Join a channel.

        Arguments:
            channel [string]: channel to join, with prefix"""
        self.send_raw("JOIN {0}".format(channel))

    def leave(self, channel, message="Leaving"):
        """Leave a channel.

        Arguments:
            channel [string]: channel to leave, with prefix.
            message [string]: the message that will be sent with your PART"""
        self.send_raw("PART {0} :{1}".format(channel, message))

    def kick(self, channel, user, reason=""):
        """Kick a user from a channel.
        Usually requires privileges in that channel.

        Arguments:
            channel -- the target channel
            user -- the target user
            reason -- Optional. Specify a reason for the kick.
        """
        self.send_raw("KICK {0} {1} :{2}".format(channel, user, reason))

    def mode(self, target, mode="", args=""):
        """Set the mode(s) of a channel or user, with optional arguments.

        Arguments:
            target -- the target channel or user
            mode -- Optional. One or more valid mode characters
            args -- Optional. One or more arguments (eg usernames).
        """
        self.send_raw("MODE {0} {1} {2}".format(target, mode, args))

    def away(self, message=""):
        """Mark yourself as away, specifying a message to be sent to others. If
        message is omitted, the away status will be removed.

        Arguments:
            message -- Message to be sent. Must be omitted to unmark
        """
        self.send_raw("AWAY {0}".format(message))

    def invite(self, user, channel):
        """Invite a user to a channel.

        Arguments;
            user -- The user to invite
            channel -- The channel to invite to
        """
        self.send_raw("INVITE {0} {1}".format(user, channel))

    def privmsg(self, target, message):
        """Send a message to target channel or user.

        Arguments:
            target [string | midori.api.User | midori.api.Channel]: Message recipient.
            message [string]: Message to send."""
        self.send_raw("PRIVMSG {0} :{1}".format(str(target), message))

    def action(self, target, message):
        """Send an action (/me) to a target channel or user.

        Arguments:
            target [string | midori.api.User | midori.api.Channel]: Message recipient.
            message [string]: Message to send."""
        self.send_raw("PRIVMSG {0} :\x01ACTION{1}\x01".format(str(target), message))

    def notice(self, target, message):
        """Send a notice to a user or channel.

        Arguments:
            target -- Either a user or a channel (prefixed with the usual hash)
            message -- The message to send
        """
        self.send_raw("NOTICE {0} :{1}".format(target, message))

    # Modes

    def voice(self, channel, nick):
        """Gives voice to someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "+v", nick)

    def devoice(self, channel, nick):
        """Removes voice from someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "-v", nick)

    def hop(self, channel, nick):
        """Gives half operator status to someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "+h", nick)

    def dehop(self, channel, nick):
        """Removes half operator status from someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "-h", nick)

    def op(self, channel, nick):
        """Gives operator status to someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "+o", nick)

    def deop(self, channel, nick):
        """Removes operator status from someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "-o", nick)

    def protect(self, channel, nick):
        """Gives protected status to someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "+a", nick)

    def deprotect(self, channel, nick):
        """Removes protected status from someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "-a", nick)

    def owner(self, channel, nick):
        """Gives owner status to someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "+q", nick)

    def deowner(self, channel, nick):
        """Removes owner status from someone on a channel.

        Arguments:
            channel -- The channel on which to set the mode.
            nick -- The targeted user.
        """
        self.mode(channel, "-q", nick)

    def ban(self, channel, nick):
        """Sets a ban on a channel against a nickname.

        This method will set a ban on nick!*@*.
        For more precise bans, use ban_by_mask.

        Arguments:
            channel -- The channel on which to set the ban.
            nick -- The user to ban.
        """
        self.mode(channel, "+b", nick + "!*@*")

    def unban(self, channel, nick):
        """Removes a ban on a channel against a nickname.

        This method will unset bans on nick!*@*.
        For more precise unbanning, use unban_by_mask.

        Arguments:
            channel -- The channel on which to remove the ban.
            nick -- The user to unban.
        """
        self.mode(channel, "-b", "{0}!*@*".format(nick))

    def ban_by_mask(self, channel, mask):
        """Sets a ban on a channel against a mask in the form of
        "nick!user@host". Wildcards accepted.

        Arguments:
            channel -- The channel on which to set the ban.
            mask -- The mask to ban.
        """
        self.mode(channel, "+b", mask)

    def unban_by_mask(self, channel, mask):
        """Removes a ban on a channel against a mask in the form of
        "nick!user@host". Wildcards accepted.

        Arguments:
            channel -- The channel on which to remove the ban.
            mask -- The mask to unban.
        """
        self.mode(channel, "-b", mask)

    def kickban(self, channel, nick, reason=""):
        """Sets a ban on a user, then kicks them from the channel.

        Arguments:
            channel -- The channel from which to kickban.
            nick -- The user to kickban.
            reason -- Optional. A reason for the kickban.
        """
        self.ban(channel, nick)
        self.kick(channel, nick, reason)

class MidoriUserDictionary(weakref.WeakValueDictionary):
    def get(self, a, b):
        if a in self:
            return weakref.WeakValueDictionary.get(self, a)
        else:
            return TransientUser(b)

class PrivateMessage(object):
    def __init__(self, sender, target, ctxmode, message):
        self.sender = sender
        self.channel = target
        self.context = ctxmode
        self.raw_message = message
        self.message = strip_controls(message)

class Channel(object):
    def __init__(self, name):
        self.users = set()
        self.buffer = deque(maxlen=10)
        self.name = name

    def __str__(self):
        return self.name

class User(object):
    def __init__(self, user_tuple):
        self.channels = weakref.WeakSet()
        self.buffer = deque(maxlen=10)
        self.nick = user_tuple[0]
        self.user_name = user_tuple[1]
        self.hostmask = user_tuple[2]

    def __str__(self):
        return self.nick

class TransientUser(object):
    def __init__(self, user_tuple):
        self.channels = ()
        self.buffer = ()
        self.nick = user_tuple[0]
        self.user_name = user_tuple[1]
        self.hostmask = user_tuple[2]

    def __str__(self):
        return self.nick

def strip_controls(string):
    return re.sub("\x02|\x03([0-9]{2}(,[0-9]{2})?)?|\x1F|\x0F|\x16", "", string)
