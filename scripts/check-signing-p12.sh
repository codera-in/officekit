#!/bin/bash
# Imports a Developer ID .p12 into a throwaway keychain with the same commands the release
# workflow uses, and reports each step. Usage: scripts/check-signing-p12.sh path/to/file.p12
# The password is read from the terminal and never written anywhere; the keychain is deleted at the end.
set -u

p12="${1:-}"
if [ -z "$p12" ] || [ ! -f "$p12" ]; then
  echo "usage: $0 path/to/file.p12" >&2
  exit 2
fi

printf 'p12 password: '
read -rs password
echo

work="$(mktemp -d)"
keychain="$work/check.keychain-db"
keychain_password="$(openssl rand -base64 32)"
cleanup() { security delete-keychain "$keychain" >/dev/null 2>&1; rm -rf "$work"; }
trap cleanup EXIT

step() { echo; echo "== $1"; }

step "create and unlock keychain"
security create-keychain -p "$keychain_password" "$keychain" && security set-keychain-settings -lut 3600 "$keychain" \
  && security unlock-keychain -p "$keychain_password" "$keychain" && echo ok

step "import the p12 (same flags as the workflow)"
security import "$p12" -k "$keychain" -P "$password" -T /usr/bin/codesign 2>&1 | sed 's/^/   /'
echo "   exit: ${PIPESTATUS[0]}"

step "private keys and certificates now in the keychain"
echo "   private keys: $(security dump-keychain "$keychain" 2>/dev/null | grep -c 'class: 0x00000010')"
echo "   certificates: $(security dump-keychain "$keychain" 2>/dev/null | grep -c 'class: 0x80000000')"

step "set-key-partition-list (the step that failed in CI)"
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$keychain_password" "$keychain" >"$work/out.txt" 2>"$work/err.txt"
code=$?
echo "   exit: $code"
echo "   password length: ${#keychain_password}"
head -3 "$work/err.txt" | sed 's/^/   stderr: /'

step "signing identities visible"
security find-identity -v -p codesigning "$keychain" 2>&1 | sed 's/^/   /'
