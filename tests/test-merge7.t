initial
  $ hg init test-a
  $ cd test-a
  $ cat >test.txt <<"EOF"
  > 1
  > 2
  > 3
  > EOF
  $ hg add test.txt
  $ hg commit -m "Initial"

clone
  $ cd ..
  $ hg clone test-a test-b
  updating to branch default
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved

change test-a
  $ cd test-a
  $ cat >test.txt <<"EOF"
  > one
  > two
  > three
  > EOF
  $ hg commit -m "Numbers as words"

change test-b
  $ cd ../test-b
  $ cat >test.txt <<"EOF"
  > 1
  > 2.5
  > 3
  > EOF
  $ hg commit -m "2 -> 2.5"

now pull and merge from test-a
  $ hg pull ../test-a
  pulling from ../test-a
  searching for changes
  adding changesets
  adding manifests
  adding file changes
  added 1 changesets with 1 changes to 1 files (+1 heads)
  new changesets 96b70246a118
  (run 'hg heads' to see heads, 'hg merge' to merge)
  $ hg merge
  merging test.txt
  warning: conflicts while merging test.txt! (edit, then use 'hg resolve --mark')
  0 files updated, 0 files merged, 0 files removed, 1 files unresolved
  use 'hg resolve' to retry unresolved file merges or 'hg merge --abort' to abandon
  [1]
resolve conflict
  $ cat >test.txt <<"EOF"
  > one
  > two-point-five
  > three
  > EOF
  $ rm -f *.orig
  $ hg resolve -m test.txt
  (no more unresolved files)
  $ hg commit -m "Merge 1"

change test-a again
  $ cd ../test-a
  $ cat >test.txt <<"EOF"
  > one
  > two-point-one
  > three
  > EOF
  $ hg commit -m "two -> two-point-one"

pull and merge from test-a again
  $ cd ../test-b
  $ hg pull ../test-a
  pulling from ../test-a
  searching for changes
  adding changesets
  adding manifests
  adding file changes
  added 1 changesets with 1 changes to 1 files (+1 heads)
  new changesets 40d11a4173a8
  (run 'hg heads' to see heads, 'hg merge' to merge)
  $ hg merge --debug
  resolving manifests
   branchmerge: True, force: False, partial: False
   ancestor: 96b70246a118, local: 50c3a7e29886+, remote: 40d11a4173a8
  starting 4 threads for background file closing (?)
   preserving test.txt for resolve of test.txt
   test.txt: versions differ -> m
  picked tool ':merge' for test.txt (binary False symlink False changedelete False)
  merging test.txt
  my test.txt@50c3a7e29886+ other test.txt@40d11a4173a8 ancestor test.txt@96b70246a118
  warning: conflicts while merging test.txt! (edit, then use 'hg resolve --mark')
  0 files updated, 0 files merged, 0 files removed, 1 files unresolved
  use 'hg resolve' to retry unresolved file merges or 'hg merge --abort' to abandon
  [1]

  $ cat test.txt
  one
  <<<<<<< working copy: 50c3a7e29886 - test: Merge 1
  two-point-five
  =======
  two-point-one
  >>>>>>> merge rev:    40d11a4173a8 - test: two -> two-point-one
  three

  $ hg debugindex test.txt
     rev linkrev       nodeid           p1           p2
       0       0 01365c4cca56 000000000000 000000000000
       1       1 7b013192566a 01365c4cca56 000000000000
       2       2 8fe46a3eb557 01365c4cca56 000000000000
       3       3 fc3148072371 7b013192566a 8fe46a3eb557
       4       4 d40249267ae3 8fe46a3eb557 000000000000

  $ hg log
  changeset:   4:40d11a4173a8
  tag:         tip
  parent:      2:96b70246a118
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     two -> two-point-one
  
  changeset:   3:50c3a7e29886
  parent:      1:d1e159716d41
  parent:      2:96b70246a118
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     Merge 1
  
  changeset:   2:96b70246a118
  parent:      0:b1832b9d912a
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     Numbers as words
  
  changeset:   1:d1e159716d41
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     2 -> 2.5
  
  changeset:   0:b1832b9d912a
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     Initial
  

  $ cd ..
