# branchmap.py - logic to computes, maintain and stores branchmap for local repo
#
# Copyright 2005-2007 Olivia Mackall <olivia@selenic.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.


import struct

from .node import (
    bin,
    hex,
    nullrev,
)

from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    TYPE_CHECKING,
    Tuple,
    Union,
)

from . import (
    encoding,
    error,
    obsolete,
    scmutil,
    util,
)

from .utils import (
    repoviewutil,
    stringutil,
)

if TYPE_CHECKING:
    from . import localrepo

    assert [localrepo]

subsettable = repoviewutil.subsettable

calcsize = struct.calcsize
pack_into = struct.pack_into
unpack_from = struct.unpack_from


class BranchMapCache:
    """mapping of filtered views of repo with their branchcache"""

    def __init__(self):
        self._per_filter = {}

    def __getitem__(self, repo):
        self.updatecache(repo)
        bcache = self._per_filter[repo.filtername]
        assert bcache._filtername == repo.filtername, (
            bcache._filtername,
            repo.filtername,
        )
        return bcache

    def update_disk(self, repo):
        """ensure and up-to-date cache is (or will be) written on disk

        The cache for this repository view is updated  if needed and written on
        disk.

        If a transaction is in progress, the writing is schedule to transaction
        close. See the `BranchMapCache.write_dirty` method.

        This method exist independently of __getitem__ as it is sometime useful
        to signal that we have no intend to use the data in memory yet.
        """
        self.updatecache(repo)
        bcache = self._per_filter[repo.filtername]
        assert bcache._filtername == repo.filtername, (
            bcache._filtername,
            repo.filtername,
        )
        tr = repo.currenttransaction()
        if getattr(tr, 'finalized', True):
            bcache.sync_disk(repo)

    def updatecache(self, repo):
        """Update the cache for the given filtered view on a repository"""
        # This can trigger updates for the caches for subsets of the filtered
        # view, e.g. when there is no cache for this filtered view or the cache
        # is stale.

        cl = repo.changelog
        filtername = repo.filtername
        bcache = self._per_filter.get(filtername)
        if bcache is None or not bcache.validfor(repo):
            # cache object missing or cache object stale? Read from disk
            bcache = branch_cache_from_file(repo)

        revs = []
        if bcache is None:
            # no (fresh) cache available anymore, perhaps we can re-use
            # the cache for a subset, then extend that to add info on missing
            # revisions.
            subsetname = subsettable.get(filtername)
            if subsetname is not None:
                subset = repo.filtered(subsetname)
                self.updatecache(subset)
                bcache = self._per_filter[subset.filtername].inherit_for(repo)
                extrarevs = subset.changelog.filteredrevs - cl.filteredrevs
                revs.extend(r for r in extrarevs if r <= bcache.tiprev)
            else:
                # nothing to fall back on, start empty.
                bcache = new_branch_cache(repo)

        revs.extend(cl.revs(start=bcache.tiprev + 1))
        if revs:
            bcache.update(repo, revs)

        assert bcache.validfor(repo), filtername
        self._per_filter[repo.filtername] = bcache

    def replace(self, repo, remotebranchmap):
        """Replace the branchmap cache for a repo with a branch mapping.

        This is likely only called during clone with a branch map from a
        remote.

        """
        cl = repo.changelog
        clrev = cl.rev
        clbranchinfo = cl.branchinfo
        rbheads = []
        closed = set()
        for bheads in remotebranchmap.values():
            rbheads += bheads
            for h in bheads:
                r = clrev(h)
                b, c = clbranchinfo(r)
                if c:
                    closed.add(h)

        if rbheads:
            rtiprev = max((int(clrev(node)) for node in rbheads))
            cache = new_branch_cache(
                repo,
                remotebranchmap,
                repo[rtiprev].node(),
                rtiprev,
                closednodes=closed,
            )

            # Try to stick it as low as possible
            # filter above served are unlikely to be fetch from a clone
            for candidate in (b'base', b'immutable', b'served'):
                rview = repo.filtered(candidate)
                if cache.validfor(rview):
                    cache._filtername = candidate
                    self._per_filter[candidate] = cache
                    cache._state = STATE_DIRTY
                    cache.write(rview)
                    return

    def clear(self):
        self._per_filter.clear()

    def write_dirty(self, repo):
        unfi = repo.unfiltered()
        for filtername in repoviewutil.get_ordered_subset():
            cache = self._per_filter.get(filtername)
            if cache is None:
                continue
            if filtername is None:
                repo = unfi
            else:
                repo = unfi.filtered(filtername)
            cache.sync_disk(repo)


def _unknownnode(node):
    """raises ValueError when branchcache found a node which does not exists"""
    raise ValueError('node %s does not exist' % node.hex())


def _branchcachedesc(repo):
    if repo.filtername is not None:
        return b'branch cache (%s)' % repo.filtername
    else:
        return b'branch cache'


class _BaseBranchCache:
    """A dict like object that hold branches heads cache.

    This cache is used to avoid costly computations to determine all the
    branch heads of a repo.
    """

    def __init__(
        self,
        repo: "localrepo.localrepository",
        entries: Union[
            Dict[bytes, List[bytes]], Iterable[Tuple[bytes, List[bytes]]]
        ] = (),
        closed_nodes: Optional[Set[bytes]] = None,
    ) -> None:
        """hasnode is a function which can be used to verify whether changelog
        has a given node or not. If it's not provided, we assume that every node
        we have exists in changelog"""
        # closednodes is a set of nodes that close their branch. If the branch
        # cache has been updated, it may contain nodes that are no longer
        # heads.
        if closed_nodes is None:
            closed_nodes = set()
        self._closednodes = set(closed_nodes)
        self._entries = dict(entries)

    def __iter__(self):
        return iter(self._entries)

    def __setitem__(self, key, value):
        self._entries[key] = value

    def __getitem__(self, key):
        return self._entries[key]

    def __contains__(self, key):
        return key in self._entries

    def iteritems(self):
        return self._entries.items()

    items = iteritems

    def hasbranch(self, label):
        """checks whether a branch of this name exists or not"""
        return label in self._entries

    def _branchtip(self, heads):
        """Return tuple with last open head in heads and false,
        otherwise return last closed head and true."""
        tip = heads[-1]
        closed = True
        for h in reversed(heads):
            if h not in self._closednodes:
                tip = h
                closed = False
                break
        return tip, closed

    def branchtip(self, branch):
        """Return the tipmost open head on branch head, otherwise return the
        tipmost closed head on branch.
        Raise KeyError for unknown branch."""
        return self._branchtip(self[branch])[0]

    def iteropen(self, nodes):
        return (n for n in nodes if n not in self._closednodes)

    def branchheads(self, branch, closed=False):
        heads = self._entries[branch]
        if not closed:
            heads = list(self.iteropen(heads))
        return heads

    def iterbranches(self):
        for bn, heads in self.items():
            yield (bn, heads) + self._branchtip(heads)

    def iterheads(self):
        """returns all the heads"""
        return self._entries.values()

    def update(self, repo, revgen):
        """Given a branchhead cache, self, that may have extra nodes or be
        missing heads, and a generator of nodes that are strictly a superset of
        heads missing, this function updates self to be correct.
        """
        starttime = util.timer()
        cl = repo.changelog
        # collect new branch entries
        newbranches = {}
        getbranchinfo = repo.revbranchcache().branchinfo
        max_rev = -1
        for r in revgen:
            branch, closesbranch = getbranchinfo(r)
            newbranches.setdefault(branch, []).append(r)
            if closesbranch:
                self._closednodes.add(cl.node(r))
            max_rev = max(max_rev, r)
        if max_rev < 0:
            msg = "running branchcache.update without revision to update"
            raise error.ProgrammingError(msg)

        # Delay fetching the topological heads until they are needed.
        # A repository without non-continous branches can skip this part.
        topoheads = None

        # If a changeset is visible, its parents must be visible too, so
        # use the faster unfiltered parent accessor.
        parentrevs = repo.unfiltered().changelog.parentrevs

        # Faster than using ctx.obsolete()
        obsrevs = obsolete.getrevs(repo, b'obsolete')

        for branch, newheadrevs in newbranches.items():
            # For every branch, compute the new branchheads.
            # A branchhead is a revision such that no descendant is on
            # the same branch.
            #
            # The branchheads are computed iteratively in revision order.
            # This ensures topological order, i.e. parents are processed
            # before their children. Ancestors are inclusive here, i.e.
            # any revision is an ancestor of itself.
            #
            # Core observations:
            # - The current revision is always a branchhead for the
            #   repository up to that point.
            # - It is the first revision of the branch if and only if
            #   there was no branchhead before. In that case, it is the
            #   only branchhead as there are no possible ancestors on
            #   the same branch.
            # - If a parent is on the same branch, a branchhead can
            #   only be an ancestor of that parent, if it is parent
            #   itself. Otherwise it would have been removed as ancestor
            #   of that parent before.
            # - Therefore, if all parents are on the same branch, they
            #   can just be removed from the branchhead set.
            # - If one parent is on the same branch and the other is not
            #   and there was exactly one branchhead known, the existing
            #   branchhead can only be an ancestor if it is the parent.
            #   Otherwise it would have been removed as ancestor of
            #   the parent before. The other parent therefore can't have
            #   a branchhead as ancestor.
            # - In all other cases, the parents on different branches
            #   could have a branchhead as ancestor. Those parents are
            #   kept in the "uncertain" set. If all branchheads are also
            #   topological heads, they can't have descendants and further
            #   checks can be skipped. Otherwise, the ancestors of the
            #   "uncertain" set are removed from branchheads.
            #   This computation is heavy and avoided if at all possible.
            bheads = self._entries.get(branch, [])
            bheadset = {cl.rev(node) for node in bheads}
            uncertain = set()
            for newrev in sorted(newheadrevs):
                if newrev in obsrevs:
                    # We ignore obsolete changesets as they shouldn't be
                    # considered heads.
                    continue

                if not bheadset:
                    bheadset.add(newrev)
                    continue

                parents = [p for p in parentrevs(newrev) if p != nullrev]
                samebranch = set()
                otherbranch = set()
                obsparents = set()
                for p in parents:
                    if p in obsrevs:
                        # We ignored this obsolete changeset earlier, but now
                        # that it has non-ignored children, we need to make
                        # sure their ancestors are not considered heads. To
                        # achieve that, we will simply treat this obsolete
                        # changeset as a parent from other branch.
                        obsparents.add(p)
                    elif p in bheadset or getbranchinfo(p)[0] == branch:
                        samebranch.add(p)
                    else:
                        otherbranch.add(p)
                if not (len(bheadset) == len(samebranch) == 1):
                    uncertain.update(otherbranch)
                    uncertain.update(obsparents)
                bheadset.difference_update(samebranch)
                bheadset.add(newrev)

            if uncertain:
                if topoheads is None:
                    topoheads = set(cl.headrevs())
                if bheadset - topoheads:
                    floorrev = min(bheadset)
                    if floorrev <= max(uncertain):
                        ancestors = set(cl.ancestors(uncertain, floorrev))
                        bheadset -= ancestors
            if bheadset:
                self[branch] = [cl.node(rev) for rev in sorted(bheadset)]

        duration = util.timer() - starttime
        repo.ui.log(
            b'branchcache',
            b'updated %s in %.4f seconds\n',
            _branchcachedesc(repo),
            duration,
        )
        return max_rev


STATE_CLEAN = 1
STATE_INHERITED = 2
STATE_DIRTY = 3


class _LocalBranchCache(_BaseBranchCache):
    """base class of branch-map info for a local repo or repoview"""

    _base_filename = None

    def __init__(
        self,
        repo: "localrepo.localrepository",
        entries: Union[
            Dict[bytes, List[bytes]], Iterable[Tuple[bytes, List[bytes]]]
        ] = (),
        tipnode: Optional[bytes] = None,
        tiprev: Optional[int] = nullrev,
        filteredhash: Optional[bytes] = None,
        closednodes: Optional[Set[bytes]] = None,
        hasnode: Optional[Callable[[bytes], bool]] = None,
        verify_node: bool = False,
        inherited: bool = False,
    ) -> None:
        """hasnode is a function which can be used to verify whether changelog
        has a given node or not. If it's not provided, we assume that every node
        we have exists in changelog"""
        self._filtername = repo.filtername
        if tipnode is None:
            self.tipnode = repo.nullid
        else:
            self.tipnode = tipnode
        self.tiprev = tiprev
        self.filteredhash = filteredhash
        self._state = STATE_CLEAN
        if inherited:
            self._state = STATE_INHERITED

        super().__init__(repo=repo, entries=entries, closed_nodes=closednodes)
        # closednodes is a set of nodes that close their branch. If the branch
        # cache has been updated, it may contain nodes that are no longer
        # heads.

        # Do we need to verify branch at all ?
        self._verify_node = verify_node
        # branches for which nodes are verified
        self._verifiedbranches = set()
        self._hasnode = None
        if self._verify_node:
            self._hasnode = repo.changelog.hasnode

    def validfor(self, repo):
        """check that cache contents are valid for (a subset of) this repo

        - False when the order of changesets changed or if we detect a strip.
        - True when cache is up-to-date for the current repo or its subset."""
        try:
            node = repo.changelog.node(self.tiprev)
        except IndexError:
            # changesets were stripped and now we don't even have enough to
            # find tiprev
            return False
        if self.tipnode != node:
            # tiprev doesn't correspond to tipnode: repo was stripped, or this
            # repo has a different order of changesets
            return False
        tiphash = scmutil.filteredhash(repo, self.tiprev, needobsolete=True)
        # hashes don't match if this repo view has a different set of filtered
        # revisions (e.g. due to phase changes) or obsolete revisions (e.g.
        # history was rewritten)
        return self.filteredhash == tiphash

    @classmethod
    def fromfile(cls, repo):
        f = None
        try:
            f = repo.cachevfs(cls._filename(repo))
            lineiter = iter(f)
            init_kwargs = cls._load_header(repo, lineiter)
            bcache = cls(
                repo,
                verify_node=True,
                **init_kwargs,
            )
            if not bcache.validfor(repo):
                # invalidate the cache
                raise ValueError('tip differs')
            bcache._load_heads(repo, lineiter)
        except (IOError, OSError):
            return None

        except Exception as inst:
            if repo.ui.debugflag:
                msg = b'invalid %s: %s\n'
                msg %= (
                    _branchcachedesc(repo),
                    stringutil.forcebytestr(inst),
                )
                repo.ui.debug(msg)
            bcache = None

        finally:
            if f:
                f.close()

        return bcache

    @classmethod
    def _load_header(cls, repo, lineiter) -> "dict[str, Any]":
        """parse the head of a branchmap file

        return parameters to pass to a newly created class instance.
        """
        cachekey = next(lineiter).rstrip(b'\n').split(b" ", 2)
        last, lrev = cachekey[:2]
        last, lrev = bin(last), int(lrev)
        filteredhash = None
        if len(cachekey) > 2:
            filteredhash = bin(cachekey[2])
        return {
            "tipnode": last,
            "tiprev": lrev,
            "filteredhash": filteredhash,
        }

    def _load_heads(self, repo, lineiter):
        """fully loads the branchcache by reading from the file using the line
        iterator passed"""
        for line in lineiter:
            line = line.rstrip(b'\n')
            if not line:
                continue
            node, state, label = line.split(b" ", 2)
            if state not in b'oc':
                raise ValueError('invalid branch state')
            label = encoding.tolocal(label.strip())
            node = bin(node)
            self._entries.setdefault(label, []).append(node)
            if state == b'c':
                self._closednodes.add(node)

    @classmethod
    def _filename(cls, repo):
        """name of a branchcache file for a given repo or repoview"""
        filename = cls._base_filename
        assert filename is not None
        if repo.filtername:
            filename = b'%s-%s' % (filename, repo.filtername)
        return filename

    def inherit_for(self, repo):
        """return a deep copy of the branchcache object"""
        assert repo.filtername != self._filtername
        other = type(self)(
            repo=repo,
            # we always do a shally copy of self._entries, and the values is
            # always replaced, so no need to deepcopy until the above remains
            # true.
            entries=self._entries,
            tipnode=self.tipnode,
            tiprev=self.tiprev,
            filteredhash=self.filteredhash,
            closednodes=set(self._closednodes),
            verify_node=self._verify_node,
            inherited=True,
        )
        # also copy information about the current verification state
        other._verifiedbranches = set(self._verifiedbranches)
        return other

    def sync_disk(self, repo):
        """synchronise the on disk file with the cache state

        If new value specific to this filter level need to be written, the file
        will be updated, if the state of the branchcache is inherited from a
        subset, any stalled on disk file will be deleted.

        That method does nothing if there is nothing to do.
        """
        if self._state == STATE_DIRTY:
            self.write(repo)
        elif self._state == STATE_INHERITED:
            filename = self._filename(repo)
            repo.cachevfs.tryunlink(filename)

    def write(self, repo):
        assert self._filtername == repo.filtername, (
            self._filtername,
            repo.filtername,
        )
        assert self._state == STATE_DIRTY, self._state
        # This method should not be called during an open transaction
        tr = repo.currenttransaction()
        if not getattr(tr, 'finalized', True):
            msg = "writing branchcache in the middle of a transaction"
            raise error.ProgrammingError(msg)
        try:
            filename = self._filename(repo)
            with repo.cachevfs(filename, b"w", atomictemp=True) as f:
                self._write_header(f)
                nodecount = self._write_heads(f)
            repo.ui.log(
                b'branchcache',
                b'wrote %s with %d labels and %d nodes\n',
                _branchcachedesc(repo),
                len(self._entries),
                nodecount,
            )
            self._state = STATE_CLEAN
        except (IOError, OSError, error.Abort) as inst:
            # Abort may be raised by read only opener, so log and continue
            repo.ui.debug(
                b"couldn't write branch cache: %s\n"
                % stringutil.forcebytestr(inst)
            )

    def _write_header(self, fp) -> None:
        """write the branch cache header to a file"""
        cachekey = [hex(self.tipnode), b'%d' % self.tiprev]
        if self.filteredhash is not None:
            cachekey.append(hex(self.filteredhash))
        fp.write(b" ".join(cachekey) + b'\n')

    def _write_heads(self, fp) -> int:
        """write list of heads to a file

        Return the number of heads written."""
        nodecount = 0
        for label, nodes in sorted(self._entries.items()):
            label = encoding.fromlocal(label)
            for node in nodes:
                nodecount += 1
                if node in self._closednodes:
                    state = b'c'
                else:
                    state = b'o'
                fp.write(b"%s %s %s\n" % (hex(node), state, label))
        return nodecount

    def _verifybranch(self, branch):
        """verify head nodes for the given branch."""
        if not self._verify_node:
            return
        if branch not in self._entries or branch in self._verifiedbranches:
            return
        assert self._hasnode is not None
        for n in self._entries[branch]:
            if not self._hasnode(n):
                _unknownnode(n)

        self._verifiedbranches.add(branch)

    def _verifyall(self):
        """verifies nodes of all the branches"""
        for b in self._entries.keys():
            if b not in self._verifiedbranches:
                self._verifybranch(b)

    def __getitem__(self, key):
        self._verifybranch(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self._verifybranch(key)
        return super().__contains__(key)

    def iteritems(self):
        self._verifyall()
        return super().iteritems()

    items = iteritems

    def iterheads(self):
        """returns all the heads"""
        self._verifyall()
        return super().iterheads()

    def hasbranch(self, label):
        """checks whether a branch of this name exists or not"""
        self._verifybranch(label)
        return super().hasbranch(label)

    def branchheads(self, branch, closed=False):
        self._verifybranch(branch)
        return super().branchheads(branch, closed=closed)

    def update(self, repo, revgen):
        assert self._filtername == repo.filtername, (
            self._filtername,
            repo.filtername,
        )
        cl = repo.changelog
        max_rev = super().update(repo, revgen)
        # new tip revision which we found after iterating items from new
        # branches
        if max_rev is not None and max_rev > self.tiprev:
            self.tiprev = max_rev
            self.tipnode = cl.node(max_rev)

        if not self.validfor(repo):
            # old cache key is now invalid for the repo, but we've just updated
            # the cache and we assume it's valid, so let's make the cache key
            # valid as well by recomputing it from the cached data
            self.tipnode = repo.nullid
            self.tiprev = nullrev
            for heads in self.iterheads():
                if not heads:
                    # all revisions on a branch are obsolete
                    continue
                # note: tiprev is not necessarily the tip revision of repo,
                # because the tip could be obsolete (i.e. not a head)
                tiprev = max(cl.rev(node) for node in heads)
                if tiprev > self.tiprev:
                    self.tipnode = cl.node(tiprev)
                    self.tiprev = tiprev
        self.filteredhash = scmutil.filteredhash(
            repo, self.tiprev, needobsolete=True
        )
        self._state = STATE_DIRTY
        tr = repo.currenttransaction()
        if getattr(tr, 'finalized', True):
            # Avoid premature writing.
            #
            # (The cache warming setup by localrepo will update the file later.)
            self.write(repo)


def branch_cache_from_file(repo) -> Optional[_LocalBranchCache]:
    """Build a branch cache from on-disk data if possible

    Return a branch cache of the right format depending of the repository.
    """
    if repo.ui.configbool(b"experimental", b"branch-cache-v3"):
        return BranchCacheV3.fromfile(repo)
    else:
        return BranchCacheV2.fromfile(repo)


def new_branch_cache(repo, *args, **kwargs):
    """Build a new branch cache from argument

    Return a branch cache of the right format depending of the repository.
    """
    if repo.ui.configbool(b"experimental", b"branch-cache-v3"):
        return BranchCacheV3(repo, *args, **kwargs)
    else:
        return BranchCacheV2(repo, *args, **kwargs)


class BranchCacheV2(_LocalBranchCache):
    """a branch cache using version 2 of the format on disk

    The cache is serialized on disk in the following format:

    <tip hex node> <tip rev number> [optional filtered repo hex hash]
    <branch head hex node> <open/closed state> <branch name>
    <branch head hex node> <open/closed state> <branch name>
    ...

    The first line is used to check if the cache is still valid. If the
    branch cache is for a filtered repo view, an optional third hash is
    included that hashes the hashes of all filtered and obsolete revisions.

    The open/closed state is represented by a single letter 'o' or 'c'.
    This field can be used to avoid changelog reads when determining if a
    branch head closes a branch or not.
    """

    _base_filename = b"branch2"


class BranchCacheV3(_LocalBranchCache):
    """a branch cache using version 3 of the format on disk

    This version is still EXPERIMENTAL and the format is subject to changes.

    The cache is serialized on disk in the following format:

    <cache-key-xxx>=<xxx-value> <cache-key-yyy>=<yyy-value> […]
    <branch head hex node> <open/closed state> <branch name>
    <branch head hex node> <open/closed state> <branch name>
    ...

    The first line is used to check if the cache is still valid. It is a series
    of key value pair. The following key are recognized:

    - tip-rev: the rev-num of the tip-most revision seen by this cache
    - tip-node: the node-id of the tip-most revision sen by this cache
    - filtered-hash: the hash of all filtered and obsolete revisions (before
                     tip-rev) ignored by this cache.

    The tip-rev is used to know how far behind the value in the file are
    compared to the current repository state.

    The tip-node and filtered-hash are used to detect if this cache can be used
    for this repository state at all.

    The open/closed state is represented by a single letter 'o' or 'c'.
    This field can be used to avoid changelog reads when determining if a
    branch head closes a branch or not.
    """

    _base_filename = b"branch3"

    def _write_header(self, fp) -> None:
        cache_keys = {
            b"tip-node": hex(self.tipnode),
            b"tip-rev": b'%d' % self.tiprev,
        }
        if self.filteredhash is not None:
            cache_keys[b"filtered-hash"] = hex(self.filteredhash)
        pieces = (b"%s=%s" % i for i in sorted(cache_keys.items()))
        fp.write(b" ".join(pieces) + b'\n')

    @classmethod
    def _load_header(cls, repo, lineiter):
        header_line = next(lineiter)
        pieces = header_line.rstrip(b'\n').split(b" ")
        cache_keys = dict(p.split(b'=', 1) for p in pieces)

        args = {}
        for k, v in cache_keys.items():
            if k == b"tip-rev":
                args["tiprev"] = int(v)
            elif k == b"tip-node":
                args["tipnode"] = bin(v)
            elif k == b"filtered-hash":
                args["filteredhash"] = bin(v)
            else:
                msg = b"unknown cache key: %r" % k
                raise ValueError(msg)
        return args


class remotebranchcache(_BaseBranchCache):
    """Branchmap info for a remote connection, should not write locally"""

    def __init__(
        self,
        repo: "localrepo.localrepository",
        entries: Union[
            Dict[bytes, List[bytes]], Iterable[Tuple[bytes, List[bytes]]]
        ] = (),
        closednodes: Optional[Set[bytes]] = None,
    ) -> None:
        super().__init__(repo=repo, entries=entries, closed_nodes=closednodes)


# Revision branch info cache

_rbcversion = b'-v1'
_rbcnames = b'rbc-names' + _rbcversion
_rbcrevs = b'rbc-revs' + _rbcversion
# [4 byte hash prefix][4 byte branch name number with sign bit indicating open]
_rbcrecfmt = b'>4sI'
_rbcrecsize = calcsize(_rbcrecfmt)
_rbcmininc = 64 * _rbcrecsize
_rbcnodelen = 4
_rbcbranchidxmask = 0x7FFFFFFF
_rbccloseflag = 0x80000000


class rbcrevs:
    """a byte string consisting of an immutable prefix followed by a mutable suffix"""

    def __init__(self, revs):
        self._prefix = revs
        self._rest = bytearray()

    def __len__(self):
        return len(self._prefix) + len(self._rest)

    def unpack_record(self, rbcrevidx):
        if rbcrevidx < len(self._prefix):
            return unpack_from(_rbcrecfmt, util.buffer(self._prefix), rbcrevidx)
        else:
            return unpack_from(
                _rbcrecfmt,
                util.buffer(self._rest),
                rbcrevidx - len(self._prefix),
            )

    def make_mutable(self):
        if len(self._prefix) > 0:
            entirety = bytearray()
            entirety[:] = self._prefix
            entirety.extend(self._rest)
            self._rest = entirety
            self._prefix = bytearray()

    def truncate(self, pos):
        self.make_mutable()
        del self._rest[pos:]

    def pack_into(self, rbcrevidx, node, branchidx):
        if rbcrevidx < len(self._prefix):
            self.make_mutable()
        buf = self._rest
        start_offset = rbcrevidx - len(self._prefix)
        end_offset = start_offset + _rbcrecsize

        if len(self._rest) < end_offset:
            # bytearray doesn't allocate extra space at least in Python 3.7.
            # When multiple changesets are added in a row, precise resize would
            # result in quadratic complexity. Overallocate to compensate by
            # using the classic doubling technique for dynamic arrays instead.
            # If there was a gap in the map before, less space will be reserved.
            self._rest.extend(b'\0' * end_offset)
        return pack_into(
            _rbcrecfmt,
            buf,
            start_offset,
            node,
            branchidx,
        )

    def extend(self, extension):
        return self._rest.extend(extension)

    def slice(self, begin, end):
        if begin < len(self._prefix):
            acc = bytearray()
            acc[:] = self._prefix[begin:end]
            acc.extend(
                self._rest[begin - len(self._prefix) : end - len(self._prefix)]
            )
            return acc
        return self._rest[begin - len(self._prefix) : end - len(self._prefix)]


class revbranchcache:
    """Persistent cache, mapping from revision number to branch name and close.
    This is a low level cache, independent of filtering.

    Branch names are stored in rbc-names in internal encoding separated by 0.
    rbc-names is append-only, and each branch name is only stored once and will
    thus have a unique index.

    The branch info for each revision is stored in rbc-revs as constant size
    records. The whole file is read into memory, but it is only 'parsed' on
    demand. The file is usually append-only but will be truncated if repo
    modification is detected.
    The record for each revision contains the first 4 bytes of the
    corresponding node hash, and the record is only used if it still matches.
    Even a completely trashed rbc-revs fill thus still give the right result
    while converging towards full recovery ... assuming no incorrectly matching
    node hashes.
    The record also contains 4 bytes where 31 bits contains the index of the
    branch and the last bit indicate that it is a branch close commit.
    The usage pattern for rbc-revs is thus somewhat similar to 00changelog.i
    and will grow with it but be 1/8th of its size.
    """

    def __init__(self, repo, readonly=True):
        assert repo.filtername is None
        self._repo = repo
        self._names = []  # branch names in local encoding with static index
        self._rbcrevs = rbcrevs(bytearray())
        self._rbcsnameslen = 0  # length of names read at _rbcsnameslen
        try:
            bndata = repo.cachevfs.read(_rbcnames)
            self._rbcsnameslen = len(bndata)  # for verification before writing
            if bndata:
                self._names = [
                    encoding.tolocal(bn) for bn in bndata.split(b'\0')
                ]
        except (IOError, OSError):
            if readonly:
                # don't try to use cache - fall back to the slow path
                self.branchinfo = self._branchinfo

        if self._names:
            try:
                if repo.ui.configbool(b'storage', b'revbranchcache.mmap'):
                    with repo.cachevfs(_rbcrevs) as fp:
                        data = util.buffer(util.mmapread(fp))
                else:
                    data = repo.cachevfs.read(_rbcrevs)
                self._rbcrevs = rbcrevs(data)
            except (IOError, OSError) as inst:
                repo.ui.debug(
                    b"couldn't read revision branch cache: %s\n"
                    % stringutil.forcebytestr(inst)
                )
        # remember number of good records on disk
        self._rbcrevslen = min(
            len(self._rbcrevs) // _rbcrecsize, len(repo.changelog)
        )
        if self._rbcrevslen == 0:
            self._names = []
        self._rbcnamescount = len(self._names)  # number of names read at
        # _rbcsnameslen

    def _clear(self):
        self._rbcsnameslen = 0
        del self._names[:]
        self._rbcnamescount = 0
        self._rbcrevslen = len(self._repo.changelog)
        self._rbcrevs = rbcrevs(bytearray(self._rbcrevslen * _rbcrecsize))
        util.clearcachedproperty(self, b'_namesreverse')

    @util.propertycache
    def _namesreverse(self):
        return {b: r for r, b in enumerate(self._names)}

    def branchinfo(self, rev):
        """Return branch name and close flag for rev, using and updating
        persistent cache."""
        changelog = self._repo.changelog
        rbcrevidx = rev * _rbcrecsize

        # avoid negative index, changelog.read(nullrev) is fast without cache
        if rev == nullrev:
            return changelog.branchinfo(rev)

        # if requested rev isn't allocated, grow and cache the rev info
        if len(self._rbcrevs) < rbcrevidx + _rbcrecsize:
            return self._branchinfo(rev)

        # fast path: extract data from cache, use it if node is matching
        reponode = changelog.node(rev)[:_rbcnodelen]
        cachenode, branchidx = self._rbcrevs.unpack_record(rbcrevidx)
        close = bool(branchidx & _rbccloseflag)
        if close:
            branchidx &= _rbcbranchidxmask
        if cachenode == b'\0\0\0\0':
            pass
        elif cachenode == reponode:
            try:
                return self._names[branchidx], close
            except IndexError:
                # recover from invalid reference to unknown branch
                self._repo.ui.debug(
                    b"referenced branch names not found"
                    b" - rebuilding revision branch cache from scratch\n"
                )
                self._clear()
        else:
            # rev/node map has changed, invalidate the cache from here up
            self._repo.ui.debug(
                b"history modification detected - truncating "
                b"revision branch cache to revision %d\n" % rev
            )
            truncate = rbcrevidx + _rbcrecsize
            self._rbcrevs.truncate(truncate)
            self._rbcrevslen = min(self._rbcrevslen, truncate)

        # fall back to slow path and make sure it will be written to disk
        return self._branchinfo(rev)

    def _branchinfo(self, rev):
        """Retrieve branch info from changelog and update _rbcrevs"""
        changelog = self._repo.changelog
        b, close = changelog.branchinfo(rev)
        if b in self._namesreverse:
            branchidx = self._namesreverse[b]
        else:
            branchidx = len(self._names)
            self._names.append(b)
            self._namesreverse[b] = branchidx
        reponode = changelog.node(rev)
        if close:
            branchidx |= _rbccloseflag
        self._setcachedata(rev, reponode, branchidx)
        return b, close

    def setdata(self, rev, changelogrevision):
        """add new data information to the cache"""
        branch, close = changelogrevision.branchinfo

        if branch in self._namesreverse:
            branchidx = self._namesreverse[branch]
        else:
            branchidx = len(self._names)
            self._names.append(branch)
            self._namesreverse[branch] = branchidx
        if close:
            branchidx |= _rbccloseflag
        self._setcachedata(rev, self._repo.changelog.node(rev), branchidx)
        # If no cache data were readable (non exists, bad permission, etc)
        # the cache was bypassing itself by setting:
        #
        #   self.branchinfo = self._branchinfo
        #
        # Since we now have data in the cache, we need to drop this bypassing.
        if 'branchinfo' in vars(self):
            del self.branchinfo

    def _setcachedata(self, rev, node, branchidx):
        """Writes the node's branch data to the in-memory cache data."""
        if rev == nullrev:
            return
        rbcrevidx = rev * _rbcrecsize
        self._rbcrevs.pack_into(rbcrevidx, node, branchidx)
        self._rbcrevslen = min(self._rbcrevslen, rev)

        tr = self._repo.currenttransaction()
        if tr:
            tr.addfinalize(b'write-revbranchcache', self.write)

    def write(self, tr=None):
        """Save branch cache if it is dirty."""
        repo = self._repo
        wlock = None
        step = b''
        try:
            # write the new names
            if self._rbcnamescount < len(self._names):
                wlock = repo.wlock(wait=False)
                step = b' names'
                self._writenames(repo)

            # write the new revs
            start = self._rbcrevslen * _rbcrecsize
            if start != len(self._rbcrevs):
                step = b''
                if wlock is None:
                    wlock = repo.wlock(wait=False)
                self._writerevs(repo, start)

        except (IOError, OSError, error.Abort, error.LockError) as inst:
            repo.ui.debug(
                b"couldn't write revision branch cache%s: %s\n"
                % (step, stringutil.forcebytestr(inst))
            )
        finally:
            if wlock is not None:
                wlock.release()

    def _writenames(self, repo):
        """write the new branch names to revbranchcache"""
        if self._rbcnamescount != 0:
            f = repo.cachevfs.open(_rbcnames, b'ab')
            if f.tell() == self._rbcsnameslen:
                f.write(b'\0')
            else:
                f.close()
                repo.ui.debug(b"%s changed - rewriting it\n" % _rbcnames)
                self._rbcnamescount = 0
                self._rbcrevslen = 0
        if self._rbcnamescount == 0:
            # before rewriting names, make sure references are removed
            repo.cachevfs.unlinkpath(_rbcrevs, ignoremissing=True)
            f = repo.cachevfs.open(_rbcnames, b'wb')
        f.write(
            b'\0'.join(
                encoding.fromlocal(b)
                for b in self._names[self._rbcnamescount :]
            )
        )
        self._rbcsnameslen = f.tell()
        f.close()
        self._rbcnamescount = len(self._names)

    def _writerevs(self, repo, start):
        """write the new revs to revbranchcache"""
        revs = min(len(repo.changelog), len(self._rbcrevs) // _rbcrecsize)
        with repo.cachevfs.open(_rbcrevs, b'ab') as f:
            if f.tell() != start:
                repo.ui.debug(
                    b"truncating cache/%s to %d\n" % (_rbcrevs, start)
                )
                f.seek(start)
                if f.tell() != start:
                    start = 0
                    f.seek(start)
                f.truncate()
            end = revs * _rbcrecsize
            f.write(self._rbcrevs.slice(start, end))
        self._rbcrevslen = revs
