#!/bin/sh

set -e
set -u

cd `hg root`

# Many of the individual files that are excluded here confuse pytype
# because they do a mix of Python 2 and Python 3 things
# conditionally. There's no good way to help it out with that as far as
# I can tell, so let's just hide those files from it for now. We should
# endeavor to empty this list out over time, as some of these are
# probably hiding real problems.
#
# mercurial/bundlerepo.py       # no vfs and ui attrs on bundlerepo
# mercurial/context.py          # many [attribute-error]
# mercurial/crecord.py          # tons of [attribute-error], [module-attr]
# mercurial/debugcommands.py    # [wrong-arg-types]
# mercurial/dispatch.py         # initstdio: No attribute ... on TextIO [attribute-error]
# mercurial/exchange.py         # [attribute-error]
# mercurial/hgweb/hgweb_mod.py  # [attribute-error], [name-error], [wrong-arg-types]
# mercurial/hgweb/server.py     # [attribute-error], [name-error], [module-attr]
# mercurial/hgweb/wsgicgi.py    # confused values in os.environ
# mercurial/httppeer.py         # [attribute-error], [wrong-arg-types]
# mercurial/interfaces          # No attribute 'capabilities' on peer [attribute-error]
# mercurial/keepalive.py        # [attribute-error]
# mercurial/localrepo.py        # [attribute-error]
# mercurial/manifest.py         # [unsupported-operands], [wrong-arg-types]
# mercurial/minirst.py          # [unsupported-operands], [attribute-error]
# mercurial/pure/osutil.py      # [invalid-typevar], [not-callable]
# mercurial/pure/parsers.py     # [attribute-error]
# mercurial/repoview.py         # [attribute-error]
# mercurial/testing/storage.py  # tons of [attribute-error]
# mercurial/unionrepo.py        # ui, svfs, unfiltered [attribute-error]
# mercurial/win32.py            # [not-callable]
# mercurial/wireprotoframing.py # [unsupported-operands], [attribute-error], [import-error]
# mercurial/wireprotov1peer.py  # [attribute-error]
# mercurial/wireprotov1server.py  # BUG?: BundleValueError handler accesses subclass's attrs

# TODO: use --no-cache on test server?  Caching the files locally helps during
#       development, but may be a hinderance for CI testing.

# TODO: include hgext and hgext3rd

pytype -V 3.7 --keep-going --jobs auto doc/check-seclevel.py hgdemandimport mercurial \
    -x mercurial/bundlerepo.py \
    -x mercurial/context.py \
    -x mercurial/crecord.py \
    -x mercurial/debugcommands.py \
    -x mercurial/dispatch.py \
    -x mercurial/exchange.py \
    -x mercurial/hgweb/hgweb_mod.py \
    -x mercurial/hgweb/server.py \
    -x mercurial/hgweb/wsgicgi.py \
    -x mercurial/httppeer.py \
    -x mercurial/interfaces \
    -x mercurial/keepalive.py \
    -x mercurial/localrepo.py \
    -x mercurial/manifest.py \
    -x mercurial/minirst.py \
    -x mercurial/pure/osutil.py \
    -x mercurial/pure/parsers.py \
    -x mercurial/repoview.py \
    -x mercurial/testing/storage.py \
    -x mercurial/thirdparty \
    -x mercurial/unionrepo.py \
    -x mercurial/win32.py \
    -x mercurial/wireprotoframing.py \
    -x mercurial/wireprotov1peer.py \
    -x mercurial/wireprotov1server.py

echo 'pytype crashed while generating the following type stubs:'
find .pytype/pyi -name '*.pyi' | xargs grep -l '# Caught error' | sort
