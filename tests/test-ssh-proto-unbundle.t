  $ cat > hgrc-sshv2 << EOF
  > %include $HGRCPATH
  > [experimental]
  > sshpeer.advertise-v2 = true
  > sshserver.support-v2 = true
  > EOF

  $ debugwireproto() {
  >   commands=`cat -`
  >   echo 'testing ssh1'
  >   tip=`hg log -r tip -T '{node}'`
  >   echo "${commands}" | hg --verbose debugwireproto --localssh --noreadstderr
  >   if [ -n "$1" ]; then
  >       hg --config extensions.strip= strip --no-backup -r "all() - ::${tip}"
  >   fi
  >   echo ""
  >   echo 'testing ssh2'
  >   echo "${commands}" | HGRCPATH=$TESTTMP/hgrc-sshv2 hg --verbose debugwireproto --localssh --noreadstderr
  >   if [ -n "$1" ]; then
  >       hg --config extensions.strip= strip --no-backup -r "all() - ::${tip}"
  >   fi
  > }

Generate some bundle files

  $ hg init repo
  $ cd repo
  $ echo 0 > foo
  $ hg -q commit -A -m initial
  $ hg bundle --all -t none-v1 ../initial.v1.hg
  1 changesets found
  $ cd ..

Test pushing bundle1 payload to a server with bundle1 disabled

  $ hg init no-bundle1
  $ cd no-bundle1
  $ cat > .hg/hgrc << EOF
  > [server]
  > bundle1 = false
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 115:
  e>     abort: incompatible Mercurial client; bundle2 required\n
  e>     (see https://www.mercurial-scm.org/wiki/IncompatibleClient)\n
  remote: abort: incompatible Mercurial client; bundle2 required
  remote: (see https://www.mercurial-scm.org/wiki/IncompatibleClient)
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 115:
  e>     abort: incompatible Mercurial client; bundle2 required\n
  e>     (see https://www.mercurial-scm.org/wiki/IncompatibleClient)\n
  remote: abort: incompatible Mercurial client; bundle2 required
  remote: (see https://www.mercurial-scm.org/wiki/IncompatibleClient)
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

  $ cd ..

Create a pretxnchangegroup hook that fails. Give it multiple modes of printing
output so we can test I/O capture and behavior.

Test pushing to a server that has a pretxnchangegroup Python hook that fails

  $ cat > $TESTTMP/failhook << EOF
  > from __future__ import print_function
  > import sys
  > def hook1line(ui, repo, **kwargs):
  >     ui.write('ui.write 1 line\n')
  >     return 1
  > def hook2lines(ui, repo, **kwargs):
  >     ui.write('ui.write 2 lines 1\n')
  >     ui.write('ui.write 2 lines 2\n')
  >     return 1
  > def hook1lineflush(ui, repo, **kwargs):
  >     ui.write('ui.write 1 line flush\n')
  >     ui.flush()
  >     return 1
  > def hookmultiflush(ui, repo, **kwargs):
  >     ui.write('ui.write 1st\n')
  >     ui.flush()
  >     ui.write('ui.write 2nd\n')
  >     ui.flush()
  >     return 1
  > def hookwriteandwriteerr(ui, repo, **kwargs):
  >     ui.write('ui.write 1\n')
  >     ui.write_err('ui.write_err 1\n')
  >     ui.write('ui.write 2\n')
  >     ui.write_err('ui.write_err 2\n')
  >     return 1
  > def hookprintstdout(ui, repo, **kwargs):
  >     print('printed line')
  >     return 1
  > def hookprintandwrite(ui, repo, **kwargs):
  >     print('print 1')
  >     ui.write('ui.write 1\n')
  >     print('print 2')
  >     ui.write('ui.write 2\n')
  >     return 1
  > def hookprintstderrandstdout(ui, repo, **kwargs):
  >     print('stdout 1')
  >     print('stderr 1', file=sys.stderr)
  >     print('stdout 2')
  >     print('stderr 2', file=sys.stderr)
  >     return 1
  > EOF

  $ hg init failrepo
  $ cd failrepo

ui.write() in hook is redirected to stderr

  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.fail = python:$TESTTMP/failhook:hook1line
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 196:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1 line\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1 line
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 196:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1 line\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1 line
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

And a variation that writes multiple lines using ui.write

  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.fail = python:$TESTTMP/failhook:hook2lines
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 218:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 2 lines 1\n
  e>     ui.write 2 lines 2\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 2 lines 1
  remote: ui.write 2 lines 2
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 218:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 2 lines 1\n
  e>     ui.write 2 lines 2\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 2 lines 1
  remote: ui.write 2 lines 2
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

And a variation that does a ui.flush() after writing output

  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.fail = python:$TESTTMP/failhook:hook1lineflush
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 202:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1 line flush\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1 line flush
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 202:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1 line flush\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1 line flush
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

Multiple writes + flush

  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.fail = python:$TESTTMP/failhook:hookmultiflush
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 206:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1st\n
  e>     ui.write 2nd\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1st
  remote: ui.write 2nd
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 206:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1st\n
  e>     ui.write 2nd\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1st
  remote: ui.write 2nd
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

ui.write() + ui.write_err() output is captured

  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.fail = python:$TESTTMP/failhook:hookwriteandwriteerr
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 232:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1\n
  e>     ui.write_err 1\n
  e>     ui.write 2\n
  e>     ui.write_err 2\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1
  remote: ui.write_err 1
  remote: ui.write 2
  remote: ui.write_err 2
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 232:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1\n
  e>     ui.write_err 1\n
  e>     ui.write 2\n
  e>     ui.write_err 2\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1
  remote: ui.write_err 1
  remote: ui.write 2
  remote: ui.write_err 2
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

print() output is captured

  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.fail = python:$TESTTMP/failhook:hookprintstdout
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 193:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     printed line\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: printed line
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 193:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     printed line\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: printed line
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

Mixed print() and ui.write() are both captured

  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.fail = python:$TESTTMP/failhook:hookprintandwrite
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 218:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1\n
  e>     ui.write 2\n
  e>     print 1\n
  e>     print 2\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1
  remote: ui.write 2
  remote: print 1
  remote: print 2
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 218:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1\n
  e>     ui.write 2\n
  e>     print 1\n
  e>     print 2\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1
  remote: ui.write 2
  remote: print 1
  remote: print 2
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

print() to stdout and stderr both get captured

  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.fail = python:$TESTTMP/failhook:hookprintstderrandstdout
  > EOF

  $ debugwireproto << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 216:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     stderr 1\n
  e>     stderr 2\n
  e>     stdout 1\n
  e>     stdout 2\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: stderr 1
  remote: stderr 2
  remote: stdout 1
  remote: stdout 2
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 216:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     stderr 1\n
  e>     stderr 2\n
  e>     stdout 1\n
  e>     stdout 2\n
  e>     transaction abort!\n
  e>     rollback completed\n
  e>     abort: pretxnchangegroup.fail hook failed\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: stderr 1
  remote: stderr 2
  remote: stdout 1
  remote: stdout 2
  remote: transaction abort!
  remote: rollback completed
  remote: abort: pretxnchangegroup.fail hook failed
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 0
  result: 0
  remote output: 

  $ cd ..

Pushing a bundle1 with no output

  $ hg init simplerepo
  $ cd simplerepo

  $ debugwireproto 1 << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 100:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 1
  result: 1
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 100:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 1
  result: 1
  remote output: 

  $ cd ..

Pushing a bundle1 with ui.write() and ui.write_err()

  $ cat > $TESTTMP/hook << EOF
  > def hookuiwrite(ui, repo, **kwargs):
  >     ui.write('ui.write 1\n')
  >     ui.write_err('ui.write_err 1\n')
  >     ui.write('ui.write 2\n')
  >     ui.write_err('ui.write_err 2\n')
  > EOF

  $ hg init uiwriterepo
  $ cd uiwriterepo
  $ cat > .hg/hgrc << EOF
  > [hooks]
  > pretxnchangegroup.hook = python:$TESTTMP/hook:hookuiwrite
  > EOF

  $ debugwireproto 1 << EOF
  > command unbundle
  > # This is "force" in hex.
  >     heads 666f726365
  >     PUSHFILE ../initial.v1.hg
  > EOF
  testing ssh1
  creating ssh peer from handshake results
  i> write(104) -> None:
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 4:
  o>     384\n
  o> readline() -> 384:
  o>     capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN\n
  o> readline() -> 2:
  o>     1\n
  o> readline() -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 152:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1\n
  e>     ui.write_err 1\n
  e>     ui.write 2\n
  e>     ui.write_err 2\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1
  remote: ui.write_err 1
  remote: ui.write 2
  remote: ui.write_err 2
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 1
  result: 1
  remote output: 
  
  testing ssh2
  creating ssh peer from handshake results
  i> write(171) -> None:
  i>     upgrade * proto=exp-ssh-v2-0001\n (glob)
  i>     hello\n
  i>     between\n
  i>     pairs 81\n
  i>     0000000000000000000000000000000000000000-0000000000000000000000000000000000000000
  i> flush() -> None
  o> readline() -> 62:
  o>     upgraded * exp-ssh-v2-0001\n (glob)
  o> readline() -> 4:
  o>     383\n
  o> read(383) -> 383: capabilities: lookup changegroupsubset branchmap pushkey known getbundle unbundlehash batch streamreqs=generaldelta,revlogv1 $USUAL_BUNDLE2_CAPS_SERVER$ unbundle=HG10GZ,HG10BZ,HG10UN
  o> read(1) -> 1:
  o>     \n
  sending unbundle command
  i> write(9) -> None:
  i>     unbundle\n
  i> write(9) -> None:
  i>     heads 10\n
  i> write(10) -> None: 666f726365
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  i> write(4) -> None:
  i>     426\n
  i> write(426) -> None:
  i>     HG10UN\x00\x00\x00\x9eh\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00>cba485ca3678256e044428f70f58291196f6e9de\n
  i>     test\n
  i>     0 0\n
  i>     foo\n
  i>     \n
  i>     initial\x00\x00\x00\x00\x00\x00\x00\x8d\xcb\xa4\x85\xca6x%n\x04D(\xf7\x0fX)\x11\x96\xf6\xe9\xde\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00-foo\x00362fef284ce2ca02aecc8de6d5e8a1c3af0556fe\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x07foo\x00\x00\x00b6/\xef(L\xe2\xca\x02\xae\xcc\x8d\xe6\xd5\xe8\xa1\xc3\xaf\x05V\xfe\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00h\x98b\x13\xbdD\x85\xeaQS55\xe3\xfc\x9ex\x00zq\x1f\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x020\n
  i>     \x00\x00\x00\x00\x00\x00\x00\x00
  i> write(2) -> None:
  i>     0\n
  i> flush() -> None
  o> readline() -> 2:
  o>     0\n
  e> read(-1) -> 152:
  e>     adding changesets\n
  e>     adding manifests\n
  e>     adding file changes\n
  e>     added 1 changesets with 1 changes to 1 files\n
  e>     ui.write 1\n
  e>     ui.write_err 1\n
  e>     ui.write 2\n
  e>     ui.write_err 2\n
  remote: adding changesets
  remote: adding manifests
  remote: adding file changes
  remote: added 1 changesets with 1 changes to 1 files
  remote: ui.write 1
  remote: ui.write_err 1
  remote: ui.write 2
  remote: ui.write_err 2
  o> read(0) -> 0: 
  o> readline() -> 2:
  o>     1\n
  o> read(1) -> 1: 1
  result: 1
  remote output: 
