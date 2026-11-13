"""네이티브 확장(caffeinate._curl_cffi._wrapper) 빌드 배선

CAFFEINATE_LIBCURL_DIR 이 있으면 패치한 libcurl-impersonate 로 cffi 확장을 빌드해 플랫폼 휠
(cp311-abi3-<plat>) 을 만든다. 없으면 순수 파이썬 휠/설치가 되고, 런타임에 설치된 curl_cffi 로
폴백한다 (README "설치" 참고). 나머지 메타데이터는 pyproject.toml.
"""
import os

from setuptools import setup

kwargs: dict = {}
if os.environ.get("CAFFEINATE_LIBCURL_DIR"):
    from setuptools.command.bdist_wheel import bdist_wheel

    class bdist_wheel_abi3(bdist_wheel):
        def get_tag(self):
            python, abi, plat = super().get_tag()
            # cffi 확장은 limited API 로 빌드된다 -> CPython 3.11+ 공용 abi3 휠
            if python.startswith("cp") and not abi.endswith("t"):
                return "cp311", "abi3", plat
            return python, abi, plat

    kwargs = {
        "cffi_modules": ["native/build_ffi.py:ffibuilder"],
        "cmdclass": {"bdist_wheel": bdist_wheel_abi3},
    }

setup(**kwargs)
