#!/usr/bin/env python
#
# Simple asynchronous HTTP proxy with tunnelling (CONNECT).
#
# GET/POST proxying based on
# http://groups.google.com/group/python-tornado/msg/7bea08e7a049cf26
#
# Copyright (C) 2012 Senko Rasic <senko.rasic@dobarkod.hr>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import sys
import socket

import tornado.httpserver
import tornado.ioloop
import tornado.iostream
import tornado.web
import tornado.httpclient
import redis
import time
import json

__all__ = ['ProxyHandler', 'run_proxy']

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
    
class ProxyHandler(tornado.web.RequestHandler):
    SUPPORTED_METHODS = ['GET', 'POST', 'CONNECT']
    LIMIT_HEADERS = False
    SUPPORTED_HEADERS = ('Date', 'Cache-Control', 'Server',
                        'Content-Type', 'Location','Accept-Ranges',
                        'X-Powered-By','Set-Cookie','Expires','P3p',
                        'Pragma','Last-Modified','Etag','WWW-Authenticate',
						'Vary',)
    DEBUG = True
    
    @tornado.web.asynchronous
    def get(self):
        print "GETTING"
        def handle_response(response):
            print "Handing Response for %s which is first?: %s" % (scope.session,scope.first)
            request = {"method":self.request.method,"uri":self.request.uri,"session":scope.session}
            scope.add_request(response.code, request)
            if response.error and not isinstance(response.error,
                    tornado.httpclient.HTTPError):
                self.set_status(500)
                self.write('Internal server error:\n' + str(response.error))
            else:
                if (response.code == 599):
                    self.set_status(500)
                else:
                    self.set_status(response.code)
                for header in self.SUPPORTED_HEADERS:
                    v = response.headers.get(header)
                    if v:
                        self.set_header(header, v)
                if response.body:
                    boday = response.body
                    if scope.first:
                        xtra = '<script type="text/javascript">$(window).load(function(){setTimeout(function() {$.ajax({url: "/proxy/finish",context: document.body}).done(function() {$( this ).addClass( "done" );});}, 3000);});</script>'
                        boday += xtra
                        scope.first = False
                    self.write(boday)
            self.finish()

        req = tornado.httpclient.HTTPRequest(url=self.request.uri,
            method=self.request.method, body=self.request.body,
            headers=self.request.headers, follow_redirects=False,
            allow_nonstandard_methods=True,validate_cert=False)

        request = "%s\t%s" % (self.request.method,self.request.uri)
        if self.DEBUG:
            print request
        
        if self.request.uri[-13:] == "/proxy/finish":
            scope.increment_session()
            self.set_status(200)
            self.finish()
            return
        
        client = tornado.httpclient.AsyncHTTPClient()
        try:
            client.fetch(req, handle_response)
        except tornado.httpclient.HTTPError as e:
            if hasattr(e, 'response') and e.response:
                handle_response(e.response)
            else:
                self.set_status(500)
                self.write('Internal server error:\n' + str(e))
                self.finish()

    @tornado.web.asynchronous
    def post(self):
        print "POSTING"
        scope.first = True
        return self.get()

    @tornado.web.asynchronous
    def connect(self):
        host, port = self.request.uri.split(':')
        client = self.request.connection.stream

        def read_from_client(data):
            upstream.write(data)

        def read_from_upstream(data):
            client.write(data)

        def client_close(data=None):
            if upstream.closed():
                return
            if data:
                upstream.write(data)
            upstream.close()

        def upstream_close(data=None):
            if client.closed():
                return
            if data:
                client.write(data)
            client.close()

        def start_tunnel():
            client.read_until_close(client_close, read_from_client)
            upstream.read_until_close(upstream_close, read_from_upstream)
            client.write(b'HTTP/1.0 200 Connection established\r\n\r\n')

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        upstream = tornado.iostream.IOStream(s)
        upstream.connect((host, int(port)), start_tunnel)

def run_proxy(port, start_ioloop=True):
    """
    Run proxy on the specified port. If start_ioloop is True (default),
    the tornado IOLoop will be started immediately.
    """
    app = tornado.web.Application([
        (r'.*', ProxyHandler),
    ])
    app.listen(port)
    ioloop = tornado.ioloop.IOLoop.instance()
    if start_ioloop:
        ioloop.start()

if __name__ == '__main__':
    port = 8888
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    print ("Starting HTTP proxy on port %d" % port)
    run_proxy(port)
