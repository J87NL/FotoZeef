#!/usr/bin/env bash
# Fails when anything in the bundle needs a newer glibc than the oldest Linux the
# AppImage supports, or carries a piece of glibc itself. PyInstaller copies the build
# machine's own libraries, and those need at least that machine's glibc.
#
# It reads the "Version References" every ELF file declares (objdump -p): that is
# what the loader checks, including tags such as GLIBC_ABI_DT_RELR that no symbol
# shows.
#
#   bash packaging/linux/check_glibc.sh dist/FotoZeef [2.35]
set -euo pipefail

BUNDLE="${1:?bundle folder}"
LIMIT="${2:-2.35}"

command -v objdump >/dev/null || { echo "::error::objdump is missing (binutils)"; exit 1; }
[ -d "$BUNDLE" ] || { echo "::error::$BUNDLE is not a folder"; exit 1; }

scanned=0
newest="0"
offender=""
failures=0
while IFS= read -r -d '' file; do
  [ "$(head -c 4 "$file" | od -An -c | tr -d ' ')" = '177ELF' ] || continue
  scanned=$((scanned + 1))
  name="${file#"$BUNDLE"/}"
  references="$(objdump -p "$file")"
  if grep -qE 'GLIBC_(ABI_|PRIVATE)' <<<"$references"; then
    echo "::error::$name needs $(grep -oE 'GLIBC_(ABI_[A-Z0-9_]+|PRIVATE)' <<<"$references" | sort -u | tr '\n' ' ')- a glibc part or feature newer than $LIMIT"
    failures=$((failures + 1))
  fi
  version="$(grep -oE 'GLIBC_2\.[0-9]+' <<<"$references" | sed 's/GLIBC_//' | sort -uV | tail -1 || true)"
  [ -n "$version" ] || continue
  if [ "$(printf '%s\n%s\n' "$version" "$newest" | sort -V | tail -1)" = "$version" ] && [ "$version" != "$newest" ]; then
    newest="$version"
    offender="$name"
  fi
done < <(find "$BUNDLE" -type f -print0)

[ "$scanned" -gt 0 ] || { echo "::error::no ELF files found in $BUNDLE"; exit 1; }
echo "scanned $scanned ELF files; newest glibc needed: $newest ($offender)"
if [ "$(printf '%s\n%s\n' "$newest" "$LIMIT" | sort -V | tail -1)" != "$LIMIT" ]; then
  echo "::error::$offender needs glibc $newest; the AppImage must run on glibc $LIMIT (Ubuntu 22.04)."
  failures=$((failures + 1))
fi
[ "$failures" -eq 0 ]
