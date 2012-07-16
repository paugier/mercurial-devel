  $ cat >> $HGRCPATH << EOF
  > [extensions]
  > graphlog=
  > [phases]
  > # public changeset are not obsolete
  > publish=false
  > EOF
  $ mkcommit() {
  >    echo "$1" > "$1"
  >    hg add "$1"
  >    hg ci -m "add $1"
  > }
  $ getid() {
  >    hg id --debug -ir "desc('$1')"
  > }


  $ hg init tmpa
  $ cd tmpa

Killing a single changeset without replacement

  $ mkcommit kill_me
  $ hg debugobsolete -d '0 0' `getid kill_me` -u babar
  $ hg debugobsolete
  97b7c2d76b1845ed3eb988cd612611e72406cef0 0 {'date': '0 0', 'user': 'babar'}
  $ cd ..

Killing a single changeset with replacement

  $ hg init tmpb
  $ cd tmpb
  $ mkcommit a
  $ mkcommit b
  $ mkcommit original_c
  $ hg up "desc('b')"
  0 files updated, 0 files merged, 1 files removed, 0 files unresolved
  $ mkcommit new_c
  created new head
  $ hg debugobsolete `getid original_c`  `getid new_c` -d '56 12'
  $ hg debugobsolete
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}

do it again (it read the obsstore before adding new changeset)

  $ hg up '.^'
  0 files updated, 0 files merged, 1 files removed, 0 files unresolved
  $ mkcommit new_2_c
  created new head
  $ hg debugobsolete -d '1337 0' `getid new_c` `getid new_2_c`
  $ hg debugobsolete
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}
  cdbce2fbb16313928851e97e0d85413f3f7eb77f ca819180edb99ed25ceafb3e9584ac287e240b00 0 {'date': '1337 0', 'user': 'test'}

Register two markers with a missing node

  $ hg up '.^'
  0 files updated, 0 files merged, 1 files removed, 0 files unresolved
  $ mkcommit new_3_c
  created new head
  $ hg debugobsolete -d '1338 0' `getid new_2_c` 1337133713371337133713371337133713371337
  $ hg debugobsolete -d '1339 0' 1337133713371337133713371337133713371337 `getid new_3_c`
  $ hg debugobsolete
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}
  cdbce2fbb16313928851e97e0d85413f3f7eb77f ca819180edb99ed25ceafb3e9584ac287e240b00 0 {'date': '1337 0', 'user': 'test'}
  ca819180edb99ed25ceafb3e9584ac287e240b00 1337133713371337133713371337133713371337 0 {'date': '1338 0', 'user': 'test'}
  1337133713371337133713371337133713371337 5601fb93a350734d935195fee37f4054c529ff39 0 {'date': '1339 0', 'user': 'test'}

Check that graphlog detect that a changeset is obsolete:

  $ hg glog
  @  changeset:   5:5601fb93a350
  |  tag:         tip
  |  parent:      1:7c3bad9141dc
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add new_3_c
  |
  o  changeset:   1:7c3bad9141dc
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add b
  |
  o  changeset:   0:1f0dee641bb7
     user:        test
     date:        Thu Jan 01 00:00:00 1970 +0000
     summary:     add a
  

Check that public changeset are not accounted as obsolete:

  $ hg phase --public 2
  $ hg --config 'extensions.graphlog=' glog
  @  changeset:   5:5601fb93a350
  |  tag:         tip
  |  parent:      1:7c3bad9141dc
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add new_3_c
  |
  | o  changeset:   2:245bde4270cd
  |/   user:        test
  |    date:        Thu Jan 01 00:00:00 1970 +0000
  |    summary:     add original_c
  |
  o  changeset:   1:7c3bad9141dc
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add b
  |
  o  changeset:   0:1f0dee641bb7
     user:        test
     date:        Thu Jan 01 00:00:00 1970 +0000
     summary:     add a
  

  $ cd ..

Exchange Test
============================

Destination repo does not have any data
---------------------------------------

Try to pull markers
(extinct changeset are excluded but marker are pushed)

  $ hg init tmpc
  $ cd tmpc
  $ hg pull ../tmpb
  pulling from ../tmpb
  requesting all changes
  adding changesets
  adding manifests
  adding file changes
  added 4 changesets with 4 changes to 4 files (+1 heads)
  (run 'hg heads' to see heads, 'hg merge' to merge)
  $ hg debugobsolete
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}
  cdbce2fbb16313928851e97e0d85413f3f7eb77f ca819180edb99ed25ceafb3e9584ac287e240b00 0 {'date': '1337 0', 'user': 'test'}
  ca819180edb99ed25ceafb3e9584ac287e240b00 1337133713371337133713371337133713371337 0 {'date': '1338 0', 'user': 'test'}
  1337133713371337133713371337133713371337 5601fb93a350734d935195fee37f4054c529ff39 0 {'date': '1339 0', 'user': 'test'}

Rollback//Transaction support

  $ hg debugobsolete -d '1340 0' aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  $ hg debugobsolete
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}
  cdbce2fbb16313928851e97e0d85413f3f7eb77f ca819180edb99ed25ceafb3e9584ac287e240b00 0 {'date': '1337 0', 'user': 'test'}
  ca819180edb99ed25ceafb3e9584ac287e240b00 1337133713371337133713371337133713371337 0 {'date': '1338 0', 'user': 'test'}
  1337133713371337133713371337133713371337 5601fb93a350734d935195fee37f4054c529ff39 0 {'date': '1339 0', 'user': 'test'}
  aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 0 {'date': '1340 0', 'user': 'test'}
  $ hg rollback -n
  repository tip rolled back to revision 3 (undo debugobsolete)
  $ hg rollback
  repository tip rolled back to revision 3 (undo debugobsolete)
  $ hg debugobsolete
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}
  cdbce2fbb16313928851e97e0d85413f3f7eb77f ca819180edb99ed25ceafb3e9584ac287e240b00 0 {'date': '1337 0', 'user': 'test'}
  ca819180edb99ed25ceafb3e9584ac287e240b00 1337133713371337133713371337133713371337 0 {'date': '1338 0', 'user': 'test'}
  1337133713371337133713371337133713371337 5601fb93a350734d935195fee37f4054c529ff39 0 {'date': '1339 0', 'user': 'test'}

  $ cd ..

Try to pull markers

  $ hg init tmpd
  $ hg -R tmpb push tmpd
  pushing to tmpd
  searching for changes
  adding changesets
  adding manifests
  adding file changes
  added 4 changesets with 4 changes to 4 files (+1 heads)
  $ hg -R tmpd debugobsolete
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}
  cdbce2fbb16313928851e97e0d85413f3f7eb77f ca819180edb99ed25ceafb3e9584ac287e240b00 0 {'date': '1337 0', 'user': 'test'}
  ca819180edb99ed25ceafb3e9584ac287e240b00 1337133713371337133713371337133713371337 0 {'date': '1338 0', 'user': 'test'}
  1337133713371337133713371337133713371337 5601fb93a350734d935195fee37f4054c529ff39 0 {'date': '1339 0', 'user': 'test'}


Destination repo have existing data
---------------------------------------

On pull

  $ hg init tmpe
  $ cd tmpe
  $ hg debugobsolete -d '1339 0' 2448244824482448244824482448244824482448 1339133913391339133913391339133913391339
  $ hg pull ../tmpb
  pulling from ../tmpb
  requesting all changes
  adding changesets
  adding manifests
  adding file changes
  added 4 changesets with 4 changes to 4 files (+1 heads)
  (run 'hg heads' to see heads, 'hg merge' to merge)
  $ hg debugobsolete
  2448244824482448244824482448244824482448 1339133913391339133913391339133913391339 0 {'date': '1339 0', 'user': 'test'}
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}
  cdbce2fbb16313928851e97e0d85413f3f7eb77f ca819180edb99ed25ceafb3e9584ac287e240b00 0 {'date': '1337 0', 'user': 'test'}
  ca819180edb99ed25ceafb3e9584ac287e240b00 1337133713371337133713371337133713371337 0 {'date': '1338 0', 'user': 'test'}
  1337133713371337133713371337133713371337 5601fb93a350734d935195fee37f4054c529ff39 0 {'date': '1339 0', 'user': 'test'}


On push

  $ hg push ../tmpc
  pushing to ../tmpc
  searching for changes
  no changes found
  [1]
  $ hg -R ../tmpc debugobsolete
  245bde4270cd1072a27757984f9cda8ba26f08ca cdbce2fbb16313928851e97e0d85413f3f7eb77f 0 {'date': '56 12', 'user': 'test'}
  cdbce2fbb16313928851e97e0d85413f3f7eb77f ca819180edb99ed25ceafb3e9584ac287e240b00 0 {'date': '1337 0', 'user': 'test'}
  ca819180edb99ed25ceafb3e9584ac287e240b00 1337133713371337133713371337133713371337 0 {'date': '1338 0', 'user': 'test'}
  1337133713371337133713371337133713371337 5601fb93a350734d935195fee37f4054c529ff39 0 {'date': '1339 0', 'user': 'test'}
  2448244824482448244824482448244824482448 1339133913391339133913391339133913391339 0 {'date': '1339 0', 'user': 'test'}

detect outgoing obsolete and unstable
---------------------------------------


  $ hg glog
  o  changeset:   3:5601fb93a350
  |  tag:         tip
  |  parent:      1:7c3bad9141dc
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add new_3_c
  |
  | o  changeset:   2:245bde4270cd
  |/   user:        test
  |    date:        Thu Jan 01 00:00:00 1970 +0000
  |    summary:     add original_c
  |
  o  changeset:   1:7c3bad9141dc
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add b
  |
  o  changeset:   0:1f0dee641bb7
     user:        test
     date:        Thu Jan 01 00:00:00 1970 +0000
     summary:     add a
  
  $ hg up 'desc("new_3_c")'
  3 files updated, 0 files merged, 0 files removed, 0 files unresolved
  $ mkcommit original_d
  $ mkcommit original_e
  $ hg debugobsolete `getid original_d` -d '0 0'
  $ hg log -r 'obsolete()'
  changeset:   4:7c694bff0650
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     add original_d
  
  $ hg glog -r '::unstable()'
  @  changeset:   5:6e572121998e
  |  tag:         tip
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add original_e
  |
  x  changeset:   4:7c694bff0650
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add original_d
  |
  o  changeset:   3:5601fb93a350
  |  parent:      1:7c3bad9141dc
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add new_3_c
  |
  o  changeset:   1:7c3bad9141dc
  |  user:        test
  |  date:        Thu Jan 01 00:00:00 1970 +0000
  |  summary:     add b
  |
  o  changeset:   0:1f0dee641bb7
     user:        test
     date:        Thu Jan 01 00:00:00 1970 +0000
     summary:     add a
  

refuse to push obsolete changeset

  $ hg push ../tmpc/ -r 'desc("original_d")'
  pushing to ../tmpc/
  searching for changes
  abort: push includes an obsolete changeset: 7c694bff0650!
  [255]

refuse to push unstable changeset

  $ hg push ../tmpc/
  pushing to ../tmpc/
  searching for changes
  abort: push includes an unstable changeset: 6e572121998e!
  [255]

Test that extinct changeset are properly detected

  $ hg log -r 'extinct()'

Don't try to push extinct changeset

  $ hg init ../tmpf
  $ hg out  ../tmpf
  comparing with ../tmpf
  searching for changes
  changeset:   0:1f0dee641bb7
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     add a
  
  changeset:   1:7c3bad9141dc
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     add b
  
  changeset:   2:245bde4270cd
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     add original_c
  
  changeset:   3:5601fb93a350
  parent:      1:7c3bad9141dc
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     add new_3_c
  
  changeset:   4:7c694bff0650
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     add original_d
  
  changeset:   5:6e572121998e
  tag:         tip
  user:        test
  date:        Thu Jan 01 00:00:00 1970 +0000
  summary:     add original_e
  
  $ hg push ../tmpf -f # -f because be push unstable too
  pushing to ../tmpf
  searching for changes
  adding changesets
  adding manifests
  adding file changes
  added 6 changesets with 6 changes to 6 files (+1 heads)

no warning displayed

  $ hg push ../tmpf
  pushing to ../tmpf
  searching for changes
  no changes found
  [1]
