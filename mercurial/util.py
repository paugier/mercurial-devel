# util.py - Mercurial utility functions and platform specfic implementations
#
#  Copyright 2005 K. Thananchayan <thananck@yahoo.com>
#  Copyright 2005-2007 Matt Mackall <mpm@selenic.com>
#  Copyright 2006 Vadim Gelfer <vadim.gelfer@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

"""Mercurial utility functions and platform specfic implementations.

This contains helper routines that are independent of the SCM core and
hide platform-specific details from the core.
"""

from i18n import _
import error, osutil, encoding
import errno, re, shutil, sys, tempfile, traceback
import os, time, calendar, textwrap, unicodedata, signal
import imp, socket, urllib

# Python compatibility

def sha1(s):
    return _fastsha1(s)

def _fastsha1(s):
    # This function will import sha1 from hashlib or sha (whichever is
    # available) and overwrite itself with it on the first call.
    # Subsequent calls will go directly to the imported function.
    if sys.version_info >= (2, 5):
        from hashlib import sha1 as _sha1
    else:
        from sha import sha as _sha1
    global _fastsha1, sha1
    _fastsha1 = sha1 = _sha1
    return _sha1(s)

import __builtin__

if sys.version_info[0] < 3:
    def fakebuffer(sliceable, offset=0):
        return sliceable[offset:]
else:
    def fakebuffer(sliceable, offset=0):
        return memoryview(sliceable)[offset:]
try:
    buffer
except NameError:
    __builtin__.buffer = fakebuffer

import subprocess
closefds = os.name == 'posix'

def popen2(cmd, env=None, newlines=False):
    # Setting bufsize to -1 lets the system decide the buffer size.
    # The default for bufsize is 0, meaning unbuffered. This leads to
    # poor performance on Mac OS X: http://bugs.python.org/issue4194
    p = subprocess.Popen(cmd, shell=True, bufsize=-1,
                         close_fds=closefds,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         universal_newlines=newlines,
                         env=env)
    return p.stdin, p.stdout

def popen3(cmd, env=None, newlines=False):
    p = subprocess.Popen(cmd, shell=True, bufsize=-1,
                         close_fds=closefds,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         universal_newlines=newlines,
                         env=env)
    return p.stdin, p.stdout, p.stderr

def version():
    """Return version information if available."""
    try:
        import __version__
        return __version__.version
    except ImportError:
        return 'unknown'

# used by parsedate
defaultdateformats = (
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d %I:%M:%S%p',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d %I:%M%p',
    '%Y-%m-%d',
    '%m-%d',
    '%m/%d',
    '%m/%d/%y',
    '%m/%d/%Y',
    '%a %b %d %H:%M:%S %Y',
    '%a %b %d %I:%M:%S%p %Y',
    '%a, %d %b %Y %H:%M:%S',        #  GNU coreutils "/bin/date --rfc-2822"
    '%b %d %H:%M:%S %Y',
    '%b %d %I:%M:%S%p %Y',
    '%b %d %H:%M:%S',
    '%b %d %I:%M:%S%p',
    '%b %d %H:%M',
    '%b %d %I:%M%p',
    '%b %d %Y',
    '%b %d',
    '%H:%M:%S',
    '%I:%M:%S%p',
    '%H:%M',
    '%I:%M%p',
)

extendeddateformats = defaultdateformats + (
    "%Y",
    "%Y-%m",
    "%b",
    "%b %Y",
    )

def cachefunc(func):
    '''cache the result of function calls'''
    # XXX doesn't handle keywords args
    cache = {}
    if func.func_code.co_argcount == 1:
        # we gain a small amount of time because
        # we don't need to pack/unpack the list
        def f(arg):
            if arg not in cache:
                cache[arg] = func(arg)
            return cache[arg]
    else:
        def f(*args):
            if args not in cache:
                cache[args] = func(*args)
            return cache[args]

    return f

def lrucachefunc(func):
    '''cache most recent results of function calls'''
    cache = {}
    order = []
    if func.func_code.co_argcount == 1:
        def f(arg):
            if arg not in cache:
                if len(cache) > 20:
                    del cache[order.pop(0)]
                cache[arg] = func(arg)
            else:
                order.remove(arg)
            order.append(arg)
            return cache[arg]
    else:
        def f(*args):
            if args not in cache:
                if len(cache) > 20:
                    del cache[order.pop(0)]
                cache[args] = func(*args)
            else:
                order.remove(args)
            order.append(args)
            return cache[args]

    return f

class propertycache(object):
    def __init__(self, func):
        self.func = func
        self.name = func.__name__
    def __get__(self, obj, type=None):
        result = self.func(obj)
        setattr(obj, self.name, result)
        return result

def pipefilter(s, cmd):
    '''filter string S through command CMD, returning its output'''
    p = subprocess.Popen(cmd, shell=True, close_fds=closefds,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    pout, perr = p.communicate(s)
    return pout

def tempfilter(s, cmd):
    '''filter string S through a pair of temporary files with CMD.
    CMD is used as a template to create the real command to be run,
    with the strings INFILE and OUTFILE replaced by the real names of
    the temporary files generated.'''
    inname, outname = None, None
    try:
        infd, inname = tempfile.mkstemp(prefix='hg-filter-in-')
        fp = os.fdopen(infd, 'wb')
        fp.write(s)
        fp.close()
        outfd, outname = tempfile.mkstemp(prefix='hg-filter-out-')
        os.close(outfd)
        cmd = cmd.replace('INFILE', inname)
        cmd = cmd.replace('OUTFILE', outname)
        code = os.system(cmd)
        if sys.platform == 'OpenVMS' and code & 1:
            code = 0
        if code:
            raise Abort(_("command '%s' failed: %s") %
                        (cmd, explainexit(code)))
        fp = open(outname, 'rb')
        r = fp.read()
        fp.close()
        return r
    finally:
        try:
            if inname:
                os.unlink(inname)
        except OSError:
            pass
        try:
            if outname:
                os.unlink(outname)
        except OSError:
            pass

filtertable = {
    'tempfile:': tempfilter,
    'pipe:': pipefilter,
    }

def filter(s, cmd):
    "filter a string through a command that transforms its input to its output"
    for name, fn in filtertable.iteritems():
        if cmd.startswith(name):
            return fn(s, cmd[len(name):].lstrip())
    return pipefilter(s, cmd)

def binary(s):
    """return true if a string is binary data"""
    return bool(s and '\0' in s)

def increasingchunks(source, min=1024, max=65536):
    '''return no less than min bytes per chunk while data remains,
    doubling min after each chunk until it reaches max'''
    def log2(x):
        if not x:
            return 0
        i = 0
        while x:
            x >>= 1
            i += 1
        return i - 1

    buf = []
    blen = 0
    for chunk in source:
        buf.append(chunk)
        blen += len(chunk)
        if blen >= min:
            if min < max:
                min = min << 1
                nmin = 1 << log2(blen)
                if nmin > min:
                    min = nmin
                if min > max:
                    min = max
            yield ''.join(buf)
            blen = 0
            buf = []
    if buf:
        yield ''.join(buf)

Abort = error.Abort

def always(fn):
    return True

def never(fn):
    return False

def pathto(root, n1, n2):
    '''return the relative path from one place to another.
    root should use os.sep to separate directories
    n1 should use os.sep to separate directories
    n2 should use "/" to separate directories
    returns an os.sep-separated path.

    If n1 is a relative path, it's assumed it's
    relative to root.
    n2 should always be relative to root.
    '''
    if not n1:
        return localpath(n2)
    if os.path.isabs(n1):
        if os.path.splitdrive(root)[0] != os.path.splitdrive(n1)[0]:
            return os.path.join(root, localpath(n2))
        n2 = '/'.join((pconvert(root), n2))
    a, b = splitpath(n1), n2.split('/')
    a.reverse()
    b.reverse()
    while a and b and a[-1] == b[-1]:
        a.pop()
        b.pop()
    b.reverse()
    return os.sep.join((['..'] * len(a)) + b) or '.'

_hgexecutable = None

def mainfrozen():
    """return True if we are a frozen executable.

    The code supports py2exe (most common, Windows only) and tools/freeze
    (portable, not much used).
    """
    return (hasattr(sys, "frozen") or # new py2exe
            hasattr(sys, "importers") or # old py2exe
            imp.is_frozen("__main__")) # tools/freeze

def hgexecutable():
    """return location of the 'hg' executable.

    Defaults to $HG or 'hg' in the search path.
    """
    if _hgexecutable is None:
        hg = os.environ.get('HG')
        if hg:
            _sethgexecutable(hg)
        elif mainfrozen():
            _sethgexecutable(sys.executable)
        else:
            exe = findexe('hg') or os.path.basename(sys.argv[0])
            _sethgexecutable(exe)
    return _hgexecutable

def _sethgexecutable(path):
    """set location of the 'hg' executable"""
    global _hgexecutable
    _hgexecutable = path

def system(cmd, environ={}, cwd=None, onerr=None, errprefix=None, out=None):
    '''enhanced shell command execution.
    run with environment maybe modified, maybe in different dir.

    if command fails and onerr is None, return status.  if ui object,
    print error message and return status, else raise onerr object as
    exception.

    if out is specified, it is assumed to be a file-like object that has a
    write() method. stdout and stderr will be redirected to out.'''
    try:
        sys.stdout.flush()
    except Exception:
        pass
    def py2shell(val):
        'convert python object into string that is useful to shell'
        if val is None or val is False:
            return '0'
        if val is True:
            return '1'
        return str(val)
    origcmd = cmd
    cmd = quotecommand(cmd)
    env = dict(os.environ)
    env.update((k, py2shell(v)) for k, v in environ.iteritems())
    env['HG'] = hgexecutable()
    if out is None or out == sys.__stdout__:
        rc = subprocess.call(cmd, shell=True, close_fds=closefds,
                             env=env, cwd=cwd)
    else:
        proc = subprocess.Popen(cmd, shell=True, close_fds=closefds,
                                env=env, cwd=cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        for line in proc.stdout:
            out.write(line)
        proc.wait()
        rc = proc.returncode
    if sys.platform == 'OpenVMS' and rc & 1:
        rc = 0
    if rc and onerr:
        errmsg = '%s %s' % (os.path.basename(origcmd.split(None, 1)[0]),
                            explainexit(rc)[0])
        if errprefix:
            errmsg = '%s: %s' % (errprefix, errmsg)
        try:
            onerr.warn(errmsg + '\n')
        except AttributeError:
            raise onerr(errmsg)
    return rc

def checksignature(func):
    '''wrap a function with code to check for calling errors'''
    def check(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except TypeError:
            if len(traceback.extract_tb(sys.exc_info()[2])) == 1:
                raise error.SignatureError
            raise

    return check

def makedir(path, notindexed):
    os.mkdir(path)

def unlinkpath(f):
    """unlink and remove the directory if it is empty"""
    os.unlink(f)
    # try removing directories that might now be empty
    try:
        os.removedirs(os.path.dirname(f))
    except OSError:
        pass

def copyfile(src, dest):
    "copy a file, preserving mode and atime/mtime"
    if os.path.islink(src):
        try:
            os.unlink(dest)
        except OSError:
            pass
        os.symlink(os.readlink(src), dest)
    else:
        try:
            shutil.copyfile(src, dest)
            shutil.copymode(src, dest)
        except shutil.Error, inst:
            raise Abort(str(inst))

def copyfiles(src, dst, hardlink=None):
    """Copy a directory tree using hardlinks if possible"""

    if hardlink is None:
        hardlink = (os.stat(src).st_dev ==
                    os.stat(os.path.dirname(dst)).st_dev)

    num = 0
    if os.path.isdir(src):
        os.mkdir(dst)
        for name, kind in osutil.listdir(src):
            srcname = os.path.join(src, name)
            dstname = os.path.join(dst, name)
            hardlink, n = copyfiles(srcname, dstname, hardlink)
            num += n
    else:
        if hardlink:
            try:
                oslink(src, dst)
            except (IOError, OSError):
                hardlink = False
                shutil.copy(src, dst)
        else:
            shutil.copy(src, dst)
        num += 1

    return hardlink, num

_winreservednames = '''con prn aux nul
    com1 com2 com3 com4 com5 com6 com7 com8 com9
    lpt1 lpt2 lpt3 lpt4 lpt5 lpt6 lpt7 lpt8 lpt9'''.split()
_winreservedchars = ':*?"<>|'
def checkwinfilename(path):
    '''Check that the base-relative path is a valid filename on Windows.
    Returns None if the path is ok, or a UI string describing the problem.

    >>> checkwinfilename("just/a/normal/path")
    >>> checkwinfilename("foo/bar/con.xml")
    "filename contains 'con', which is reserved on Windows"
    >>> checkwinfilename("foo/con.xml/bar")
    "filename contains 'con', which is reserved on Windows"
    >>> checkwinfilename("foo/bar/xml.con")
    >>> checkwinfilename("foo/bar/AUX/bla.txt")
    "filename contains 'AUX', which is reserved on Windows"
    >>> checkwinfilename("foo/bar/bla:.txt")
    "filename contains ':', which is reserved on Windows"
    >>> checkwinfilename("foo/bar/b\07la.txt")
    "filename contains '\\\\x07', which is invalid on Windows"
    >>> checkwinfilename("foo/bar/bla ")
    "filename ends with ' ', which is not allowed on Windows"
    '''
    for n in path.replace('\\', '/').split('/'):
        if not n:
            continue
        for c in n:
            if c in _winreservedchars:
                return _("filename contains '%s', which is reserved "
                         "on Windows") % c
            if ord(c) <= 31:
                return _("filename contains %r, which is invalid "
                         "on Windows") % c
        base = n.split('.')[0]
        if base and base.lower() in _winreservednames:
            return _("filename contains '%s', which is reserved "
                     "on Windows") % base
        t = n[-1]
        if t in '. ':
            return _("filename ends with '%s', which is not allowed "
                     "on Windows") % t

def lookupreg(key, name=None, scope=None):
    return None

def hidewindow():
    """Hide current shell window.

    Used to hide the window opened when starting asynchronous
    child process under Windows, unneeded on other systems.
    """
    pass

if os.name == 'nt':
    checkosfilename = checkwinfilename
    from windows import *
else:
    from posix import *

def makelock(info, pathname):
    try:
        return os.symlink(info, pathname)
    except OSError, why:
        if why.errno == errno.EEXIST:
            raise
    except AttributeError: # no symlink in os
        pass

    ld = os.open(pathname, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
    os.write(ld, info)
    os.close(ld)

def readlock(pathname):
    try:
        return os.readlink(pathname)
    except OSError, why:
        if why.errno not in (errno.EINVAL, errno.ENOSYS):
            raise
    except AttributeError: # no symlink in os
        pass
    fp = posixfile(pathname)
    r = fp.read()
    fp.close()
    return r

def fstat(fp):
    '''stat file object that may not have fileno method.'''
    try:
        return os.fstat(fp.fileno())
    except AttributeError:
        return os.stat(fp.name)

# File system features

def checkcase(path):
    """
    Check whether the given path is on a case-sensitive filesystem

    Requires a path (like /foo/.hg) ending with a foldable final
    directory component.
    """
    s1 = os.stat(path)
    d, b = os.path.split(path)
    p2 = os.path.join(d, b.upper())
    if path == p2:
        p2 = os.path.join(d, b.lower())
    try:
        s2 = os.stat(p2)
        if s2 == s1:
            return False
        return True
    except OSError:
        return True

_fspathcache = {}
def fspath(name, root):
    '''Get name in the case stored in the filesystem

    The name is either relative to root, or it is an absolute path starting
    with root. Note that this function is unnecessary, and should not be
    called, for case-sensitive filesystems (simply because it's expensive).
    '''
    # If name is absolute, make it relative
    if name.lower().startswith(root.lower()):
        l = len(root)
        if name[l] == os.sep or name[l] == os.altsep:
            l = l + 1
        name = name[l:]

    if not os.path.lexists(os.path.join(root, name)):
        return None

    seps = os.sep
    if os.altsep:
        seps = seps + os.altsep
    # Protect backslashes. This gets silly very quickly.
    seps.replace('\\','\\\\')
    pattern = re.compile(r'([^%s]+)|([%s]+)' % (seps, seps))
    dir = os.path.normcase(os.path.normpath(root))
    result = []
    for part, sep in pattern.findall(name):
        if sep:
            result.append(sep)
            continue

        if dir not in _fspathcache:
            _fspathcache[dir] = os.listdir(dir)
        contents = _fspathcache[dir]

        lpart = part.lower()
        lenp = len(part)
        for n in contents:
            if lenp == len(n) and n.lower() == lpart:
                result.append(n)
                break
        else:
            # Cannot happen, as the file exists!
            result.append(part)
        dir = os.path.join(dir, lpart)

    return ''.join(result)

def checknlink(testfile):
    '''check whether hardlink count reporting works properly'''

    # testfile may be open, so we need a separate file for checking to
    # work around issue2543 (or testfile may get lost on Samba shares)
    f1 = testfile + ".hgtmp1"
    if os.path.lexists(f1):
        return False
    try:
        posixfile(f1, 'w').close()
    except IOError:
        return False

    f2 = testfile + ".hgtmp2"
    fd = None
    try:
        try:
            oslink(f1, f2)
        except OSError:
            return False

        # nlinks() may behave differently for files on Windows shares if
        # the file is open.
        fd = posixfile(f2)
        return nlinks(f2) > 1
    finally:
        if fd is not None:
            fd.close()
        for f in (f1, f2):
            try:
                os.unlink(f)
            except OSError:
                pass

    return False

def endswithsep(path):
    '''Check path ends with os.sep or os.altsep.'''
    return path.endswith(os.sep) or os.altsep and path.endswith(os.altsep)

def splitpath(path):
    '''Split path by os.sep.
    Note that this function does not use os.altsep because this is
    an alternative of simple "xxx.split(os.sep)".
    It is recommended to use os.path.normpath() before using this
    function if need.'''
    return path.split(os.sep)

def gui():
    '''Are we running in a GUI?'''
    if sys.platform == 'darwin':
        if 'SSH_CONNECTION' in os.environ:
            # handle SSH access to a box where the user is logged in
            return False
        elif getattr(osutil, 'isgui', None):
            # check if a CoreGraphics session is available
            return osutil.isgui()
        else:
            # pure build; use a safe default
            return True
    else:
        return os.name == "nt" or os.environ.get("DISPLAY")

def mktempcopy(name, emptyok=False, createmode=None):
    """Create a temporary file with the same contents from name

    The permission bits are copied from the original file.

    If the temporary file is going to be truncated immediately, you
    can use emptyok=True as an optimization.

    Returns the name of the temporary file.
    """
    d, fn = os.path.split(name)
    fd, temp = tempfile.mkstemp(prefix='.%s-' % fn, dir=d)
    os.close(fd)
    # Temporary files are created with mode 0600, which is usually not
    # what we want.  If the original file already exists, just copy
    # its mode.  Otherwise, manually obey umask.
    try:
        st_mode = os.lstat(name).st_mode & 0777
    except OSError, inst:
        if inst.errno != errno.ENOENT:
            raise
        st_mode = createmode
        if st_mode is None:
            st_mode = ~umask
        st_mode &= 0666
    os.chmod(temp, st_mode)
    if emptyok:
        return temp
    try:
        try:
            ifp = posixfile(name, "rb")
        except IOError, inst:
            if inst.errno == errno.ENOENT:
                return temp
            if not getattr(inst, 'filename', None):
                inst.filename = name
            raise
        ofp = posixfile(temp, "wb")
        for chunk in filechunkiter(ifp):
            ofp.write(chunk)
        ifp.close()
        ofp.close()
    except:
        try: os.unlink(temp)
        except: pass
        raise
    return temp

class atomictempfile(object):
    '''writeable file object that atomically updates a file

    All writes will go to a temporary copy of the original file. Call
    rename() when you are done writing, and atomictempfile will rename
    the temporary copy to the original name, making the changes visible.

    Unlike other file-like objects, close() discards your writes by
    simply deleting the temporary file.
    '''
    def __init__(self, name, mode='w+b', createmode=None):
        self.__name = name      # permanent name
        self._tempname = mktempcopy(name, emptyok=('w' in mode),
                                    createmode=createmode)
        self._fp = posixfile(self._tempname, mode)

        # delegated methods
        self.write = self._fp.write
        self.fileno = self._fp.fileno

    def rename(self):
        if not self._fp.closed:
            self._fp.close()
            rename(self._tempname, localpath(self.__name))

    def close(self):
        if not self._fp.closed:
            try:
                os.unlink(self._tempname)
            except OSError:
                pass
            self._fp.close()

    def __del__(self):
        if hasattr(self, '_fp'): # constructor actually did something
            self.close()

def makedirs(name, mode=None):
    """recursive directory creation with parent mode inheritance"""
    parent = os.path.abspath(os.path.dirname(name))
    try:
        os.mkdir(name)
        if mode is not None:
            os.chmod(name, mode)
        return
    except OSError, err:
        if err.errno == errno.EEXIST:
            return
        if not name or parent == name or err.errno != errno.ENOENT:
            raise
    makedirs(parent, mode)
    makedirs(name, mode)

def readfile(path):
    fp = open(path, 'rb')
    try:
        return fp.read()
    finally:
        fp.close()

def writefile(path, text):
    fp = open(path, 'wb')
    try:
        fp.write(text)
    finally:
        fp.close()

def appendfile(path, text):
    fp = open(path, 'ab')
    try:
        fp.write(text)
    finally:
        fp.close()

class chunkbuffer(object):
    """Allow arbitrary sized chunks of data to be efficiently read from an
    iterator over chunks of arbitrary size."""

    def __init__(self, in_iter):
        """in_iter is the iterator that's iterating over the input chunks.
        targetsize is how big a buffer to try to maintain."""
        def splitbig(chunks):
            for chunk in chunks:
                if len(chunk) > 2**20:
                    pos = 0
                    while pos < len(chunk):
                        end = pos + 2 ** 18
                        yield chunk[pos:end]
                        pos = end
                else:
                    yield chunk
        self.iter = splitbig(in_iter)
        self._queue = []

    def read(self, l):
        """Read L bytes of data from the iterator of chunks of data.
        Returns less than L bytes if the iterator runs dry."""
        left = l
        buf = ''
        queue = self._queue
        while left > 0:
            # refill the queue
            if not queue:
                target = 2**18
                for chunk in self.iter:
                    queue.append(chunk)
                    target -= len(chunk)
                    if target <= 0:
                        break
                if not queue:
                    break

            chunk = queue.pop(0)
            left -= len(chunk)
            if left < 0:
                queue.insert(0, chunk[left:])
                buf += chunk[:left]
            else:
                buf += chunk

        return buf

def filechunkiter(f, size=65536, limit=None):
    """Create a generator that produces the data in the file size
    (default 65536) bytes at a time, up to optional limit (default is
    to read all data).  Chunks may be less than size bytes if the
    chunk is the last chunk in the file, or the file is a socket or
    some other type of file that sometimes reads less data than is
    requested."""
    assert size >= 0
    assert limit is None or limit >= 0
    while True:
        if limit is None:
            nbytes = size
        else:
            nbytes = min(limit, size)
        s = nbytes and f.read(nbytes)
        if not s:
            break
        if limit:
            limit -= len(s)
        yield s

def makedate():
    lt = time.localtime()
    if lt[8] == 1 and time.daylight:
        tz = time.altzone
    else:
        tz = time.timezone
    t = time.mktime(lt)
    if t < 0:
        hint = _("check your clock")
        raise Abort(_("negative timestamp: %d") % t, hint=hint)
    return t, tz

def datestr(date=None, format='%a %b %d %H:%M:%S %Y %1%2'):
    """represent a (unixtime, offset) tuple as a localized time.
    unixtime is seconds since the epoch, and offset is the time zone's
    number of seconds away from UTC. if timezone is false, do not
    append time zone to string."""
    t, tz = date or makedate()
    if t < 0:
        t = 0   # time.gmtime(lt) fails on Windows for lt < -43200
        tz = 0
    if "%1" in format or "%2" in format:
        sign = (tz > 0) and "-" or "+"
        minutes = abs(tz) // 60
        format = format.replace("%1", "%c%02d" % (sign, minutes // 60))
        format = format.replace("%2", "%02d" % (minutes % 60))
    s = time.strftime(format, time.gmtime(float(t) - tz))
    return s

def shortdate(date=None):
    """turn (timestamp, tzoff) tuple into iso 8631 date."""
    return datestr(date, format='%Y-%m-%d')

def strdate(string, format, defaults=[]):
    """parse a localized time string and return a (unixtime, offset) tuple.
    if the string cannot be parsed, ValueError is raised."""
    def timezone(string):
        tz = string.split()[-1]
        if tz[0] in "+-" and len(tz) == 5 and tz[1:].isdigit():
            sign = (tz[0] == "+") and 1 or -1
            hours = int(tz[1:3])
            minutes = int(tz[3:5])
            return -sign * (hours * 60 + minutes) * 60
        if tz == "GMT" or tz == "UTC":
            return 0
        return None

    # NOTE: unixtime = localunixtime + offset
    offset, date = timezone(string), string
    if offset is not None:
        date = " ".join(string.split()[:-1])

    # add missing elements from defaults
    usenow = False # default to using biased defaults
    for part in ("S", "M", "HI", "d", "mb", "yY"): # decreasing specificity
        found = [True for p in part if ("%"+p) in format]
        if not found:
            date += "@" + defaults[part][usenow]
            format += "@%" + part[0]
        else:
            # We've found a specific time element, less specific time
            # elements are relative to today
            usenow = True

    timetuple = time.strptime(date, format)
    localunixtime = int(calendar.timegm(timetuple))
    if offset is None:
        # local timezone
        unixtime = int(time.mktime(timetuple))
        offset = unixtime - localunixtime
    else:
        unixtime = localunixtime + offset
    return unixtime, offset

def parsedate(date, formats=None, bias={}):
    """parse a localized date/time and return a (unixtime, offset) tuple.

    The date may be a "unixtime offset" string or in one of the specified
    formats. If the date already is a (unixtime, offset) tuple, it is returned.
    """
    if not date:
        return 0, 0
    if isinstance(date, tuple) and len(date) == 2:
        return date
    if not formats:
        formats = defaultdateformats
    date = date.strip()
    try:
        when, offset = map(int, date.split(' '))
    except ValueError:
        # fill out defaults
        now = makedate()
        defaults = {}
        for part in ("d", "mb", "yY", "HI", "M", "S"):
            # this piece is for rounding the specific end of unknowns
            b = bias.get(part)
            if b is None:
                if part[0] in "HMS":
                    b = "00"
                else:
                    b = "0"

            # this piece is for matching the generic end to today's date
            n = datestr(now, "%" + part[0])

            defaults[part] = (b, n)

        for format in formats:
            try:
                when, offset = strdate(date, format, defaults)
            except (ValueError, OverflowError):
                pass
            else:
                break
        else:
            raise Abort(_('invalid date: %r') % date)
    # validate explicit (probably user-specified) date and
    # time zone offset. values must fit in signed 32 bits for
    # current 32-bit linux runtimes. timezones go from UTC-12
    # to UTC+14
    if abs(when) > 0x7fffffff:
        raise Abort(_('date exceeds 32 bits: %d') % when)
    if when < 0:
        raise Abort(_('negative date value: %d') % when)
    if offset < -50400 or offset > 43200:
        raise Abort(_('impossible time zone offset: %d') % offset)
    return when, offset

def matchdate(date):
    """Return a function that matches a given date match specifier

    Formats include:

    '{date}' match a given date to the accuracy provided

    '<{date}' on or before a given date

    '>{date}' on or after a given date

    >>> p1 = parsedate("10:29:59")
    >>> p2 = parsedate("10:30:00")
    >>> p3 = parsedate("10:30:59")
    >>> p4 = parsedate("10:31:00")
    >>> p5 = parsedate("Sep 15 10:30:00 1999")
    >>> f = matchdate("10:30")
    >>> f(p1[0])
    False
    >>> f(p2[0])
    True
    >>> f(p3[0])
    True
    >>> f(p4[0])
    False
    >>> f(p5[0])
    False
    """

    def lower(date):
        d = dict(mb="1", d="1")
        return parsedate(date, extendeddateformats, d)[0]

    def upper(date):
        d = dict(mb="12", HI="23", M="59", S="59")
        for days in ("31", "30", "29"):
            try:
                d["d"] = days
                return parsedate(date, extendeddateformats, d)[0]
            except:
                pass
        d["d"] = "28"
        return parsedate(date, extendeddateformats, d)[0]

    date = date.strip()

    if not date:
        raise Abort(_("dates cannot consist entirely of whitespace"))
    elif date[0] == "<":
        if not date[1:]:
            raise Abort(_("invalid day spec, use '<DATE'"))
        when = upper(date[1:])
        return lambda x: x <= when
    elif date[0] == ">":
        if not date[1:]:
            raise Abort(_("invalid day spec, use '>DATE'"))
        when = lower(date[1:])
        return lambda x: x >= when
    elif date[0] == "-":
        try:
            days = int(date[1:])
        except ValueError:
            raise Abort(_("invalid day spec: %s") % date[1:])
        if days < 0:
            raise Abort(_("%s must be nonnegative (see 'hg help dates')")
                % date[1:])
        when = makedate()[0] - days * 3600 * 24
        return lambda x: x >= when
    elif " to " in date:
        a, b = date.split(" to ")
        start, stop = lower(a), upper(b)
        return lambda x: x >= start and x <= stop
    else:
        start, stop = lower(date), upper(date)
        return lambda x: x >= start and x <= stop

def shortuser(user):
    """Return a short representation of a user name or email address."""
    f = user.find('@')
    if f >= 0:
        user = user[:f]
    f = user.find('<')
    if f >= 0:
        user = user[f + 1:]
    f = user.find(' ')
    if f >= 0:
        user = user[:f]
    f = user.find('.')
    if f >= 0:
        user = user[:f]
    return user

def email(author):
    '''get email of author.'''
    r = author.find('>')
    if r == -1:
        r = None
    return author[author.find('<') + 1:r]

def _ellipsis(text, maxlength):
    if len(text) <= maxlength:
        return text, False
    else:
        return "%s..." % (text[:maxlength - 3]), True

def ellipsis(text, maxlength=400):
    """Trim string to at most maxlength (default: 400) characters."""
    try:
        # use unicode not to split at intermediate multi-byte sequence
        utext, truncated = _ellipsis(text.decode(encoding.encoding),
                                     maxlength)
        if not truncated:
            return text
        return utext.encode(encoding.encoding)
    except (UnicodeDecodeError, UnicodeEncodeError):
        return _ellipsis(text, maxlength)[0]

def bytecount(nbytes):
    '''return byte count formatted as readable string, with units'''

    units = (
        (100, 1 << 30, _('%.0f GB')),
        (10, 1 << 30, _('%.1f GB')),
        (1, 1 << 30, _('%.2f GB')),
        (100, 1 << 20, _('%.0f MB')),
        (10, 1 << 20, _('%.1f MB')),
        (1, 1 << 20, _('%.2f MB')),
        (100, 1 << 10, _('%.0f KB')),
        (10, 1 << 10, _('%.1f KB')),
        (1, 1 << 10, _('%.2f KB')),
        (1, 1, _('%.0f bytes')),
        )

    for multiplier, divisor, format in units:
        if nbytes >= divisor * multiplier:
            return format % (nbytes / float(divisor))
    return units[-1][2] % nbytes

def uirepr(s):
    # Avoid double backslash in Windows path repr()
    return repr(s).replace('\\\\', '\\')

# delay import of textwrap
def MBTextWrapper(**kwargs):
    class tw(textwrap.TextWrapper):
        """
        Extend TextWrapper for double-width characters.

        Some Asian characters use two terminal columns instead of one.
        A good example of this behavior can be seen with u'\u65e5\u672c',
        the two Japanese characters for "Japan":
        len() returns 2, but when printed to a terminal, they eat 4 columns.

        (Note that this has nothing to do whatsoever with unicode
        representation, or encoding of the underlying string)
        """
        def __init__(self, **kwargs):
            textwrap.TextWrapper.__init__(self, **kwargs)

        def _cutdown(self, str, space_left):
            l = 0
            ucstr = unicode(str, encoding.encoding)
            colwidth = unicodedata.east_asian_width
            for i in xrange(len(ucstr)):
                l += colwidth(ucstr[i]) in 'WFA' and 2 or 1
                if space_left < l:
                    return (ucstr[:i].encode(encoding.encoding),
                            ucstr[i:].encode(encoding.encoding))
            return str, ''

        # overriding of base class
        def _handle_long_word(self, reversed_chunks, cur_line, cur_len, width):
            space_left = max(width - cur_len, 1)

            if self.break_long_words:
                cut, res = self._cutdown(reversed_chunks[-1], space_left)
                cur_line.append(cut)
                reversed_chunks[-1] = res
            elif not cur_line:
                cur_line.append(reversed_chunks.pop())

    global MBTextWrapper
    MBTextWrapper = tw
    return tw(**kwargs)

def wrap(line, width, initindent='', hangindent=''):
    maxindent = max(len(hangindent), len(initindent))
    if width <= maxindent:
        # adjust for weird terminal size
        width = max(78, maxindent + 1)
    wrapper = MBTextWrapper(width=width,
                            initial_indent=initindent,
                            subsequent_indent=hangindent)
    return wrapper.fill(line)

def iterlines(iterator):
    for chunk in iterator:
        for line in chunk.splitlines():
            yield line

def expandpath(path):
    return os.path.expanduser(os.path.expandvars(path))

def hgcmd():
    """Return the command used to execute current hg

    This is different from hgexecutable() because on Windows we want
    to avoid things opening new shell windows like batch files, so we
    get either the python call or current executable.
    """
    if mainfrozen():
        return [sys.executable]
    return gethgcmd()

def rundetached(args, condfn):
    """Execute the argument list in a detached process.

    condfn is a callable which is called repeatedly and should return
    True once the child process is known to have started successfully.
    At this point, the child process PID is returned. If the child
    process fails to start or finishes before condfn() evaluates to
    True, return -1.
    """
    # Windows case is easier because the child process is either
    # successfully starting and validating the condition or exiting
    # on failure. We just poll on its PID. On Unix, if the child
    # process fails to start, it will be left in a zombie state until
    # the parent wait on it, which we cannot do since we expect a long
    # running process on success. Instead we listen for SIGCHLD telling
    # us our child process terminated.
    terminated = set()
    def handler(signum, frame):
        terminated.add(os.wait())
    prevhandler = None
    if hasattr(signal, 'SIGCHLD'):
        prevhandler = signal.signal(signal.SIGCHLD, handler)
    try:
        pid = spawndetached(args)
        while not condfn():
            if ((pid in terminated or not testpid(pid))
                and not condfn()):
                return -1
            time.sleep(0.1)
        return pid
    finally:
        if prevhandler is not None:
            signal.signal(signal.SIGCHLD, prevhandler)

try:
    any, all = any, all
except NameError:
    def any(iterable):
        for i in iterable:
            if i:
                return True
        return False

    def all(iterable):
        for i in iterable:
            if not i:
                return False
        return True

def interpolate(prefix, mapping, s, fn=None, escape_prefix=False):
    """Return the result of interpolating items in the mapping into string s.

    prefix is a single character string, or a two character string with
    a backslash as the first character if the prefix needs to be escaped in
    a regular expression.

    fn is an optional function that will be applied to the replacement text
    just before replacement.

    escape_prefix is an optional flag that allows using doubled prefix for
    its escaping.
    """
    fn = fn or (lambda s: s)
    patterns = '|'.join(mapping.keys())
    if escape_prefix:
        patterns += '|' + prefix
        if len(prefix) > 1:
            prefix_char = prefix[1:]
        else:
            prefix_char = prefix
        mapping[prefix_char] = prefix_char
    r = re.compile(r'%s(%s)' % (prefix, patterns))
    return r.sub(lambda x: fn(mapping[x.group()[1:]]), s)

def getport(port):
    """Return the port for a given network service.

    If port is an integer, it's returned as is. If it's a string, it's
    looked up using socket.getservbyname(). If there's no matching
    service, util.Abort is raised.
    """
    try:
        return int(port)
    except ValueError:
        pass

    try:
        return socket.getservbyname(port)
    except socket.error:
        raise Abort(_("no port number associated with service '%s'") % port)

_booleans = {'1': True, 'yes': True, 'true': True, 'on': True, 'always': True,
             '0': False, 'no': False, 'false': False, 'off': False,
             'never': False}

def parsebool(s):
    """Parse s into a boolean.

    If s is not a valid boolean, returns None.
    """
    return _booleans.get(s.lower(), None)

_hexdig = '0123456789ABCDEFabcdef'
_hextochr = dict((a + b, chr(int(a + b, 16)))
                 for a in _hexdig for b in _hexdig)

def _urlunquote(s):
    """unquote('abc%20def') -> 'abc def'."""
    res = s.split('%')
    # fastpath
    if len(res) == 1:
        return s
    s = res[0]
    for item in res[1:]:
        try:
            s += _hextochr[item[:2]] + item[2:]
        except KeyError:
            s += '%' + item
        except UnicodeDecodeError:
            s += unichr(int(item[:2], 16)) + item[2:]
    return s

class url(object):
    r"""Reliable URL parser.

    This parses URLs and provides attributes for the following
    components:

    <scheme>://<user>:<passwd>@<host>:<port>/<path>?<query>#<fragment>

    Missing components are set to None. The only exception is
    fragment, which is set to '' if present but empty.

    If parsefragment is False, fragment is included in query. If
    parsequery is False, query is included in path. If both are
    False, both fragment and query are included in path.

    See http://www.ietf.org/rfc/rfc2396.txt for more information.

    Note that for backward compatibility reasons, bundle URLs do not
    take host names. That means 'bundle://../' has a path of '../'.

    Examples:

    >>> url('http://www.ietf.org/rfc/rfc2396.txt')
    <url scheme: 'http', host: 'www.ietf.org', path: 'rfc/rfc2396.txt'>
    >>> url('ssh://[::1]:2200//home/joe/repo')
    <url scheme: 'ssh', host: '[::1]', port: '2200', path: '/home/joe/repo'>
    >>> url('file:///home/joe/repo')
    <url scheme: 'file', path: '/home/joe/repo'>
    >>> url('file:///c:/temp/foo/')
    <url scheme: 'file', path: 'c:/temp/foo/'>
    >>> url('bundle:foo')
    <url scheme: 'bundle', path: 'foo'>
    >>> url('bundle://../foo')
    <url scheme: 'bundle', path: '../foo'>
    >>> url(r'c:\foo\bar')
    <url path: 'c:\\foo\\bar'>
    >>> url(r'\\blah\blah\blah')
    <url path: '\\\\blah\\blah\\blah'>

    Authentication credentials:

    >>> url('ssh://joe:xyz@x/repo')
    <url scheme: 'ssh', user: 'joe', passwd: 'xyz', host: 'x', path: 'repo'>
    >>> url('ssh://joe@x/repo')
    <url scheme: 'ssh', user: 'joe', host: 'x', path: 'repo'>

    Query strings and fragments:

    >>> url('http://host/a?b#c')
    <url scheme: 'http', host: 'host', path: 'a', query: 'b', fragment: 'c'>
    >>> url('http://host/a?b#c', parsequery=False, parsefragment=False)
    <url scheme: 'http', host: 'host', path: 'a?b#c'>
    """

    _safechars = "!~*'()+"
    _safepchars = "/!~*'()+"
    _matchscheme = re.compile(r'^[a-zA-Z0-9+.\-]+:').match

    def __init__(self, path, parsequery=True, parsefragment=True):
        # We slowly chomp away at path until we have only the path left
        self.scheme = self.user = self.passwd = self.host = None
        self.port = self.path = self.query = self.fragment = None
        self._localpath = True
        self._hostport = ''
        self._origpath = path

        # special case for Windows drive letters and UNC paths
        if hasdriveletter(path) or path.startswith(r'\\'):
            self.path = path
            return

        # For compatibility reasons, we can't handle bundle paths as
        # normal URLS
        if path.startswith('bundle:'):
            self.scheme = 'bundle'
            path = path[7:]
            if path.startswith('//'):
                path = path[2:]
            self.path = path
            return

        if self._matchscheme(path):
            parts = path.split(':', 1)
            if parts[0]:
                self.scheme, path = parts
                self._localpath = False

        if not path:
            path = None
            if self._localpath:
                self.path = ''
                return
        else:
            if parsefragment and '#' in path:
                path, self.fragment = path.split('#', 1)
                if not path:
                    path = None
            if self._localpath:
                self.path = path
                return

            if parsequery and '?' in path:
                path, self.query = path.split('?', 1)
                if not path:
                    path = None
                if not self.query:
                    self.query = None

            # // is required to specify a host/authority
            if path and path.startswith('//'):
                parts = path[2:].split('/', 1)
                if len(parts) > 1:
                    self.host, path = parts
                    path = path
                else:
                    self.host = parts[0]
                    path = None
                if not self.host:
                    self.host = None
                    # path of file:///d is /d
                    # path of file:///d:/ is d:/, not /d:/
                    if path and not hasdriveletter(path):
                        path = '/' + path

            if self.host and '@' in self.host:
                self.user, self.host = self.host.rsplit('@', 1)
                if ':' in self.user:
                    self.user, self.passwd = self.user.split(':', 1)
                if not self.host:
                    self.host = None

            # Don't split on colons in IPv6 addresses without ports
            if (self.host and ':' in self.host and
                not (self.host.startswith('[') and self.host.endswith(']'))):
                self._hostport = self.host
                self.host, self.port = self.host.rsplit(':', 1)
                if not self.host:
                    self.host = None

            if (self.host and self.scheme == 'file' and
                self.host not in ('localhost', '127.0.0.1', '[::1]')):
                raise Abort(_('file:// URLs can only refer to localhost'))

        self.path = path

        # leave the query string escaped
        for a in ('user', 'passwd', 'host', 'port',
                  'path', 'fragment'):
            v = getattr(self, a)
            if v is not None:
                setattr(self, a, _urlunquote(v))

    def __repr__(self):
        attrs = []
        for a in ('scheme', 'user', 'passwd', 'host', 'port', 'path',
                  'query', 'fragment'):
            v = getattr(self, a)
            if v is not None:
                attrs.append('%s: %r' % (a, v))
        return '<url %s>' % ', '.join(attrs)

    def __str__(self):
        r"""Join the URL's components back into a URL string.

        Examples:

        >>> str(url('http://user:pw@host:80/?foo#bar'))
        'http://user:pw@host:80/?foo#bar'
        >>> str(url('http://user:pw@host:80/?foo=bar&baz=42'))
        'http://user:pw@host:80/?foo=bar&baz=42'
        >>> str(url('http://user:pw@host:80/?foo=bar%3dbaz'))
        'http://user:pw@host:80/?foo=bar%3dbaz'
        >>> str(url('ssh://user:pw@[::1]:2200//home/joe#'))
        'ssh://user:pw@[::1]:2200//home/joe#'
        >>> str(url('http://localhost:80//'))
        'http://localhost:80//'
        >>> str(url('http://localhost:80/'))
        'http://localhost:80/'
        >>> str(url('http://localhost:80'))
        'http://localhost:80/'
        >>> str(url('bundle:foo'))
        'bundle:foo'
        >>> str(url('bundle://../foo'))
        'bundle:../foo'
        >>> str(url('path'))
        'path'
        >>> str(url('file:///tmp/foo/bar'))
        'file:///tmp/foo/bar'
        >>> print url(r'bundle:foo\bar')
        bundle:foo\bar
        """
        if self._localpath:
            s = self.path
            if self.scheme == 'bundle':
                s = 'bundle:' + s
            if self.fragment:
                s += '#' + self.fragment
            return s

        s = self.scheme + ':'
        if self.user or self.passwd or self.host:
            s += '//'
        elif self.scheme and (not self.path or self.path.startswith('/')):
            s += '//'
        if self.user:
            s += urllib.quote(self.user, safe=self._safechars)
        if self.passwd:
            s += ':' + urllib.quote(self.passwd, safe=self._safechars)
        if self.user or self.passwd:
            s += '@'
        if self.host:
            if not (self.host.startswith('[') and self.host.endswith(']')):
                s += urllib.quote(self.host)
            else:
                s += self.host
        if self.port:
            s += ':' + urllib.quote(self.port)
        if self.host:
            s += '/'
        if self.path:
            # TODO: similar to the query string, we should not unescape the
            # path when we store it, the path might contain '%2f' = '/',
            # which we should *not* escape.
            s += urllib.quote(self.path, safe=self._safepchars)
        if self.query:
            # we store the query in escaped form.
            s += '?' + self.query
        if self.fragment is not None:
            s += '#' + urllib.quote(self.fragment, safe=self._safepchars)
        return s

    def authinfo(self):
        user, passwd = self.user, self.passwd
        try:
            self.user, self.passwd = None, None
            s = str(self)
        finally:
            self.user, self.passwd = user, passwd
        if not self.user:
            return (s, None)
        return (s, (None, (str(self), self.host),
                    self.user, self.passwd or ''))

    def isabs(self):
        if self.scheme and self.scheme != 'file':
            return True # remote URL
        if hasdriveletter(self.path):
            return True # absolute for our purposes - can't be joined()
        if self.path.startswith(r'\\'):
            return True # Windows UNC path
        if self.path.startswith('/'):
            return True # POSIX-style
        return False

    def localpath(self):
        if self.scheme == 'file' or self.scheme == 'bundle':
            path = self.path or '/'
            # For Windows, we need to promote hosts containing drive
            # letters to paths with drive letters.
            if hasdriveletter(self._hostport):
                path = self._hostport + '/' + self.path
            elif self.host is not None and self.path:
                path = '/' + path
            return path
        return self._origpath

def hasscheme(path):
    return bool(url(path).scheme)

def hasdriveletter(path):
    return path[1:2] == ':' and path[0:1].isalpha()

def urllocalpath(path):
    return url(path, parsequery=False, parsefragment=False).localpath()

def hidepassword(u):
    '''hide user credential in a url string'''
    u = url(u)
    if u.passwd:
        u.passwd = '***'
    return str(u)

def removeauth(u):
    '''remove all authentication information from a url string'''
    u = url(u)
    u.user = u.passwd = None
    return str(u)

def isatty(fd):
    try:
        return fd.isatty()
    except AttributeError:
        return False
