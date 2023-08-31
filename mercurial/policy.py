# policy.py - module policy logic for Mercurial.
#
# Copyright 2015 Gregory Szorc <gregory.szorc@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.


import os
import sys

# Rules for how modules can be loaded. Values are:
#
#    c - require C extensions
#    rust+c - require Rust and C extensions
#    rust+c-allow - allow Rust and C extensions with fallback to pure Python
#                   for each
#    allow - allow pure Python implementation when C loading fails
#    cffi - required cffi versions (implemented within pure module)
#    cffi-allow - allow pure Python implementation if cffi version is missing
#    py - only load pure Python modules
#
# By default, fall back to the pure modules so the in-place build can
# run without recompiling the C extensions. This will be overridden by
# __modulepolicy__ generated by setup.py.
policy = b'allow'
_packageprefs = {
    # policy: (versioned package, pure package)
    b'c': ('cext', None),
    b'allow': ('cext', 'pure'),
    b'cffi': ('cffi', None),
    b'cffi-allow': ('cffi', 'pure'),
    b'py': (None, 'pure'),
    # For now, rust policies impact importrust only
    b'rust+c': ('cext', None),
    b'rust+c-allow': ('cext', 'pure'),
}

try:
    from . import __modulepolicy__

    policy = __modulepolicy__.modulepolicy
except ImportError:
    pass

# PyPy doesn't load C extensions.
#
# The canonical way to do this is to test platform.python_implementation().
# But we don't import platform and don't bloat for it here.
if '__pypy__' in sys.builtin_module_names:
    policy = b'cffi'

# Environment variable can always force settings.
if 'HGMODULEPOLICY' in os.environ:
    policy = os.environ['HGMODULEPOLICY'].encode('utf-8')


def _importfrom(pkgname, modname):
    # from .<pkgname> import <modname> (where . is looked through this module)
    fakelocals = {}
    pkg = __import__(pkgname, globals(), fakelocals, [modname], level=1)
    try:
        fakelocals[modname] = mod = getattr(pkg, modname)
    except AttributeError:
        raise ImportError('cannot import name %s' % modname)
    # force import; fakelocals[modname] may be replaced with the real module
    getattr(mod, '__doc__', None)
    return fakelocals[modname]


# keep in sync with "version" in C modules
_cextversions = {
    ('cext', 'base85'): 1,
    ('cext', 'bdiff'): 3,
    ('cext', 'mpatch'): 1,
    ('cext', 'osutil'): 4,
    ('cext', 'parsers'): 21,
}

# map import request to other package or module
_modredirects = {
    ('cext', 'charencode'): ('cext', 'parsers'),
    ('cffi', 'base85'): ('pure', 'base85'),
    ('cffi', 'charencode'): ('pure', 'charencode'),
    ('cffi', 'parsers'): ('pure', 'parsers'),
}


def _checkmod(pkgname, modname, mod):
    expected = _cextversions.get((pkgname, modname))
    actual = getattr(mod, 'version', None)
    if actual != expected:
        raise ImportError(
            'cannot import module %s.%s '
            '(expected version: %d, actual: %r)'
            % (pkgname, modname, expected, actual)
        )


def importmod(modname):
    """Import module according to policy and check API version"""
    try:
        verpkg, purepkg = _packageprefs[policy]
    except KeyError:
        raise ImportError('invalid HGMODULEPOLICY %r' % policy)
    assert verpkg or purepkg
    if verpkg:
        pn, mn = _modredirects.get((verpkg, modname), (verpkg, modname))
        try:
            mod = _importfrom(pn, mn)
            if pn == verpkg:
                _checkmod(pn, mn, mod)
            return mod
        except ImportError:
            if not purepkg:
                raise
    pn, mn = _modredirects.get((purepkg, modname), (purepkg, modname))
    return _importfrom(pn, mn)


def _isrustpermissive():
    """Assuming the policy is a Rust one, tell if it's permissive."""
    return policy.endswith(b'-allow')


def importrust(modname, member=None, default=None):
    """Import Rust module according to policy and availability.

    If policy isn't a Rust one, this returns `default`.

    If either the module or its member is not available, this returns `default`
    if policy is permissive and raises `ImportError` if not.
    """
    if not policy.startswith(b'rust'):
        return default

    try:
        mod = _importfrom('rustext', modname)
    except ImportError:
        if _isrustpermissive():
            return default
        raise
    if member is None:
        return mod

    try:
        return getattr(mod, member)
    except AttributeError:
        if _isrustpermissive():
            return default
        raise ImportError("Cannot import name %s" % member)
