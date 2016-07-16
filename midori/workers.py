import logging
import select
import socket
import ssl
import threading

import midori
import midori.core

try:
    import queue
except ImportError:
    import Queue as queue

logger = logging.getLogger(__name__)

class ThreadPool(object):
    """Thread pool.
       stop: Stops all threads in this pool.
       dispatch: Execute call asynchronously with args and kwargs.
                                     When and where it will execute is undefined."""
    def __init__(self, nthreads):
        self.queue = queue.Queue()
        self.threads = set()
        for i in range(nthreads):
            t = WorkerThread()
            t.pool_handle = self.queue
            self.threads.add(t)
            t.start()
        logger.info("Thread pool filled with {0} threads.".format(nthreads))

    def dispatch(self, call, args=(), kwargs=None):
        task = ThreadPoolTask(call, args, kwargs if kwargs else {})
        self.queue.put(task)

    def stop(self):
        for i in self.threads:
            self.queue.put(ThreadPoolTask(None, None, None, name="ThreadStop"))

class ThreadPoolTask(object):
    def __init__(self, call, args, kwargs, name="Task"):
        self.name = name
        self.call = call
        self.args = args
        self.kwargs = kwargs

class WorkerThread(threading.Thread):
    """Thread that runs tasks from its parent ThreadPool.
       Should not be used directly."""
    def run(self):
        tasks_done = 0
        while 1:
            task = self.pool_handle.get()
            if task.name == "ThreadStop":
                logger.info("WorkerThread exiting.")
                break
            else:
                try:
                    task.call(*task.args, **task.kwargs)
                except Exception:
                    logger.error("{0}: Exception in dispatched task...".format(self.name),
                                 exc_info=1)
                    pass
                finally:
                    tasks_done += 1

class NetworkThread(threading.Thread):
    """Thread responsible for actually reading/writing to the socket."""
    def __init__(self, midori_inst, host, port, use_ssl, read_queue, write_queue):
        super(NetworkThread, self).__init__()
        self.host = host
        self.port = port
        self.ssl = use_ssl
        self.read_buffer = b""
        self.midori_inst = midori_inst
        self.read_queue = read_queue
        self.write_queue = write_queue
        self.retry_send_with = None

    def parse_buffer(self):
        commands = self.read_buffer.split(b"\r\n")
        self.read_buffer = commands.pop()
        for command in commands:
            command_obj = midori.core.Command(command.decode("utf-8"))
            self.read_queue.put(command_obj)

    def run(self):
        self.stopping = 0
        address = self.midori_inst.config("bind_addr", "0.0.0.0")
        if ":" in address:
            af = socket.AF_INET6 # ipv6
        else:
            af = socket.AF_INET # ipv4 (plebs)
        self.irc_socket = socket.socket(af, socket.SOCK_STREAM)
        if self.ssl:
            self.irc_socket = ssl.wrap_socket(self.irc_socket)
        try:
            self.irc_socket.bind((address, 0))
        except OSError as e:
            logger.error("Cannot bind net thread! {0}".format(e.strerror))
            return
        self.irc_socket.connect((self.host, self.port))
        self.irc_socket.setblocking(0)
        logger.info("Connected to {0}:{1}.".format(self.host, self.port))
        while self.irc_socket.fileno() > 0:
            if self.stopping and self.write_queue.empty():
                self.stop()
                return
            reads = [self.irc_socket.fileno()]
            writes = []
            if not self.write_queue.empty():
                writes.append(self.irc_socket.fileno())
            r, w, x = select.select(reads, writes, [], 1.0 / 30)
            if self.irc_socket.fileno() in r:
                try:
                    data = self.irc_socket.recv(4096)
                except ssl.SSLError:
                    pass
                except OSError:
                    self.stop()
                    self.read_queue.put(None)
                    logger.error("Socket closed unexpectedly!", exc_info=1)
                    return
                else:
                    if not data:
                        self.stop()
                        self.read_queue.put(None)
                        logger.error("Socket closed unexpectedly!")
                        return
                    self.read_buffer += data
                    self.midori_inst.workers.dispatch(self.parse_buffer)
            if self.irc_socket.fileno() in w:
                if not self.retry_send_with:
                    try:
                        package = self.write_queue.get_nowait()
                    except queue.Empty:
                        pass
                    midori.net_send.info(u"\033[31m{0}\033[0m".format(package.decode("utf-8")
                                                                             .strip("\r\n")))
                else:
                    package = self.retry_send_with
                    self.retry_send_with = None
                try:
                    self.irc_socket.send(package)
                except ssl.SSLError:
                    self.retry_send_with = package

    def stop(self):
        self.irc_socket.close()
