# sshpeer.py - ssh repository proxy class for mercurial
#
# Copyright 2005, 2006 Matt Mackall <mpm@selenic.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from __future__ import absolute_import

import re
import uuid

from .i18n import _
from . import (
    error,
    pycompat,
    util,
    wireproto,
    wireprotoserver,
)

def _serverquote(s):
    """quote a string for the remote shell ... which we assume is sh"""
    if not s:
        return s
    if re.match('[a-zA-Z0-9@%_+=:,./-]*$', s):
        return s
    return "'%s'" % s.replace("'", "'\\''")

def _forwardoutput(ui, pipe):
    """display all data currently available on pipe as remote output.

    This is non blocking."""
    s = util.readpipe(pipe)
    if s:
        for l in s.splitlines():
            ui.status(_("remote: "), l, '\n')

class doublepipe(object):
    """Operate a side-channel pipe in addition of a main one

    The side-channel pipe contains server output to be forwarded to the user
    input. The double pipe will behave as the "main" pipe, but will ensure the
    content of the "side" pipe is properly processed while we wait for blocking
    call on the "main" pipe.

    If large amounts of data are read from "main", the forward will cease after
    the first bytes start to appear. This simplifies the implementation
    without affecting actual output of sshpeer too much as we rarely issue
    large read for data not yet emitted by the server.

    The main pipe is expected to be a 'bufferedinputpipe' from the util module
    that handle all the os specific bits. This class lives in this module
    because it focus on behavior specific to the ssh protocol."""

    def __init__(self, ui, main, side):
        self._ui = ui
        self._main = main
        self._side = side

    def _wait(self):
        """wait until some data are available on main or side

        return a pair of boolean (ismainready, issideready)

        (This will only wait for data if the setup is supported by `util.poll`)
        """
        if getattr(self._main, 'hasbuffer', False): # getattr for classic pipe
            return (True, True) # main has data, assume side is worth poking at.
        fds = [self._main.fileno(), self._side.fileno()]
        try:
            act = util.poll(fds)
        except NotImplementedError:
            # non supported yet case, assume all have data.
            act = fds
        return (self._main.fileno() in act, self._side.fileno() in act)

    def write(self, data):
        return self._call('write', data)

    def read(self, size):
        r = self._call('read', size)
        if size != 0 and not r:
            # We've observed a condition that indicates the
            # stdout closed unexpectedly. Check stderr one
            # more time and snag anything that's there before
            # letting anyone know the main part of the pipe
            # closed prematurely.
            _forwardoutput(self._ui, self._side)
        return r

    def readline(self):
        return self._call('readline')

    def _call(self, methname, data=None):
        """call <methname> on "main", forward output of "side" while blocking
        """
        # data can be '' or 0
        if (data is not None and not data) or self._main.closed:
            _forwardoutput(self._ui, self._side)
            return ''
        while True:
            mainready, sideready = self._wait()
            if sideready:
                _forwardoutput(self._ui, self._side)
            if mainready:
                meth = getattr(self._main, methname)
                if data is None:
                    return meth()
                else:
                    return meth(data)

    def close(self):
        return self._main.close()

    def flush(self):
        return self._main.flush()

def _cleanuppipes(ui, pipei, pipeo, pipee):
    """Clean up pipes used by an SSH connection."""
    if pipeo:
        pipeo.close()
    if pipei:
        pipei.close()

    if pipee:
        # Try to read from the err descriptor until EOF.
        try:
            for l in pipee:
                ui.status(_('remote: '), l)
        except (IOError, ValueError):
            pass

        pipee.close()

def _makeconnection(ui, sshcmd, args, remotecmd, path, sshenv=None):
    """Create an SSH connection to a server.

    Returns a tuple of (process, stdin, stdout, stderr) for the
    spawned process.
    """
    cmd = '%s %s %s' % (
        sshcmd,
        args,
        util.shellquote('%s -R %s serve --stdio' % (
            _serverquote(remotecmd), _serverquote(path))))

    ui.debug('running %s\n' % cmd)
    cmd = util.quotecommand(cmd)

    # no buffer allow the use of 'select'
    # feel free to remove buffering and select usage when we ultimately
    # move to threading.
    stdin, stdout, stderr, proc = util.popen4(cmd, bufsize=0, env=sshenv)

    stdout = doublepipe(ui, util.bufferedinputpipe(stdout), stderr)
    stdin = doublepipe(ui, stdin, stderr)

    return proc, stdin, stdout, stderr

def _performhandshake(ui, stdin, stdout, stderr):
    def badresponse():
        msg = _('no suitable response from remote hg')
        hint = ui.config('ui', 'ssherrorhint')
        raise error.RepoError(msg, hint=hint)

    # The handshake consists of sending wire protocol commands in reverse
    # order of protocol implementation and then sniffing for a response
    # to one of them.
    #
    # Those commands (from oldest to newest) are:
    #
    # ``between``
    #   Asks for the set of revisions between a pair of revisions. Command
    #   present in all Mercurial server implementations.
    #
    # ``hello``
    #   Instructs the server to advertise its capabilities. Introduced in
    #   Mercurial 0.9.1.
    #
    # ``upgrade``
    #   Requests upgrade from default transport protocol version 1 to
    #   a newer version. Introduced in Mercurial 4.6 as an experimental
    #   feature.
    #
    # The ``between`` command is issued with a request for the null
    # range. If the remote is a Mercurial server, this request will
    # generate a specific response: ``1\n\n``. This represents the
    # wire protocol encoded value for ``\n``. We look for ``1\n\n``
    # in the output stream and know this is the response to ``between``
    # and we're at the end of our handshake reply.
    #
    # The response to the ``hello`` command will be a line with the
    # length of the value returned by that command followed by that
    # value. If the server doesn't support ``hello`` (which should be
    # rare), that line will be ``0\n``. Otherwise, the value will contain
    # RFC 822 like lines. Of these, the ``capabilities:`` line contains
    # the capabilities of the server.
    #
    # The ``upgrade`` command isn't really a command in the traditional
    # sense of version 1 of the transport because it isn't using the
    # proper mechanism for formatting insteads: instead, it just encodes
    # arguments on the line, delimited by spaces.
    #
    # The ``upgrade`` line looks like ``upgrade <token> <capabilities>``.
    # If the server doesn't support protocol upgrades, it will reply to
    # this line with ``0\n``. Otherwise, it emits an
    # ``upgraded <token> <protocol>`` line to both stdout and stderr.
    # Content immediately following this line describes additional
    # protocol and server state.
    #
    # In addition to the responses to our command requests, the server
    # may emit "banner" output on stdout. SSH servers are allowed to
    # print messages to stdout on login. Issuing commands on connection
    # allows us to flush this banner output from the server by scanning
    # for output to our well-known ``between`` command. Of course, if
    # the banner contains ``1\n\n``, this will throw off our detection.

    requestlog = ui.configbool('devel', 'debug.peer-request')

    # Generate a random token to help identify responses to version 2
    # upgrade request.
    token = pycompat.sysbytes(str(uuid.uuid4()))
    upgradecaps = [
        ('proto', wireprotoserver.SSHV2),
    ]
    upgradecaps = util.urlreq.urlencode(upgradecaps)

    try:
        pairsarg = '%s-%s' % ('0' * 40, '0' * 40)
        handshake = [
            'hello\n',
            'between\n',
            'pairs %d\n' % len(pairsarg),
            pairsarg,
        ]

        # Request upgrade to version 2 if configured.
        if ui.configbool('experimental', 'sshpeer.advertise-v2'):
            ui.debug('sending upgrade request: %s %s\n' % (token, upgradecaps))
            handshake.insert(0, 'upgrade %s %s\n' % (token, upgradecaps))

        if requestlog:
            ui.debug('devel-peer-request: hello\n')
        ui.debug('sending hello command\n')
        if requestlog:
            ui.debug('devel-peer-request: between\n')
            ui.debug('devel-peer-request:   pairs: %d bytes\n' % len(pairsarg))
        ui.debug('sending between command\n')

        stdin.write(''.join(handshake))
        stdin.flush()
    except IOError:
        badresponse()

    # Assume version 1 of wire protocol by default.
    protoname = wireprotoserver.SSHV1
    reupgraded = re.compile(b'^upgraded %s (.*)$' % re.escape(token))

    lines = ['', 'dummy']
    max_noise = 500
    while lines[-1] and max_noise:
        try:
            l = stdout.readline()
            _forwardoutput(ui, stderr)

            # Look for reply to protocol upgrade request. It has a token
            # in it, so there should be no false positives.
            m = reupgraded.match(l)
            if m:
                protoname = m.group(1)
                ui.debug('protocol upgraded to %s\n' % protoname)
                # If an upgrade was handled, the ``hello`` and ``between``
                # requests are ignored. The next output belongs to the
                # protocol, so stop scanning lines.
                break

            # Otherwise it could be a banner, ``0\n`` response if server
            # doesn't support upgrade.

            if lines[-1] == '1\n' and l == '\n':
                break
            if l:
                ui.debug('remote: ', l)
            lines.append(l)
            max_noise -= 1
        except IOError:
            badresponse()
    else:
        badresponse()

    caps = set()

    # For version 1, we should see a ``capabilities`` line in response to the
    # ``hello`` command.
    if protoname == wireprotoserver.SSHV1:
        for l in reversed(lines):
            # Look for response to ``hello`` command. Scan from the back so
            # we don't misinterpret banner output as the command reply.
            if l.startswith('capabilities:'):
                caps.update(l[:-1].split(':')[1].split())
                break
    elif protoname == wireprotoserver.SSHV2:
        # We see a line with number of bytes to follow and then a value
        # looking like ``capabilities: *``.
        line = stdout.readline()
        try:
            valuelen = int(line)
        except ValueError:
            badresponse()

        capsline = stdout.read(valuelen)
        if not capsline.startswith('capabilities: '):
            badresponse()

        ui.debug('remote: %s\n' % capsline)

        caps.update(capsline.split(':')[1].split())
        # Trailing newline.
        stdout.read(1)

    # Error if we couldn't find capabilities, this means:
    #
    # 1. Remote isn't a Mercurial server
    # 2. Remote is a <0.9.1 Mercurial server
    # 3. Remote is a future Mercurial server that dropped ``hello``
    #    and other attempted handshake mechanisms.
    if not caps:
        badresponse()

    return protoname, caps

class sshv1peer(wireproto.wirepeer):
    def __init__(self, ui, url, proc, stdin, stdout, stderr, caps):
        """Create a peer from an existing SSH connection.

        ``proc`` is a handle on the underlying SSH process.
        ``stdin``, ``stdout``, and ``stderr`` are handles on the stdio
        pipes for that process.
        ``caps`` is a set of capabilities supported by the remote.
        """
        self._url = url
        self._ui = ui
        # self._subprocess is unused. Keeping a handle on the process
        # holds a reference and prevents it from being garbage collected.
        self._subprocess = proc
        self._pipeo = stdin
        self._pipei = stdout
        self._pipee = stderr
        self._caps = caps

    # Begin of _basepeer interface.

    @util.propertycache
    def ui(self):
        return self._ui

    def url(self):
        return self._url

    def local(self):
        return None

    def peer(self):
        return self

    def canpush(self):
        return True

    def close(self):
        pass

    # End of _basepeer interface.

    # Begin of _basewirecommands interface.

    def capabilities(self):
        return self._caps

    # End of _basewirecommands interface.

    def _readerr(self):
        _forwardoutput(self.ui, self._pipee)

    def _abort(self, exception):
        self._cleanup()
        raise exception

    def _cleanup(self):
        _cleanuppipes(self.ui, self._pipei, self._pipeo, self._pipee)

    __del__ = _cleanup

    def _submitbatch(self, req):
        rsp = self._callstream("batch", cmds=wireproto.encodebatchcmds(req))
        available = self._getamount()
        # TODO this response parsing is probably suboptimal for large
        # batches with large responses.
        toread = min(available, 1024)
        work = rsp.read(toread)
        available -= toread
        chunk = work
        while chunk:
            while ';' in work:
                one, work = work.split(';', 1)
                yield wireproto.unescapearg(one)
            toread = min(available, 1024)
            chunk = rsp.read(toread)
            available -= toread
            work += chunk
        yield wireproto.unescapearg(work)

    def _callstream(self, cmd, **args):
        args = pycompat.byteskwargs(args)
        if (self.ui.debugflag
            and self.ui.configbool('devel', 'debug.peer-request')):
            dbg = self.ui.debug
            line = 'devel-peer-request: %s\n'
            dbg(line % cmd)
            for key, value in sorted(args.items()):
                if not isinstance(value, dict):
                    dbg(line % '  %s: %d bytes' % (key, len(value)))
                else:
                    for dk, dv in sorted(value.items()):
                        dbg(line % '  %s-%s: %d' % (key, dk, len(dv)))
        self.ui.debug("sending %s command\n" % cmd)
        self._pipeo.write("%s\n" % cmd)
        _func, names = wireproto.commands[cmd]
        keys = names.split()
        wireargs = {}
        for k in keys:
            if k == '*':
                wireargs['*'] = args
                break
            else:
                wireargs[k] = args[k]
                del args[k]
        for k, v in sorted(wireargs.iteritems()):
            self._pipeo.write("%s %d\n" % (k, len(v)))
            if isinstance(v, dict):
                for dk, dv in v.iteritems():
                    self._pipeo.write("%s %d\n" % (dk, len(dv)))
                    self._pipeo.write(dv)
            else:
                self._pipeo.write(v)
        self._pipeo.flush()

        return self._pipei

    def _callcompressable(self, cmd, **args):
        return self._callstream(cmd, **args)

    def _call(self, cmd, **args):
        self._callstream(cmd, **args)
        return self._recv()

    def _callpush(self, cmd, fp, **args):
        r = self._call(cmd, **args)
        if r:
            return '', r
        for d in iter(lambda: fp.read(4096), ''):
            self._send(d)
        self._send("", flush=True)
        r = self._recv()
        if r:
            return '', r
        return self._recv(), ''

    def _calltwowaystream(self, cmd, fp, **args):
        r = self._call(cmd, **args)
        if r:
            # XXX needs to be made better
            raise error.Abort(_('unexpected remote reply: %s') % r)
        for d in iter(lambda: fp.read(4096), ''):
            self._send(d)
        self._send("", flush=True)
        return self._pipei

    def _getamount(self):
        l = self._pipei.readline()
        if l == '\n':
            self._readerr()
            msg = _('check previous remote output')
            self._abort(error.OutOfBandError(hint=msg))
        self._readerr()
        try:
            return int(l)
        except ValueError:
            self._abort(error.ResponseError(_("unexpected response:"), l))

    def _recv(self):
        return self._pipei.read(self._getamount())

    def _send(self, data, flush=False):
        self._pipeo.write("%d\n" % len(data))
        if data:
            self._pipeo.write(data)
        if flush:
            self._pipeo.flush()
        self._readerr()

class sshv2peer(sshv1peer):
    """A peer that speakers version 2 of the transport protocol."""
    # Currently version 2 is identical to version 1 post handshake.
    # And handshake is performed before the peer is instantiated. So
    # we need no custom code.

def instance(ui, path, create):
    """Create an SSH peer.

    The returned object conforms to the ``wireproto.wirepeer`` interface.
    """
    u = util.url(path, parsequery=False, parsefragment=False)
    if u.scheme != 'ssh' or not u.host or u.path is None:
        raise error.RepoError(_("couldn't parse location %s") % path)

    util.checksafessh(path)

    if u.passwd is not None:
        raise error.RepoError(_('password in URL not supported'))

    sshcmd = ui.config('ui', 'ssh')
    remotecmd = ui.config('ui', 'remotecmd')
    sshaddenv = dict(ui.configitems('sshenv'))
    sshenv = util.shellenviron(sshaddenv)
    remotepath = u.path or '.'

    args = util.sshargs(sshcmd, u.host, u.user, u.port)

    if create:
        cmd = '%s %s %s' % (sshcmd, args,
            util.shellquote('%s init %s' %
                (_serverquote(remotecmd), _serverquote(remotepath))))
        ui.debug('running %s\n' % cmd)
        res = ui.system(cmd, blockedtag='sshpeer', environ=sshenv)
        if res != 0:
            raise error.RepoError(_('could not create remote repo'))

    proc, stdin, stdout, stderr = _makeconnection(ui, sshcmd, args, remotecmd,
                                                  remotepath, sshenv)

    try:
        protoname, caps = _performhandshake(ui, stdin, stdout, stderr)
    except Exception:
        _cleanuppipes(ui, stdout, stdin, stderr)
        raise

    if protoname == wireprotoserver.SSHV1:
        return sshv1peer(ui, path, proc, stdin, stdout, stderr, caps)
    elif protoname == wireprotoserver.SSHV2:
        return sshv2peer(ui, path, proc, stdin, stdout, stderr, caps)
    else:
        _cleanuppipes(ui, stdout, stdin, stderr)
        raise error.RepoError(_('unknown version of SSH protocol: %s') %
                              protoname)
