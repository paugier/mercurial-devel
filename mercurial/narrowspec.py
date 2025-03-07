# narrowspec.py - methods for working with a narrow view of a repository
#
# Copyright 2017 Google, Inc.
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import weakref

from .i18n import _
from . import (
    error,
    match as matchmod,
    merge,
    mergestate as mergestatemod,
    scmutil,
    sparse,
    txnutil,
    util,
)

# The file in .hg/store/ that indicates which paths exit in the store
FILENAME = b'narrowspec'
# The file in .hg/ that indicates which paths exit in the dirstate
DIRSTATE_FILENAME = b'narrowspec.dirstate'

# Pattern prefixes that are allowed in narrow patterns. This list MUST
# only contain patterns that are fast and safe to evaluate. Keep in mind
# that patterns are supplied by clients and executed on remote servers
# as part of wire protocol commands. That means that changes to this
# data structure influence the wire protocol and should not be taken
# lightly - especially removals.
VALID_PREFIXES = (
    b'path:',
    b'rootfilesin:',
)


def normalizesplitpattern(kind, pat):
    """Returns the normalized version of a pattern and kind.

    Returns a tuple with the normalized kind and normalized pattern.
    """
    pat = pat.rstrip(b'/')
    _validatepattern(pat)
    return kind, pat


def _numlines(s):
    """Returns the number of lines in s, including ending empty lines."""
    # We use splitlines because it is Unicode-friendly and thus Python 3
    # compatible. However, it does not count empty lines at the end, so trick
    # it by adding a character at the end.
    return len((s + b'x').splitlines())


def _validatepattern(pat):
    """Validates the pattern and aborts if it is invalid.

    Patterns are stored in the narrowspec as newline-separated
    POSIX-style bytestring paths. There's no escaping.
    """

    # We use newlines as separators in the narrowspec file, so don't allow them
    # in patterns.
    if _numlines(pat) > 1:
        raise error.Abort(_(b'newlines are not allowed in narrowspec paths'))

    components = pat.split(b'/')
    if b'.' in components or b'..' in components:
        raise error.Abort(
            _(b'"." and ".." are not allowed in narrowspec paths')
        )


def normalizepattern(pattern, defaultkind=b'path'):
    """Returns the normalized version of a text-format pattern.

    If the pattern has no kind, the default will be added.
    """
    kind, pat = matchmod._patsplit(pattern, defaultkind)
    return b'%s:%s' % normalizesplitpattern(kind, pat)


def parsepatterns(pats):
    """Parses an iterable of patterns into a typed pattern set.

    Patterns are assumed to be ``path:`` if no prefix is present.
    For safety and performance reasons, only some prefixes are allowed.
    See ``validatepatterns()``.

    This function should be used on patterns that come from the user to
    normalize and validate them to the internal data structure used for
    representing patterns.
    """
    res = {normalizepattern(orig) for orig in pats}
    validatepatterns(res)
    return res


def validatepatterns(pats):
    """Validate that patterns are in the expected data structure and format.

    And that is a set of normalized patterns beginning with ``path:`` or
    ``rootfilesin:``.

    This function should be used to validate internal data structures
    and patterns that are loaded from sources that use the internal,
    prefixed pattern representation (but can't necessarily be fully trusted).
    """
    with util.timedcm('narrowspec.validatepatterns(pats size=%d)', len(pats)):
        if not isinstance(pats, set):
            raise error.ProgrammingError(
                b'narrow patterns should be a set; got %r' % pats
            )

        for pat in pats:
            if not pat.startswith(VALID_PREFIXES):
                # Use a Mercurial exception because this can happen due to user
                # bugs (e.g. manually updating spec file).
                raise error.Abort(
                    _(b'invalid prefix on narrow pattern: %s') % pat,
                    hint=_(
                        b'narrow patterns must begin with one of '
                        b'the following: %s'
                    )
                    % b', '.join(VALID_PREFIXES),
                )


def format(includes, excludes):
    output = b'[include]\n'
    for i in sorted(includes - excludes):
        output += i + b'\n'
    output += b'[exclude]\n'
    for e in sorted(excludes):
        output += e + b'\n'
    return output


def match(root, include=None, exclude=None):
    if not include:
        # Passing empty include and empty exclude to matchmod.match()
        # gives a matcher that matches everything, so explicitly use
        # the nevermatcher.
        return matchmod.never()
    return matchmod.match(
        root, b'', [], include=include or [], exclude=exclude or []
    )


def parseconfig(ui, spec):
    # maybe we should care about the profiles returned too
    includepats, excludepats, profiles = sparse.parseconfig(ui, spec, b'narrow')
    if profiles:
        raise error.Abort(
            _(
                b"including other spec files using '%include' is not"
                b" supported in narrowspec"
            )
        )

    validatepatterns(includepats)
    validatepatterns(excludepats)

    return includepats, excludepats


def load(repo):
    # Treat "narrowspec does not exist" the same as "narrowspec file exists
    # and is empty".
    spec = None
    if txnutil.mayhavepending(repo.root):
        pending_path = b"%s.pending" % FILENAME
        if repo.svfs.exists(pending_path):
            spec = repo.svfs.tryread(FILENAME)
    if spec is None:
        spec = repo.svfs.tryread(FILENAME)
    return parseconfig(repo.ui, spec)


def save(repo, includepats, excludepats):
    repo = repo.unfiltered()

    validatepatterns(includepats)
    validatepatterns(excludepats)
    spec = format(includepats, excludepats)

    tr = repo.currenttransaction()
    if tr is None:
        m = "changing narrow spec outside of a transaction"
        raise error.ProgrammingError(m)
    else:
        # the roundtrip is sometime different
        # not taking any chance for now
        value = parseconfig(repo.ui, spec)
        reporef = weakref.ref(repo)

        def clean_pending(tr):
            r = reporef()
            if r is not None:
                r._pending_narrow_pats = None

        tr.addpostclose(b'narrow-spec', clean_pending)
        tr.addabort(b'narrow-spec', clean_pending)
        repo._pending_narrow_pats = value

        def write_spec(f):
            f.write(spec)

        tr.addfilegenerator(
            # XXX think about order at some point
            b"narrow-spec",
            (FILENAME,),
            write_spec,
            location=b'store',
        )


def copytoworkingcopy(repo):
    repo = repo.unfiltered()
    tr = repo.currenttransaction()
    spec = format(*repo.narrowpats)
    if tr is None:
        m = "changing narrow spec outside of a transaction"
        raise error.ProgrammingError(m)
    else:
        reporef = weakref.ref(repo)

        def clean_pending(tr):
            r = reporef()
            if r is not None:
                r._pending_narrow_pats_dirstate = None

        tr.addpostclose(b'narrow-spec-dirstate', clean_pending)
        tr.addabort(b'narrow-spec-dirstate', clean_pending)
        repo._pending_narrow_pats_dirstate = repo.narrowpats

        def write_spec(f):
            f.write(spec)

        tr.addfilegenerator(
            # XXX think about order at some point
            b"narrow-spec-dirstate",
            (DIRSTATE_FILENAME,),
            write_spec,
            location=b'plain',
        )


def restrictpatterns(req_includes, req_excludes, repo_includes, repo_excludes):
    r"""Restricts the patterns according to repo settings,
    results in a logical AND operation

    :param req_includes: requested includes
    :param req_excludes: requested excludes
    :param repo_includes: repo includes
    :param repo_excludes: repo excludes
    :return: include patterns, exclude patterns, and invalid include patterns.
    """
    res_excludes = set(req_excludes)
    res_excludes.update(repo_excludes)
    invalid_includes = []
    if not req_includes:
        res_includes = set(repo_includes)
    elif b'path:.' not in repo_includes:
        res_includes = []
        for req_include in req_includes:
            req_include = util.expandpath(util.normpath(req_include))
            if req_include in repo_includes:
                res_includes.append(req_include)
                continue
            valid = False
            for repo_include in repo_includes:
                if req_include.startswith(repo_include + b'/'):
                    valid = True
                    res_includes.append(req_include)
                    break
            if not valid:
                invalid_includes.append(req_include)
        if len(res_includes) == 0:
            res_excludes = {b'path:.'}
        else:
            res_includes = set(res_includes)
    else:
        res_includes = set(req_includes)
    return res_includes, res_excludes, invalid_includes


# These two are extracted for extensions (specifically for Google's CitC file
# system)
def _deletecleanfiles(repo, files):
    for f in files:
        repo.wvfs.unlinkpath(f)


def _writeaddedfiles(repo, pctx, files):
    mresult = merge.mergeresult()
    mf = repo[b'.'].manifest()
    for f in files:
        if not repo.wvfs.exists(f):
            mresult.addfile(
                f,
                mergestatemod.ACTION_GET,
                (mf.flags(f), False),
                b"narrowspec updated",
            )
    merge.applyupdates(
        repo,
        mresult,
        wctx=repo[None],
        mctx=repo[b'.'],
        overwrite=False,
        wantfiledata=False,
    )


def checkworkingcopynarrowspec(repo):
    # Avoid infinite recursion when updating the working copy
    if getattr(repo, '_updatingnarrowspec', False):
        return
    storespec = repo.narrowpats
    wcspec = repo._pending_narrow_pats_dirstate
    if wcspec is None:
        oldspec = repo.vfs.tryread(DIRSTATE_FILENAME)
        wcspec = parseconfig(repo.ui, oldspec)
    if wcspec != storespec:
        raise error.StateError(
            _(b"working copy's narrowspec is stale"),
            hint=_(b"run 'hg tracked --update-working-copy'"),
        )


def updateworkingcopy(repo, assumeclean=False):
    """updates the working copy and dirstate from the store narrowspec

    When assumeclean=True, files that are not known to be clean will also
    be deleted. It is then up to the caller to make sure they are clean.
    """
    old = repo._pending_narrow_pats_dirstate
    if old is None:
        oldspec = repo.vfs.tryread(DIRSTATE_FILENAME)
        oldincludes, oldexcludes = parseconfig(repo.ui, oldspec)
    else:
        oldincludes, oldexcludes = old
    newincludes, newexcludes = repo.narrowpats
    repo._updatingnarrowspec = True

    oldmatch = match(repo.root, include=oldincludes, exclude=oldexcludes)
    newmatch = match(repo.root, include=newincludes, exclude=newexcludes)
    addedmatch = matchmod.differencematcher(newmatch, oldmatch)
    removedmatch = matchmod.differencematcher(oldmatch, newmatch)

    assert repo.currentwlock() is not None
    ds = repo.dirstate
    with ds.running_status(repo):
        lookup, status, _mtime_boundary = ds.status(
            removedmatch,
            subrepos=[],
            ignored=True,
            clean=True,
            unknown=True,
        )
    trackeddirty = status.modified + status.added
    clean = status.clean
    if assumeclean:
        clean.extend(lookup)
    else:
        trackeddirty.extend(lookup)
    _deletecleanfiles(repo, clean)
    uipathfn = scmutil.getuipathfn(repo)
    for f in sorted(trackeddirty):
        repo.ui.status(
            _(b'not deleting possibly dirty file %s\n') % uipathfn(f)
        )
    for f in sorted(status.unknown):
        repo.ui.status(_(b'not deleting unknown file %s\n') % uipathfn(f))
    for f in sorted(status.ignored):
        repo.ui.status(_(b'not deleting ignored file %s\n') % uipathfn(f))
    for f in clean + trackeddirty:
        ds.update_file(f, p1_tracked=False, wc_tracked=False)

    pctx = repo[b'.']

    # only update added files that are in the sparse checkout
    addedmatch = matchmod.intersectmatchers(addedmatch, sparse.matcher(repo))
    newfiles = [f for f in pctx.manifest().walk(addedmatch) if f not in ds]
    for f in newfiles:
        ds.update_file(f, p1_tracked=True, wc_tracked=True, possibly_dirty=True)
    _writeaddedfiles(repo, pctx, newfiles)
    repo._updatingnarrowspec = False
