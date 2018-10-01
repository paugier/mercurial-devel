  $ . $TESTDIR/wireprotohelpers.sh

  $ hg init server
  $ enablehttpv2 server
  $ cd server
  $ cat >> .hg/hgrc << EOF
  > [web]
  > push_ssl = false
  > allow-push = *
  > EOF
  $ hg debugdrawdag << EOF
  > C D
  > |/
  > B
  > |
  > A
  > EOF

  $ hg serve -p $HGPORT -d --pid-file hg.pid -E error.log
  $ cat hg.pid > $DAEMON_PIDS

pushkey for a bookmark works

  $ sendhttpv2peer << EOF
  > command pushkey
  >     namespace bookmarks
  >     key @
  >     old
  >     new 426bada5c67598ca65036d57d9e4b64b0c1ce7a0
  > EOF
  creating http peer for wire protocol version 2
  sending pushkey command
  s>     *\r\n (glob)
  s>     Accept-Encoding: identity\r\n
  s>     accept: application/mercurial-exp-framing-0005\r\n
  s>     content-type: application/mercurial-exp-framing-0005\r\n
  s>     content-length: 105\r\n
  s>     host: $LOCALIP:$HGPORT\r\n (glob)
  s>     user-agent: Mercurial debugwireproto\r\n
  s>     \r\n
  s>     a\x00\x00\x01\x00\x01\x01\x11\xa2Dargs\xa4CkeyA@InamespaceIbookmarksCnewX(426bada5c67598ca65036d57d9e4b64b0c1ce7a0Cold@DnameGpushkey
  s> makefile('rb', None)
  s>     HTTP/1.1 200 OK\r\n
  s>     Server: testing stub value\r\n
  s>     Date: $HTTP_DATE$\r\n
  s>     Content-Type: application/mercurial-exp-framing-0005\r\n
  s>     Transfer-Encoding: chunked\r\n
  s>     \r\n
  s>     13\r\n
  s>     \x0b\x00\x00\x01\x00\x02\x011
  s>     \xa1FstatusBok
  s>     \r\n
  received frame(size=11; request=1; stream=2; streamflags=stream-begin; type=command-response; flags=continuation)
  s>     9\r\n
  s>     \x01\x00\x00\x01\x00\x02\x001
  s>     \xf5
  s>     \r\n
  received frame(size=1; request=1; stream=2; streamflags=; type=command-response; flags=continuation)
  s>     8\r\n
  s>     \x00\x00\x00\x01\x00\x02\x002
  s>     \r\n
  s>     0\r\n
  s>     \r\n
  received frame(size=0; request=1; stream=2; streamflags=; type=command-response; flags=eos)
  response: True
  (sent 2 HTTP requests and * bytes; received * bytes in responses) (glob)

  $ sendhttpv2peer << EOF
  > command listkeys
  >     namespace bookmarks
  > EOF
  creating http peer for wire protocol version 2
  sending listkeys command
  s>     POST /api/exp-http-v2-0002/ro/listkeys HTTP/1.1\r\n
  s>     Accept-Encoding: identity\r\n
  s>     accept: application/mercurial-exp-framing-0005\r\n
  s>     content-type: application/mercurial-exp-framing-0005\r\n
  s>     content-length: 49\r\n
  s>     host: $LOCALIP:$HGPORT\r\n (glob)
  s>     user-agent: Mercurial debugwireproto\r\n
  s>     \r\n
  s>     )\x00\x00\x01\x00\x01\x01\x11\xa2Dargs\xa1InamespaceIbookmarksDnameHlistkeys
  s> makefile('rb', None)
  s>     HTTP/1.1 200 OK\r\n
  s>     Server: testing stub value\r\n
  s>     Date: $HTTP_DATE$\r\n
  s>     Content-Type: application/mercurial-exp-framing-0005\r\n
  s>     Transfer-Encoding: chunked\r\n
  s>     \r\n
  s>     13\r\n
  s>     \x0b\x00\x00\x01\x00\x02\x011
  s>     \xa1FstatusBok
  s>     \r\n
  received frame(size=11; request=1; stream=2; streamflags=stream-begin; type=command-response; flags=continuation)
  s>     35\r\n
  s>     -\x00\x00\x01\x00\x02\x001
  s>     \xa1A@X(426bada5c67598ca65036d57d9e4b64b0c1ce7a0
  s>     \r\n
  received frame(size=45; request=1; stream=2; streamflags=; type=command-response; flags=continuation)
  s>     8\r\n
  s>     \x00\x00\x00\x01\x00\x02\x002
  s>     \r\n
  s>     0\r\n
  s>     \r\n
  received frame(size=0; request=1; stream=2; streamflags=; type=command-response; flags=eos)
  response: {
    b'@': b'426bada5c67598ca65036d57d9e4b64b0c1ce7a0'
  }
  (sent 2 HTTP requests and * bytes; received * bytes in responses) (glob)

  $ cat error.log
