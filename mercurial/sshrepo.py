# sshrepo.py - ssh repository proxy class for mercurial
#
# Copyright 2005, 2006 Matt Mackall <mpm@selenic.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from node import bin, hex
from i18n import _
import repo, util, error, encoding, wireproto
import re, urllib

class remotelock(object):
    def __init__(self, repo):
        self.repo = repo
    def release(self):
        self.repo.unlock()
        self.repo = None
    def __del__(self):
        if self.repo:
            self.release()

class sshrepository(wireproto.wirerepository):
    def __init__(self, ui, path, create=0):
        self._url = path
        self.ui = ui

        m = re.match(r'^ssh://(([^@]+)@)?([^:/]+)(:(\d+))?(/(.*))?$', path)
        if not m:
            self.abort(error.RepoError(_("couldn't parse location %s") % path))

        self.user = m.group(2)
        self.host = m.group(3)
        self.port = m.group(5)
        self.path = m.group(7) or "."

        sshcmd = self.ui.config("ui", "ssh", "ssh")
        remotecmd = self.ui.config("ui", "remotecmd", "hg")

        args = util.sshargs(sshcmd, self.host, self.user, self.port)

        if create:
            cmd = '%s %s "%s init %s"'
            cmd = cmd % (sshcmd, args, remotecmd, self.path)

            ui.note(_('running %s\n') % cmd)
            res = util.system(cmd)
            if res != 0:
                self.abort(error.RepoError(_("could not create remote repo")))

        self.validate_repo(ui, sshcmd, args, remotecmd)

    def url(self):
        return self._url

    def validate_repo(self, ui, sshcmd, args, remotecmd):
        # cleanup up previous run
        self.cleanup()

        cmd = '%s %s "%s -R %s serve --stdio"'
        cmd = cmd % (sshcmd, args, remotecmd, self.path)

        cmd = util.quotecommand(cmd)
        ui.note(_('running %s\n') % cmd)
        self.pipeo, self.pipei, self.pipee = util.popen3(cmd)

        # skip any noise generated by remote shell
        self.do_cmd("hello")
        r = self.do_cmd("between", pairs=("%s-%s" % ("0"*40, "0"*40)))
        lines = ["", "dummy"]
        max_noise = 500
        while lines[-1] and max_noise:
            l = r.readline()
            self.readerr()
            if lines[-1] == "1\n" and l == "\n":
                break
            if l:
                ui.debug("remote: ", l)
            lines.append(l)
            max_noise -= 1
        else:
            self.abort(error.RepoError(_("no suitable response from remote hg")))

        self.capabilities = set()
        for l in reversed(lines):
            if l.startswith("capabilities:"):
                self.capabilities.update(l[:-1].split(":")[1].split())
                break

    def readerr(self):
        while 1:
            size = util.fstat(self.pipee).st_size
            if size == 0:
                break
            l = self.pipee.readline()
            if not l:
                break
            self.ui.status(_("remote: "), l)

    def abort(self, exception):
        self.cleanup()
        raise exception

    def _abort(self, exception):
        self.cleanup()
        raise exception

    def cleanup(self):
        try:
            self.pipeo.close()
            self.pipei.close()
            # read the error descriptor until EOF
            for l in self.pipee:
                self.ui.status(_("remote: "), l)
            self.pipee.close()
        except:
            pass

    __del__ = cleanup

    def do_cmd(self, cmd, **args):
        self.ui.debug("sending %s command\n" % cmd)
        self.pipeo.write("%s\n" % cmd)
        for k, v in sorted(args.iteritems()):
            self.pipeo.write("%s %d\n" % (k, len(v)))
            self.pipeo.write(v)
        self.pipeo.flush()

        return self.pipei

    def call(self, cmd, **args):
        self.do_cmd(cmd, **args)
        return self._recv()

    def _call(self, cmd, **args):
        self.do_cmd(cmd, **args)
        return self._recv()

    def _recv(self):
        l = self.pipei.readline()
        self.readerr()
        try:
            l = int(l)
        except:
            self.abort(error.ResponseError(_("unexpected response:"), l))
        return self.pipei.read(l)

    def _send(self, data, flush=False):
        self.pipeo.write("%d\n" % len(data))
        if data:
            self.pipeo.write(data)
        if flush:
            self.pipeo.flush()
        self.readerr()

    def lock(self):
        self.call("lock")
        return remotelock(self)

    def unlock(self):
        self.call("unlock")

    def changegroup(self, nodes, kind):
        n = " ".join(map(hex, nodes))
        return self.do_cmd("changegroup", roots=n)

    def changegroupsubset(self, bases, heads, kind):
        self.requirecap('changegroupsubset', _('look up remote changes'))
        bases = " ".join(map(hex, bases))
        heads = " ".join(map(hex, heads))
        return self.do_cmd("changegroupsubset", bases=bases, heads=heads)

    def unbundle(self, cg, heads, source):
        '''Send cg (a readable file-like object representing the
        changegroup to push, typically a chunkbuffer object) to the
        remote server as a bundle. Return an integer indicating the
        result of the push (see localrepository.addchangegroup()).'''
        d = self.call("unbundle", heads=' '.join(map(hex, heads)))
        if d:
            # remote may send "unsynced changes"
            self.abort(error.RepoError(_("push refused: %s") % d))

        while 1:
            d = cg.read(4096)
            if not d:
                break
            self._send(d)

        self._send("", flush=True)

        r = self._recv()
        if r:
            # remote may send "unsynced changes"
            self.abort(error.RepoError(_("push failed: %s") % r))

        r = self._recv()
        try:
            return int(r)
        except:
            self.abort(error.ResponseError(_("unexpected response:"), r))

    def addchangegroup(self, cg, source, url):
        '''Send a changegroup to the remote server.  Return an integer
        similar to unbundle(). DEPRECATED, since it requires locking the
        remote.'''
        d = self.call("addchangegroup")
        if d:
            self.abort(error.RepoError(_("push refused: %s") % d))
        while 1:
            d = cg.read(4096)
            if not d:
                break
            self.pipeo.write(d)
            self.readerr()

        self.pipeo.flush()

        self.readerr()
        r = self._recv()
        if not r:
            return 1
        try:
            return int(r)
        except:
            self.abort(error.ResponseError(_("unexpected response:"), r))

    def stream_out(self):
        return self.do_cmd('stream_out')

instance = sshrepository
