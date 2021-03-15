"""revset to select sample of repository

Hopefully this is useful to create interesting discovery cases.
"""

import collections
import random

from mercurial.i18n import _

from mercurial import (
    registrar,
    revset,
    revsetlang,
    smartset,
)

revsetpredicate = registrar.revsetpredicate()


@revsetpredicate(b'scratch(REVS, <count>, [seed])')
def scratch(repo, subset, x):
    """randomly remove <count> revision from the repository top

    This subset is created by recursively picking changeset starting from the
    heads. It can be summarized using the following algorithm::

        selected = set()
        for i in range(<count>):
            unselected = repo.revs("not <selected>")
            candidates = repo.revs("heads(<unselected>)")
            pick = random.choice(candidates)
            selected.add(pick)
    """
    m = _(b"scratch expects revisions, count argument and an optional seed")
    args = revsetlang.getargs(x, 2, 3, m)
    if len(args) == 2:
        x, n = args
        rand = random
    elif len(args) == 3:
        x, n, seed = args
        seed = revsetlang.getinteger(seed, _(b"seed should be a number"))
        rand = random.Random(seed)
    else:
        assert False

    n = revsetlang.getinteger(n, _(b"scratch expects a number"))

    selected = set()
    heads = set()
    children_count = collections.defaultdict(lambda: 0)
    parents = repo.changelog._uncheckedparentrevs

    baseset = revset.getset(repo, smartset.fullreposet(repo), x)
    baseset.sort()
    for r in baseset:
        heads.add(r)

        p1, p2 = parents(r)
        if p1 >= 0:
            heads.discard(p1)
            children_count[p1] += 1
        if p2 >= 0:
            heads.discard(p2)
            children_count[p2] += 1

    for h in heads:
        assert children_count[h] == 0

    selected = set()
    for x in range(n):
        if not heads:
            break
        pick = rand.choice(list(heads))
        heads.remove(pick)
        assert pick not in selected
        selected.add(pick)
        p1, p2 = parents(pick)
        if p1 in children_count:
            assert p1 in children_count
            children_count[p1] -= 1
            assert children_count[p1] >= 0
            if children_count[p1] == 0:
                assert p1 not in selected, (r, p1)
                heads.add(p1)
        if p2 in children_count:
            assert p2 in children_count
            children_count[p2] -= 1
            assert children_count[p2] >= 0
            if children_count[p2] == 0:
                assert p2 not in selected, (r, p2)
                heads.add(p2)

    return smartset.baseset(selected) & subset
