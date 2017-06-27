  $ cat >> $HGRCPATH <<EOF
  > [extensions]
  > rebase=
  > 
  > [phases]
  > publish=False
  > 
  > [alias]
  > tglog = log -G --template "{rev}: '{desc}' {branches}\n"
  > tglogp = log -G --template "{rev}:{phase} '{desc}' {branches}\n"
  > EOF


  $ hg init a
  $ cd a

  $ echo A > A
  $ hg ci -Am A
  adding A

  $ echo B > B
  $ hg ci -Am B
  adding B

  $ echo C >> A
  $ hg ci -m C

  $ hg up -q -C 0

  $ echo D >> A
  $ hg ci -m D
  created new head

  $ echo E > E
  $ hg ci -Am E
  adding E

  $ cd ..


Changes during an interruption - continue:

  $ hg clone -q -u . a a1
  $ cd a1

  $ hg tglog
  @  4: 'E'
  |
  o  3: 'D'
  |
  | o  2: 'C'
  | |
  | o  1: 'B'
  |/
  o  0: 'A'
  
Rebasing B onto E:

  $ hg rebase -s 1 -d 4
  rebasing 1:27547f69f254 "B"
  rebasing 2:965c486023db "C"
  merging A
  warning: conflicts while merging A! (edit, then use 'hg resolve --mark')
  unresolved conflicts (see hg resolve, then hg rebase --continue)
  [1]

Force a commit on C during the interruption:

  $ hg up -q -C 2 --config 'extensions.rebase=!'

  $ echo 'Extra' > Extra
  $ hg add Extra
  $ hg ci -m 'Extra' --config 'extensions.rebase=!'

Force this commit onto secret phase

  $ hg phase --force --secret 6

  $ hg tglogp
  @  6:secret 'Extra'
  |
  | o  5:draft 'B'
  | |
  | o  4:draft 'E'
  | |
  | o  3:draft 'D'
  | |
  o |  2:draft 'C'
  | |
  o |  1:draft 'B'
  |/
  o  0:draft 'A'
  
Resume the rebasing:

  $ hg rebase --continue
  already rebased 1:27547f69f254 "B" as 45396c49d53b
  rebasing 2:965c486023db "C"
  merging A
  warning: conflicts while merging A! (edit, then use 'hg resolve --mark')
  unresolved conflicts (see hg resolve, then hg rebase --continue)
  [1]

Solve the conflict and go on:

  $ echo 'conflict solved' > A
  $ rm A.orig
  $ hg resolve -m A
  (no more unresolved files)
  continue: hg rebase --continue

  $ hg rebase --continue
  already rebased 1:27547f69f254 "B" as 45396c49d53b
  rebasing 2:965c486023db "C"
  warning: new changesets detected on source branch, not stripping

  $ hg tglogp
  o  7:draft 'C'
  |
  | o  6:secret 'Extra'
  | |
  o |  5:draft 'B'
  | |
  @ |  4:draft 'E'
  | |
  o |  3:draft 'D'
  | |
  | o  2:draft 'C'
  | |
  | o  1:draft 'B'
  |/
  o  0:draft 'A'
  
  $ cd ..


Changes during an interruption - abort:

  $ hg clone -q -u . a a2
  $ cd a2

  $ hg tglog
  @  4: 'E'
  |
  o  3: 'D'
  |
  | o  2: 'C'
  | |
  | o  1: 'B'
  |/
  o  0: 'A'
  
Rebasing B onto E:

  $ hg rebase -s 1 -d 4
  rebasing 1:27547f69f254 "B"
  rebasing 2:965c486023db "C"
  merging A
  warning: conflicts while merging A! (edit, then use 'hg resolve --mark')
  unresolved conflicts (see hg resolve, then hg rebase --continue)
  [1]

Force a commit on B' during the interruption:

  $ hg up -q -C 5 --config 'extensions.rebase=!'

  $ echo 'Extra' > Extra
  $ hg add Extra
  $ hg ci -m 'Extra' --config 'extensions.rebase=!'

  $ hg tglog
  @  6: 'Extra'
  |
  o  5: 'B'
  |
  o  4: 'E'
  |
  o  3: 'D'
  |
  | o  2: 'C'
  | |
  | o  1: 'B'
  |/
  o  0: 'A'
  
Abort the rebasing:

  $ hg rebase --abort
  warning: new changesets detected on target branch, can't strip
  rebase aborted

  $ hg tglog
  @  6: 'Extra'
  |
  o  5: 'B'
  |
  o  4: 'E'
  |
  o  3: 'D'
  |
  | o  2: 'C'
  | |
  | o  1: 'B'
  |/
  o  0: 'A'
  
  $ cd ..

Changes during an interruption - abort (again):

  $ hg clone -q -u . a a3
  $ cd a3

  $ hg tglogp
  @  4:draft 'E'
  |
  o  3:draft 'D'
  |
  | o  2:draft 'C'
  | |
  | o  1:draft 'B'
  |/
  o  0:draft 'A'
  
Rebasing B onto E:

  $ hg rebase -s 1 -d 4
  rebasing 1:27547f69f254 "B"
  rebasing 2:965c486023db "C"
  merging A
  warning: conflicts while merging A! (edit, then use 'hg resolve --mark')
  unresolved conflicts (see hg resolve, then hg rebase --continue)
  [1]

Change phase on B and B'

  $ hg up -q -C 5 --config 'extensions.rebase=!'
  $ hg phase --public 1
  $ hg phase --public 5
  $ hg phase --secret -f 2

  $ hg tglogp
  @  5:public 'B'
  |
  o  4:public 'E'
  |
  o  3:public 'D'
  |
  | o  2:secret 'C'
  | |
  | o  1:public 'B'
  |/
  o  0:public 'A'
  
Abort the rebasing:

  $ hg rebase --abort
  warning: can't clean up public changesets 45396c49d53b
  rebase aborted

  $ hg tglogp
  @  5:public 'B'
  |
  o  4:public 'E'
  |
  o  3:public 'D'
  |
  | o  2:secret 'C'
  | |
  | o  1:public 'B'
  |/
  o  0:public 'A'
  

Test rebase interrupted by hooks

  $ hg up 2
  1 files updated, 0 files merged, 1 files removed, 0 files unresolved
  $ echo F > F
  $ hg add F
  $ hg ci -m F

  $ cd ..

(precommit version)

  $ cp -R a3 hook-precommit
  $ cd hook-precommit
  $ hg rebase --source 2 --dest 5 --tool internal:other --config 'hooks.precommit=hg status | grep "M A"'
  rebasing 2:965c486023db "C"
  M A
  rebasing 6:a0b2430ebfb8 "F" (tip)
  abort: precommit hook exited with status 1
  [255]
  $ hg tglogp
  @  7:secret 'C'
  |
  | @  6:secret 'F'
  | |
  o |  5:public 'B'
  | |
  o |  4:public 'E'
  | |
  o |  3:public 'D'
  | |
  | o  2:secret 'C'
  | |
  | o  1:public 'B'
  |/
  o  0:public 'A'
  
  $ hg rebase --continue
  already rebased 2:965c486023db "C" as 401ccec5e39f
  rebasing 6:a0b2430ebfb8 "F"
  saved backup bundle to $TESTTMP/hook-precommit/.hg/strip-backup/965c486023db-aa6250e7-backup.hg (glob)
  $ hg tglogp
  @  6:secret 'F'
  |
  o  5:secret 'C'
  |
  o  4:public 'B'
  |
  o  3:public 'E'
  |
  o  2:public 'D'
  |
  | o  1:public 'B'
  |/
  o  0:public 'A'
  
  $ cd ..

(pretxncommit version)

  $ cp -R a3 hook-pretxncommit
  $ cd hook-pretxncommit
  $ hg rebase --source 2 --dest 5 --tool internal:other --config 'hooks.pretxncommit=hg log -r $HG_NODE | grep "summary:     C"'
  rebasing 2:965c486023db "C"
  summary:     C
  rebasing 6:a0b2430ebfb8 "F" (tip)
  transaction abort!
  rollback completed
  abort: pretxncommit hook exited with status 1
  [255]
  $ hg tglogp
  @  7:secret 'C'
  |
  | @  6:secret 'F'
  | |
  o |  5:public 'B'
  | |
  o |  4:public 'E'
  | |
  o |  3:public 'D'
  | |
  | o  2:secret 'C'
  | |
  | o  1:public 'B'
  |/
  o  0:public 'A'
  
  $ hg rebase --continue
  already rebased 2:965c486023db "C" as 401ccec5e39f
  rebasing 6:a0b2430ebfb8 "F"
  saved backup bundle to $TESTTMP/hook-pretxncommit/.hg/strip-backup/965c486023db-aa6250e7-backup.hg (glob)
  $ hg tglogp
  @  6:secret 'F'
  |
  o  5:secret 'C'
  |
  o  4:public 'B'
  |
  o  3:public 'E'
  |
  o  2:public 'D'
  |
  | o  1:public 'B'
  |/
  o  0:public 'A'
  
  $ cd ..

(pretxnclose version)

  $ cp -R a3 hook-pretxnclose
  $ cd hook-pretxnclose
  $ hg rebase --source 2 --dest 5 --tool internal:other --config 'hooks.pretxnclose=hg log -r tip | grep "summary:     C"'
  rebasing 2:965c486023db "C"
  summary:     C
  rebasing 6:a0b2430ebfb8 "F" (tip)
  transaction abort!
  rollback completed
  abort: pretxnclose hook exited with status 1
  [255]
  $ hg tglogp
  @  7:secret 'C'
  |
  | @  6:secret 'F'
  | |
  o |  5:public 'B'
  | |
  o |  4:public 'E'
  | |
  o |  3:public 'D'
  | |
  | o  2:secret 'C'
  | |
  | o  1:public 'B'
  |/
  o  0:public 'A'
  
  $ hg rebase --continue
  already rebased 2:965c486023db "C" as 401ccec5e39f
  rebasing 6:a0b2430ebfb8 "F"
  saved backup bundle to $TESTTMP/hook-pretxnclose/.hg/strip-backup/965c486023db-aa6250e7-backup.hg (glob)
  $ hg tglogp
  @  6:secret 'F'
  |
  o  5:secret 'C'
  |
  o  4:public 'B'
  |
  o  3:public 'E'
  |
  o  2:public 'D'
  |
  | o  1:public 'B'
  |/
  o  0:public 'A'
  
  $ cd ..
