=======================================================
Test check for obsolescence and instability during push
=======================================================

  $ . $TESTDIR/testlib/obsmarker-common.sh

  $ cat >> $HGRCPATH << EOF
  > [phases]
  > publish=false
  > [experimental]
  > evolution = all
  > EOF


Tests that pushing orphaness to the server is detected
======================================================

initial setup

  $ mkdir base
  $ cd base
  $ hg init server
  $ cd server
  $ mkcommit root
  $ hg phase --public .
  $ mkcommit commit_A0_
  $ mkcommit commit_B0_
  $ cd ..
  $ hg init client
  $ cd client
  $ echo '[paths]' >> .hg/hgrc
  $ echo 'default=../server' >> .hg/hgrc
  $ hg pull
  pulling from $TESTTMP/base/server
  requesting all changes
  adding changesets
  adding manifests
  adding file changes
  added 3 changesets with 3 changes to 3 files
  new changesets 1e4be0697311:c09d8ab29fda (2 drafts)
  (run 'hg update' to get a working copy)
  $ hg up 'desc("root")'
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved
(having some unrelated change affects discovery result, we should ideally test both case)
  $ hg branch unrelated --quiet
  $ mkcommit unrelated
  $ hg up null
  0 files updated, 0 files merged, 2 files removed, 0 files unresolved
  $ hg log -G
  o  changeset:   3:16affbe0f986
  |  branch:      unrelated
  |  tag:         tip
  |  parent:      0:1e4be0697311
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     unrelated
  |
  | o  changeset:   2:c09d8ab29fda
  | |  user:        test
  | |  date:        Thu Jan 01 00:00:00 1970 +0000
  | |  summary:     commit_B0_
  | |
  | o  changeset:   1:37624bf21024
  |/   user:        test
  |    date:        Thu Jan 01 00:00:00 1970 +0000
  |    summary:     commit_A0_
  |
  o  changeset:   0:1e4be0697311
     user:        test
     date:        Thu Jan 01 00:00:00 1970 +0000
     summary:     root
  
  $ cd ..
  $ cd ..


Orphan from pruning
-------------------

Setup

  $ cp -R base check-pruned
  $ cd check-pruned/client
  $ hg debugobsolete --record-parents `getid 'desc("commit_A0_")'`
  1 new obsolescence markers
  obsoleted 1 changesets
  1 new orphan changesets
  $ hg log -G
  o  changeset:   3:16affbe0f986
  |  branch:      unrelated
  |  tag:         tip
  |  parent:      0:1e4be0697311
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     unrelated
  |
  | *  changeset:   2:c09d8ab29fda
  | |  user:        test
  | |  date:        Thu Jan 01 00:00:00 1970 +0000
  | |  instability: orphan
  | |  summary:     commit_B0_
  | |
  | x  changeset:   1:37624bf21024
  |/   user:        test
  |    date:        Thu Jan 01 00:00:00 1970 +0000
  |    obsolete:    pruned
  |    summary:     commit_A0_
  |
  o  changeset:   0:1e4be0697311
     user:        test
     date:        Thu Jan 01 00:00:00 1970 +0000
     summary:     root
  

Pushing the result is prevented with a message

  $ hg push --new-branch
  pushing to $TESTTMP/check-pruned/server
  searching for changes
  abort: push includes orphan changeset: c09d8ab29fda!
  [255]

  $ cd ../..
