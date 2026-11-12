#!/usr/bin/env bash
# Fails when anything in the bundle needs a newer glibc than the oldest Linux the
# AppImage supports. PyInstaller copies the build machine's own libraries (glib,
# libstdc++, ...), and those need at least that machine's glibc.
#
#   bash packaging/linux/check_glibc.sh dist/FotoZeef [2.35]
set -euo pipefail

BUNDLE="${1:?bundle folder}"
LIMIT="${2:-2.35}"

newest="GLIBC_0"
offender=""
while IFS= read -r -d '' file; do
  version="$(objdump -T "$file" 2>/dev/null | grep -o 'GLIBC_2\.[0-9]*' | sort -uV | tail -1 || true)"
  [ -n "$version" ] || continue
  if [ "$(printf '%s\n%s\n' "$version" "$newest" | sort -V | tail -1)" = "$version" ] && [ "$version" != "$newest" ]; then
    newest="$version"
    offender="$file"
  fi
done < <(find "$BUNDLE" -type f \( -name '*.so*' -o -perm -u+x \) -print0)

echo "newest glibc symbol needed: $newest (${offender#"$BUNDLE"/})"
if [ "$(printf '%s\n%s\n' "${newest#GLIBC_}" "$LIMIT" | sort -V | tail -1)" != "$LIMIT" ]; then
  echo "::error::${offender#"$BUNDLE"/} needs $newest; the AppImage must run on glibc $LIMIT (Ubuntu 22.04)."
  exit 1
fi
