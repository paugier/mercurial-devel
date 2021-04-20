# patchbomb.py - sending Mercurial changesets as patch emails
#
#  Copyright 2005-2009 Olivia Mackall <olivia@selenic.com> and others
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

'''command to send changesets as (a series of) patch emails

The series is started off with a "[PATCH 0 of N]" introduction, which
describes the series as a whole.

Each patch email has a Subject line of "[PATCH M of N] ...", using the
first line of the changeset description as the subject text. The
message contains two or three body parts:

- The changeset description.
- [Optional] The result of running diffstat on the patch.
- The patch itself, as generated by :hg:`export`.

Each message refers to the first in the series using the In-Reply-To
and References headers, so they will show up as a sequence in threaded
mail and news readers, and in mail archives.

To configure other defaults, add a section like this to your
configuration file::

  [email]
  from = My Name <my@email>
  to = recipient1, recipient2, ...
  cc = cc1, cc2, ...
  bcc = bcc1, bcc2, ...
  reply-to = address1, address2, ...

Use ``[patchbomb]`` as configuration section name if you need to
override global ``[email]`` address settings.

Then you can use the :hg:`email` command to mail a series of
changesets as a patchbomb.

You can also either configure the method option in the email section
to be a sendmail compatible mailer or fill out the [smtp] section so
that the patchbomb extension can automatically send patchbombs
directly from the commandline. See the [email] and [smtp] sections in
hgrc(5) for details.

By default, :hg:`email` will prompt for a ``To`` or ``CC`` header if
you do not supply one via configuration or the command line.  You can
override this to never prompt by configuring an empty value::

  [email]
  cc =

You can control the default inclusion of an introduction message with the
``patchbomb.intro`` configuration option. The configuration is always
overwritten by command line flags like --intro and --desc::

  [patchbomb]
  intro=auto   # include introduction message if more than 1 patch (default)
  intro=never  # never include an introduction message
  intro=always # always include an introduction message

You can specify a template for flags to be added in subject prefixes. Flags
specified by --flag option are exported as ``{flags}`` keyword::

  [patchbomb]
  flagtemplate = "{separate(' ',
                            ifeq(branch, 'default', '', branch|upper),
                            flags)}"

You can set patchbomb to always ask for confirmation by setting
``patchbomb.confirm`` to true.
'''
from __future__ import absolute_import

import email.encoders as emailencoders
import email.mime.base as emimebase
import email.mime.multipart as emimemultipart
import email.utils as eutil
import errno
import os
import socket

from mercurial.i18n import _
from mercurial.pycompat import open
from mercurial.node import bin
from mercurial import (
    cmdutil,
    commands,
    encoding,
    error,
    formatter,
    hg,
    mail,
    patch,
    pycompat,
    registrar,
    scmutil,
    templater,
    util,
)
from mercurial.utils import (
    dateutil,
    urlutil,
)

stringio = util.stringio

cmdtable = {}
command = registrar.command(cmdtable)

configtable = {}
configitem = registrar.configitem(configtable)

configitem(
    b'patchbomb',
    b'bundletype',
    default=None,
)
configitem(
    b'patchbomb',
    b'bcc',
    default=None,
)
configitem(
    b'patchbomb',
    b'cc',
    default=None,
)
configitem(
    b'patchbomb',
    b'confirm',
    default=False,
)
configitem(
    b'patchbomb',
    b'flagtemplate',
    default=None,
)
configitem(
    b'patchbomb',
    b'from',
    default=None,
)
configitem(
    b'patchbomb',
    b'intro',
    default=b'auto',
)
configitem(
    b'patchbomb',
    b'publicurl',
    default=None,
)
configitem(
    b'patchbomb',
    b'reply-to',
    default=None,
)
configitem(
    b'patchbomb',
    b'to',
    default=None,
)

# Note for extension authors: ONLY specify testedwith = 'ships-with-hg-core' for
# extensions which SHIP WITH MERCURIAL. Non-mainline extensions should
# be specifying the version(s) of Mercurial they are tested with, or
# leave the attribute unspecified.
testedwith = b'ships-with-hg-core'


def _addpullheader(seq, ctx):
    """Add a header pointing to a public URL where the changeset is available"""
    repo = ctx.repo()
    # experimental config: patchbomb.publicurl
    # waiting for some logic that check that the changeset are available on the
    # destination before patchbombing anything.
    publicurl = repo.ui.config(b'patchbomb', b'publicurl')
    if publicurl:
        return b'Available At %s\n#              hg pull %s -r %s' % (
            publicurl,
            publicurl,
            ctx,
        )
    return None


def uisetup(ui):
    cmdutil.extraexport.append(b'pullurl')
    cmdutil.extraexportmap[b'pullurl'] = _addpullheader


def reposetup(ui, repo):
    if not repo.local():
        return
    repo._wlockfreeprefix.add(b'last-email.txt')


def prompt(ui, prompt, default=None, rest=b':'):
    if default:
        prompt += b' [%s]' % default
    return ui.prompt(prompt + rest, default)


def introwanted(ui, opts, number):
    '''is an introductory message apparently wanted?'''
    introconfig = ui.config(b'patchbomb', b'intro')
    if opts.get(b'intro') or opts.get(b'desc'):
        intro = True
    elif introconfig == b'always':
        intro = True
    elif introconfig == b'never':
        intro = False
    elif introconfig == b'auto':
        intro = number > 1
    else:
        ui.write_err(
            _(b'warning: invalid patchbomb.intro value "%s"\n') % introconfig
        )
        ui.write_err(_(b'(should be one of always, never, auto)\n'))
        intro = number > 1
    return intro


def _formatflags(ui, repo, rev, flags):
    """build flag string optionally by template"""
    tmpl = ui.config(b'patchbomb', b'flagtemplate')
    if not tmpl:
        return b' '.join(flags)
    out = util.stringio()
    spec = formatter.literal_templatespec(templater.unquotestring(tmpl))
    with formatter.templateformatter(ui, out, b'patchbombflag', {}, spec) as fm:
        fm.startitem()
        fm.context(ctx=repo[rev])
        fm.write(b'flags', b'%s', fm.formatlist(flags, name=b'flag'))
    return out.getvalue()


def _formatprefix(ui, repo, rev, flags, idx, total, numbered):
    """build prefix to patch subject"""
    flag = _formatflags(ui, repo, rev, flags)
    if flag:
        flag = b' ' + flag

    if not numbered:
        return b'[PATCH%s]' % flag
    else:
        tlen = len(b"%d" % total)
        return b'[PATCH %0*d of %d%s]' % (tlen, idx, total, flag)


def makepatch(
    ui,
    repo,
    rev,
    patchlines,
    opts,
    _charsets,
    idx,
    total,
    numbered,
    patchname=None,
):

    desc = []
    node = None
    body = b''

    for line in patchlines:
        if line.startswith(b'#'):
            if line.startswith(b'# Node ID'):
                node = line.split()[-1]
            continue
        if line.startswith(b'diff -r') or line.startswith(b'diff --git'):
            break
        desc.append(line)

    if not patchname and not node:
        raise ValueError

    if opts.get(b'attach') and not opts.get(b'body'):
        body = (
            b'\n'.join(desc[1:]).strip()
            or b'Patch subject is complete summary.'
        )
        body += b'\n\n\n'

    if opts.get(b'plain'):
        while patchlines and patchlines[0].startswith(b'# '):
            patchlines.pop(0)
        if patchlines:
            patchlines.pop(0)
        while patchlines and not patchlines[0].strip():
            patchlines.pop(0)

    ds = patch.diffstat(patchlines)
    if opts.get(b'diffstat'):
        body += ds + b'\n\n'

    addattachment = opts.get(b'attach') or opts.get(b'inline')
    if not addattachment or opts.get(b'body'):
        body += b'\n'.join(patchlines)

    if addattachment:
        msg = emimemultipart.MIMEMultipart()
        if body:
            msg.attach(mail.mimeencode(ui, body, _charsets, opts.get(b'test')))
        p = mail.mimetextpatch(
            b'\n'.join(patchlines), 'x-patch', opts.get(b'test')
        )
        binnode = bin(node)
        # if node is mq patch, it will have the patch file's name as a tag
        if not patchname:
            patchtags = [
                t
                for t in repo.nodetags(binnode)
                if t.endswith(b'.patch') or t.endswith(b'.diff')
            ]
            if patchtags:
                patchname = patchtags[0]
            elif total > 1:
                patchname = cmdutil.makefilename(
                    repo[node], b'%b-%n.patch', seqno=idx, total=total
                )
            else:
                patchname = cmdutil.makefilename(repo[node], b'%b.patch')
        disposition = r'inline'
        if opts.get(b'attach'):
            disposition = r'attachment'
        p['Content-Disposition'] = (
            disposition + '; filename=' + encoding.strfromlocal(patchname)
        )
        msg.attach(p)
    else:
        msg = mail.mimetextpatch(body, display=opts.get(b'test'))

    prefix = _formatprefix(
        ui, repo, rev, opts.get(b'flag'), idx, total, numbered
    )
    subj = desc[0].strip().rstrip(b'. ')
    if not numbered:
        subj = b' '.join([prefix, opts.get(b'subject') or subj])
    else:
        subj = b' '.join([prefix, subj])
    msg['Subject'] = mail.headencode(ui, subj, _charsets, opts.get(b'test'))
    msg['X-Mercurial-Node'] = pycompat.sysstr(node)
    msg['X-Mercurial-Series-Index'] = '%i' % idx
    msg['X-Mercurial-Series-Total'] = '%i' % total
    return msg, subj, ds


def _getpatches(repo, revs, **opts):
    """return a list of patches for a list of revisions

    Each patch in the list is itself a list of lines.
    """
    ui = repo.ui
    prev = repo[b'.'].rev()
    for r in revs:
        if r == prev and (repo[None].files() or repo[None].deleted()):
            ui.warn(_(b'warning: working directory has uncommitted changes\n'))
        output = stringio()
        cmdutil.exportfile(
            repo, [r], output, opts=patch.difffeatureopts(ui, opts, git=True)
        )
        yield output.getvalue().split(b'\n')


def _getbundle(repo, dest, **opts):
    """return a bundle containing changesets missing in "dest"

    The `opts` keyword-arguments are the same as the one accepted by the
    `bundle` command.

    The bundle is a returned as a single in-memory binary blob.
    """
    ui = repo.ui
    tmpdir = pycompat.mkdtemp(prefix=b'hg-email-bundle-')
    tmpfn = os.path.join(tmpdir, b'bundle')
    btype = ui.config(b'patchbomb', b'bundletype')
    if btype:
        opts['type'] = btype
    try:
        dests = []
        if dest:
            dests = [dest]
        commands.bundle(ui, repo, tmpfn, *dests, **opts)
        return util.readfile(tmpfn)
    finally:
        try:
            os.unlink(tmpfn)
        except OSError:
            pass
        os.rmdir(tmpdir)


def _getdescription(repo, defaultbody, sender, **opts):
    """obtain the body of the introduction message and return it

    This is also used for the body of email with an attached bundle.

    The body can be obtained either from the command line option or entered by
    the user through the editor.
    """
    ui = repo.ui
    if opts.get('desc'):
        body = open(opts.get('desc')).read()
    else:
        ui.write(
            _(b'\nWrite the introductory message for the patch series.\n\n')
        )
        body = ui.edit(
            defaultbody, sender, repopath=repo.path, action=b'patchbombbody'
        )
        # Save series description in case sendmail fails
        msgfile = repo.vfs(b'last-email.txt', b'wb')
        msgfile.write(body)
        msgfile.close()
    return body


def _getbundlemsgs(repo, sender, bundle, **opts):
    """Get the full email for sending a given bundle

    This function returns a list of "email" tuples (subject, content, None).
    The list is always one message long in that case.
    """
    ui = repo.ui
    _charsets = mail._charsets(ui)
    subj = opts.get('subject') or prompt(
        ui, b'Subject:', b'A bundle for your repository'
    )

    body = _getdescription(repo, b'', sender, **opts)
    msg = emimemultipart.MIMEMultipart()
    if body:
        msg.attach(mail.mimeencode(ui, body, _charsets, opts.get('test')))
    datapart = emimebase.MIMEBase('application', 'x-mercurial-bundle')
    datapart.set_payload(bundle)
    bundlename = b'%s.hg' % opts.get('bundlename', b'bundle')
    datapart.add_header(
        'Content-Disposition',
        'attachment',
        filename=encoding.strfromlocal(bundlename),
    )
    emailencoders.encode_base64(datapart)
    msg.attach(datapart)
    msg['Subject'] = mail.headencode(ui, subj, _charsets, opts.get('test'))
    return [(msg, subj, None)]


def _makeintro(repo, sender, revs, patches, **opts):
    """make an introduction email, asking the user for content if needed

    email is returned as (subject, body, cumulative-diffstat)"""
    ui = repo.ui
    _charsets = mail._charsets(ui)

    # use the last revision which is likely to be a bookmarked head
    prefix = _formatprefix(
        ui, repo, revs.last(), opts.get('flag'), 0, len(patches), numbered=True
    )
    subj = opts.get('subject') or prompt(
        ui, b'(optional) Subject: ', rest=prefix, default=b''
    )
    if not subj:
        return None  # skip intro if the user doesn't bother

    subj = prefix + b' ' + subj

    body = b''
    if opts.get('diffstat'):
        # generate a cumulative diffstat of the whole patch series
        diffstat = patch.diffstat(sum(patches, []))
        body = b'\n' + diffstat
    else:
        diffstat = None

    body = _getdescription(repo, body, sender, **opts)
    msg = mail.mimeencode(ui, body, _charsets, opts.get('test'))
    msg['Subject'] = mail.headencode(ui, subj, _charsets, opts.get('test'))
    return (msg, subj, diffstat)


def _getpatchmsgs(repo, sender, revs, patchnames=None, **opts):
    """return a list of emails from a list of patches

    This involves introduction message creation if necessary.

    This function returns a list of "email" tuples (subject, content, None).
    """
    bytesopts = pycompat.byteskwargs(opts)
    ui = repo.ui
    _charsets = mail._charsets(ui)
    patches = list(_getpatches(repo, revs, **opts))
    msgs = []

    ui.write(_(b'this patch series consists of %d patches.\n\n') % len(patches))

    # build the intro message, or skip it if the user declines
    if introwanted(ui, bytesopts, len(patches)):
        msg = _makeintro(repo, sender, revs, patches, **opts)
        if msg:
            msgs.append(msg)

    # are we going to send more than one message?
    numbered = len(msgs) + len(patches) > 1

    # now generate the actual patch messages
    name = None
    assert len(revs) == len(patches)
    for i, (r, p) in enumerate(zip(revs, patches)):
        if patchnames:
            name = patchnames[i]
        msg = makepatch(
            ui,
            repo,
            r,
            p,
            bytesopts,
            _charsets,
            i + 1,
            len(patches),
            numbered,
            name,
        )
        msgs.append(msg)

    return msgs


def _getoutgoing(repo, dest, revs):
    '''Return the revisions present locally but not in dest'''
    ui = repo.ui
    paths = urlutil.get_push_paths(repo, ui, [dest])
    safe_paths = [urlutil.hidepassword(p.rawloc) for p in paths]
    ui.status(_(b'comparing with %s\n') % b','.join(safe_paths))

    revs = [r for r in revs if r >= 0]
    if not revs:
        revs = [repo.changelog.tiprev()]
    revs = repo.revs(b'outgoing(%s) and ::%ld', dest or b'', revs)
    if not revs:
        ui.status(_(b"no changes found\n"))
    return revs


def _msgid(node, timestamp):
    try:
        hostname = encoding.strfromlocal(encoding.environ[b'HGHOSTNAME'])
    except KeyError:
        hostname = socket.getfqdn()
    return '<%s.%d@%s>' % (node, timestamp, hostname)


emailopts = [
    (b'', b'body', None, _(b'send patches as inline message text (default)')),
    (b'a', b'attach', None, _(b'send patches as attachments')),
    (b'i', b'inline', None, _(b'send patches as inline attachments')),
    (
        b'',
        b'bcc',
        [],
        _(b'email addresses of blind carbon copy recipients'),
        _(b'EMAIL'),
    ),
    (b'c', b'cc', [], _(b'email addresses of copy recipients'), _(b'EMAIL')),
    (b'', b'confirm', None, _(b'ask for confirmation before sending')),
    (b'd', b'diffstat', None, _(b'add diffstat output to messages')),
    (
        b'',
        b'date',
        b'',
        _(b'use the given date as the sending date'),
        _(b'DATE'),
    ),
    (
        b'',
        b'desc',
        b'',
        _(b'use the given file as the series description'),
        _(b'FILE'),
    ),
    (b'f', b'from', b'', _(b'email address of sender'), _(b'EMAIL')),
    (b'n', b'test', None, _(b'print messages that would be sent')),
    (
        b'm',
        b'mbox',
        b'',
        _(b'write messages to mbox file instead of sending them'),
        _(b'FILE'),
    ),
    (
        b'',
        b'reply-to',
        [],
        _(b'email addresses replies should be sent to'),
        _(b'EMAIL'),
    ),
    (
        b's',
        b'subject',
        b'',
        _(b'subject of first message (intro or single patch)'),
        _(b'TEXT'),
    ),
    (
        b'',
        b'in-reply-to',
        b'',
        _(b'message identifier to reply to'),
        _(b'MSGID'),
    ),
    (b'', b'flag', [], _(b'flags to add in subject prefixes'), _(b'FLAG')),
    (b't', b'to', [], _(b'email addresses of recipients'), _(b'EMAIL')),
]


@command(
    b'email',
    [
        (b'g', b'git', None, _(b'use git extended diff format')),
        (b'', b'plain', None, _(b'omit hg patch header')),
        (
            b'o',
            b'outgoing',
            None,
            _(b'send changes not found in the target repository'),
        ),
        (
            b'b',
            b'bundle',
            None,
            _(b'send changes not in target as a binary bundle'),
        ),
        (
            b'B',
            b'bookmark',
            b'',
            _(b'send changes only reachable by given bookmark'),
            _(b'BOOKMARK'),
        ),
        (
            b'',
            b'bundlename',
            b'bundle',
            _(b'name of the bundle attachment file'),
            _(b'NAME'),
        ),
        (b'r', b'rev', [], _(b'a revision to send'), _(b'REV')),
        (
            b'',
            b'force',
            None,
            _(
                b'run even when remote repository is unrelated '
                b'(with -b/--bundle)'
            ),
        ),
        (
            b'',
            b'base',
            [],
            _(
                b'a base changeset to specify instead of a destination '
                b'(with -b/--bundle)'
            ),
            _(b'REV'),
        ),
        (
            b'',
            b'intro',
            None,
            _(b'send an introduction email for a single patch'),
        ),
    ]
    + emailopts
    + cmdutil.remoteopts,
    _(b'hg email [OPTION]... [DEST]...'),
    helpcategory=command.CATEGORY_IMPORT_EXPORT,
)
def email(ui, repo, *revs, **opts):
    """send changesets by email

    By default, diffs are sent in the format generated by
    :hg:`export`, one per message. The series starts with a "[PATCH 0
    of N]" introduction, which describes the series as a whole.

    Each patch email has a Subject line of "[PATCH M of N] ...", using
    the first line of the changeset description as the subject text.
    The message contains two or three parts. First, the changeset
    description.

    With the -d/--diffstat option, if the diffstat program is
    installed, the result of running diffstat on the patch is inserted.

    Finally, the patch itself, as generated by :hg:`export`.

    With the -d/--diffstat or --confirm options, you will be presented
    with a final summary of all messages and asked for confirmation before
    the messages are sent.

    By default the patch is included as text in the email body for
    easy reviewing. Using the -a/--attach option will instead create
    an attachment for the patch. With -i/--inline an inline attachment
    will be created. You can include a patch both as text in the email
    body and as a regular or an inline attachment by combining the
    -a/--attach or -i/--inline with the --body option.

    With -B/--bookmark changesets reachable by the given bookmark are
    selected.

    With -o/--outgoing, emails will be generated for patches not found
    in the destination repository (or only those which are ancestors
    of the specified revisions if any are provided)

    With -b/--bundle, changesets are selected as for --outgoing, but a
    single email containing a binary Mercurial bundle as an attachment
    will be sent. Use the ``patchbomb.bundletype`` config option to
    control the bundle type as with :hg:`bundle --type`.

    With -m/--mbox, instead of previewing each patchbomb message in a
    pager or sending the messages directly, it will create a UNIX
    mailbox file with the patch emails. This mailbox file can be
    previewed with any mail user agent which supports UNIX mbox
    files.

    With -n/--test, all steps will run, but mail will not be sent.
    You will be prompted for an email recipient address, a subject and
    an introductory message describing the patches of your patchbomb.
    Then when all is done, patchbomb messages are displayed.

    In case email sending fails, you will find a backup of your series
    introductory message in ``.hg/last-email.txt``.

    The default behavior of this command can be customized through
    configuration. (See :hg:`help patchbomb` for details)

    Examples::

      hg email -r 3000          # send patch 3000 only
      hg email -r 3000 -r 3001  # send patches 3000 and 3001
      hg email -r 3000:3005     # send patches 3000 through 3005
      hg email 3000             # send patch 3000 (deprecated)

      hg email -o               # send all patches not in default
      hg email -o DEST          # send all patches not in DEST
      hg email -o -r 3000       # send all ancestors of 3000 not in default
      hg email -o -r 3000 DEST  # send all ancestors of 3000 not in DEST

      hg email -B feature       # send all ancestors of feature bookmark

      hg email -b               # send bundle of all patches not in default
      hg email -b DEST          # send bundle of all patches not in DEST
      hg email -b -r 3000       # bundle of all ancestors of 3000 not in default
      hg email -b -r 3000 DEST  # bundle of all ancestors of 3000 not in DEST

      hg email -o -m mbox &&    # generate an mbox file...
        mutt -R -f mbox         # ... and view it with mutt
      hg email -o -m mbox &&    # generate an mbox file ...
        formail -s sendmail \\   # ... and use formail to send from the mbox
          -bm -t < mbox         # ... using sendmail

    Before using this command, you will need to enable email in your
    hgrc. See the [email] section in hgrc(5) for details.
    """
    opts = pycompat.byteskwargs(opts)

    _charsets = mail._charsets(ui)

    bundle = opts.get(b'bundle')
    date = opts.get(b'date')
    mbox = opts.get(b'mbox')
    outgoing = opts.get(b'outgoing')
    rev = opts.get(b'rev')
    bookmark = opts.get(b'bookmark')

    if not (opts.get(b'test') or mbox):
        # really sending
        mail.validateconfig(ui)

    if not (revs or rev or outgoing or bundle or bookmark):
        raise error.Abort(
            _(b'specify at least one changeset with -B, -r or -o')
        )

    if outgoing and bundle:
        raise error.Abort(
            _(
                b"--outgoing mode always on with --bundle;"
                b" do not re-specify --outgoing"
            )
        )
    cmdutil.check_at_most_one_arg(opts, b'rev', b'bookmark')

    if outgoing or bundle:
        if len(revs) > 1:
            raise error.Abort(_(b"too many destinations"))
        if revs:
            dest = revs[0]
        else:
            dest = None
        revs = []

    if rev:
        if revs:
            raise error.Abort(_(b'use only one form to specify the revision'))
        revs = rev
    elif bookmark:
        if bookmark not in repo._bookmarks:
            raise error.Abort(_(b"bookmark '%s' not found") % bookmark)
        revs = scmutil.bookmarkrevs(repo, bookmark)

    revs = scmutil.revrange(repo, revs)
    if outgoing:
        revs = _getoutgoing(repo, dest, revs)
    if bundle:
        opts[b'revs'] = [b"%d" % r for r in revs]

    # check if revision exist on the public destination
    publicurl = repo.ui.config(b'patchbomb', b'publicurl')
    if publicurl:
        repo.ui.debug(b'checking that revision exist in the public repo\n')
        try:
            publicpeer = hg.peer(repo, {}, publicurl)
        except error.RepoError:
            repo.ui.write_err(
                _(b'unable to access public repo: %s\n') % publicurl
            )
            raise
        if not publicpeer.capable(b'known'):
            repo.ui.debug(b'skipping existence checks: public repo too old\n')
        else:
            out = [repo[r] for r in revs]
            known = publicpeer.known(h.node() for h in out)
            missing = []
            for idx, h in enumerate(out):
                if not known[idx]:
                    missing.append(h)
            if missing:
                if len(missing) > 1:
                    msg = _(b'public "%s" is missing %s and %i others')
                    msg %= (publicurl, missing[0], len(missing) - 1)
                else:
                    msg = _(b'public url %s is missing %s')
                    msg %= (publicurl, missing[0])
                missingrevs = [ctx.rev() for ctx in missing]
                revhint = b' '.join(
                    b'-r %s' % h for h in repo.set(b'heads(%ld)', missingrevs)
                )
                hint = _(b"use 'hg push %s %s'") % (publicurl, revhint)
                raise error.Abort(msg, hint=hint)

    # start
    if date:
        start_time = dateutil.parsedate(date)
    else:
        start_time = dateutil.makedate()

    def genmsgid(id):
        return _msgid(id[:20], int(start_time[0]))

    # deprecated config: patchbomb.from
    sender = (
        opts.get(b'from')
        or ui.config(b'email', b'from')
        or ui.config(b'patchbomb', b'from')
        or prompt(ui, b'From', ui.username())
    )

    if bundle:
        stropts = pycompat.strkwargs(opts)
        bundledata = _getbundle(repo, dest, **stropts)
        bundleopts = stropts.copy()
        bundleopts.pop('bundle', None)  # already processed
        msgs = _getbundlemsgs(repo, sender, bundledata, **bundleopts)
    else:
        msgs = _getpatchmsgs(repo, sender, revs, **pycompat.strkwargs(opts))

    showaddrs = []

    def getaddrs(header, ask=False, default=None):
        configkey = header.lower()
        opt = header.replace(b'-', b'_').lower()
        addrs = opts.get(opt)
        if addrs:
            showaddrs.append(b'%s: %s' % (header, b', '.join(addrs)))
            return mail.addrlistencode(ui, addrs, _charsets, opts.get(b'test'))

        # not on the command line: fallback to config and then maybe ask
        addr = ui.config(b'email', configkey) or ui.config(
            b'patchbomb', configkey
        )
        if not addr:
            specified = ui.hasconfig(b'email', configkey) or ui.hasconfig(
                b'patchbomb', configkey
            )
            if not specified and ask:
                addr = prompt(ui, header, default=default)
        if addr:
            showaddrs.append(b'%s: %s' % (header, addr))
            return mail.addrlistencode(ui, [addr], _charsets, opts.get(b'test'))
        elif default:
            return mail.addrlistencode(
                ui, [default], _charsets, opts.get(b'test')
            )
        return []

    to = getaddrs(b'To', ask=True)
    if not to:
        # we can get here in non-interactive mode
        raise error.Abort(_(b'no recipient addresses provided'))
    cc = getaddrs(b'Cc', ask=True, default=b'')
    bcc = getaddrs(b'Bcc')
    replyto = getaddrs(b'Reply-To')

    confirm = ui.configbool(b'patchbomb', b'confirm')
    confirm |= bool(opts.get(b'diffstat') or opts.get(b'confirm'))

    if confirm:
        ui.write(_(b'\nFinal summary:\n\n'), label=b'patchbomb.finalsummary')
        ui.write((b'From: %s\n' % sender), label=b'patchbomb.from')
        for addr in showaddrs:
            ui.write(b'%s\n' % addr, label=b'patchbomb.to')
        for m, subj, ds in msgs:
            ui.write((b'Subject: %s\n' % subj), label=b'patchbomb.subject')
            if ds:
                ui.write(ds, label=b'patchbomb.diffstats')
        ui.write(b'\n')
        if ui.promptchoice(
            _(b'are you sure you want to send (yn)?$$ &Yes $$ &No')
        ):
            raise error.Abort(_(b'patchbomb canceled'))

    ui.write(b'\n')

    parent = opts.get(b'in_reply_to') or None
    # angle brackets may be omitted, they're not semantically part of the msg-id
    if parent is not None:
        parent = encoding.strfromlocal(parent)
        if not parent.startswith('<'):
            parent = '<' + parent
        if not parent.endswith('>'):
            parent += '>'

    sender_addr = eutil.parseaddr(encoding.strfromlocal(sender))[1]
    sender = mail.addressencode(ui, sender, _charsets, opts.get(b'test'))
    sendmail = None
    firstpatch = None
    progress = ui.makeprogress(
        _(b'sending'), unit=_(b'emails'), total=len(msgs)
    )
    for i, (m, subj, ds) in enumerate(msgs):
        try:
            m['Message-Id'] = genmsgid(m['X-Mercurial-Node'])
            if not firstpatch:
                firstpatch = m['Message-Id']
            m['X-Mercurial-Series-Id'] = firstpatch
        except TypeError:
            m['Message-Id'] = genmsgid('patchbomb')
        if parent:
            m['In-Reply-To'] = parent
            m['References'] = parent
        if not parent or 'X-Mercurial-Node' not in m:
            parent = m['Message-Id']

        m['User-Agent'] = 'Mercurial-patchbomb/%s' % util.version().decode()
        m['Date'] = eutil.formatdate(start_time[0], localtime=True)

        start_time = (start_time[0] + 1, start_time[1])
        m['From'] = sender
        m['To'] = ', '.join(to)
        if cc:
            m['Cc'] = ', '.join(cc)
        if bcc:
            m['Bcc'] = ', '.join(bcc)
        if replyto:
            m['Reply-To'] = ', '.join(replyto)
        if opts.get(b'test'):
            ui.status(_(b'displaying '), subj, b' ...\n')
            ui.pager(b'email')
            generator = mail.Generator(ui, mangle_from_=False)
            try:
                generator.flatten(m, False)
                ui.write(b'\n')
            except IOError as inst:
                if inst.errno != errno.EPIPE:
                    raise
        else:
            if not sendmail:
                sendmail = mail.connect(ui, mbox=mbox)
            ui.status(_(b'sending '), subj, b' ...\n')
            progress.update(i, item=subj)
            if not mbox:
                # Exim does not remove the Bcc field
                del m['Bcc']
            fp = stringio()
            generator = mail.Generator(fp, mangle_from_=False)
            generator.flatten(m, False)
            alldests = to + bcc + cc
            sendmail(sender_addr, alldests, fp.getvalue())

    progress.complete()
