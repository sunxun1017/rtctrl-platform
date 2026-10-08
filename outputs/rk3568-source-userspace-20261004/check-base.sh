#!/bin/sh
set -eu
export PATH=/bin
expected_release=${1:?Pass the exact expected kernel release}
test "$(uname -r)" = "$expected_release"
test "$(uname -m)" = aarch64
sha256sum -c /etc/rtctrl/source-tests.sha256
echo ROOTFS_SOURCE_TEST_BEGIN
/usr/bin/codec-test
/usr/bin/pty-test
echo ROOTFS_SOURCE_TEST_PASSED
