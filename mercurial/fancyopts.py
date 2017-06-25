# fancyopts.py - better command line parsing
#
#  Copyright 2005-2009 Matt Mackall <mpm@selenic.com> and others
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from __future__ import absolute_import

from .i18n import _
from . import (
    error,
    pycompat,
)

# Set of flags to not apply boolean negation logic on
nevernegate = {
    # avoid --no-noninteractive
    'noninteractive',
    # These two flags are special because they cause hg to do one
    # thing and then exit, and so aren't suitable for use in things
    # like aliases anyway.
    'help',
    'version',
}

def gnugetopt(args, options, longoptions):
    """Parse options mostly like getopt.gnu_getopt.

    This is different from getopt.gnu_getopt in that an argument of - will
    become an argument of - instead of vanishing completely.
    """
    extraargs = []
    if '--' in args:
        stopindex = args.index('--')
        extraargs = args[stopindex + 1:]
        args = args[:stopindex]
    opts, parseargs = pycompat.getoptb(args, options, longoptions)
    args = []
    while parseargs:
        arg = parseargs.pop(0)
        if arg and arg[0:1] == '-' and len(arg) > 1:
            parseargs.insert(0, arg)
            topts, newparseargs = pycompat.getoptb(parseargs,\
                                            options, longoptions)
            opts = opts + topts
            parseargs = newparseargs
        else:
            args.append(arg)
    args.extend(extraargs)
    return opts, args


def fancyopts(args, options, state, gnu=False):
    """
    read args, parse options, and store options in state

    each option is a tuple of:

      short option or ''
      long option
      default value
      description
      option value label(optional)

    option types include:

      boolean or none - option sets variable in state to true
      string - parameter string is stored in state
      list - parameter string is added to a list
      integer - parameter strings is stored as int
      function - call function with parameter

    non-option args are returned
    """
    namelist = []
    shortlist = ''
    argmap = {}
    defmap = {}
    negations = {}
    alllong = set(o[1] for o in options)

    for option in options:
        if len(option) == 5:
            short, name, default, comment, dummy = option
        else:
            short, name, default, comment = option
        # convert opts to getopt format
        oname = name
        name = name.replace('-', '_')

        argmap['-' + short] = argmap['--' + oname] = name
        defmap[name] = default

        # copy defaults to state
        if isinstance(default, list):
            state[name] = default[:]
        elif callable(default):
            state[name] = None
        else:
            state[name] = default

        # does it take a parameter?
        if not (default is None or default is True or default is False):
            if short:
                short += ':'
            if oname:
                oname += '='
        elif oname not in nevernegate:
            if oname.startswith('no-'):
                insert = oname[3:]
            else:
                insert = 'no-' + oname
            # backout (as a practical example) has both --commit and
            # --no-commit options, so we don't want to allow the
            # negations of those flags.
            if insert not in alllong:
                assert ('--' + oname) not in negations
                negations['--' + insert] = '--' + oname
                namelist.append(insert)
        if short:
            shortlist += short
        if name:
            namelist.append(oname)

    # parse arguments
    if gnu:
        parse = gnugetopt
    else:
        parse = pycompat.getoptb
    opts, args = parse(args, shortlist, namelist)

    # transfer result to state
    for opt, val in opts:
        boolval = True
        negation = negations.get(opt, False)
        if negation:
            opt = negation
            boolval = False
        name = argmap[opt]
        obj = defmap[name]
        t = type(obj)
        if callable(obj):
            state[name] = defmap[name](val)
        elif t is type(1):
            try:
                state[name] = int(val)
            except ValueError:
                raise error.Abort(_('invalid value %r for option %s, '
                                   'expected int') % (val, opt))
        elif t is type(''):
            state[name] = val
        elif t is type([]):
            state[name].append(val)
        elif t is type(None) or t is type(False):
            state[name] = boolval

    # return unparsed args
    return args
