# revlogdeltas.py - Logic around delta computation for revlog
#
# Copyright 2005-2007 Matt Mackall <mpm@selenic.com>
# Copyright 2018 Octobus <contact@octobus.net>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.
"""Helper class to compute deltas stored inside revlogs"""

from __future__ import absolute_import

import heapq
import struct

# import stuff from node for others to import from revlog
from ..node import (
    nullrev,
)
from ..i18n import _

from .constants import (
    REVIDX_ISCENSORED,
    REVIDX_RAWTEXT_CHANGING_FLAGS,
)

from ..thirdparty import (
    attr,
)

from .. import (
    error,
    mdiff,
)

RevlogError = error.RevlogError
CensoredNodeError = error.CensoredNodeError

# maximum <delta-chain-data>/<revision-text-length> ratio
LIMIT_DELTA2TEXT = 2

class _testrevlog(object):
    """minimalist fake revlog to use in doctests"""

    def __init__(self, data, density=0.5, mingap=0):
        """data is an list of revision payload boundaries"""
        self._data = data
        self._srdensitythreshold = density
        self._srmingapsize = mingap

    def start(self, rev):
        if rev == 0:
            return 0
        return self._data[rev - 1]

    def end(self, rev):
        return self._data[rev]

    def length(self, rev):
        return self.end(rev) - self.start(rev)

    def __len__(self):
        return len(self._data)

def slicechunk(revlog, revs, deltainfo=None, targetsize=None):
    """slice revs to reduce the amount of unrelated data to be read from disk.

    ``revs`` is sliced into groups that should be read in one time.
    Assume that revs are sorted.

    The initial chunk is sliced until the overall density (payload/chunks-span
    ratio) is above `revlog._srdensitythreshold`. No gap smaller than
    `revlog._srmingapsize` is skipped.

    If `targetsize` is set, no chunk larger than `targetsize` will be yield.
    For consistency with other slicing choice, this limit won't go lower than
    `revlog._srmingapsize`.

    If individual revisions chunk are larger than this limit, they will still
    be raised individually.

    >>> revlog = _testrevlog([
    ...  5,  #00 (5)
    ...  10, #01 (5)
    ...  12, #02 (2)
    ...  12, #03 (empty)
    ...  27, #04 (15)
    ...  31, #05 (4)
    ...  31, #06 (empty)
    ...  42, #07 (11)
    ...  47, #08 (5)
    ...  47, #09 (empty)
    ...  48, #10 (1)
    ...  51, #11 (3)
    ...  74, #12 (23)
    ...  85, #13 (11)
    ...  86, #14 (1)
    ...  91, #15 (5)
    ... ])

    >>> list(slicechunk(revlog, list(range(16))))
    [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]]
    >>> list(slicechunk(revlog, [0, 15]))
    [[0], [15]]
    >>> list(slicechunk(revlog, [0, 11, 15]))
    [[0], [11], [15]]
    >>> list(slicechunk(revlog, [0, 11, 13, 15]))
    [[0], [11, 13, 15]]
    >>> list(slicechunk(revlog, [1, 2, 3, 5, 8, 10, 11, 14]))
    [[1, 2], [5, 8, 10, 11], [14]]

    Slicing with a maximum chunk size
    >>> list(slicechunk(revlog, [0, 11, 13, 15], targetsize=15))
    [[0], [11], [13], [15]]
    >>> list(slicechunk(revlog, [0, 11, 13, 15], targetsize=20))
    [[0], [11], [13, 15]]
    """
    if targetsize is not None:
        targetsize = max(targetsize, revlog._srmingapsize)
    # targetsize should not be specified when evaluating delta candidates:
    # * targetsize is used to ensure we stay within specification when reading,
    # * deltainfo is used to pick are good delta chain when writing.
    if not (deltainfo is None or targetsize is None):
        msg = 'cannot use `targetsize` with a `deltainfo`'
        raise error.ProgrammingError(msg)
    for chunk in _slicechunktodensity(revlog, revs,
                                      deltainfo,
                                      revlog._srdensitythreshold,
                                      revlog._srmingapsize):
        for subchunk in _slicechunktosize(revlog, chunk, targetsize):
            yield subchunk

def _slicechunktosize(revlog, revs, targetsize=None):
    """slice revs to match the target size

    This is intended to be used on chunk that density slicing selected by that
    are still too large compared to the read garantee of revlog. This might
    happens when "minimal gap size" interrupted the slicing or when chain are
    built in a way that create large blocks next to each other.

    >>> revlog = _testrevlog([
    ...  3,  #0 (3)
    ...  5,  #1 (2)
    ...  6,  #2 (1)
    ...  8,  #3 (2)
    ...  8,  #4 (empty)
    ...  11, #5 (3)
    ...  12, #6 (1)
    ...  13, #7 (1)
    ...  14, #8 (1)
    ... ])

    Cases where chunk is already small enough
    >>> list(_slicechunktosize(revlog, [0], 3))
    [[0]]
    >>> list(_slicechunktosize(revlog, [6, 7], 3))
    [[6, 7]]
    >>> list(_slicechunktosize(revlog, [0], None))
    [[0]]
    >>> list(_slicechunktosize(revlog, [6, 7], None))
    [[6, 7]]

    cases where we need actual slicing
    >>> list(_slicechunktosize(revlog, [0, 1], 3))
    [[0], [1]]
    >>> list(_slicechunktosize(revlog, [1, 3], 3))
    [[1], [3]]
    >>> list(_slicechunktosize(revlog, [1, 2, 3], 3))
    [[1, 2], [3]]
    >>> list(_slicechunktosize(revlog, [3, 5], 3))
    [[3], [5]]
    >>> list(_slicechunktosize(revlog, [3, 4, 5], 3))
    [[3], [5]]
    >>> list(_slicechunktosize(revlog, [5, 6, 7, 8], 3))
    [[5], [6, 7, 8]]
    >>> list(_slicechunktosize(revlog, [0, 1, 2, 3, 4, 5, 6, 7, 8], 3))
    [[0], [1, 2], [3], [5], [6, 7, 8]]

    Case with too large individual chunk (must return valid chunk)
    >>> list(_slicechunktosize(revlog, [0, 1], 2))
    [[0], [1]]
    >>> list(_slicechunktosize(revlog, [1, 3], 1))
    [[1], [3]]
    >>> list(_slicechunktosize(revlog, [3, 4, 5], 2))
    [[3], [5]]
    """
    assert targetsize is None or 0 <= targetsize
    if targetsize is None or segmentspan(revlog, revs) <= targetsize:
        yield revs
        return

    startrevidx = 0
    startdata = revlog.start(revs[0])
    endrevidx = 0
    iterrevs = enumerate(revs)
    next(iterrevs) # skip first rev.
    for idx, r in iterrevs:
        span = revlog.end(r) - startdata
        if span <= targetsize:
            endrevidx = idx
        else:
            chunk = _trimchunk(revlog, revs, startrevidx, endrevidx + 1)
            if chunk:
                yield chunk
            startrevidx = idx
            startdata = revlog.start(r)
            endrevidx = idx
    yield _trimchunk(revlog, revs, startrevidx)

def _slicechunktodensity(revlog, revs, deltainfo=None, targetdensity=0.5,
                         mingapsize=0):
    """slice revs to reduce the amount of unrelated data to be read from disk.

    ``revs`` is sliced into groups that should be read in one time.
    Assume that revs are sorted.

    ``deltainfo`` is a _deltainfo instance of a revision that we would append
    to the top of the revlog.

    The initial chunk is sliced until the overall density (payload/chunks-span
    ratio) is above `targetdensity`. No gap smaller than `mingapsize` is
    skipped.

    >>> revlog = _testrevlog([
    ...  5,  #00 (5)
    ...  10, #01 (5)
    ...  12, #02 (2)
    ...  12, #03 (empty)
    ...  27, #04 (15)
    ...  31, #05 (4)
    ...  31, #06 (empty)
    ...  42, #07 (11)
    ...  47, #08 (5)
    ...  47, #09 (empty)
    ...  48, #10 (1)
    ...  51, #11 (3)
    ...  74, #12 (23)
    ...  85, #13 (11)
    ...  86, #14 (1)
    ...  91, #15 (5)
    ... ])

    >>> list(_slicechunktodensity(revlog, list(range(16))))
    [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]]
    >>> list(_slicechunktodensity(revlog, [0, 15]))
    [[0], [15]]
    >>> list(_slicechunktodensity(revlog, [0, 11, 15]))
    [[0], [11], [15]]
    >>> list(_slicechunktodensity(revlog, [0, 11, 13, 15]))
    [[0], [11, 13, 15]]
    >>> list(_slicechunktodensity(revlog, [1, 2, 3, 5, 8, 10, 11, 14]))
    [[1, 2], [5, 8, 10, 11], [14]]
    >>> list(_slicechunktodensity(revlog, [1, 2, 3, 5, 8, 10, 11, 14],
    ...                           mingapsize=20))
    [[1, 2, 3, 5, 8, 10, 11], [14]]
    >>> list(_slicechunktodensity(revlog, [1, 2, 3, 5, 8, 10, 11, 14],
    ...                           targetdensity=0.95))
    [[1, 2], [5], [8, 10, 11], [14]]
    >>> list(_slicechunktodensity(revlog, [1, 2, 3, 5, 8, 10, 11, 14],
    ...                           targetdensity=0.95, mingapsize=12))
    [[1, 2], [5, 8, 10, 11], [14]]
    """
    start = revlog.start
    length = revlog.length

    if len(revs) <= 1:
        yield revs
        return

    nextrev = len(revlog)
    nextoffset = revlog.end(nextrev - 1)

    if deltainfo is None:
        deltachainspan = segmentspan(revlog, revs)
        chainpayload = sum(length(r) for r in revs)
    else:
        deltachainspan = deltainfo.distance
        chainpayload = deltainfo.compresseddeltalen

    if deltachainspan < mingapsize:
        yield revs
        return

    readdata = deltachainspan

    if deltachainspan:
        density = chainpayload / float(deltachainspan)
    else:
        density = 1.0

    if density >= targetdensity:
        yield revs
        return

    if deltainfo is not None and deltainfo.deltalen:
        revs = list(revs)
        revs.append(nextrev)

    # Store the gaps in a heap to have them sorted by decreasing size
    gapsheap = []
    heapq.heapify(gapsheap)
    prevend = None
    for i, rev in enumerate(revs):
        if rev < nextrev:
            revstart = start(rev)
            revlen = length(rev)
        else:
            revstart = nextoffset
            revlen = deltainfo.deltalen

        # Skip empty revisions to form larger holes
        if revlen == 0:
            continue

        if prevend is not None:
            gapsize = revstart - prevend
            # only consider holes that are large enough
            if gapsize > mingapsize:
                heapq.heappush(gapsheap, (-gapsize, i))

        prevend = revstart + revlen

    # Collect the indices of the largest holes until the density is acceptable
    indicesheap = []
    heapq.heapify(indicesheap)
    while gapsheap and density < targetdensity:
        oppgapsize, gapidx = heapq.heappop(gapsheap)

        heapq.heappush(indicesheap, gapidx)

        # the gap sizes are stored as negatives to be sorted decreasingly
        # by the heap
        readdata -= (-oppgapsize)
        if readdata > 0:
            density = chainpayload / float(readdata)
        else:
            density = 1.0

    # Cut the revs at collected indices
    previdx = 0
    while indicesheap:
        idx = heapq.heappop(indicesheap)

        chunk = _trimchunk(revlog, revs, previdx, idx)
        if chunk:
            yield chunk

        previdx = idx

    chunk = _trimchunk(revlog, revs, previdx)
    if chunk:
        yield chunk

def _trimchunk(revlog, revs, startidx, endidx=None):
    """returns revs[startidx:endidx] without empty trailing revs

    Doctest Setup
    >>> revlog = _testrevlog([
    ...  5,  #0
    ...  10, #1
    ...  12, #2
    ...  12, #3 (empty)
    ...  17, #4
    ...  21, #5
    ...  21, #6 (empty)
    ... ])

    Contiguous cases:
    >>> _trimchunk(revlog, [0, 1, 2, 3, 4, 5, 6], 0)
    [0, 1, 2, 3, 4, 5]
    >>> _trimchunk(revlog, [0, 1, 2, 3, 4, 5, 6], 0, 5)
    [0, 1, 2, 3, 4]
    >>> _trimchunk(revlog, [0, 1, 2, 3, 4, 5, 6], 0, 4)
    [0, 1, 2]
    >>> _trimchunk(revlog, [0, 1, 2, 3, 4, 5, 6], 2, 4)
    [2]
    >>> _trimchunk(revlog, [0, 1, 2, 3, 4, 5, 6], 3)
    [3, 4, 5]
    >>> _trimchunk(revlog, [0, 1, 2, 3, 4, 5, 6], 3, 5)
    [3, 4]

    Discontiguous cases:
    >>> _trimchunk(revlog, [1, 3, 5, 6], 0)
    [1, 3, 5]
    >>> _trimchunk(revlog, [1, 3, 5, 6], 0, 2)
    [1]
    >>> _trimchunk(revlog, [1, 3, 5, 6], 1, 3)
    [3, 5]
    >>> _trimchunk(revlog, [1, 3, 5, 6], 1)
    [3, 5]
    """
    length = revlog.length

    if endidx is None:
        endidx = len(revs)

    # If we have a non-emtpy delta candidate, there are nothing to trim
    if revs[endidx - 1] < len(revlog):
        # Trim empty revs at the end, except the very first revision of a chain
        while (endidx > 1
                and endidx > startidx
                and length(revs[endidx - 1]) == 0):
            endidx -= 1

    return revs[startidx:endidx]

def segmentspan(revlog, revs, deltainfo=None):
    """Get the byte span of a segment of revisions

    revs is a sorted array of revision numbers

    >>> revlog = _testrevlog([
    ...  5,  #0
    ...  10, #1
    ...  12, #2
    ...  12, #3 (empty)
    ...  17, #4
    ... ])

    >>> segmentspan(revlog, [0, 1, 2, 3, 4])
    17
    >>> segmentspan(revlog, [0, 4])
    17
    >>> segmentspan(revlog, [3, 4])
    5
    >>> segmentspan(revlog, [1, 2, 3,])
    7
    >>> segmentspan(revlog, [1, 3])
    7
    """
    if not revs:
        return 0
    if deltainfo is not None and len(revlog) <= revs[-1]:
        if len(revs) == 1:
            return deltainfo.deltalen
        offset = revlog.end(len(revlog) - 1)
        end = deltainfo.deltalen + offset
    else:
        end = revlog.end(revs[-1])
    return end - revlog.start(revs[0])

def _textfromdelta(fh, revlog, baserev, delta, p1, p2, flags, expectednode):
    """build full text from a (base, delta) pair and other metadata"""
    # special case deltas which replace entire base; no need to decode
    # base revision. this neatly avoids censored bases, which throw when
    # they're decoded.
    hlen = struct.calcsize(">lll")
    if delta[:hlen] == mdiff.replacediffheader(revlog.rawsize(baserev),
                                               len(delta) - hlen):
        fulltext = delta[hlen:]
    else:
        # deltabase is rawtext before changed by flag processors, which is
        # equivalent to non-raw text
        basetext = revlog.revision(baserev, _df=fh, raw=False)
        fulltext = mdiff.patch(basetext, delta)

    try:
        res = revlog._processflags(fulltext, flags, 'read', raw=True)
        fulltext, validatehash = res
        if validatehash:
            revlog.checkhash(fulltext, expectednode, p1=p1, p2=p2)
        if flags & REVIDX_ISCENSORED:
            raise RevlogError(_('node %s is not censored') % expectednode)
    except CensoredNodeError:
        # must pass the censored index flag to add censored revisions
        if not flags & REVIDX_ISCENSORED:
            raise
    return fulltext

@attr.s(slots=True, frozen=True)
class _deltainfo(object):
    distance = attr.ib()
    deltalen = attr.ib()
    data = attr.ib()
    base = attr.ib()
    chainbase = attr.ib()
    chainlen = attr.ib()
    compresseddeltalen = attr.ib()
    snapshotdepth = attr.ib()

def isgooddeltainfo(revlog, deltainfo, revinfo):
    """Returns True if the given delta is good. Good means that it is within
    the disk span, disk size, and chain length bounds that we know to be
    performant."""
    if deltainfo is None:
        return False

    # - 'deltainfo.distance' is the distance from the base revision --
    #   bounding it limits the amount of I/O we need to do.
    # - 'deltainfo.compresseddeltalen' is the sum of the total size of
    #   deltas we need to apply -- bounding it limits the amount of CPU
    #   we consume.

    if revlog._sparserevlog:
        # As sparse-read will be used, we can consider that the distance,
        # instead of being the span of the whole chunk,
        # is the span of the largest read chunk
        base = deltainfo.base

        if base != nullrev:
            deltachain = revlog._deltachain(base)[0]
        else:
            deltachain = []

        # search for the first non-snapshot revision
        for idx, r in enumerate(deltachain):
            if not revlog.issnapshot(r):
                break
        deltachain = deltachain[idx:]
        chunks = slicechunk(revlog, deltachain, deltainfo)
        all_span = [segmentspan(revlog, revs, deltainfo)
                    for revs in chunks]
        distance = max(all_span)
    else:
        distance = deltainfo.distance

    textlen = revinfo.textlen
    defaultmax = textlen * 4
    maxdist = revlog._maxdeltachainspan
    if not maxdist:
        maxdist = distance # ensure the conditional pass
    maxdist = max(maxdist, defaultmax)
    if revlog._sparserevlog and maxdist < revlog._srmingapsize:
        # In multiple place, we are ignoring irrelevant data range below a
        # certain size. Be also apply this tradeoff here and relax span
        # constraint for small enought content.
        maxdist = revlog._srmingapsize

    # Bad delta from read span:
    #
    #   If the span of data read is larger than the maximum allowed.
    if maxdist < distance:
        return False

    # Bad delta from new delta size:
    #
    #   If the delta size is larger than the target text, storing the
    #   delta will be inefficient.
    if textlen < deltainfo.deltalen:
        return False

    # Bad delta from cumulated payload size:
    #
    #   If the sum of delta get larger than K * target text length.
    if textlen * LIMIT_DELTA2TEXT < deltainfo.compresseddeltalen:
        return False

    # Bad delta from chain length:
    #
    #   If the number of delta in the chain gets too high.
    if (revlog._maxchainlen
            and revlog._maxchainlen < deltainfo.chainlen):
        return False

    # bad delta from intermediate snapshot size limit
    #
    #   If an intermediate snapshot size is higher than the limit.  The
    #   limit exist to prevent endless chain of intermediate delta to be
    #   created.
    if (deltainfo.snapshotdepth is not None and
            (textlen >> deltainfo.snapshotdepth) < deltainfo.deltalen):
        return False

    # bad delta if new intermediate snapshot is larger than the previous
    # snapshot
    if (deltainfo.snapshotdepth
            and revlog.length(deltainfo.base) < deltainfo.deltalen):
        return False

    return True

def _candidategroups(revlog, p1, p2, cachedelta):
    """
    Provides revisions that present an interest to be diffed against,
    grouped by level of easiness.
    """
    gdelta = revlog._generaldelta
    curr = len(revlog)
    prev = curr - 1
    p1r, p2r = revlog.rev(p1), revlog.rev(p2)

    # should we try to build a delta?
    if prev != nullrev and revlog._storedeltachains:
        tested = set()
        # This condition is true most of the time when processing
        # changegroup data into a generaldelta repo. The only time it
        # isn't true is if this is the first revision in a delta chain
        # or if ``format.generaldelta=true`` disabled ``lazydeltabase``.
        if cachedelta and gdelta and revlog._lazydeltabase:
            # Assume what we received from the server is a good choice
            # build delta will reuse the cache
            yield (cachedelta[0],)
            tested.add(cachedelta[0])

        if gdelta:
            # exclude already lazy tested base if any
            parents = [p for p in (p1r, p2r)
                       if p != nullrev and p not in tested]

            if not revlog._deltabothparents and len(parents) == 2:
                parents.sort()
                # To minimize the chance of having to build a fulltext,
                # pick first whichever parent is closest to us (max rev)
                yield (parents[1],)
                # then the other one (min rev) if the first did not fit
                yield (parents[0],)
                tested.update(parents)
            elif len(parents) > 0:
                # Test all parents (1 or 2), and keep the best candidate
                yield parents
                tested.update(parents)

        if prev not in tested:
            # other approach failed try against prev to hopefully save us a
            # fulltext.
            yield (prev,)
            tested.add(prev)

class deltacomputer(object):
    def __init__(self, revlog):
        self.revlog = revlog

    def buildtext(self, revinfo, fh):
        """Builds a fulltext version of a revision

        revinfo: _revisioninfo instance that contains all needed info
        fh:      file handle to either the .i or the .d revlog file,
                 depending on whether it is inlined or not
        """
        btext = revinfo.btext
        if btext[0] is not None:
            return btext[0]

        revlog = self.revlog
        cachedelta = revinfo.cachedelta
        baserev = cachedelta[0]
        delta = cachedelta[1]

        fulltext = btext[0] = _textfromdelta(fh, revlog, baserev, delta,
                                             revinfo.p1, revinfo.p2,
                                             revinfo.flags, revinfo.node)
        return fulltext

    def _builddeltadiff(self, base, revinfo, fh):
        revlog = self.revlog
        t = self.buildtext(revinfo, fh)
        if revlog.iscensored(base):
            # deltas based on a censored revision must replace the
            # full content in one patch, so delta works everywhere
            header = mdiff.replacediffheader(revlog.rawsize(base), len(t))
            delta = header + t
        else:
            ptext = revlog.revision(base, _df=fh, raw=True)
            delta = mdiff.textdiff(ptext, t)

        return delta

    def _builddeltainfo(self, revinfo, base, fh):
        # can we use the cached delta?
        if revinfo.cachedelta and revinfo.cachedelta[0] == base:
            delta = revinfo.cachedelta[1]
        else:
            delta = self._builddeltadiff(base, revinfo, fh)
        revlog = self.revlog
        header, data = revlog.compress(delta)
        deltalen = len(header) + len(data)
        chainbase = revlog.chainbase(base)
        offset = revlog.end(len(revlog) - 1)
        dist = deltalen + offset - revlog.start(chainbase)
        if revlog._generaldelta:
            deltabase = base
        else:
            deltabase = chainbase
        chainlen, compresseddeltalen = revlog._chaininfo(base)
        chainlen += 1
        compresseddeltalen += deltalen

        revlog = self.revlog
        snapshotdepth = None
        if deltabase == nullrev:
            snapshotdepth = 0
        elif revlog._sparserevlog and revlog.issnapshot(deltabase):
            # A delta chain should always be one full snapshot,
            # zero or more semi-snapshots, and zero or more deltas
            p1, p2 = revlog.rev(revinfo.p1), revlog.rev(revinfo.p2)
            if deltabase not in (p1, p2) and revlog.issnapshot(deltabase):
                snapshotdepth = len(revlog._deltachain(deltabase)[0])

        return _deltainfo(dist, deltalen, (header, data), deltabase,
                          chainbase, chainlen, compresseddeltalen,
                          snapshotdepth)

    def _fullsnapshotinfo(self, fh, revinfo):
        curr = len(self.revlog)
        rawtext = self.buildtext(revinfo, fh)
        data = self.revlog.compress(rawtext)
        compresseddeltalen = deltalen = dist = len(data[1]) + len(data[0])
        deltabase = chainbase = curr
        snapshotdepth = 0
        chainlen = 1

        return _deltainfo(dist, deltalen, data, deltabase,
                          chainbase, chainlen, compresseddeltalen,
                          snapshotdepth)

    def finddeltainfo(self, revinfo, fh):
        """Find an acceptable delta against a candidate revision

        revinfo: information about the revision (instance of _revisioninfo)
        fh:      file handle to either the .i or the .d revlog file,
                 depending on whether it is inlined or not

        Returns the first acceptable candidate revision, as ordered by
        _candidategroups

        If no suitable deltabase is found, we return delta info for a full
        snapshot.
        """
        if not revinfo.textlen:
            return self._fullsnapshotinfo(fh, revinfo)

        # no delta for flag processor revision (see "candelta" for why)
        # not calling candelta since only one revision needs test, also to
        # avoid overhead fetching flags again.
        if revinfo.flags & REVIDX_RAWTEXT_CHANGING_FLAGS:
            return self._fullsnapshotinfo(fh, revinfo)

        cachedelta = revinfo.cachedelta
        p1 = revinfo.p1
        p2 = revinfo.p2
        revlog = self.revlog

        deltalength = self.revlog.length
        deltaparent = self.revlog.deltaparent

        deltainfo = None
        deltas_limit = revinfo.textlen * LIMIT_DELTA2TEXT
        groups = _candidategroups(self.revlog, p1, p2, cachedelta)
        for candidaterevs in groups:
            # filter out delta base that will never produce good delta
            candidaterevs = [r for r in candidaterevs
                             if self.revlog.length(r) <= deltas_limit]
            nominateddeltas = []
            for candidaterev in candidaterevs:
                # skip over empty delta (no need to include them in a chain)
                while candidaterev != nullrev and not deltalength(candidaterev):
                    candidaterev = deltaparent(candidaterev)
                # no need to try a delta against nullid, this will be handled
                # by fulltext later.
                if candidaterev == nullrev:
                    continue
                # no delta for rawtext-changing revs (see "candelta" for why)
                if revlog.flags(candidaterev) & REVIDX_RAWTEXT_CHANGING_FLAGS:
                    continue
                candidatedelta = self._builddeltainfo(revinfo, candidaterev, fh)
                if isgooddeltainfo(self.revlog, candidatedelta, revinfo):
                    nominateddeltas.append(candidatedelta)
            if nominateddeltas:
                deltainfo = min(nominateddeltas, key=lambda x: x.deltalen)
                break

        if deltainfo is None:
            deltainfo = self._fullsnapshotinfo(fh, revinfo)
        return deltainfo
