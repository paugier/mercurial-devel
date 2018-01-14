# lfs - hash-preserving large file support using Git-LFS protocol
#
# Copyright 2017 Facebook, Inc.
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

"""lfs - large file support (EXPERIMENTAL)

The extension reads its configuration from a versioned ``.hglfs``
configuration file found in the root of the working directory. The
``.hglfs`` file uses the same syntax as all other Mercurial
configuration files. It uses a single section, ``[track]``.

The ``[track]`` section specifies which files are stored as LFS (or
not). Each line is keyed by a file pattern, with a predicate value.
The first file pattern match is used, so put more specific patterns
first.  The available predicates are ``all()``, ``none()``, and
``size()``. See "hg help filesets.size" for the latter.

Example versioned ``.hglfs`` file::

  [track]
  # No Makefile or python file, anywhere, will be LFS
  **Makefile = none()
  **.py = none()

  **.zip = all()
  **.exe = size(">1MB")

  # Catchall for everything not matched above
  ** = size(">10MB")

Configs::

    [lfs]
    # Remote endpoint. Multiple protocols are supported:
    # - http(s)://user:pass@example.com/path
    #   git-lfs endpoint
    # - file:///tmp/path
    #   local filesystem, usually for testing
    # if unset, lfs will prompt setting this when it must use this value.
    # (default: unset)
    url = https://example.com/lfs

    # Which files to track in LFS.  Path tests are "**.extname" for file
    # extensions, and "path:under/some/directory" for path prefix.  Both
    # are relative to the repository root, and the latter must be quoted.
    # File size can be tested with the "size()" fileset, and tests can be
    # joined with fileset operators.  (See "hg help filesets.operators".)
    #
    # Some examples:
    # - all()                       # everything
    # - none()                      # nothing
    # - size(">20MB")               # larger than 20MB
    # - !**.txt                     # anything not a *.txt file
    # - **.zip | **.tar.gz | **.7z  # some types of compressed files
    # - "path:bin"                  # files under "bin" in the project root
    # - (**.php & size(">2MB")) | (**.js & size(">5MB")) | **.tar.gz
    #     | ("path:bin" & !"path:/bin/README") | size(">1GB")
    # (default: none())
    #
    # This is ignored if there is a tracked '.hglfs' file, and this setting
    # will eventually be deprecated and removed.
    track = size(">10M")

    # how many times to retry before giving up on transferring an object
    retry = 5

    # the local directory to store lfs files for sharing across local clones.
    # If not set, the cache is located in an OS specific cache location.
    usercache = /path/to/global/cache
"""

from __future__ import absolute_import

from mercurial.i18n import _

from mercurial import (
    bundle2,
    changegroup,
    cmdutil,
    config,
    context,
    error,
    exchange,
    extensions,
    filelog,
    fileset,
    hg,
    localrepo,
    minifileset,
    node,
    pycompat,
    registrar,
    revlog,
    scmutil,
    templatekw,
    upgrade,
    util,
    vfs as vfsmod,
    wireproto,
)

from . import (
    blobstore,
    wrapper,
)

# Note for extension authors: ONLY specify testedwith = 'ships-with-hg-core' for
# extensions which SHIP WITH MERCURIAL. Non-mainline extensions should
# be specifying the version(s) of Mercurial they are tested with, or
# leave the attribute unspecified.
testedwith = 'ships-with-hg-core'

configtable = {}
configitem = registrar.configitem(configtable)

configitem('experimental', 'lfs.user-agent',
    default=None,
)

configitem('lfs', 'url',
    default=None,
)
configitem('lfs', 'usercache',
    default=None,
)
# Deprecated
configitem('lfs', 'threshold',
    default=None,
)
configitem('lfs', 'track',
    default='none()',
)
configitem('lfs', 'retry',
    default=5,
)

cmdtable = {}
command = registrar.command(cmdtable)

templatekeyword = registrar.templatekeyword()

def featuresetup(ui, supported):
    # don't die on seeing a repo with the lfs requirement
    supported |= {'lfs'}

def uisetup(ui):
    localrepo.localrepository.featuresetupfuncs.add(featuresetup)

def reposetup(ui, repo):
    # Nothing to do with a remote repo
    if not repo.local():
        return

    repo.svfs.lfslocalblobstore = blobstore.local(repo)
    repo.svfs.lfsremoteblobstore = blobstore.remote(repo)

    # Push hook
    repo.prepushoutgoinghooks.add('lfs', wrapper.prepush)

    class lfsrepo(repo.__class__):
        @localrepo.unfilteredmethod
        def commitctx(self, ctx, error=False):
            repo.svfs.options['lfstrack'] = _trackedmatcher(self, ctx)
            return super(lfsrepo, self).commitctx(ctx, error)

    repo.__class__ = lfsrepo

    if 'lfs' not in repo.requirements:
        def checkrequireslfs(ui, repo, **kwargs):
            if 'lfs' not in repo.requirements:
                last = kwargs.get('node_last')
                _bin = node.bin
                if last:
                    s = repo.set('%n:%n', _bin(kwargs['node']), _bin(last))
                else:
                    s = repo.set('%n', _bin(kwargs['node']))
            for ctx in s:
                # TODO: is there a way to just walk the files in the commit?
                if any(ctx[f].islfs() for f in ctx.files() if f in ctx):
                    repo.requirements.add('lfs')
                    repo._writerequirements()
                    break

        ui.setconfig('hooks', 'commit.lfs', checkrequireslfs, 'lfs')
        ui.setconfig('hooks', 'pretxnchangegroup.lfs', checkrequireslfs, 'lfs')

def _trackedmatcher(repo, ctx):
    """Return a function (path, size) -> bool indicating whether or not to
    track a given file with lfs."""
    data = ''

    if '.hglfs' in ctx.added() or '.hglfs' in ctx.modified():
        data = ctx['.hglfs'].data()
    elif '.hglfs' not in ctx.removed():
        p1 = repo['.']

        if '.hglfs' not in p1:
            # No '.hglfs' in wdir or in parent.  Fallback to config
            # for now.
            trackspec = repo.ui.config('lfs', 'track')

            # deprecated config: lfs.threshold
            threshold = repo.ui.configbytes('lfs', 'threshold')
            if threshold:
                fileset.parse(trackspec)  # make sure syntax errors are confined
                trackspec = "(%s) | size('>%d')" % (trackspec, threshold)

            return minifileset.compile(trackspec)

        data = p1['.hglfs'].data()

    # In removed, or not in parent
    if not data:
        return lambda p, s: False

    # Parse errors here will abort with a message that points to the .hglfs file
    # and line number.
    cfg = config.config()
    cfg.parse('.hglfs', data)

    try:
        rules = [(minifileset.compile(pattern), minifileset.compile(rule))
                 for pattern, rule in cfg.items('track')]
    except error.ParseError as e:
        # The original exception gives no indicator that the error is in the
        # .hglfs file, so add that.

        # TODO: See if the line number of the file can be made available.
        raise error.Abort(_('parse error in .hglfs: %s') % e)

    def _match(path, size):
        for pat, rule in rules:
            if pat(path, size):
                return rule(path, size)

        return False

    return _match

def wrapfilelog(filelog):
    wrapfunction = extensions.wrapfunction

    wrapfunction(filelog, 'addrevision', wrapper.filelogaddrevision)
    wrapfunction(filelog, 'renamed', wrapper.filelogrenamed)
    wrapfunction(filelog, 'size', wrapper.filelogsize)

def extsetup(ui):
    wrapfilelog(filelog.filelog)

    wrapfunction = extensions.wrapfunction

    wrapfunction(cmdutil, '_updatecatformatter', wrapper._updatecatformatter)
    wrapfunction(scmutil, 'wrapconvertsink', wrapper.convertsink)

    wrapfunction(upgrade, '_finishdatamigration',
                 wrapper.upgradefinishdatamigration)

    wrapfunction(upgrade, 'preservedrequirements',
                 wrapper.upgraderequirements)

    wrapfunction(upgrade, 'supporteddestrequirements',
                 wrapper.upgraderequirements)

    wrapfunction(changegroup,
                 'supportedoutgoingversions',
                 wrapper.supportedoutgoingversions)
    wrapfunction(changegroup,
                 'allsupportedversions',
                 wrapper.allsupportedversions)

    wrapfunction(exchange, 'push', wrapper.push)
    wrapfunction(wireproto, '_capabilities', wrapper._capabilities)

    wrapfunction(context.basefilectx, 'cmp', wrapper.filectxcmp)
    wrapfunction(context.basefilectx, 'isbinary', wrapper.filectxisbinary)
    context.basefilectx.islfs = wrapper.filectxislfs

    revlog.addflagprocessor(
        revlog.REVIDX_EXTSTORED,
        (
            wrapper.readfromstore,
            wrapper.writetostore,
            wrapper.bypasscheckhash,
        ),
    )

    wrapfunction(hg, 'clone', wrapper.hgclone)
    wrapfunction(hg, 'postshare', wrapper.hgpostshare)

    # Make bundle choose changegroup3 instead of changegroup2. This affects
    # "hg bundle" command. Note: it does not cover all bundle formats like
    # "packed1". Using "packed1" with lfs will likely cause trouble.
    names = [k for k, v in exchange._bundlespeccgversions.items() if v == '02']
    for k in names:
        exchange._bundlespeccgversions[k] = '03'

    # bundlerepo uses "vfsmod.readonlyvfs(othervfs)", we need to make sure lfs
    # options and blob stores are passed from othervfs to the new readonlyvfs.
    wrapfunction(vfsmod.readonlyvfs, '__init__', wrapper.vfsinit)

    # when writing a bundle via "hg bundle" command, upload related LFS blobs
    wrapfunction(bundle2, 'writenewbundle', wrapper.writenewbundle)

@templatekeyword('lfs_files')
def lfsfiles(repo, ctx, **args):
    """List of strings. LFS files added or modified by the changeset."""
    args = pycompat.byteskwargs(args)

    pointers = wrapper.pointersfromctx(ctx) # {path: pointer}
    files = sorted(pointers.keys())

    def lfsattrs(v):
        # In the file spec, version is first and the other keys are sorted.
        sortkeyfunc = lambda x: (x[0] != 'version', x)
        items = sorted(pointers[v].iteritems(), key=sortkeyfunc)
        return util.sortdict(items)

    makemap = lambda v: {
        'file': v,
        'oid': pointers[v].oid(),
        'lfsattrs': templatekw.hybriddict(lfsattrs(v)),
    }

    # TODO: make the separator ', '?
    f = templatekw._showlist('lfs_file', files, args)
    return templatekw._hybrid(f, files, makemap, pycompat.identity)

@command('debuglfsupload',
         [('r', 'rev', [], _('upload large files introduced by REV'))])
def debuglfsupload(ui, repo, **opts):
    """upload lfs blobs added by the working copy parent or given revisions"""
    revs = opts.get('rev', [])
    pointers = wrapper.extractpointers(repo, scmutil.revrange(repo, revs))
    wrapper.uploadblobs(repo, pointers)
