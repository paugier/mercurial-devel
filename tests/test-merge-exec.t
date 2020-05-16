===============================================
Testing merge involving change to the exec flag
===============================================

#require execbit


Initial setup
==============


  $ hg init base-repo
  $ cd base-repo
  $ cat << EOF > a
  > 1
  > 2
  > 3
  > 4
  > 5
  > 6
  > 7
  > 8
  > 9
  > EOF
  $ touch b
  $ hg add a b
  $ hg commit -m "initial commit"
  $ cd ..

Testing merging mode change
===========================

setup

Change on one side, executable bit on the other

  $ hg clone base-repo simple-merge-repo
  updating to branch default
  2 files updated, 0 files merged, 0 files removed, 0 files unresolved
  $ cd simple-merge-repo
  $ chmod +x a
  $ hg ci -m "make a executable, no change"
  $ [ -x a ] || echo "executable bit not recorded"
  $ hg up ".^"
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved
  $ cat << EOF > a
  > 1
  > 2
  > 3
  > 4
  > 5
  > 6
  > 7
  > x
  > 9
  > EOF
  $ hg commit -m "edit end of file"
  created new head

merge them (from the update side)

  $ hg merge 'desc("make a executable, no change")'
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved
  (branch merge, don't forget to commit)
  $ hg st
  M a
  $ [ -x a ] || echo "executable bit lost"

merge them (from the chmod side)

  $ hg up -C 'desc("make a executable, no change")'
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved
  $ hg merge 'desc("edit end of file")'
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved
  (branch merge, don't forget to commit)
  $ hg st
  M a
  $ [ -x a ] || echo "executable bit lost"


  $ cd ..

Testing merging mode change with rename
=======================================

  $ hg clone base-repo rename-merge-repo
  updating to branch default
  2 files updated, 0 files merged, 0 files removed, 0 files unresolved
  $ cd rename-merge-repo

make "a" executable on one side

  $ chmod +x a
  $ hg status
  M a
  $ hg ci -m "make a executable"
  $ [ -x a ] || echo "executable bit not recorded"
  $ hg up ".^"
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved

make "a" renamed on the other side

  $ hg mv a z
  $ hg st --copies
  A z
    a
  R a
  $ hg ci -m "rename a to z"
  created new head

merge them (from the rename side)

  $ hg merge 'desc("make a executable")'
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved (false !)
  0 files updated, 0 files merged, 0 files removed, 0 files unresolved (true !)
  (branch merge, don't forget to commit)
  $ hg st --copies
  M z (false !)
    a (false !)
  $ [ -x z ] || echo "executable bit lost"
  executable bit lost (true !)

merge them (from the chmod side)

  $ hg up -C 'desc("make a executable")'
  1 files updated, 0 files merged, 1 files removed, 0 files unresolved
  $ hg merge 'desc("rename a to z")'
  1 files updated, 0 files merged, 0 files removed, 0 files unresolved (false !)
  1 files updated, 0 files merged, 1 files removed, 0 files unresolved (true !)
  (branch merge, don't forget to commit)
  $ hg st --copies
  M z
    a (false !)
  R a
  $ [ -x z ] || echo "executable bit lost"
  executable bit lost (true !)


  $ cd ..
