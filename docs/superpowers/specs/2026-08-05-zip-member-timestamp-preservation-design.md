# ZIP member timestamp preservation design

## Goal

Preserve the ZIP modification timestamp of every unchanged member when converting
a ZIP or CBZ archive to a CBZ archive.

## Design

`extract_zip_archive()` will restore a member's ZIP `date_time` as the extracted
file's filesystem modification time after copying its contents. It will defer
directory modification times until every member has been extracted, because
creating child paths can alter a directory's timestamp.

The existing writer will continue to write entries in stable POSIX-relative
lexical order with deflate compression. Its use of filesystem metadata will then
carry the restored timestamps into the resulting archive. Converted JPEG pages
remain newly created JXL files and do not inherit JPEG timestamps.

The change applies only to ZIP and CBZ inputs. RAR and 7Z metadata handling is
unchanged.

## Errors and compatibility

Failure to apply a timestamp is treated as an archive filesystem error through
the existing `ZipArchiveError` path. ZIP timestamps have ZIP's normal local-time
and two-second-resolution limitations.

## Tests

Add an end-to-end conversion test with a deliberately fixed timestamp on an
unchanged non-JPEG ZIP member. Assert that the output member has the same
`ZipInfo.date_time`. Keep existing ordering and conversion behavior covered by
the current suite.
