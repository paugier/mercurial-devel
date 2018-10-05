# narrowwirepeer.py - passes narrow spec with unbundle command
#
# Copyright 2017 Google, Inc.
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from __future__ import absolute_import

from mercurial import (
    bundle2,
    error,
    extensions,
    hg,
    narrowspec,
    pycompat,
    wireprototypes,
    wireprotov1peer,
    wireprotov1server,
)

def uisetup():
    wireprotov1peer.wirepeer.narrow_widen = peernarrowwiden

def reposetup(repo):
    def wirereposetup(ui, peer):
        def wrapped(orig, cmd, *args, **kwargs):
            if cmd == 'unbundle':
                # TODO: don't blindly add include/exclude wireproto
                # arguments to unbundle.
                include, exclude = repo.narrowpats
                kwargs[r"includepats"] = ','.join(include)
                kwargs[r"excludepats"] = ','.join(exclude)
            return orig(cmd, *args, **kwargs)
        extensions.wrapfunction(peer, '_calltwowaystream', wrapped)
    hg.wirepeersetupfuncs.append(wirereposetup)

@wireprotov1server.wireprotocommand('narrow_widen', 'oldincludes oldexcludes'
                                                    ' newincludes newexcludes'
                                                    ' commonheads cgversion'
                                                    ' known ellipses',
                                    permission='pull')
def narrow_widen(repo, proto, oldincludes, oldexcludes, newincludes,
                 newexcludes, commonheads, cgversion, known, ellipses):
    """wireprotocol command to send data when a narrow clone is widen. We will
    be sending a changegroup here.

    The current set of arguments which are required:
    oldincludes: the old includes of the narrow copy
    oldexcludes: the old excludes of the narrow copy
    newincludes: the new includes of the narrow copy
    newexcludes: the new excludes of the narrow copy
    commonheads: list of heads which are common between the server and client
    cgversion(maybe): the changegroup version to produce
    known: list of nodes which are known on the client (used in ellipses cases)
    ellipses: whether to send ellipses data or not
    """

    preferuncompressed = False
    try:
        oldincludes = wireprototypes.decodelist(oldincludes)
        newincludes = wireprototypes.decodelist(newincludes)
        oldexcludes = wireprototypes.decodelist(oldexcludes)
        newexcludes = wireprototypes.decodelist(newexcludes)
        # validate the patterns
        narrowspec.validatepatterns(set(oldincludes))
        narrowspec.validatepatterns(set(newincludes))
        narrowspec.validatepatterns(set(oldexcludes))
        narrowspec.validatepatterns(set(newexcludes))

        common = wireprototypes.decodelist(commonheads)
        known = None
        if known:
            known = wireprototypes.decodelist(known)
        if ellipses == '0':
            ellipses = False
        else:
            ellipses = bool(ellipses)
        cgversion = cgversion
        newmatch = narrowspec.match(repo.root, include=newincludes,
                                    exclude=newexcludes)
        oldmatch = narrowspec.match(repo.root, include=oldincludes,
                                    exclude=oldexcludes)

        bundler = bundle2.widen_bundle(repo, oldmatch, newmatch, common, known,
                                             cgversion, ellipses)
    except error.Abort as exc:
        bundler = bundle2.bundle20(repo.ui)
        manargs = [('message', pycompat.bytestr(exc))]
        advargs = []
        if exc.hint is not None:
            advargs.append(('hint', exc.hint))
        bundler.addpart(bundle2.bundlepart('error:abort', manargs, advargs))
        preferuncompressed = True

    chunks = bundler.getchunks()
    return wireprototypes.streamres(gen=chunks,
                                    prefer_uncompressed=preferuncompressed)

def peernarrowwiden(remote, **kwargs):
    for ch in (r'oldincludes', r'newincludes', r'oldexcludes', r'newexcludes',
               r'commonheads', r'known'):
        kwargs[ch] = wireprototypes.encodelist(kwargs[ch])

    kwargs[r'ellipses'] = '%i' % bool(kwargs[r'ellipses'])
    f = remote._callcompressable('narrow_widen', **kwargs)
    return bundle2.getunbundler(remote.ui, f)
