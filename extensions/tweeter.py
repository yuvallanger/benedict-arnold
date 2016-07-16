from tweepy.streaming import StreamListener
from tweepy import OAuthHandler
from tweepy import Stream, API
from requests_futures.sessions import FuturesSession
import time
import threading
import json
import midori
import re
import requests
import sqlite3
import logging
logger = logging.getLogger(__name__)

ARCHIVE_TODAY_URL = "https://archive.is/submit/"
CHANNEL = "#"

import HTMLParser
HTML_PARSER = HTMLParser.HTMLParser()

def connect_db():
    connection = sqlite3.connect("archived_stuff.db", check_same_thread=False)
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("CREATE TABLE IF NOT EXISTS links (source TEXT, artoday TEXT)")
    connection.commit()
    return connection

def authenticate(cfg):
    auth = OAuthHandler(cfg["consumer_key"], cfg["consumer_secret"])
    auth.set_access_token(cfg["access_token"], cfg["access_token_secret"])
    return auth

class StreamThread(threading.Thread):
    def __init__(self, listener):
        super(StreamThread, self).__init__()
        self.listener = listener
        self.exit = 0

    def run(self):
        while not self.exit:
            logger.info("connecting to twitter...")
            self.stream = Stream(self.listener.auth, self.listener)
            self.stream.filter(follow=self.listener.follow_ids)
            if not self.exit:
                time.sleep(5)

    def stop(self):
        self.exit = 1
        self.stream.disconnect()

class TweetStream(StreamListener):
    def __init__(self, api, cfg):
        super(TweetStream, self).__init__()
        self.gsession = FuturesSession(max_workers=10)

        self.mapi = api
        self.cfg = cfg
        self.install_hooks()

        self.auth = authenticate(cfg)
        self.twapi = API(auth_handler=self.auth)
        self.id_cache = {}

        self.load_following()
        self.database = connect_db()
        self.db_lock = threading.RLock()

        self.sthread = None
        self.filter_others = 1
        self.restart_stream()

    def install_hooks(self):
        self.mapi.hook_raw("KICK", self.on_kick)
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_follow,
                              predicate=lambda cmd: cmd.message.startswith("*follow"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_unfollow,
                              predicate=lambda cmd: cmd.message.startswith("*ufollow"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_silence,
                              predicate=lambda cmd: cmd.message.startswith("*silence"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_usilence,
                              predicate=lambda cmd: cmd.message.startswith("*usilence"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_spamon,
                              predicate=lambda cmd: cmd.message.startswith("*nofilter"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_spamoff,
                              predicate=lambda cmd: cmd.message.startswith("*yesfilter"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_arc,
                              predicate=lambda cmd: cmd.message.startswith("*arc"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_disgnostic,
                              predicate=lambda cmd: cmd.message.startswith("*diagnostics"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_helpinfo,
                              predicate=lambda cmd: cmd.message.startswith("*help"))
        self.mapi.hook_command(midori.CONTEXT_CHANNEL, self.api_get_tweet)

    def load_following(self):
        try:
            with open("follows.json", "r") as f:
                self.follow_ids = json.load(f)
        except:
            print("No following.")
            self.follow_ids = []

        try:
            with open("silence.json", "r") as f:
                self.silenced_ids = json.load(f)
        except:
            print("No silenced.")
            self.silenced_ids = []

    def save_follows(self):
        with open("follows.json", "w") as f:
            json.dump(self.follow_ids, f)
        with open("silence.json", "w") as f:
            json.dump(self.silenced_ids, f)

    def restart_stream(self):
        if self.sthread:
            self.sthread.stop()
        self.sthread = StreamThread(self)
        self.sthread.daemon = 1
        self.sthread.start()

    def api_helpinfo(self, cmd):
        self.mapi.privmsg(cmd.channel, "To show twitter user's tweets: *follow user | Top stop showing twitter user's tweets *ufollow user | To archive.today (and attempt waybacking behind the scenes ) something *arc URL")

    def api_follow(self, cmd):
        user = self.m_get_userid(cmd.message[8:].strip())
        if not user: #or cmd.channel.name != "#nasa_surveilance_van_no.7":
            self.mapi.privmsg(cmd.channel, "An argument is required (*follow user)")
        else:
            self.follow_ids.append(user)
            self.save_follows()
            self.mapi.privmsg(cmd.channel, "Added to the stalking list. Restarting stream...")
            self.restart_stream()

    def api_unfollow(self, cmd):
        user = self.m_get_userid(cmd.message[9:].strip())
        if not user: #or cmd.channel.name != "#nasa_surveilance_van_no.7":
            self.mapi.privmsg(cmd.channel, "An argument is required (*ufollow user)")
        else:
            try:
                int(user)
                self.follow_ids.remove(user)
            except ValueError:
                self.mapi.privmsg(cmd.channel, "Not in list.")
            else:
                self.save_follows()
                self.mapi.privmsg(cmd.channel, "Removed from the stalking list. Restarting stream...")
                self.restart_stream()

    def api_silence(self, cmd):
        user = self.m_get_userid(cmd.message[9:].strip())
        if not user: #or cmd.channel.name != "#nasa_surveilance_van_no.7":
            self.mapi.privmsg(cmd.channel, "An argument is required (*silence user)")
        else:
            self.silenced_ids.append(user)
            self.save_follows()
            self.mapi.privmsg(cmd.channel, "Silenced. Use '*usilence <name>' to un-silence later.")
            self.restart_stream()

    def api_usilence(self, cmd):
        user = self.m_get_userid(cmd.message[10:].strip())
        if not user: #or cmd.channel.name != "#nasa_surveilance_van_no.7":
            self.mapi.privmsg(cmd.channel, "An argument is required (*usilence user)")
        else:
            try:
                int(user)
                self.silenced_ids.remove(user)
            except ValueError:
                self.mapi.privmsg(cmd.channel, "Not in list.")
            else:
                self.save_follows()
                self.mapi.privmsg(cmd.channel, "Un-silenced.")
                self.restart_stream()

    def api_spamon(self, cmd):
        self.filter_others = 0

    def api_spamoff(self, cmd):
        self.filter_others = 1

    def api_get_tweet(self, cmd):
        statuses = re.findall("http(?:s)?://twitter.com/[a-z0-9\\-_]+/status(?:es)?/([0-9]+)",
                              cmd.message.lower())
        if not statuses:
            return
        statuses = set(statuses)

        for id_ in statuses:
            try:
                tweet = self.twapi.get_status(id=id_)
            except:
                continue

            the_url = "https://twitter.com/{0}/status/{1}".format(tweet.author.screen_name, tweet.id_str)
            urls = self.m_tweet_archive_sync(the_url)
            self.midori_push(tweet, urls, cmd.channel)

    def api_arc(self, cmd):
        to_arc = cmd.message[4:].strip()
        to_arc = to_arc.split(" ", 1)[0]

        if re.match("http(?:s)?://twitter.com/[a-z0-9\\-_]+/status(?:es)?/([0-9]+)", to_arc):
            self.mapi.privmsg(cmd.channel, "Simply linking a tweet is enough to get it archived.")
            return

        if not to_arc:
            self.mapi.privmsg(cmd.channel, "An argument is required. (*arc https://example.com...)")
            return

        links = self.m_archive_sync(to_arc)
        if links:
            self.mapi.privmsg(cmd.channel, "{0}: {1}".format(cmd.sender.nick, ", ".join(links)))
        else:
            self.mapi.privmsg(cmd.channel, "Archive failed; probably an invalid URL.")

    def api_disgnostic(self, cmd):
        if cmd.sender.hostmask != self.cfg["owner_host"]:
            self.mapi.notice(cmd.sender, "You need to authenticate with your NASA employee ID and passphrase before doing that.")
        else:
            self.mapi.notice(cmd.sender, "{0}".format(str(self.follow_ids)))
            ul = self.m_convert_ids_to_users(self.follow_ids)
            self.mapi.notice(cmd.sender, "{0}".format(str([u.screen_name for u in ul])))

            self.mapi.notice(cmd.sender, "{0}".format(str(self.silenced_ids)))
            ul = self.m_convert_ids_to_users(self.silenced_ids)
            self.mapi.notice(cmd.sender, "{0}".format(str([u.screen_name for u in ul])))

    def on_kick(self, command):
        if command.args[1] == self.mapi.nick and command.args[0] == self.cfg["channel"]:
            self.mapi.join(self.cfg["channel"])

    def m_archive_sync(self, url):
        future_at = self.gsession.post(ARCHIVE_TODAY_URL, data={
            "url": url,
        }, headers={
            "Referer": "https://archive.is",
            "Connection": "close",
        }, timeout=30, verify=True, allow_redirects=False)

        #future_pe = self.gsession.post("http://www.peeep.us/upload.php", data={
        #    "r_url": url,
        #}, headers={
        #    "Content-Type": "application/x-www-form-urlencoded",
        #}, timeout=30, allow_redirects=False)

        # blackhole archive; todo: put it in db
        self.gsession.head("http://web.archive.org/save/{0}".format(url), headers={
            "Referer": "https://archive.org/web/"
        }, timeout=30)

        response_at = future_at.result()
        #response_pe = future_pe.result()

        arc_url = []
        if "Refresh" in response_at.headers:
            arc_url.append(response_at.headers["Refresh"][6:])
            with self.db_lock:
                self.database.execute("INSERT INTO links VALUES (?, ?)", (url, response_at.headers["Refresh"][6:]))
                self.database.commit()
        elif "Location" in response_at.headers:
            arc_url.append(response_at.headers["Location"])
            with self.db_lock:
                self.database.execute("INSERT INTO links VALUES (?, ?)", (url, response_at.headers["Location"]))
                self.database.commit()

        #if "Location" in response_pe.headers:
        #    arc_url.append("http://peeep.us" + response_pe.headers["Location"])
        #    with self.db_lock:
        #        self.database.execute("INSERT INTO links VALUES (?, ?)", (url, "http://peeep.us" + response_pe.headers["Location"]))
        #        self.database.commit()

        return arc_url or None

    def m_tweet_archive_sync(self, url):
        future_at = self.gsession.post(ARCHIVE_TODAY_URL, data={
            "url": url,
        }, headers={
            "Referer": "https://archive.is",
            "Connection": "close",
        }, timeout=30, verify=True, allow_redirects=False)

        future_ts = self.gsession.get("http://tweetsave.com/api.php?mode=save&tweet=", params={
            "mode": "save",
            "tweet": url
        }, timeout=30)

        response = future_ts.result()
        response_at = future_at.result()

        arc_url = []
        try:
            payload = response.json()
            if "redirect" in payload and payload["status"] == "OK":
                arc_url.append(payload["redirect"])
                with self.db_lock:
                    self.database.execute("INSERT INTO links VALUES (?, ?)", (url, payload["redirect"]))
                    self.database.commit()
        except:
            pass

        if "Refresh" in response_at.headers:
            arc_url.append(response_at.headers["Refresh"][6:])
            with self.db_lock:
                self.database.execute("INSERT INTO links VALUES (?, ?)", (url, response_at.headers["Refresh"][6:]))
                self.database.commit()
        elif "Location" in response_at.headers:
            arc_url.append(response_at.headers["Location"])
            with self.db_lock:
                self.database.execute("INSERT INTO links VALUES (?, ?)", (url, response_at.headers["Location"]))
                self.database.commit()

        return arc_url

    def m_convert_ids_to_users(self, l):
        return self.twapi.lookup_users(user_ids=l)

    def m_get_userid(self, name):
        name = name.lower()
        if name in self.id_cache:
            return self.id_cache[name]
        else:
            try:
                user = self.twapi.get_user(screen_name=name)
            except:
                return None
            self.id_cache[name] = user.id_str
            return user.id_str

    def midori_push(self, tweet, arc, channel, the_url=None):
        tw = HTML_PARSER.unescape(tweet.text).replace("\n", " ")
        for url in tweet.entities["urls"]:
            tw = tw.replace(url["url"], url["expanded_url"])
        if arc:
            text = (u"@{0}: \"{1}\" {3}({2})".format(
                    tweet.author.screen_name, tw, ", ".join(arc),
                    "({0}) ".format(the_url) if the_url else ""))
        else:
            text = (u"@{0}: \"{1}\" ({2})".format(
                    tweet.author.screen_name, tw, the_url))
        self.mapi.privmsg(channel, text)

    def on_status(self, tweet):
        if self.filter_others and tweet.author.id_str not in self.follow_ids:
            return True
        the_url = "https://twitter.com/{0}/status/{1}".format(tweet.author.screen_name, tweet.id_str)
        if tweet.author.id_str not in self.silenced_ids:
            self.midori_push(tweet, None, self.cfg["channel"], the_url)
        links = self.m_tweet_archive_sync(the_url)
        if tweet.author.id_str not in self.silenced_ids:
            self.mapi.privmsg(self.cfg["channel"], "-> {0}".format(", ".join(links)))
        return True

    def on_disconnect(self, status):
        print(status)
        print("disconnected :^(")
        self.mapiobj.privmsg(CHANNEL, "Lost connection.")

__identifier__ = "twitter.stream"
__dependencies__ = []
__version__ = "1.0"
__ext_class__ = TweetStream
