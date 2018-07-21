# filesetlang.py - parser, tokenizer and utility for file set language
#
# Copyright 2010 Matt Mackall <mpm@selenic.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from __future__ import absolute_import

from .i18n import _
from . import (
    error,
    parser,
    pycompat,
)

# common weight constants for static optimization
# (see registrar.filesetpredicate for details)
WEIGHT_CHECK_FILENAME = 0.5
WEIGHT_READ_CONTENTS = 30
WEIGHT_STATUS = 10
WEIGHT_STATUS_THOROUGH = 50

elements = {
    # token-type: binding-strength, primary, prefix, infix, suffix
    "(": (20, None, ("group", 1, ")"), ("func", 1, ")"), None),
    ":": (15, None, None, ("kindpat", 15), None),
    "-": (5, None, ("negate", 19), ("minus", 5), None),
    "not": (10, None, ("not", 10), None, None),
    "!": (10, None, ("not", 10), None, None),
    "and": (5, None, None, ("and", 5), None),
    "&": (5, None, None, ("and", 5), None),
    "or": (4, None, None, ("or", 4), None),
    "|": (4, None, None, ("or", 4), None),
    "+": (4, None, None, ("or", 4), None),
    ",": (2, None, None, ("list", 2), None),
    ")": (0, None, None, None, None),
    "symbol": (0, "symbol", None, None, None),
    "string": (0, "string", None, None, None),
    "end": (0, None, None, None, None),
}

keywords = {'and', 'or', 'not'}

symbols = {}

globchars = ".*{}[]?/\\_"

def tokenize(program):
    pos, l = 0, len(program)
    program = pycompat.bytestr(program)
    while pos < l:
        c = program[pos]
        if c.isspace(): # skip inter-token whitespace
            pass
        elif c in "(),-:|&+!": # handle simple operators
            yield (c, None, pos)
        elif (c in '"\'' or c == 'r' and
              program[pos:pos + 2] in ("r'", 'r"')): # handle quoted strings
            if c == 'r':
                pos += 1
                c = program[pos]
                decode = lambda x: x
            else:
                decode = parser.unescapestr
            pos += 1
            s = pos
            while pos < l: # find closing quote
                d = program[pos]
                if d == '\\': # skip over escaped characters
                    pos += 2
                    continue
                if d == c:
                    yield ('string', decode(program[s:pos]), s)
                    break
                pos += 1
            else:
                raise error.ParseError(_("unterminated string"), s)
        elif c.isalnum() or c in globchars or ord(c) > 127:
            # gather up a symbol/keyword
            s = pos
            pos += 1
            while pos < l: # find end of symbol
                d = program[pos]
                if not (d.isalnum() or d in globchars or ord(d) > 127):
                    break
                pos += 1
            sym = program[s:pos]
            if sym in keywords: # operator keywords
                yield (sym, None, s)
            else:
                yield ('symbol', sym, s)
            pos -= 1
        else:
            raise error.ParseError(_("syntax error"), pos)
        pos += 1
    yield ('end', None, pos)

def parse(expr):
    p = parser.parser(elements)
    tree, pos = p.parse(tokenize(expr))
    if pos != len(expr):
        raise error.ParseError(_("invalid token"), pos)
    return parser.simplifyinfixops(tree, {'list', 'or'})

def getsymbol(x):
    if x and x[0] == 'symbol':
        return x[1]
    raise error.ParseError(_('not a symbol'))

def getstring(x, err):
    if x and (x[0] == 'string' or x[0] == 'symbol'):
        return x[1]
    raise error.ParseError(err)

def getkindpat(x, y, allkinds, err):
    kind = getsymbol(x)
    pat = getstring(y, err)
    if kind not in allkinds:
        raise error.ParseError(_("invalid pattern kind: %s") % kind)
    return '%s:%s' % (kind, pat)

def getpattern(x, allkinds, err):
    if x and x[0] == 'kindpat':
        return getkindpat(x[1], x[2], allkinds, err)
    return getstring(x, err)

def getlist(x):
    if not x:
        return []
    if x[0] == 'list':
        return list(x[1:])
    return [x]

def getargs(x, min, max, err):
    l = getlist(x)
    if len(l) < min or len(l) > max:
        raise error.ParseError(err)
    return l

def _analyze(x):
    if x is None:
        return x

    op = x[0]
    if op in {'string', 'symbol'}:
        return x
    if op == 'kindpat':
        getsymbol(x[1])  # kind must be a symbol
        t = _analyze(x[2])
        return (op, x[1], t)
    if op == 'group':
        return _analyze(x[1])
    if op == 'negate':
        raise error.ParseError(_("can't use negate operator in this context"))
    if op == 'not':
        t = _analyze(x[1])
        return (op, t)
    if op == 'and':
        ta = _analyze(x[1])
        tb = _analyze(x[2])
        return (op, ta, tb)
    if op == 'minus':
        return _analyze(('and', x[1], ('not', x[2])))
    if op in {'list', 'or'}:
        ts = tuple(_analyze(y) for y in x[1:])
        return (op,) + ts
    if op == 'func':
        getsymbol(x[1])  # function name must be a symbol
        ta = _analyze(x[2])
        return (op, x[1], ta)
    raise error.ProgrammingError('invalid operator %r' % op)

def analyze(x):
    """Transform raw parsed tree to evaluatable tree which can be fed to
    optimize() or getmatch()

    All pseudo operations should be mapped to real operations or functions
    defined in methods or symbols table respectively.
    """
    return _analyze(x)

def _optimizeandops(op, ta, tb):
    if tb is not None and tb[0] == 'not':
        return ('minus', ta, tb[1])
    return (op, ta, tb)

def _optimize(x):
    if x is None:
        return 0, x

    op = x[0]
    if op in {'string', 'symbol'}:
        return WEIGHT_CHECK_FILENAME, x
    if op == 'kindpat':
        w, t = _optimize(x[2])
        return w, (op, x[1], t)
    if op == 'not':
        w, t = _optimize(x[1])
        return w, (op, t)
    if op == 'and':
        wa, ta = _optimize(x[1])
        wb, tb = _optimize(x[2])
        if wa <= wb:
            return wa, _optimizeandops(op, ta, tb)
        else:
            return wb, _optimizeandops(op, tb, ta)
    if op == 'or':
        ws, ts = zip(*(_optimize(y) for y in x[1:]))
        ts = tuple(it[1] for it in sorted(enumerate(ts),
                                          key=lambda it: ws[it[0]]))
        return max(ws), (op,) + ts
    if op == 'list':
        ws, ts = zip(*(_optimize(y) for y in x[1:]))
        return sum(ws), (op,) + ts
    if op == 'func':
        f = getsymbol(x[1])
        w = getattr(symbols.get(f), '_weight', 1)
        wa, ta = _optimize(x[2])
        return w + wa, (op, x[1], ta)
    raise error.ProgrammingError('invalid operator %r' % op)

def optimize(x):
    """Reorder/rewrite evaluatable tree for optimization

    All pseudo operations should be transformed beforehand.
    """
    _w, t = _optimize(x)
    return t

def prettyformat(tree):
    return parser.prettyformat(tree, ('string', 'symbol'))
