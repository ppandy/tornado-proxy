
"""
A simple echo server for telnet, implemented using tornado.gen
"""

import itertools
import socket

import tornado.gen
import tornado.ioloop
import tornado.iostream
import tornado.tcpserver
import redis
import time
import json

class Scope(object):

    session = None
    first = True
    key = "proxy_request"
    timeout = 10
    REDIS_HOST = '127.0.0.1'
    REDIS_PORT = 6379
    
    def __init__(self):
        self.r = redis.StrictRedis(host=self.REDIS_HOST, port=self.REDIS_PORT, db=0)
        self.session = 1
        self.r.set(self.key,self.session)
        #self.r.zremrangebyrank(self.key+"::"+str(self.session),0,-1)
        self.set_expire()
        #self.cache = []
        #self.cache_size = 200
    
    def add_request(self,status,request):
        #print ("Adding Record for Session %s of %s") % (scope.session, status)
        self.r.zadd(self.key+"::"+str(status)+"::"+str(scope.session), time.time(), json.dumps(request))
                
    def increment_session(self):
        self.session += 1
        self.r.set(self.key,self.session)
        self.set_expire()
         
    def reset_session(self):
        self.session = 1
        self.set_expire()
        
    def set_expire(self):
        self.r.expire(self.key+"::"+str(self.session),self.timeout)
        
scope = Scope() 

@tornado.gen.coroutine
def read_until(stream, delimiter, _idalloc=itertools.count()):
    cb_id = next(_idalloc)
    cb = yield tornado.gen.Callback(cb_id)
    stream.read_until(delimiter, cb)
    result = yield tornado.gen.Wait(cb_id)
    raise tornado.gen.Return(result)

def write(stream, data):
    return tornado.gen.Task(stream.write, data)
    
class SimpleEcho(object):
    """
        Per-connection object.
    """
    DEBUG = True

    @tornado.gen.coroutine
    def on_connect(self):
        yield self.dispatch()
        return

    @tornado.gen.coroutine
    def on_disconnect(self):
        yield []
        return

    @tornado.gen.coroutine
    def dispatch(self):
        try:
            while True:
                line = yield read_until(self.stream,"\n")
                obj = line.split(' ')
                request = {"method":obj[9],"uri":obj[10],"session":1}
                scope.add_request(obj[7].replace('TCP_MISS/',''), request)
                if self.DEBUG:
                    yield write("{}", repr(line))
        except tornado.iostream.StreamClosedError:
            pass
        return

    def log(self, msg, *args, **kwargs):
        print "{}".format(msg.format(*args, **kwargs))
        return

class SimpleEchoServer(tornado.tcpserver.TCPServer):
    """
        Server listener object.
    """

    def __init__(self, io_loop=None, ssl_options=None, max_buffer_size=None):

        tornado.tcpserver.TCPServer.__init__(self,
            io_loop=io_loop, ssl_options=ssl_options, max_buffer_size=max_buffer_size)

        return

    @tornado.gen.coroutine
    def handle_stream(self, stream, address):
        
        conn = SimpleEcho()
        stream.set_close_callback(conn.on_disconnect)
        stream.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        stream.socket.setsockopt(socket.IPPROTO_TCP, socket.SO_KEEPALIVE, 1)
        conn.stream = stream
        yield conn.on_connect()
        return

if __name__ == "__main__":

    server = SimpleEchoServer()
    server.listen(8889)

    tornado.ioloop.IOLoop.instance().start()
