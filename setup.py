#
# This is the mercurial setup script.
#
# 'python setup.py install', or
# 'python setup.py --help' for more options
import os

# Mercurial can't work on 3.6.0 or 3.6.1 due to a bug in % formatting
# in bytestrings.
supportedpy = ','.join(
    [
        '>=3.6.2',
    ]
)

import sys, platform
import sysconfig


def sysstr(s):
    return s.decode('latin-1')


def eprint(*args, **kwargs):
    kwargs['file'] = sys.stderr
    print(*args, **kwargs)


import ssl

# ssl.HAS_TLSv1* are preferred to check support but they were added in Python
# 3.7. Prior to CPython commit 6e8cda91d92da72800d891b2fc2073ecbc134d98
# (backported to the 3.7 branch), ssl.PROTOCOL_TLSv1_1 / ssl.PROTOCOL_TLSv1_2
# were defined only if compiled against a OpenSSL version with TLS 1.1 / 1.2
# support. At the mentioned commit, they were unconditionally defined.
_notset = object()
has_tlsv1_1 = getattr(ssl, 'HAS_TLSv1_1', _notset)
if has_tlsv1_1 is _notset:
    has_tlsv1_1 = getattr(ssl, 'PROTOCOL_TLSv1_1', _notset) is not _notset
has_tlsv1_2 = getattr(ssl, 'HAS_TLSv1_2', _notset)
if has_tlsv1_2 is _notset:
    has_tlsv1_2 = getattr(ssl, 'PROTOCOL_TLSv1_2', _notset) is not _notset
if not (has_tlsv1_1 or has_tlsv1_2):
    error = """
The `ssl` module does not advertise support for TLS 1.1 or TLS 1.2.
Please make sure that your Python installation was compiled against an OpenSSL
version enabling these features (likely this requires the OpenSSL version to
be at least 1.0.1).
"""
    print(error, file=sys.stderr)
    sys.exit(1)

DYLIB_SUFFIX = sysconfig.get_config_vars()['EXT_SUFFIX']

# Solaris Python packaging brain damage
try:
    import hashlib

    sha = hashlib.sha1()
except ImportError:
    try:
        import sha

        sha.sha  # silence unused import warning
    except ImportError:
        raise SystemExit(
            "Couldn't import standard hashlib (incomplete Python install)."
        )

try:
    import zlib

    zlib.compressobj  # silence unused import warning
except ImportError:
    raise SystemExit(
        "Couldn't import standard zlib (incomplete Python install)."
    )

# The base IronPython distribution (as of 2.7.1) doesn't support bz2
isironpython = False
try:
    isironpython = (
        platform.python_implementation().lower().find("ironpython") != -1
    )
except AttributeError:
    pass

if isironpython:
    sys.stderr.write("warning: IronPython detected (no bz2 support)\n")
else:
    try:
        import bz2

        bz2.BZ2Compressor  # silence unused import warning
    except ImportError:
        raise SystemExit(
            "Couldn't import standard bz2 (incomplete Python install)."
        )

ispypy = "PyPy" in sys.version

import ctypes
import stat, subprocess, time
import re
import shutil
import tempfile

# We have issues with setuptools on some platforms and builders. Until
# those are resolved, setuptools is opt-in except for platforms where
# we don't have issues.
issetuptools = os.name == 'nt' or 'FORCE_SETUPTOOLS' in os.environ
if issetuptools:
    from setuptools import setup
else:
    try:
        from distutils.core import setup
    except ModuleNotFoundError:
        from setuptools import setup
from distutils.ccompiler import new_compiler
from distutils.core import Command, Extension
from distutils.dist import Distribution
from distutils.command.build import build
from distutils.command.build_ext import build_ext
from distutils.command.build_py import build_py
from distutils.command.build_scripts import build_scripts
from distutils.command.install import install
from distutils.command.install_lib import install_lib
from distutils.command.install_scripts import install_scripts
from distutils import log
from distutils.spawn import spawn, find_executable
from distutils import file_util
from distutils.errors import (
    CCompilerError,
    DistutilsError,
    DistutilsExecError,
)
from distutils.sysconfig import get_python_inc


def write_if_changed(path, content):
    """Write content to a file iff the content hasn't changed."""
    if os.path.exists(path):
        with open(path, 'rb') as fh:
            current = fh.read()
    else:
        current = b''

    if current != content:
        with open(path, 'wb') as fh:
            fh.write(content)


scripts = ['hg']
if os.name == 'nt':
    # We remove hg.bat if we are able to build hg.exe.
    scripts.append('contrib/win32/hg.bat')


def cancompile(cc, code):
    tmpdir = tempfile.mkdtemp(prefix='hg-install-')
    devnull = oldstderr = None
    try:
        fname = os.path.join(tmpdir, 'testcomp.c')
        f = open(fname, 'w')
        f.write(code)
        f.close()
        # Redirect stderr to /dev/null to hide any error messages
        # from the compiler.
        # This will have to be changed if we ever have to check
        # for a function on Windows.
        devnull = open('/dev/null', 'w')
        oldstderr = os.dup(sys.stderr.fileno())
        os.dup2(devnull.fileno(), sys.stderr.fileno())
        objects = cc.compile([fname], output_dir=tmpdir)
        cc.link_executable(objects, os.path.join(tmpdir, "a.out"))
        return True
    except Exception:
        return False
    finally:
        if oldstderr is not None:
            os.dup2(oldstderr, sys.stderr.fileno())
        if devnull is not None:
            devnull.close()
        shutil.rmtree(tmpdir)


# simplified version of distutils.ccompiler.CCompiler.has_function
# that actually removes its temporary files.
def hasfunction(cc, funcname):
    code = 'int main(void) { %s(); }\n' % funcname
    return cancompile(cc, code)


def hasheader(cc, headername):
    code = '#include <%s>\nint main(void) { return 0; }\n' % headername
    return cancompile(cc, code)


# py2exe needs to be installed to work
try:
    import py2exe

    py2exe.patch_distutils()
    py2exeloaded = True
    # import py2exe's patched Distribution class
    from distutils.core import Distribution
except ImportError:
    py2exeloaded = False


def runcmd(cmd, env, cwd=None):
    p = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd
    )
    out, err = p.communicate()
    return p.returncode, out, err


class hgcommand:
    def __init__(self, cmd, env):
        self.cmd = cmd
        self.env = env

    def __repr__(self):
        return f"<hgcommand cmd={self.cmd} env={self.env}>"

    def run(self, args):
        cmd = self.cmd + args
        returncode, out, err = runcmd(cmd, self.env)
        err = filterhgerr(err)
        if err:
            print("stderr from '%s':" % (' '.join(cmd)), file=sys.stderr)
            print(err, file=sys.stderr)
        if returncode != 0:
            print(
                "non zero-return '%s': %d" % (' '.join(cmd), returncode),
                file=sys.stderr,
            )
            return b''
        return out


def filterhgerr(err):
    # If root is executing setup.py, but the repository is owned by
    # another user (as in "sudo python setup.py install") we will get
    # trust warnings since the .hg/hgrc file is untrusted. That is
    # fine, we don't want to load it anyway.  Python may warn about
    # a missing __init__.py in mercurial/locale, we also ignore that.
    err = [
        e
        for e in err.splitlines()
        if (
            not e.startswith(b'not trusting file')
            and not e.startswith(b'warning: Not importing')
            and not (
                e.startswith(b'obsolete feature not enabled')
                or e.startswith(b'"obsolete" feature not enabled')
            )
            and not e.startswith(b'*** failed to import extension')
            and not e.startswith(b'devel-warn:')
            and not (
                e.startswith(b'(third party extension')
                and e.endswith(b'or newer of Mercurial; disabling)')
            )
        )
    ]
    return b'\n'.join(b'  ' + e for e in err)


def findhg():
    """Try to figure out how we should invoke hg for examining the local
    repository contents.

    Returns an hgcommand object."""
    # By default, prefer the "hg" command in the user's path.  This was
    # presumably the hg command that the user used to create this repository.
    #
    # This repository may require extensions or other settings that would not
    # be enabled by running the hg script directly from this local repository.
    hgenv = os.environ.copy()
    # Use HGPLAIN to disable hgrc settings that would change output formatting,
    # and disable localization for the same reasons.
    hgenv['HGPLAIN'] = '1'
    hgenv['LANGUAGE'] = 'C'
    hgcmd = ['hg']
    # Run a simple "hg log" command just to see if using hg from the user's
    # path works and can successfully interact with this repository.  Windows
    # gives precedence to hg.exe in the current directory, so fall back to the
    # python invocation of local hg, where pythonXY.dll can always be found.
    check_cmd = ['log', '-r.', '-Ttest']
    attempts = []

    def attempt(cmd, env):
        try:
            retcode, out, err = runcmd(hgcmd + check_cmd, hgenv)
            res = (True, retcode, out, err)
            if retcode == 0 and not filterhgerr(err):
                return True
        except EnvironmentError as e:
            res = (False, e)
        attempts.append((cmd, res))
        return False

    if os.name != 'nt' or not os.path.exists("hg.exe"):
        if attempt(hgcmd + check_cmd, hgenv):
            return hgcommand(hgcmd, hgenv)

    # Fall back to trying the local hg installation (pure python)
    repo_hg = os.path.join(os.path.dirname(__file__), 'hg')
    hgenv = localhgenv()
    hgcmd = [sys.executable, repo_hg]
    if attempt(hgcmd + check_cmd, hgenv):
        return hgcommand(hgcmd, hgenv)
    # Fall back to trying the local hg installation (whatever we can)
    hgenv = localhgenv(pure_python=False)
    hgcmd = [sys.executable, repo_hg]
    if attempt(hgcmd + check_cmd, hgenv):
        return hgcommand(hgcmd, hgenv)

    eprint("/!\\")
    eprint(r"/!\ Unable to find a working hg binary")
    eprint(r"/!\ Version cannot be extracted from the repository")
    eprint(r"/!\ Re-run the setup once a first version is built")
    eprint(r"/!\ Attempts:")
    for i, e in enumerate(attempts):
        eprint(r"/!\   attempt #%d:" % (i))
        eprint(r"/!\     cmd:        ", e[0])
        res = e[1]
        if res[0]:
            eprint(r"/!\     return code:", res[1])
            eprint("/!\\     std output:\n%s" % (res[2].decode()), end="")
            eprint("/!\\     std error:\n%s" % (res[3].decode()), end="")
        else:
            eprint(r"/!\     exception:  ", res[1])
    return None


def localhgenv(pure_python=True):
    """Get an environment dictionary to use for invoking or importing
    mercurial from the local repository."""
    # Execute hg out of this directory with a custom environment which takes
    # care to not use any hgrc files and do no localization.
    env = {
        'HGRCPATH': '',
        'LANGUAGE': 'C',
        'PATH': '',
    }  # make pypi modules that use os.environ['PATH'] happy
    if pure_python:
        env['HGMODULEPOLICY'] = 'py'
    if 'LD_LIBRARY_PATH' in os.environ:
        env['LD_LIBRARY_PATH'] = os.environ['LD_LIBRARY_PATH']
    if 'SystemRoot' in os.environ:
        # SystemRoot is required by Windows to load various DLLs.  See:
        # https://bugs.python.org/issue13524#msg148850
        env['SystemRoot'] = os.environ['SystemRoot']
    return env


version = ''


def _try_get_version():
    hg = findhg()
    if hg is None:
        return ''
    hgid = None
    numerictags = []
    cmd = ['log', '-r', '.', '--template', '{tags}\n']
    pieces = sysstr(hg.run(cmd)).split()
    numerictags = [t for t in pieces if t[0:1].isdigit()]
    hgid = sysstr(hg.run(['id', '-i'])).strip()
    if hgid.count('+') == 2:
        hgid = hgid.replace("+", ".", 1)
    if not hgid:
        eprint("/!\\")
        eprint(r"/!\ Unable to determine hg version from local repository")
        eprint(r"/!\ Failed to retrieve current revision tags")
        return ''
    if numerictags:  # tag(s) found
        version = numerictags[-1]
        if hgid.endswith('+'):  # propagate the dirty status to the tag
            version += '+'
    else:  # no tag found on the checked out revision
        ltagcmd = ['log', '--rev', 'wdir()', '--template', '{latesttag}']
        ltag = sysstr(hg.run(ltagcmd))
        if not ltag:
            eprint("/!\\")
            eprint(r"/!\ Unable to determine hg version from local repository")
            eprint(
                r"/!\ Failed to retrieve current revision distance to lated tag"
            )
            return ''
        changessincecmd = [
            'log',
            '-T',
            'x\n',
            '-r',
            "only(parents(),'%s')" % ltag,
        ]
        changessince = len(hg.run(changessincecmd).splitlines())
        version = '%s+hg%s.%s' % (ltag, changessince, hgid)
    if version.endswith('+'):
        version = version[:-1] + 'local' + time.strftime('%Y%m%d')
    return version


if os.path.isdir('.hg'):
    version = _try_get_version()
elif os.path.exists('.hg_archival.txt'):
    kw = dict(
        [[t.strip() for t in l.split(':', 1)] for l in open('.hg_archival.txt')]
    )
    if 'tag' in kw:
        version = kw['tag']
    elif 'latesttag' in kw:
        if 'changessincelatesttag' in kw:
            version = (
                '%(latesttag)s+hg%(changessincelatesttag)s.%(node).12s' % kw
            )
        else:
            version = '%(latesttag)s+hg%(latesttagdistance)s.%(node).12s' % kw
    else:
        version = '0+hg' + kw.get('node', '')[:12]
elif os.path.exists('mercurial/__version__.py'):
    with open('mercurial/__version__.py') as f:
        data = f.read()
    version = re.search('version = b"(.*)"', data).group(1)
if not version:
    if os.environ.get("MERCURIAL_SETUP_MAKE_LOCAL") == "1":
        version = "0.0+0"
        eprint("/!\\")
        eprint(r"/!\ Using '0.0+0' as the default version")
        eprint(r"/!\ Re-run make local once that first version is built")
        eprint("/!\\")
    else:
        eprint("/!\\")
        eprint(r"/!\ Could not determine the Mercurial version")
        eprint(r"/!\ You need to build a local version first")
        eprint(r"/!\ Run `make local` and try again")
        eprint("/!\\")
        msg = "Run `make local` first to get a working local version"
        raise SystemExit(msg)

versionb = version
if not isinstance(versionb, bytes):
    versionb = versionb.encode('ascii')

write_if_changed(
    'mercurial/__version__.py',
    b''.join(
        [
            b'# this file is autogenerated by setup.py\n'
            b'version = b"%s"\n' % versionb,
        ]
    ),
)


class hgbuild(build):
    # Insert hgbuildmo first so that files in mercurial/locale/ are found
    # when build_py is run next.
    sub_commands = [('build_mo', None)] + build.sub_commands


class hgbuildmo(build):
    description = "build translations (.mo files)"

    def run(self):
        if not find_executable('msgfmt'):
            self.warn(
                "could not find msgfmt executable, no translations "
                "will be built"
            )
            return

        podir = 'i18n'
        if not os.path.isdir(podir):
            self.warn("could not find %s/ directory" % podir)
            return

        join = os.path.join
        for po in os.listdir(podir):
            if not po.endswith('.po'):
                continue
            pofile = join(podir, po)
            modir = join('locale', po[:-3], 'LC_MESSAGES')
            mofile = join(modir, 'hg.mo')
            mobuildfile = join('mercurial', mofile)
            cmd = ['msgfmt', '-v', '-o', mobuildfile, pofile]
            if sys.platform != 'sunos5':
                # msgfmt on Solaris does not know about -c
                cmd.append('-c')
            self.mkpath(join('mercurial', modir))
            self.make_file([pofile], mobuildfile, spawn, (cmd,))


class hgdist(Distribution):
    pure = False
    rust = False
    no_rust = False
    cffi = ispypy

    global_options = Distribution.global_options + [
        ('pure', None, "use pure (slow) Python code instead of C extensions"),
        ('rust', None, "use Rust extensions additionally to C extensions"),
        (
            'no-rust',
            None,
            "do not use Rust extensions additionally to C extensions",
        ),
    ]

    negative_opt = Distribution.negative_opt.copy()
    boolean_options = ['pure', 'rust', 'no-rust']
    negative_opt['no-rust'] = 'rust'

    def _set_command_options(self, command_obj, option_dict=None):
        # Not all distutils versions in the wild have boolean_options.
        # This should be cleaned up when we're Python 3 only.
        command_obj.boolean_options = (
            getattr(command_obj, 'boolean_options', []) + self.boolean_options
        )
        return Distribution._set_command_options(
            self, command_obj, option_dict=option_dict
        )

    def parse_command_line(self):
        ret = Distribution.parse_command_line(self)
        if not (self.rust or self.no_rust):
            hgrustext = os.environ.get('HGWITHRUSTEXT')
            # TODO record it for proper rebuild upon changes
            # (see mercurial/__modulepolicy__.py)
            if hgrustext != 'cpython' and hgrustext is not None:
                if hgrustext:
                    msg = 'unknown HGWITHRUSTEXT value: %s' % hgrustext
                    print(msg, file=sys.stderr)
                hgrustext = None
            self.rust = hgrustext is not None
            self.no_rust = not self.rust
        return ret

    def has_ext_modules(self):
        # self.ext_modules is emptied in hgbuildpy.finalize_options which is
        # too late for some cases
        return not self.pure and Distribution.has_ext_modules(self)


# This is ugly as a one-liner. So use a variable.
buildextnegops = dict(getattr(build_ext, 'negative_options', {}))
buildextnegops['no-zstd'] = 'zstd'
buildextnegops['no-rust'] = 'rust'


class hgbuildext(build_ext):
    user_options = build_ext.user_options + [
        ('zstd', None, 'compile zstd bindings [default]'),
        ('no-zstd', None, 'do not compile zstd bindings'),
        (
            'rust',
            None,
            'compile Rust extensions if they are in use '
            '(requires Cargo) [default]',
        ),
        ('no-rust', None, 'do not compile Rust extensions'),
    ]

    boolean_options = build_ext.boolean_options + ['zstd', 'rust']
    negative_opt = buildextnegops

    def initialize_options(self):
        self.zstd = True
        self.rust = True

        return build_ext.initialize_options(self)

    def finalize_options(self):
        # Unless overridden by the end user, build extensions in parallel.
        # Only influences behavior on Python 3.5+.
        if getattr(self, 'parallel', None) is None:
            self.parallel = True

        return build_ext.finalize_options(self)

    def build_extensions(self):
        ruststandalones = [
            e for e in self.extensions if isinstance(e, RustStandaloneExtension)
        ]
        self.extensions = [
            e for e in self.extensions if e not in ruststandalones
        ]
        # Filter out zstd if disabled via argument.
        if not self.zstd:
            self.extensions = [
                e for e in self.extensions if e.name != 'mercurial.zstd'
            ]

        # Build Rust standalone extensions if it'll be used
        # and its build is not explicitly disabled (for external build
        # as Linux distributions would do)
        if self.distribution.rust and self.rust:
            if not sys.platform.startswith('linux'):
                self.warn(
                    "rust extensions have only been tested on Linux "
                    "and may not behave correctly on other platforms"
                )

            for rustext in ruststandalones:
                rustext.build('' if self.inplace else self.build_lib)

        return build_ext.build_extensions(self)

    def build_extension(self, ext):
        if (
            self.distribution.rust
            and self.rust
            and isinstance(ext, RustExtension)
        ):
            ext.rustbuild()
        try:
            build_ext.build_extension(self, ext)
        except CCompilerError:
            if not getattr(ext, 'optional', False):
                raise
            log.warn(
                "Failed to build optional extension '%s' (skipping)", ext.name
            )


class hgbuildscripts(build_scripts):
    def run(self):
        if os.name != 'nt' or self.distribution.pure:
            return build_scripts.run(self)

        exebuilt = False
        try:
            self.run_command('build_hgexe')
            exebuilt = True
        except (DistutilsError, CCompilerError):
            log.warn('failed to build optional hg.exe')

        if exebuilt:
            # Copying hg.exe to the scripts build directory ensures it is
            # installed by the install_scripts command.
            hgexecommand = self.get_finalized_command('build_hgexe')
            dest = os.path.join(self.build_dir, 'hg.exe')
            self.mkpath(self.build_dir)
            self.copy_file(hgexecommand.hgexepath, dest)

            # Remove hg.bat because it is redundant with hg.exe.
            self.scripts.remove('contrib/win32/hg.bat')

        return build_scripts.run(self)


class hgbuildpy(build_py):
    def finalize_options(self):
        build_py.finalize_options(self)

        if self.distribution.pure:
            self.distribution.ext_modules = []
        elif self.distribution.cffi:
            from mercurial.cffi import (
                bdiffbuild,
                mpatchbuild,
            )

            exts = [
                mpatchbuild.ffi.distutils_extension(),
                bdiffbuild.ffi.distutils_extension(),
            ]
            # cffi modules go here
            if sys.platform == 'darwin':
                from mercurial.cffi import osutilbuild

                exts.append(osutilbuild.ffi.distutils_extension())
            self.distribution.ext_modules = exts
        else:
            h = os.path.join(get_python_inc(), 'Python.h')
            if not os.path.exists(h):
                raise SystemExit(
                    'Python headers are required to build '
                    'Mercurial but weren\'t found in %s' % h
                )

    def run(self):
        basepath = os.path.join(self.build_lib, 'mercurial')
        self.mkpath(basepath)

        rust = self.distribution.rust
        if self.distribution.pure:
            modulepolicy = 'py'
        elif self.build_lib == '.':
            # in-place build should run without rebuilding and Rust extensions
            modulepolicy = 'rust+c-allow' if rust else 'allow'
        else:
            modulepolicy = 'rust+c' if rust else 'c'

        content = b''.join(
            [
                b'# this file is autogenerated by setup.py\n',
                b'modulepolicy = b"%s"\n' % modulepolicy.encode('ascii'),
            ]
        )
        write_if_changed(os.path.join(basepath, '__modulepolicy__.py'), content)

        build_py.run(self)


class buildhgextindex(Command):
    description = 'generate prebuilt index of hgext (for frozen package)'
    user_options = []
    _indexfilename = 'hgext/__index__.py'

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        if os.path.exists(self._indexfilename):
            with open(self._indexfilename, 'w') as f:
                f.write('# empty\n')

        # here no extension enabled, disabled() lists up everything
        code = (
            'import pprint; from mercurial import extensions; '
            'ext = extensions.disabled();'
            'ext.pop("__index__", None);'
            'pprint.pprint(ext)'
        )
        returncode, out, err = runcmd(
            [sys.executable, '-c', code], localhgenv()
        )
        if err or returncode != 0:
            raise DistutilsExecError(err)

        with open(self._indexfilename, 'wb') as f:
            f.write(b'# this file is autogenerated by setup.py\n')
            f.write(b'docs = ')
            f.write(out)


class buildhgexe(build_ext):
    description = 'compile hg.exe from mercurial/exewrapper.c'

    LONG_PATHS_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel
          level="asInvoker"
          uiAccess="false"
        />
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <!-- Windows Vista -->
      <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"/>
      <!-- Windows 7 -->
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"/>
      <!-- Windows 8 -->
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"/>
      <!-- Windows 8.1 -->
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"/>
      <!-- Windows 10 and Windows 11 -->
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings
        xmlns:ws2="http://schemas.microsoft.com/SMI/2016/WindowsSettings">
      <ws2:longPathAware>true</ws2:longPathAware>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32"
                        name="Microsoft.Windows.Common-Controls"
                        version="6.0.0.0"
                        processorArchitecture="*"
                        publicKeyToken="6595b64144ccf1df"
                        language="*" />
    </dependentAssembly>
  </dependency>
</assembly>
"""

    def initialize_options(self):
        build_ext.initialize_options(self)

    def build_extensions(self):
        if os.name != 'nt':
            return
        if isinstance(self.compiler, HackedMingw32CCompiler):
            self.compiler.compiler_so = self.compiler.compiler  # no -mdll
            self.compiler.dll_libraries = []  # no -lmsrvc90

        pythonlib = None

        dirname = os.path.dirname(self.get_ext_fullpath('dummy'))
        self.hgtarget = os.path.join(dirname, 'hg')

        if getattr(sys, 'dllhandle', None):
            # Different Python installs can have different Python library
            # names. e.g. the official CPython distribution uses pythonXY.dll
            # and MinGW uses libpythonX.Y.dll.
            _kernel32 = ctypes.windll.kernel32
            _kernel32.GetModuleFileNameA.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_ulong,
            ]
            _kernel32.GetModuleFileNameA.restype = ctypes.c_ulong
            size = 1000
            buf = ctypes.create_string_buffer(size + 1)
            filelen = _kernel32.GetModuleFileNameA(
                sys.dllhandle, ctypes.byref(buf), size
            )

            if filelen > 0 and filelen != size:
                dllbasename = os.path.basename(buf.value)
                if not dllbasename.lower().endswith(b'.dll'):
                    raise SystemExit(
                        'Python DLL does not end with .dll: %s' % dllbasename
                    )
                pythonlib = dllbasename[:-4]

                # Copy the pythonXY.dll next to the binary so that it runs
                # without tampering with PATH.
                dest = os.path.join(
                    os.path.dirname(self.hgtarget),
                    os.fsdecode(dllbasename),
                )

                if not os.path.exists(dest):
                    shutil.copy(buf.value, dest)

                # Also overwrite python3.dll so that hgext.git is usable.
                # TODO: also handle the MSYS flavor
                python_x = os.path.join(
                    os.path.dirname(os.fsdecode(buf.value)),
                    "python3.dll",
                )

                if os.path.exists(python_x):
                    dest = os.path.join(
                        os.path.dirname(self.hgtarget),
                        os.path.basename(python_x),
                    )

                    shutil.copy(python_x, dest)

        if not pythonlib:
            log.warn(
                'could not determine Python DLL filename; assuming pythonXY'
            )

            hv = sys.hexversion
            pythonlib = b'python%d%d' % (hv >> 24, (hv >> 16) & 0xFF)

        log.info('using %s as Python library name' % pythonlib)
        with open('mercurial/hgpythonlib.h', 'wb') as f:
            f.write(b'/* this file is autogenerated by setup.py */\n')
            f.write(b'#define HGPYTHONLIB "%s"\n' % pythonlib)

        objects = self.compiler.compile(
            ['mercurial/exewrapper.c'],
            output_dir=self.build_temp,
            macros=[('_UNICODE', None), ('UNICODE', None)],
        )
        self.compiler.link_executable(
            objects, self.hgtarget, libraries=[], output_dir=self.build_temp
        )

        self.addlongpathsmanifest()

    def addlongpathsmanifest(self):
        """Add manifest pieces so that hg.exe understands long paths

        Why resource #1 should be used for .exe manifests? I don't know and
        wasn't able to find an explanation for mortals. But it seems to work.
        """
        exefname = self.compiler.executable_filename(self.hgtarget)
        fdauto, manfname = tempfile.mkstemp(suffix='.hg.exe.manifest')
        os.close(fdauto)
        with open(manfname, 'w', encoding="UTF-8") as f:
            f.write(self.LONG_PATHS_MANIFEST)
        log.info("long paths manifest is written to '%s'" % manfname)
        outputresource = '-outputresource:%s;#1' % exefname
        log.info("running mt.exe to update hg.exe's manifest in-place")

        self.spawn(
            [
                self.compiler.mt,
                '-nologo',
                '-manifest',
                manfname,
                outputresource,
            ]
        )
        log.info("done updating hg.exe's manifest")
        os.remove(manfname)

    @property
    def hgexepath(self):
        dir = os.path.dirname(self.get_ext_fullpath('dummy'))
        return os.path.join(self.build_temp, dir, 'hg.exe')


class hgbuilddoc(Command):
    description = 'build documentation'
    user_options = [
        ('man', None, 'generate man pages'),
        ('html', None, 'generate html pages'),
    ]

    def initialize_options(self):
        self.man = None
        self.html = None

    def finalize_options(self):
        # If --man or --html are set, only generate what we're told to.
        # Otherwise generate everything.
        have_subset = self.man is not None or self.html is not None

        if have_subset:
            self.man = True if self.man else False
            self.html = True if self.html else False
        else:
            self.man = True
            self.html = True

    def run(self):
        def normalizecrlf(p):
            with open(p, 'rb') as fh:
                orig = fh.read()

            if b'\r\n' not in orig:
                return

            log.info('normalizing %s to LF line endings' % p)
            with open(p, 'wb') as fh:
                fh.write(orig.replace(b'\r\n', b'\n'))

        def gentxt(root):
            txt = 'doc/%s.txt' % root
            log.info('generating %s' % txt)
            res, out, err = runcmd(
                [sys.executable, 'gendoc.py', root], os.environ, cwd='doc'
            )
            if res:
                raise SystemExit(
                    'error running gendoc.py: %s'
                    % '\n'.join([sysstr(out), sysstr(err)])
                )

            with open(txt, 'wb') as fh:
                fh.write(out)

        def gengendoc(root):
            gendoc = 'doc/%s.gendoc.txt' % root

            log.info('generating %s' % gendoc)
            res, out, err = runcmd(
                [sys.executable, 'gendoc.py', '%s.gendoc' % root],
                os.environ,
                cwd='doc',
            )
            if res:
                raise SystemExit(
                    'error running gendoc: %s'
                    % '\n'.join([sysstr(out), sysstr(err)])
                )

            with open(gendoc, 'wb') as fh:
                fh.write(out)

        def genman(root):
            log.info('generating doc/%s' % root)
            res, out, err = runcmd(
                [
                    sys.executable,
                    'runrst',
                    'hgmanpage',
                    '--halt',
                    'warning',
                    '--strip-elements-with-class',
                    'htmlonly',
                    '%s.txt' % root,
                    root,
                ],
                os.environ,
                cwd='doc',
            )
            if res:
                raise SystemExit(
                    'error running runrst: %s'
                    % '\n'.join([sysstr(out), sysstr(err)])
                )

            normalizecrlf('doc/%s' % root)

        def genhtml(root):
            log.info('generating doc/%s.html' % root)
            res, out, err = runcmd(
                [
                    sys.executable,
                    'runrst',
                    'html',
                    '--halt',
                    'warning',
                    '--link-stylesheet',
                    '--stylesheet-path',
                    'style.css',
                    '%s.txt' % root,
                    '%s.html' % root,
                ],
                os.environ,
                cwd='doc',
            )
            if res:
                raise SystemExit(
                    'error running runrst: %s'
                    % '\n'.join([sysstr(out), sysstr(err)])
                )

            normalizecrlf('doc/%s.html' % root)

        # This logic is duplicated in doc/Makefile.
        sources = {
            f
            for f in os.listdir('mercurial/helptext')
            if re.search(r'[0-9]\.txt$', f)
        }

        # common.txt is a one-off.
        gentxt('common')

        for source in sorted(sources):
            assert source[-4:] == '.txt'
            root = source[:-4]

            gentxt(root)
            gengendoc(root)

            if self.man:
                genman(root)
            if self.html:
                genhtml(root)


class hginstall(install):
    user_options = install.user_options + [
        (
            'old-and-unmanageable',
            None,
            'noop, present for eggless setuptools compat',
        ),
        (
            'single-version-externally-managed',
            None,
            'noop, present for eggless setuptools compat',
        ),
    ]

    sub_commands = install.sub_commands + [
        ('install_completion', lambda self: True)
    ]

    # Also helps setuptools not be sad while we refuse to create eggs.
    single_version_externally_managed = True

    def get_sub_commands(self):
        # Screen out egg related commands to prevent egg generation.  But allow
        # mercurial.egg-info generation, since that is part of modern
        # packaging.
        excl = {'bdist_egg'}
        return filter(lambda x: x not in excl, install.get_sub_commands(self))


class hginstalllib(install_lib):
    """
    This is a specialization of install_lib that replaces the copy_file used
    there so that it supports setting the mode of files after copying them,
    instead of just preserving the mode that the files originally had.  If your
    system has a umask of something like 027, preserving the permissions when
    copying will lead to a broken install.

    Note that just passing keep_permissions=False to copy_file would be
    insufficient, as it might still be applying a umask.
    """

    def run(self):
        realcopyfile = file_util.copy_file

        def copyfileandsetmode(*args, **kwargs):
            src, dst = args[0], args[1]
            dst, copied = realcopyfile(*args, **kwargs)
            if copied:
                st = os.stat(src)
                # Persist executable bit (apply it to group and other if user
                # has it)
                if st[stat.ST_MODE] & stat.S_IXUSR:
                    setmode = int('0755', 8)
                else:
                    setmode = int('0644', 8)
                m = stat.S_IMODE(st[stat.ST_MODE])
                m = (m & ~int('0777', 8)) | setmode
                os.chmod(dst, m)

        file_util.copy_file = copyfileandsetmode
        try:
            install_lib.run(self)
        finally:
            file_util.copy_file = realcopyfile


class hginstallscripts(install_scripts):
    """
    This is a specialization of install_scripts that replaces the @LIBDIR@ with
    the configured directory for modules. If possible, the path is made relative
    to the directory for scripts.
    """

    def initialize_options(self):
        install_scripts.initialize_options(self)

        self.install_lib = None

    def finalize_options(self):
        install_scripts.finalize_options(self)
        self.set_undefined_options('install', ('install_lib', 'install_lib'))

    def run(self):
        install_scripts.run(self)

        # It only makes sense to replace @LIBDIR@ with the install path if
        # the install path is known. For wheels, the logic below calculates
        # the libdir to be "../..". This is because the internal layout of a
        # wheel archive looks like:
        #
        #   mercurial-3.6.1.data/scripts/hg
        #   mercurial/__init__.py
        #
        # When installing wheels, the subdirectories of the "<pkg>.data"
        # directory are translated to system local paths and files therein
        # are copied in place. The mercurial/* files are installed into the
        # site-packages directory. However, the site-packages directory
        # isn't known until wheel install time. This means we have no clue
        # at wheel generation time what the installed site-packages directory
        # will be. And, wheels don't appear to provide the ability to register
        # custom code to run during wheel installation. This all means that
        # we can't reliably set the libdir in wheels: the default behavior
        # of looking in sys.path must do.

        if (
            os.path.splitdrive(self.install_dir)[0]
            != os.path.splitdrive(self.install_lib)[0]
        ):
            # can't make relative paths from one drive to another, so use an
            # absolute path instead
            libdir = self.install_lib
        else:
            libdir = os.path.relpath(self.install_lib, self.install_dir)

        for outfile in self.outfiles:
            with open(outfile, 'rb') as fp:
                data = fp.read()

            # skip binary files
            if b'\0' in data:
                continue

            # During local installs, the shebang will be rewritten to the final
            # install path. During wheel packaging, the shebang has a special
            # value.
            if data.startswith(b'#!python'):
                log.info(
                    'not rewriting @LIBDIR@ in %s because install path '
                    'not known' % outfile
                )
                continue

            data = data.replace(b'@LIBDIR@', libdir.encode('unicode_escape'))
            with open(outfile, 'wb') as fp:
                fp.write(data)


class hginstallcompletion(Command):
    description = 'Install shell completion'

    def initialize_options(self):
        self.install_dir = None
        self.outputs = []

    def finalize_options(self):
        self.set_undefined_options(
            'install_data', ('install_dir', 'install_dir')
        )

    def get_outputs(self):
        return self.outputs

    def run(self):
        for src, dir_path, dest in (
            (
                'bash_completion',
                ('share', 'bash-completion', 'completions'),
                'hg',
            ),
            ('zsh_completion', ('share', 'zsh', 'site-functions'), '_hg'),
        ):
            dir = os.path.join(self.install_dir, *dir_path)
            self.mkpath(dir)

            dest = os.path.join(dir, dest)
            self.outputs.append(dest)
            self.copy_file(os.path.join('contrib', src), dest)


# virtualenv installs custom distutils/__init__.py and
# distutils/distutils.cfg files which essentially proxy back to the
# "real" distutils in the main Python install. The presence of this
# directory causes py2exe to pick up the "hacked" distutils package
# from the virtualenv and "import distutils" will fail from the py2exe
# build because the "real" distutils files can't be located.
#
# We work around this by monkeypatching the py2exe code finding Python
# modules to replace the found virtualenv distutils modules with the
# original versions via filesystem scanning. This is a bit hacky. But
# it allows us to use virtualenvs for py2exe packaging, which is more
# deterministic and reproducible.
#
# It's worth noting that the common StackOverflow suggestions for this
# problem involve copying the original distutils files into the
# virtualenv or into the staging directory after setup() is invoked.
# The former is very brittle and can easily break setup(). Our hacking
# of the found modules routine has a similar result as copying the files
# manually. But it makes fewer assumptions about how py2exe works and
# is less brittle.

# This only catches virtualenvs made with virtualenv (as opposed to
# venv, which is likely what Python 3 uses).
py2exehacked = py2exeloaded and getattr(sys, 'real_prefix', None) is not None

if py2exehacked:
    from distutils.command.py2exe import py2exe as buildpy2exe
    from py2exe.mf import Module as py2exemodule

    class hgbuildpy2exe(buildpy2exe):
        def find_needed_modules(self, mf, files, modules):
            res = buildpy2exe.find_needed_modules(self, mf, files, modules)

            # Replace virtualenv's distutils modules with the real ones.
            modules = {}
            for k, v in res.modules.items():
                if k != 'distutils' and not k.startswith('distutils.'):
                    modules[k] = v

            res.modules = modules

            import opcode

            distutilsreal = os.path.join(
                os.path.dirname(opcode.__file__), 'distutils'
            )

            for root, dirs, files in os.walk(distutilsreal):
                for f in sorted(files):
                    if not f.endswith('.py'):
                        continue

                    full = os.path.join(root, f)

                    parents = ['distutils']

                    if root != distutilsreal:
                        rel = os.path.relpath(root, distutilsreal)
                        parents.extend(p for p in rel.split(os.sep))

                    modname = '%s.%s' % ('.'.join(parents), f[:-3])

                    if modname.startswith('distutils.tests.'):
                        continue

                    if modname.endswith('.__init__'):
                        modname = modname[: -len('.__init__')]
                        path = os.path.dirname(full)
                    else:
                        path = None

                    res.modules[modname] = py2exemodule(
                        modname, full, path=path
                    )

            if 'distutils' not in res.modules:
                raise SystemExit('could not find distutils modules')

            return res


cmdclass = {
    'build': hgbuild,
    'build_doc': hgbuilddoc,
    'build_mo': hgbuildmo,
    'build_ext': hgbuildext,
    'build_py': hgbuildpy,
    'build_scripts': hgbuildscripts,
    'build_hgextindex': buildhgextindex,
    'install': hginstall,
    'install_completion': hginstallcompletion,
    'install_lib': hginstalllib,
    'install_scripts': hginstallscripts,
    'build_hgexe': buildhgexe,
}

if py2exehacked:
    cmdclass['py2exe'] = hgbuildpy2exe

packages = [
    'mercurial',
    'mercurial.admin',
    'mercurial.cext',
    'mercurial.cffi',
    'mercurial.defaultrc',
    'mercurial.dirstateutils',
    'mercurial.helptext',
    'mercurial.helptext.internals',
    'mercurial.hgweb',
    'mercurial.interfaces',
    'mercurial.pure',
    'mercurial.stabletailgraph',
    'mercurial.templates',
    'mercurial.thirdparty',
    'mercurial.thirdparty.attr',
    'mercurial.thirdparty.tomli',
    'mercurial.thirdparty.zope',
    'mercurial.thirdparty.zope.interface',
    'mercurial.upgrade_utils',
    'mercurial.utils',
    'mercurial.revlogutils',
    'mercurial.testing',
    'hgext',
    'hgext.convert',
    'hgext.fsmonitor',
    'hgext.fastannotate',
    'hgext.fsmonitor.pywatchman',
    'hgext.git',
    'hgext.highlight',
    'hgext.hooklib',
    'hgext.largefiles',
    'hgext.lfs',
    'hgext.narrow',
    'hgext.remotefilelog',
    'hgext.zeroconf',
    'hgext3rd',
    'hgdemandimport',
]

for name in os.listdir(os.path.join('mercurial', 'templates')):
    if name != '__pycache__' and os.path.isdir(
        os.path.join('mercurial', 'templates', name)
    ):
        packages.append('mercurial.templates.%s' % name)

if 'HG_PY2EXE_EXTRA_INSTALL_PACKAGES' in os.environ:
    # py2exe can't cope with namespace packages very well, so we have to
    # install any hgext3rd.* extensions that we want in the final py2exe
    # image here. This is gross, but you gotta do what you gotta do.
    packages.extend(os.environ['HG_PY2EXE_EXTRA_INSTALL_PACKAGES'].split(' '))

common_depends = [
    'mercurial/bitmanipulation.h',
    'mercurial/compat.h',
    'mercurial/cext/util.h',
]
common_include_dirs = ['mercurial']

common_cflags = []

# MSVC 2008 still needs declarations at the top of the scope, but Python 3.9
# makes declarations not at the top of a scope in the headers.
if os.name != 'nt' and sys.version_info[1] < 9:
    common_cflags = ['-Werror=declaration-after-statement']

osutil_cflags = []
osutil_ldflags = []

# platform specific macros
for plat, func in [('bsd', 'setproctitle')]:
    if re.search(plat, sys.platform) and hasfunction(new_compiler(), func):
        osutil_cflags.append('-DHAVE_%s' % func.upper())

for plat, macro, code in [
    (
        'bsd|darwin',
        'BSD_STATFS',
        '''
     #include <sys/param.h>
     #include <sys/mount.h>
     int main() { struct statfs s; return sizeof(s.f_fstypename); }
     ''',
    ),
    (
        'linux',
        'LINUX_STATFS',
        '''
     #include <linux/magic.h>
     #include <sys/vfs.h>
     int main() { struct statfs s; return sizeof(s.f_type); }
     ''',
    ),
]:
    if re.search(plat, sys.platform) and cancompile(new_compiler(), code):
        osutil_cflags.append('-DHAVE_%s' % macro)

if sys.platform == 'darwin':
    osutil_ldflags += ['-framework', 'ApplicationServices']

if sys.platform == 'sunos5':
    osutil_ldflags += ['-lsocket']

xdiff_srcs = [
    'mercurial/thirdparty/xdiff/xdiffi.c',
    'mercurial/thirdparty/xdiff/xprepare.c',
    'mercurial/thirdparty/xdiff/xutils.c',
]

xdiff_headers = [
    'mercurial/thirdparty/xdiff/xdiff.h',
    'mercurial/thirdparty/xdiff/xdiffi.h',
    'mercurial/thirdparty/xdiff/xinclude.h',
    'mercurial/thirdparty/xdiff/xmacros.h',
    'mercurial/thirdparty/xdiff/xprepare.h',
    'mercurial/thirdparty/xdiff/xtypes.h',
    'mercurial/thirdparty/xdiff/xutils.h',
]


class RustCompilationError(CCompilerError):
    """Exception class for Rust compilation errors."""


class RustExtension(Extension):
    """Base classes for concrete Rust Extension classes."""

    rusttargetdir = os.path.join('rust', 'target', 'release')

    def __init__(self, mpath, sources, rustlibname, subcrate, **kw):
        Extension.__init__(self, mpath, sources, **kw)
        srcdir = self.rustsrcdir = os.path.join('rust', subcrate)

        # adding Rust source and control files to depends so that the extension
        # gets rebuilt if they've changed
        self.depends.append(os.path.join(srcdir, 'Cargo.toml'))
        cargo_lock = os.path.join(srcdir, 'Cargo.lock')
        if os.path.exists(cargo_lock):
            self.depends.append(cargo_lock)
        for dirpath, subdir, fnames in os.walk(os.path.join(srcdir, 'src')):
            self.depends.extend(
                os.path.join(dirpath, fname)
                for fname in fnames
                if os.path.splitext(fname)[1] == '.rs'
            )

    @staticmethod
    def rustdylibsuffix():
        """Return the suffix for shared libraries produced by rustc.

        See also: https://doc.rust-lang.org/reference/linkage.html
        """
        if sys.platform == 'darwin':
            return '.dylib'
        elif os.name == 'nt':
            return '.dll'
        else:
            return '.so'

    def rustbuild(self):
        env = os.environ.copy()
        if 'HGTEST_RESTOREENV' in env:
            # Mercurial tests change HOME to a temporary directory,
            # but, if installed with rustup, the Rust toolchain needs
            # HOME to be correct (otherwise the 'no default toolchain'
            # error message is issued and the build fails).
            # This happens currently with test-hghave.t, which does
            # invoke this build.

            # Unix only fix (os.path.expanduser not really reliable if
            # HOME is shadowed like this)
            import pwd

            env['HOME'] = pwd.getpwuid(os.getuid()).pw_dir

        cargocmd = ['cargo', 'rustc', '--release']

        rust_features = env.get("HG_RUST_FEATURES")
        if rust_features:
            cargocmd.extend(('--features', rust_features))

        cargocmd.append('--')
        if sys.platform == 'darwin':
            cargocmd.extend(
                ("-C", "link-arg=-undefined", "-C", "link-arg=dynamic_lookup")
            )
        try:
            subprocess.check_call(cargocmd, env=env, cwd=self.rustsrcdir)
        except FileNotFoundError:
            raise RustCompilationError("Cargo not found")
        except PermissionError:
            raise RustCompilationError(
                "Cargo found, but permission to execute it is denied"
            )
        except subprocess.CalledProcessError:
            raise RustCompilationError(
                "Cargo failed. Working directory: %r, "
                "command: %r, environment: %r"
                % (self.rustsrcdir, cargocmd, env)
            )


class RustStandaloneExtension(RustExtension):
    def __init__(self, pydottedname, rustcrate, dylibname, **kw):
        RustExtension.__init__(
            self, pydottedname, [], dylibname, rustcrate, **kw
        )
        self.dylibname = dylibname

    def build(self, target_dir):
        self.rustbuild()
        target = [target_dir]
        target.extend(self.name.split('.'))
        target[-1] += DYLIB_SUFFIX
        target = os.path.join(*target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(
            os.path.join(
                self.rusttargetdir, self.dylibname + self.rustdylibsuffix()
            ),
            target,
        )


extmodules = [
    Extension(
        'mercurial.cext.base85',
        ['mercurial/cext/base85.c'],
        include_dirs=common_include_dirs,
        extra_compile_args=common_cflags,
        depends=common_depends,
    ),
    Extension(
        'mercurial.cext.bdiff',
        ['mercurial/bdiff.c', 'mercurial/cext/bdiff.c'] + xdiff_srcs,
        include_dirs=common_include_dirs,
        extra_compile_args=common_cflags,
        depends=common_depends + ['mercurial/bdiff.h'] + xdiff_headers,
    ),
    Extension(
        'mercurial.cext.mpatch',
        ['mercurial/mpatch.c', 'mercurial/cext/mpatch.c'],
        include_dirs=common_include_dirs,
        extra_compile_args=common_cflags,
        depends=common_depends,
    ),
    Extension(
        'mercurial.cext.parsers',
        [
            'mercurial/cext/charencode.c',
            'mercurial/cext/dirs.c',
            'mercurial/cext/manifest.c',
            'mercurial/cext/parsers.c',
            'mercurial/cext/pathencode.c',
            'mercurial/cext/revlog.c',
        ],
        include_dirs=common_include_dirs,
        extra_compile_args=common_cflags,
        depends=common_depends
        + [
            'mercurial/cext/charencode.h',
            'mercurial/cext/revlog.h',
        ],
    ),
    Extension(
        'mercurial.cext.osutil',
        ['mercurial/cext/osutil.c'],
        include_dirs=common_include_dirs,
        extra_compile_args=common_cflags + osutil_cflags,
        extra_link_args=osutil_ldflags,
        depends=common_depends,
    ),
    Extension(
        'mercurial.thirdparty.zope.interface._zope_interface_coptimizations',
        [
            'mercurial/thirdparty/zope/interface/_zope_interface_coptimizations.c',
        ],
        extra_compile_args=common_cflags,
    ),
    Extension(
        'mercurial.thirdparty.sha1dc',
        [
            'mercurial/thirdparty/sha1dc/cext.c',
            'mercurial/thirdparty/sha1dc/lib/sha1.c',
            'mercurial/thirdparty/sha1dc/lib/ubc_check.c',
        ],
        extra_compile_args=common_cflags,
    ),
    Extension(
        'hgext.fsmonitor.pywatchman.bser',
        ['hgext/fsmonitor/pywatchman/bser.c'],
        extra_compile_args=common_cflags,
    ),
    RustStandaloneExtension(
        'mercurial.rustext',
        'hg-cpython',
        'librusthg',
    ),
]


sys.path.insert(0, 'contrib/python-zstandard')
import setup_zstd

zstd = setup_zstd.get_c_extension(
    name='mercurial.zstd', root=os.path.abspath(os.path.dirname(__file__))
)
zstd.extra_compile_args += common_cflags
extmodules.append(zstd)

try:
    from distutils import cygwinccompiler

    # the -mno-cygwin option has been deprecated for years
    mingw32compilerclass = cygwinccompiler.Mingw32CCompiler

    class HackedMingw32CCompiler(cygwinccompiler.Mingw32CCompiler):
        def __init__(self, *args, **kwargs):
            mingw32compilerclass.__init__(self, *args, **kwargs)
            for i in 'compiler compiler_so linker_exe linker_so'.split():
                try:
                    getattr(self, i).remove('-mno-cygwin')
                except ValueError:
                    pass

    cygwinccompiler.Mingw32CCompiler = HackedMingw32CCompiler
except ImportError:
    # the cygwinccompiler package is not available on some Python
    # distributions like the ones from the optware project for Synology
    # DiskStation boxes
    class HackedMingw32CCompiler:
        pass


if os.name == 'nt':
    # Allow compiler/linker flags to be added to Visual Studio builds.  Passing
    # extra_link_args to distutils.extensions.Extension() doesn't have any
    # effect.
    try:
        # setuptools < 65.0
        from distutils import msvccompiler
    except ImportError:
        from distutils import _msvccompiler as msvccompiler

    msvccompilerclass = msvccompiler.MSVCCompiler

    class HackedMSVCCompiler(msvccompiler.MSVCCompiler):
        def initialize(self):
            msvccompilerclass.initialize(self)
            # "warning LNK4197: export 'func' specified multiple times"
            self.ldflags_shared.append('/ignore:4197')
            self.ldflags_shared_debug.append('/ignore:4197')

    msvccompiler.MSVCCompiler = HackedMSVCCompiler

packagedata = {
    'mercurial': [
        'configitems.toml',
        'locale/*/LC_MESSAGES/hg.mo',
        'dummycert.pem',
    ],
    'mercurial.defaultrc': [
        '*.rc',
    ],
    'mercurial.helptext': [
        '*.txt',
    ],
    'mercurial.helptext.internals': [
        '*.txt',
    ],
    'mercurial.thirdparty.attr': [
        '*.pyi',
        'py.typed',
    ],
}


def ordinarypath(p):
    return p and p[0] != '.' and p[-1] != '~'


for root in ('templates',):
    for curdir, dirs, files in os.walk(os.path.join('mercurial', root)):
        packagename = curdir.replace(os.sep, '.')
        packagedata[packagename] = list(filter(ordinarypath, files))

datafiles = []

# distutils expects version to be str/unicode. Converting it to
# unicode on Python 2 still works because it won't contain any
# non-ascii bytes and will be implicitly converted back to bytes
# when operated on.
assert isinstance(version, str)
setupversion = version

extra = {}

py2exepackages = [
    'hgdemandimport',
    'hgext3rd',
    'hgext',
    'email',
    # implicitly imported per module policy
    # (cffi wouldn't be used as a frozen exe)
    'mercurial.cext',
    #'mercurial.cffi',
    'mercurial.pure',
]

py2exe_includes = []

py2exeexcludes = []
py2exedllexcludes = ['crypt32.dll']

if issetuptools:
    extra['python_requires'] = supportedpy

if py2exeloaded:
    extra['console'] = [
        {
            'script': 'hg',
            'copyright': 'Copyright (C) 2005-2024 Olivia Mackall and others',
            'product_version': version,
        }
    ]
    # Sub command of 'build' because 'py2exe' does not handle sub_commands.
    # Need to override hgbuild because it has a private copy of
    # build.sub_commands.
    hgbuild.sub_commands.insert(0, ('build_hgextindex', None))
    # put dlls in sub directory so that they won't pollute PATH
    extra['zipfile'] = 'lib/library.zip'

    # We allow some configuration to be supplemented via environment
    # variables. This is better than setup.cfg files because it allows
    # supplementing configs instead of replacing them.
    extrapackages = os.environ.get('HG_PY2EXE_EXTRA_PACKAGES')
    if extrapackages:
        py2exepackages.extend(extrapackages.split(' '))

    extra_includes = os.environ.get('HG_PY2EXE_EXTRA_INCLUDES')
    if extra_includes:
        py2exe_includes.extend(extra_includes.split(' '))

    excludes = os.environ.get('HG_PY2EXE_EXTRA_EXCLUDES')
    if excludes:
        py2exeexcludes.extend(excludes.split(' '))

    dllexcludes = os.environ.get('HG_PY2EXE_EXTRA_DLL_EXCLUDES')
    if dllexcludes:
        py2exedllexcludes.extend(dllexcludes.split(' '))

if os.environ.get('PYOXIDIZER'):
    hgbuild.sub_commands.insert(0, ('build_hgextindex', None))

if os.name == 'nt':
    # Windows binary file versions for exe/dll files must have the
    # form W.X.Y.Z, where W,X,Y,Z are numbers in the range 0..65535
    setupversion = setupversion.split(r'+', 1)[0]

setup(
    name='mercurial',
    version=setupversion,
    author='Olivia Mackall and many others',
    author_email='mercurial@mercurial-scm.org',
    url='https://mercurial-scm.org/',
    download_url='https://mercurial-scm.org/release/',
    description=(
        'Fast scalable distributed SCM (revision control, version '
        'control) system'
    ),
    long_description=(
        'Mercurial is a distributed SCM tool written in Python.'
        ' It is used by a number of large projects that require'
        ' fast, reliable distributed revision control, such as '
        'Mozilla.'
    ),
    license='GNU GPLv2 or any later version',
    classifiers=[
        'Development Status :: 6 - Mature',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Natural Language :: Danish',
        'Natural Language :: English',
        'Natural Language :: German',
        'Natural Language :: Italian',
        'Natural Language :: Japanese',
        'Natural Language :: Portuguese (Brazilian)',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: OS Independent',
        'Operating System :: POSIX',
        'Programming Language :: C',
        'Programming Language :: Python',
        'Topic :: Software Development :: Version Control',
    ],
    scripts=scripts,
    packages=packages,
    ext_modules=extmodules,
    data_files=datafiles,
    package_data=packagedata,
    cmdclass=cmdclass,
    distclass=hgdist,
    options={
        'py2exe': {
            'bundle_files': 3,
            'dll_excludes': py2exedllexcludes,
            'includes': py2exe_includes,
            'excludes': py2exeexcludes,
            'packages': py2exepackages,
        },
        'bdist_mpkg': {
            'zipdist': False,
            'license': 'COPYING',
            'readme': 'contrib/packaging/macosx/Readme.html',
            'welcome': 'contrib/packaging/macosx/Welcome.html',
        },
    },
    **extra,
)
