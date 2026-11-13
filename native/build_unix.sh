#!/usr/bin/env bash
# Build the patched libcurl-impersonate as one static archive for caffeinate's cffi extension (Linux / macOS).
#
#   native/build_unix.sh <out-dir>
#
# Output (consumed by native/build_ffi.py via CAFFEINATE_LIBCURL_DIR=<out-dir>):
#   <out-dir>/libcurl-impersonate.a   curl + BoringSSL + nghttp2/ngtcp2/nghttp3 + brotli/zstd/zlib (+ libc++ on Linux)
#   <out-dir>/include/curl/*.h         patched headers
#   <out-dir>/LICENSE*                 license texts
#
# Mirrors lexiforest/curl-impersonate v2.2.2 .github/workflows/build.yml (linux x86_64-linux-gnu / aarch64-linux-gnu
# with zig targeting glibc 2.17, macos arm64/x86_64 native) with two differences:
#   - native/patches/curl-caffeinate.patch is appended to patches/curl.patch (GNU patch applies the file sections in
#     order, so it lands on top of curl.patch inside the CMake superbuild's ExternalProject patch step)
#   - USE_LIBIDN2=OFF (no LGPL code statically linked; IDN hostnames are not needed)
#
# Linux needs: zig 0.14.0 on PATH, cmake, ninja, make, autoconf/automake/libtool, pkg-config, go, patch.
# macOS needs: brew install pkg-config make cmake ninja autoconf automake libtool gpatch gperf go (use `gmake`).
set -euo pipefail

TAG="${CURL_IMPERSONATE_TAG:-v2.2.2}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$1"
OUT="$(cd "$1" && pwd)"
WORK="${WORK_DIR:-$ROOT/native/out/work}"
SRC="$WORK/curl-impersonate"
INSTALL="$WORK/install"
MAKE="${MAKE:-make}"
OS="$(uname -s)"
ARCH="$(uname -m)"
JOBS="${JOBS:-$( (nproc || sysctl -n hw.ncpu) 2>/dev/null)}"

rm -rf "$SRC" "$INSTALL"
mkdir -p "$WORK" "$INSTALL"
git -c advice.detachedHead=false clone --depth 1 --branch "$TAG" https://github.com/lexiforest/curl-impersonate.git "$SRC"
printf '\n' >> "$SRC/patches/curl.patch"
cat "$ROOT/native/patches/curl-caffeinate.patch" >> "$SRC/patches/curl.patch"

cmake_args="-G Ninja -DCMAKE_INSTALL_PREFIX=$INSTALL -DUSE_LIBIDN2=OFF"
if [[ "$OS" == "Linux" ]]; then
  case "$ARCH" in
    x86_64) zig_target="x86_64-linux-gnu.2.17" ;;
    aarch64) zig_target="aarch64-linux-gnu.2.17" ;;
    *) echo "unsupported arch $ARCH" >&2; exit 1 ;;
  esac
  export CC="$SRC/zigshim/cc" CXX="$SRC/zigshim/cxx" AR="$SRC/zigshim/ar"
  export ZIG_FLAGS="-target $zig_target"
  cmake_args="$cmake_args -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=$ARCH"
  cmake_args="$cmake_args -DCURL_IMPERSONATE_CXX_RUNTIME_LIBRARY=c++"
  cmake_args="$cmake_args -DCURL_CA_PATH=/etc/ssl/certs -DCURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt"
else
  export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"
fi

cd "$SRC"
$MAKE configure BUILD_DIR=build CMAKE_CONFIGURE_ARGS="$cmake_args"
$MAKE build BUILD_DIR=build JOBS="$JOBS" CMAKE_CONFIGURE_ARGS="$cmake_args"
$MAKE install-strip BUILD_DIR=build JOBS="$JOBS" CMAKE_CONFIGURE_ARGS="$cmake_args"

# sanity check, like upstream `make checkbuild`
v="$("$INSTALL/bin/curl-impersonate" -V)"
echo "$v"
grep -q nghttp2 <<<"$v" && grep -q BoringSSL <<<"$v"

# merge everything into a single static archive (upstream "Create tar release files" step)
deps="$SRC/build/deps/install/lib"
lib_list="libcurl-impersonate.orig.a"
cd "$INSTALL/lib"
mv libcurl-impersonate.a libcurl-impersonate.orig.a
for l in libz.a libzstd.a libbrotlidec.a libbrotlicommon.a libbrotlienc.a libnghttp2.a libnghttp3.a libngtcp2.a \
         libngtcp2_crypto_boringssl.a libssl.a libcrypto.a; do
  cp "$deps/$l" .
  lib_list="$lib_list $l"
done
rm -f "$OUT/libcurl-impersonate.a"
if [[ "$OS" == "Darwin" ]]; then
  libtool -static -o "$OUT/libcurl-impersonate.a" $lib_list
else
  # zig omits its C++ runtime for relocatable links: locate the target-specific archives and merge them in
  cxx_link="$($CXX -### -shared -o probe.so libcurl-impersonate.orig.a 2>&1)"
  libcxx="$(printf '%s\n' "$cxx_link" | grep -oE '/[^[:space:]]+/libc\+\+\.a' | head -n 1)"
  libcxxabi="$(printf '%s\n' "$cxx_link" | grep -oE '/[^[:space:]]+/libc\+\+abi\.a' | head -n 1)"
  libunwind="$(printf '%s\n' "$cxx_link" | grep -oE '/[^[:space:]]+/libunwind\.a' | head -n 1)"
  if [[ ! -f "$libcxx" || ! -f "$libcxxabi" || ! -f "$libunwind" ]]; then
    echo "cannot locate zig C++ runtime archives" >&2; echo "$cxx_link" >&2; exit 1
  fi
  $CC -r -o full.o -Wl,--whole-archive $lib_list -Wl,--no-whole-archive \
    -Wl,--start-group "$libcxx" "$libcxxabi" "$libunwind" -Wl,--end-group
  $AR rcs "$OUT/libcurl-impersonate.a" full.o
  rm -f full.o
  unresolved="$(nm -u "$OUT/libcurl-impersonate.a" | grep -E '[[:space:]]U (_Z|__cxa|__gxx|_Unwind)' || true)"
  if [[ -n "$unresolved" ]]; then echo "unresolved C++ runtime symbols:" >&2; echo "$unresolved" >&2; exit 1; fi
fi

rm -rf "$OUT/include"
mkdir -p "$OUT/include"
cp -R "$INSTALL/include/curl" "$OUT/include/"
cp "$INSTALL"/LICENSE* "$OUT/" 2>/dev/null || true
grep -q CURLOPT_HTTP2_INITIAL_STREAM_ID "$OUT/include/curl/curl.h"
ls -la "$OUT"
