"""cffi build script for caffeinate._curl_cffi._wrapper (links the patched libcurl-impersonate).

Trimmed from curl_cffi 0.16.3 scripts/build.py. Never downloads upstream release tarballs; it only
uses the directory given by the CAFFEINATE_LIBCURL_DIR environment variable (our own patched build):

    <CAFFEINATE_LIBCURL_DIR>/
        include/curl/*.h                   patched curl headers
        Windows: libcurl-impersonate.dll + libcurl-impersonate_imp.lib  (dynamic; delvewheel bundles the DLL)
        Linux  : libcurl-impersonate.a     (single static archive incl. deps, --whole-archive)
        macOS  : libcurl-impersonate.a     (libtool-merged static archive, -force_load)

setup.py registers this file as a cffi module only when CAFFEINATE_LIBCURL_DIR is set.
NOTE: keep this file ASCII-only - cffi reads it with the locale encoding.
"""
import os
import platform
from pathlib import Path

from cffi import FFI

HERE = Path(__file__).resolve().parent
LIBDIR = Path(os.environ["CAFFEINATE_LIBCURL_DIR"]).expanduser().resolve()
SYSTEM = platform.system()

if SYSTEM == "Windows":
    obj = LIBDIR / "libcurl-impersonate.dll"
    libraries = ["Crypt32", "Secur32", "wldap32", "Normaliz", "libcurl-impersonate_imp", "iphlpapi"]
    extra_link_args: list[str] = []
else:
    obj = LIBDIR / "libcurl-impersonate.a"
    libraries = []
    if SYSTEM == "Darwin":
        extra_link_args = [f"-Wl,-force_load,{obj}", "-lc++"]
    else:
        extra_link_args = ["-Wl,--whole-archive", str(obj), "-Wl,--no-whole-archive"]
if not obj.exists():
    raise FileNotFoundError(f"{obj} not found (check CAFFEINATE_LIBCURL_DIR)")

ffibuilder = FFI()
ffibuilder.set_source(
    "caffeinate._curl_cffi._wrapper",
    '#include "shim.h"\n',
    library_dirs=[str(LIBDIR)],
    libraries=libraries,
    source_extension=".c",
    include_dirs=[str(HERE / "ffi"), str(LIBDIR / "include")],
    sources=["native/ffi/shim.c"],  # setuptools rejects absolute paths; cwd is the project root
    extra_compile_args=["-Wno-implicit-function-declaration"] if SYSTEM == "Darwin" else [],
    extra_link_args=extra_link_args,
)
ffibuilder.cdef((HERE / "ffi" / "cdef.c").read_text(encoding="utf-8"))

if __name__ == "__main__":
    ffibuilder.compile(verbose=False)
