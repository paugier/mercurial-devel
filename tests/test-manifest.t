Source bundle was generated with the following script:

# hg init
# echo a > a
# ln -s a l
# hg ci -Ama -d'0 0'
# mkdir b
# echo a > b/a
# chmod +x b/a
# hg ci -Amb -d'1 0'

  $ hg init
  $ hg unbundle "$TESTDIR/bundles/test-manifest.hg"
  adding changesets
  adding manifests
  adding file changes
  added 2 changesets with 3 changes to 3 files
  new changesets b73562a03cfe:5bdc995175ba (2 drafts)
  (run 'hg update' to get a working copy)

The next call is expected to return nothing:

  $ hg manifest

  $ hg co
  3 files updated, 0 files merged, 0 files removed, 0 files unresolved

  $ hg manifest
  a
  b/a
  l

  $ hg files -vr .
           2   a
           2 x b/a
           1 l l
  $ hg files -r . -X b
  a
  l
  $ hg files -T '{path} {size} {flags}\n'
  a 2 
  b/a 2 x
  l 1 l
  $ hg files -T '{path} {node|shortest}\n' -r.
  a 5bdc
  b/a 5bdc
  l 5bdc

  $ hg manifest -v
  644   a
  755 * b/a
  644 @ l
  $ hg manifest -T '{path} {rev}\n'
  a 1
  b/a 1
  l 1

  $ hg manifest --debug
  b789fdd96dc2f3bd229c1dd8eedf0fc60e2b68e3 644   a
  b789fdd96dc2f3bd229c1dd8eedf0fc60e2b68e3 755 * b/a
  047b75c6d7a3ef6a2243bd0e99f94f6ea6683597 644 @ l

  $ hg manifest -r 0
  a
  l

  $ hg manifest -r 1
  a
  b/a
  l

  $ hg manifest -r tip
  a
  b/a
  l

  $ hg manifest tip
  a
  b/a
  l

  $ hg manifest --all
  a
  b/a
  l

The next two calls are expected to abort:

  $ hg manifest -r 2
  abort: unknown revision '2'!
  [255]

  $ hg manifest -r tip tip
  abort: please specify just one revision
  [255]

Testing the manifest full text cache utility
--------------------------------------------

Reminder of the manifest log content

  $ hg log --debug | grep 'manifest:'
  manifest:    1:1e01206b1d2f72bd55f2a33fa8ccad74144825b7
  manifest:    0:fce2a30dedad1eef4da95ca1dc0004157aa527cf

Showing the content of the caches after the above operations

  $ hg debugmanifestfulltextcache
  cache contains 1 manifest entries, in order of most to least recent:
  id: 1e01206b1d2f72bd55f2a33fa8ccad74144825b7, size 133 bytes
  total cache data size 157 bytes, on-disk 157 bytes

(Clearing the cache in case of any content)

  $ hg debugmanifestfulltextcache --clear

Adding a new persistent entry in the cache

  $ hg debugmanifestfulltextcache --add 1e01206b1d2f72bd55f2a33fa8ccad74144825b7

  $ hg debugmanifestfulltextcache
  cache contains 1 manifest entries, in order of most to least recent:
  id: 1e01206b1d2f72bd55f2a33fa8ccad74144825b7, size 133 bytes
  total cache data size 157 bytes, on-disk 157 bytes

Check we don't duplicated entry (added from the debug command)

  $ hg debugmanifestfulltextcache --add 1e01206b1d2f72bd55f2a33fa8ccad74144825b7
  $ hg debugmanifestfulltextcache
  cache contains 1 manifest entries, in order of most to least recent:
  id: 1e01206b1d2f72bd55f2a33fa8ccad74144825b7, size 133 bytes
  total cache data size 157 bytes, on-disk 157 bytes

Adding a second entry

  $ hg debugmanifestfulltextcache --add fce2a30dedad1eef4da95ca1dc0004157aa527cf
  $ hg debugmanifestfulltextcache
  cache contains 2 manifest entries, in order of most to least recent:
  id: fce2a30dedad1eef4da95ca1dc0004157aa527cf, size 87 bytes
  id: 1e01206b1d2f72bd55f2a33fa8ccad74144825b7, size 133 bytes
  total cache data size 268 bytes, on-disk 268 bytes

Accessing the initial entry again, refresh their order

  $ hg debugmanifestfulltextcache --add 1e01206b1d2f72bd55f2a33fa8ccad74144825b7
  $ hg debugmanifestfulltextcache
  cache contains 2 manifest entries, in order of most to least recent:
  id: 1e01206b1d2f72bd55f2a33fa8ccad74144825b7, size 133 bytes
  id: fce2a30dedad1eef4da95ca1dc0004157aa527cf, size 87 bytes
  total cache data size 268 bytes, on-disk 268 bytes

Check cache clearing

  $ hg debugmanifestfulltextcache --clear
  $ hg debugmanifestfulltextcache
  cache empty

Check adding multiple entry in one go:

  $ hg debugmanifestfulltextcache --add fce2a30dedad1eef4da95ca1dc0004157aa527cf  --add 1e01206b1d2f72bd55f2a33fa8ccad74144825b7
  $ hg debugmanifestfulltextcache
  cache contains 2 manifest entries, in order of most to least recent:
  id: 1e01206b1d2f72bd55f2a33fa8ccad74144825b7, size 133 bytes
  id: fce2a30dedad1eef4da95ca1dc0004157aa527cf, size 87 bytes
  total cache data size 268 bytes, on-disk 268 bytes
  $ hg debugmanifestfulltextcache --clear

Test caching behavior on actual operation
-----------------------------------------

Make sure we start empty

  $ hg debugmanifestfulltextcache
  cache empty

Commit should have the new node cached:

  $ echo a >> b/a
  $ hg commit -m 'foo'
  $ hg debugmanifestfulltextcache
  cache contains 2 manifest entries, in order of most to least recent:
  id: 26b8653b67af8c1a0a0317c4ee8dac50a41fdb65, size 133 bytes
  id: 1e01206b1d2f72bd55f2a33fa8ccad74144825b7, size 133 bytes
  total cache data size 314 bytes, on-disk 314 bytes
  $ hg log -r 'ancestors(., 1)' --debug | grep 'manifest:'
  manifest:    1:1e01206b1d2f72bd55f2a33fa8ccad74144825b7
  manifest:    2:26b8653b67af8c1a0a0317c4ee8dac50a41fdb65

hg update should warm the cache too

(force dirstate check to avoid flackiness in manifest order)
  $ hg debugrebuilddirstate

  $ hg update 0
  0 files updated, 0 files merged, 1 files removed, 0 files unresolved
  $ hg debugmanifestfulltextcache
  cache contains 3 manifest entries, in order of most to least recent:
  id: fce2a30dedad1eef4da95ca1dc0004157aa527cf, size 87 bytes
  id: 26b8653b67af8c1a0a0317c4ee8dac50a41fdb65, size 133 bytes
  id: 1e01206b1d2f72bd55f2a33fa8ccad74144825b7, size 133 bytes
  total cache data size 425 bytes, on-disk 425 bytes
  $ hg log -r '0' --debug | grep 'manifest:'
  manifest:    0:fce2a30dedad1eef4da95ca1dc0004157aa527cf

Test file removal (especially with pure).  The tests are crafted such that there
will be contiguous spans of existing entries to ensure that is handled properly.
(In this case, a.txt, aa.txt and c.txt, cc.txt, and ccc.txt)

  $ cat > $TESTTMP/manifest.py <<EOF
  > from mercurial import (
  >     extensions,
  >     manifest,
  > )
  > def extsetup(ui):
  >     manifest.FASTDELTA_TEXTDIFF_THRESHOLD = 0
  > EOF
  $ cat >> $HGRCPATH <<EOF
  > [extensions]
  > manifest = $TESTTMP/manifest.py
  > EOF

BROKEN: Pure removes should actually remove all dropped entries

  $ hg init repo
  $ cd repo
  $ echo a > a.txt
  $ echo aa > aa.txt
  $ echo b > b.txt
  $ echo c > c.txt
  $ echo c > cc.txt
  $ echo c > ccc.txt
  $ echo b > d.txt
  $ echo c > e.txt
  $ hg ci -Aqm 'a-e'

  $ hg rm b.txt d.txt
  $ hg ci -m 'remove b and d'

  $ hg debugdata -m 1
  a.txt\x00b789fdd96dc2f3bd229c1dd8eedf0fc60e2b68e3 (esc)
  aa.txt\x00a4bdc161c8fbb523c9a60409603f8710ff49a571 (esc)
  \x00.txt\x001e88685f5ddec574a34c70af492f95b6debc8741 (esc) (pure !)
  c.txt\x00149da44f2a4e14f488b7bd4157945a9837408c00 (esc)
  cc.txt\x00149da44f2a4e14f488b7bd4157945a9837408c00 (esc)
  ccc.txt\x00149da44f2a4e14f488b7bd4157945a9837408c00 (esc)
  \x00.txt\x001e88685f5ddec574a34c70af492f95b6debc8741 (esc) (pure !)
  e.txt\x00149da44f2a4e14f488b7bd4157945a9837408c00 (esc)

  $ hg up -C . 2>&1 | grep ValueError || true
      raise ValueError("Manifest lines not in sorted order.") (pure !)
  ValueError: Manifest lines not in sorted order. (pure !)

  $ hg verify || true
  checking changesets
  checking manifests
   manifest@1: reading delta c1f6b2f803ac: Non-hexadecimal digit found (pure !)
  crosschecking files in changesets and manifests
  checking files
  checked 2 changesets with 8 changes to 8 files
  1 integrity errors encountered! (pure !)
  (first damaged changeset appears to be 1) (pure !)

  $ hg rollback -q --config ui.rollback=True
  $ hg rm b.txt d.txt
  $ echo bb > bb.txt

BROKEN: A mix of adds and removes should remove all dropped entries.

  $ hg ci -Aqm 'remove b and d; add bb'

  $ hg debugdata -m 1
  a.txt\x00b789fdd96dc2f3bd229c1dd8eedf0fc60e2b68e3 (esc)
  aa.txt\x00a4bdc161c8fbb523c9a60409603f8710ff49a571 (esc)
  bb.txt\x0004c6faf8a9fdd848a5304dfc1704749a374dff44 (esc)
  c.txt\x00149da44f2a4e14f488b7bd4157945a9837408c00 (esc)
  cc.txt\x00149da44f2a4e14f488b7bd4157945a9837408c00 (esc)
  ccc.txt\x00149da44f2a4e14f488b7bd4157945a9837408c00 (esc)
  \x00.txt\x001e88685f5ddec574a34c70af492f95b6debc8741 (esc) (pure !)
  e.txt\x00149da44f2a4e14f488b7bd4157945a9837408c00 (esc)

  $ hg up -C . 2>&1 | grep ValueError || true
      raise ValueError("Manifest lines not in sorted order.") (pure !)
  ValueError: Manifest lines not in sorted order. (pure !)

  $ hg verify || true
  checking changesets
  checking manifests
   manifest@1: reading delta 0a0385480090: Manifest lines not in sorted order. (pure !)
  crosschecking files in changesets and manifests
   bb.txt@1: in changeset but not in manifest (pure !)
  checking files
  checked 2 changesets with 9 changes to 9 files
  2 integrity errors encountered! (pure !)
  (first damaged changeset appears to be 1) (pure !)
