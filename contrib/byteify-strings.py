#!/usr/bin/env python3
#
# byteify-strings.py - transform string literals to be Python 3 safe
#
# Copyright 2015 Gregory Szorc <gregory.szorc@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from __future__ import absolute_import

import argparse
import contextlib
import errno
import os
import sys
import tempfile
import token
import tokenize

if True:
    def replacetokens(tokens):
        """Transform a stream of tokens from raw to Python 3.

        Returns a generator of possibly rewritten tokens.

        The input token list may be mutated as part of processing. However,
        its changes do not necessarily match the output token stream.
        """
        # The following utility functions access the tokens list and i index of
        # the for i, t enumerate(tokens) loop below
        def _isop(j, *o):
            """Assert that tokens[j] is an OP with one of the given values"""
            try:
                return tokens[j].type == token.OP and tokens[j].string in o
            except IndexError:
                return False

        def _findargnofcall(n):
            """Find arg n of a call expression (start at 0)

            Returns index of the first token of that argument, or None if
            there is not that many arguments.

            Assumes that token[i + 1] is '('.

            """
            nested = 0
            for j in range(i + 2, len(tokens)):
                if _isop(j, ')', ']', '}'):
                    # end of call, tuple, subscription or dict / set
                    nested -= 1
                    if nested < 0:
                        return None
                elif n == 0:
                    # this is the starting position of arg
                    return j
                elif _isop(j, '(', '[', '{'):
                    nested += 1
                elif _isop(j, ',') and nested == 0:
                    n -= 1

            return None

        def _ensureunicode(j):
            """Make sure the token at j is a unicode string

            This rewrites a string token to include the unicode literal prefix
            so the string transformer won't add the byte prefix.

            Ignores tokens that are not strings. Assumes bounds checking has
            already been done.

            """
            st = tokens[j]
            if st.type == token.STRING and st.string.startswith(("'", '"')):
                tokens[j] = st._replace(string='u%s' % st.string)

        for i, t in enumerate(tokens):
            # Convert most string literals to byte literals. String literals
            # in Python 2 are bytes. String literals in Python 3 are unicode.
            # Most strings in Mercurial are bytes and unicode strings are rare.
            # Rather than rewrite all string literals to use ``b''`` to indicate
            # byte strings, we apply this token transformer to insert the ``b``
            # prefix nearly everywhere.
            if t.type == token.STRING:
                s = t.string

                # Preserve docstrings as string literals. This is inconsistent
                # with regular unprefixed strings. However, the
                # "from __future__" parsing (which allows a module docstring to
                # exist before it) doesn't properly handle the docstring if it
                # is b''' prefixed, leading to a SyntaxError. We leave all
                # docstrings as unprefixed to avoid this. This means Mercurial
                # components touching docstrings need to handle unicode,
                # unfortunately.
                if s[0:3] in ("'''", '"""'):
                    yield t
                    continue

                # If the first character isn't a quote, it is likely a string
                # prefixing character (such as 'b', 'u', or 'r'. Ignore.
                if s[0] not in ("'", '"'):
                    yield t
                    continue

                # String literal. Prefix to make a b'' string.
                yield t._replace(string='b%s' % t.string)
                continue

            # This looks like a function call.
            if t.type == token.NAME and _isop(i + 1, '('):
                fn = t.string

                # *attr() builtins don't accept byte strings to 2nd argument.
                if (fn in ('getattr', 'setattr', 'hasattr', 'safehasattr') and
                        not _isop(i - 1, '.')):
                    arg1idx = _findargnofcall(1)
                    if arg1idx is not None:
                        _ensureunicode(arg1idx)

                # .encode() and .decode() on str/bytes/unicode don't accept
                # byte strings on Python 3.
                elif fn in ('encode', 'decode') and _isop(i - 1, '.'):
                    for argn in range(2):
                        argidx = _findargnofcall(argn)
                        if argidx is not None:
                            _ensureunicode(argidx)

                # It changes iteritems/values to items/values as they are not
                # present in Python 3 world.
                elif fn in ('iteritems', 'itervalues'):
                    yield t._replace(string=fn[4:])
                    continue

            # Emit unmodified token.
            yield t

def process(fin, fout):
    tokens = tokenize.tokenize(fin.readline)
    tokens = replacetokens(list(tokens))
    fout.write(tokenize.untokenize(tokens))

def tryunlink(fname):
    try:
        os.unlink(fname)
    except OSError as err:
        if err.errno != errno.ENOENT:
            raise

@contextlib.contextmanager
def editinplace(fname):
    n = os.path.basename(fname)
    d = os.path.dirname(fname)
    fp = tempfile.NamedTemporaryFile(prefix='.%s-' % n, suffix='~', dir=d,
                                     delete=False)
    try:
        yield fp
        fp.close()
        if os.name == 'nt':
            tryunlink(fname)
        os.rename(fp.name, fname)
    finally:
        fp.close()
        tryunlink(fp.name)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-i', '--inplace', action='store_true', default=False,
                    help='edit files in place')
    ap.add_argument('files', metavar='FILE', nargs='+', help='source file')
    args = ap.parse_args()
    for fname in args.files:
        if args.inplace:
            with editinplace(fname) as fout:
                with open(fname, 'rb') as fin:
                    process(fin, fout)
        else:
            with open(fname, 'rb') as fin:
                fout = sys.stdout.buffer
                process(fin, fout)

if __name__ == '__main__':
    main()
