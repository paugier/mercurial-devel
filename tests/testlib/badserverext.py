# badserverext.py - Extension making servers behave badly
#
# Copyright 2017 Gregory Szorc <gregory.szorc@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

# no-check-code

"""Extension to make servers behave badly.

This extension is useful for testing Mercurial behavior when various network
events occur.

Various config options in the [badserver] section influence behavior:

close-before-accept
   If true, close() the server socket when a new connection arrives before
   accept() is called. The server will then exit.

close-after-accept
   If true, the server will close() the client socket immediately after
   accept().

close-after-recv-bytes
   If defined, close the client socket after receiving this many bytes.

close-after-send-bytes
   If defined, close the client socket after sending this many bytes.
"""

from __future__ import absolute_import

import socket

from mercurial import (
    pycompat,
    registrar,
)

from mercurial.hgweb import server

configtable = {}
configitem = registrar.configitem(configtable)

configitem(
    b'badserver',
    b'close-after-accept',
    default=False,
)
configitem(
    b'badserver',
    b'close-after-recv-bytes',
    default=b'0',
)
configitem(
    b'badserver',
    b'close-after-send-bytes',
    default=b'0',
)
configitem(
    b'badserver',
    b'close-before-accept',
    default=False,
)


class ConditionTracker(object):
    def __init__(self, close_after_recv_bytes, close_after_send_bytes):
        self._all_close_after_recv_bytes = close_after_recv_bytes
        self._all_close_after_send_bytes = close_after_send_bytes

        self.target_recv_bytes = None
        self.remaining_recv_bytes = None
        self.target_send_bytes = None
        self.remaining_send_bytes = None

    def start_next_request(self):
        """move to the next set of close condition"""
        if self._all_close_after_recv_bytes:
            self.target_recv_bytes = self._all_close_after_recv_bytes.pop(0)
            self.remaining_recv_bytes = self.target_recv_bytes
        else:
            self.target_recv_bytes = None
            self.remaining_recv_bytes = None
        if self._all_close_after_send_bytes:
            self.target_send_bytes = self._all_close_after_send_bytes.pop(0)
            self.remaining_send_bytes = self.target_send_bytes
        else:
            self.target_send_bytes = None
            self.remaining_send_bytes = None

    def might_close(self):
        """True, if any processing will be needed"""
        if self.remaining_recv_bytes is not None:
            return True
        if self.remaining_send_bytes is not None:
            return True
        return False

    def forward_write(self, obj, method, data, *args, **kwargs):
        """call an underlying write function until condition are met

        When the condition are met the socket is closed
        """
        remaining = self.remaining_send_bytes

        orig = object.__getattribute__(obj, '_orig')
        bmethod = method.encode('ascii')
        func = getattr(orig, method)
        # No byte limit on this operation. Call original function.
        if not remaining:
            result = func(data, *args, **kwargs)
            obj._writelog(b'%s(%d) -> %s' % (bmethod, len(data), data))
            return result

        remaining = max(0, remaining)

        if remaining > 0:
            if remaining < len(data):
                newdata = data[0:remaining]
            else:
                newdata = data

            remaining -= len(newdata)

            obj._writelog(
                b'%s(%d from %d) -> (%d) %s'
                % (
                    bmethod,
                    len(newdata),
                    len(data),
                    remaining,
                    newdata,
                )
            )

            result = func(newdata, *args, **kwargs)

        self.remaining_send_bytes = remaining

        if remaining <= 0:
            obj._writelog(b'write limit reached; closing socket')
            object.__getattribute__(obj, '_cond_close')()
            raise Exception('connection closed after sending N bytes')

        return result

    def forward_read(self, obj, method, size=-1):
        """call an underlying read function until condition are met

        When the condition are met the socket is closed
        """
        remaining = self.remaining_recv_bytes

        orig = object.__getattribute__(obj, '_orig')
        bmethod = method.encode('ascii')
        func = getattr(orig, method)

        # No read limit. Call original function.
        if not remaining:
            result = func(size)
            obj._writelog(
                b'%s(%d) -> (%d) %s' % (bmethod, size, len(result), result)
            )
            return result

        origsize = size

        if size < 0:
            size = remaining
        else:
            size = min(remaining, size)

        result = func(size)
        remaining -= len(result)

        obj._writelog(
            b'%s(%d from %d) -> (%d) %s'
            % (bmethod, size, origsize, len(result), result)
        )

        self.remaining_recv_bytes = remaining

        if remaining <= 0:
            obj._writelog(b'read limit reached; closing socket')
            obj._cond_close()

            # This is the easiest way to abort the current request.
            raise Exception('connection closed after receiving N bytes')

        return result


# We can't adjust __class__ on a socket instance. So we define a proxy type.
class socketproxy(object):
    __slots__ = ('_orig', '_logfp', '_cond')

    def __init__(self, obj, logfp, condition_tracked):
        object.__setattr__(self, '_orig', obj)
        object.__setattr__(self, '_logfp', logfp)
        object.__setattr__(self, '_cond', condition_tracked)

    def __getattribute__(self, name):
        if name in ('makefile', 'sendall', '_writelog', '_cond_close'):
            return object.__getattribute__(self, name)

        return getattr(object.__getattribute__(self, '_orig'), name)

    def __delattr__(self, name):
        delattr(object.__getattribute__(self, '_orig'), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, '_orig'), name, value)

    def _writelog(self, msg):
        msg = msg.replace(b'\r', b'\\r').replace(b'\n', b'\\n')

        object.__getattribute__(self, '_logfp').write(msg)
        object.__getattribute__(self, '_logfp').write(b'\n')
        object.__getattribute__(self, '_logfp').flush()

    def makefile(self, mode, bufsize):
        f = object.__getattribute__(self, '_orig').makefile(mode, bufsize)

        logfp = object.__getattribute__(self, '_logfp')
        cond = object.__getattribute__(self, '_cond')

        return fileobjectproxy(f, logfp, cond)

    def sendall(self, data, flags=0):
        cond = object.__getattribute__(self, '_cond')
        return cond.forward_write(self, 'sendall', data, flags)

    def _cond_close(self):
        object.__getattribute__(self, '_orig').shutdown(socket.SHUT_RDWR)


# We can't adjust __class__ on socket._fileobject, so define a proxy.
class fileobjectproxy(object):
    __slots__ = ('_orig', '_logfp', '_cond')

    def __init__(self, obj, logfp, condition_tracked):
        object.__setattr__(self, '_orig', obj)
        object.__setattr__(self, '_logfp', logfp)
        object.__setattr__(self, '_cond', condition_tracked)

    def __getattribute__(self, name):
        if name in (
            '_close',
            'read',
            'readline',
            'write',
            '_writelog',
            '_cond_close',
        ):
            return object.__getattribute__(self, name)

        return getattr(object.__getattribute__(self, '_orig'), name)

    def __delattr__(self, name):
        delattr(object.__getattribute__(self, '_orig'), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, '_orig'), name, value)

    def _writelog(self, msg):
        msg = msg.replace(b'\r', b'\\r').replace(b'\n', b'\\n')

        object.__getattribute__(self, '_logfp').write(msg)
        object.__getattribute__(self, '_logfp').write(b'\n')
        object.__getattribute__(self, '_logfp').flush()

    def _close(self):
        # Python 3 uses an io.BufferedIO instance. Python 2 uses some file
        # object wrapper.
        if pycompat.ispy3:
            orig = object.__getattribute__(self, '_orig')

            if hasattr(orig, 'raw'):
                orig.raw._sock.shutdown(socket.SHUT_RDWR)
            else:
                self.close()
        else:
            self._sock.shutdown(socket.SHUT_RDWR)

    def read(self, size=-1):
        cond = object.__getattribute__(self, '_cond')
        return cond.forward_read(self, 'read', size)

    def readline(self, size=-1):
        cond = object.__getattribute__(self, '_cond')
        return cond.forward_read(self, 'readline', size)

    def write(self, data):
        cond = object.__getattribute__(self, '_cond')
        return cond.forward_write(self, 'write', data)

    def _cond_close(self):
        self._close()


def process_config(value):
    parts = value.split(b',')
    integers = [int(v) for v in parts if v]
    return [v if v else None for v in integers]


def extsetup(ui):
    # Change the base HTTP server class so various events can be performed.
    # See SocketServer.BaseServer for how the specially named methods work.
    class badserver(server.MercurialHTTPServer):
        def __init__(self, ui, *args, **kwargs):
            self._ui = ui
            super(badserver, self).__init__(ui, *args, **kwargs)

            all_recv_bytes = self._ui.config(
                b'badserver', b'close-after-recv-bytes'
            )
            all_recv_bytes = process_config(all_recv_bytes)
            all_send_bytes = self._ui.config(
                b'badserver', b'close-after-send-bytes'
            )
            all_send_bytes = process_config(all_send_bytes)
            self._cond = ConditionTracker(all_recv_bytes, all_send_bytes)

            # Need to inherit object so super() works.
            class badrequesthandler(self.RequestHandlerClass, object):
                def send_header(self, name, value):
                    # Make headers deterministic to facilitate testing.
                    if name.lower() == 'date':
                        value = 'Fri, 14 Apr 2017 00:00:00 GMT'
                    elif name.lower() == 'server':
                        value = 'badhttpserver'

                    return super(badrequesthandler, self).send_header(
                        name, value
                    )

            self.RequestHandlerClass = badrequesthandler

        # Called to accept() a pending socket.
        def get_request(self):
            if self._ui.configbool(b'badserver', b'close-before-accept'):
                self.socket.close()

                # Tells the server to stop processing more requests.
                self.__shutdown_request = True

                # Simulate failure to stop processing this request.
                raise socket.error('close before accept')

            if self._ui.configbool(b'badserver', b'close-after-accept'):
                request, client_address = super(badserver, self).get_request()
                request.close()
                raise socket.error('close after accept')

            return super(badserver, self).get_request()

        # Does heavy lifting of processing a request. Invokes
        # self.finish_request() which calls self.RequestHandlerClass() which
        # is a hgweb.server._httprequesthandler.
        def process_request(self, socket, address):
            # Wrap socket in a proxy if we need to count bytes.
            self._cond.start_next_request()

            if self._cond.might_close():
                socket = socketproxy(
                    socket, self.errorlog, condition_tracked=self._cond
                )

            return super(badserver, self).process_request(socket, address)

    server.MercurialHTTPServer = badserver
