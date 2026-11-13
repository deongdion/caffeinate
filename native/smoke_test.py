"""Smoke test for an installed caffeinate platform wheel (used by CI; run outside the source tree).

    python -I native/smoke_test.py [--offline]

1. `caffeinate` imports and uses the bundled `caffeinate._curl_cffi` (not the curl_cffi fallback).
2. The patched libcurl accepts CURLOPT 1900 (HTTP2_INITIAL_STREAM_ID) / 1901 (HTTP2_STREAM_WINDOW_UPDATE).
3. Online (third-party echo server tls.peet.ws only): a POST with a body is sent on h2 stream 3 and a
   stream WINDOW_UPDATE(3, 12451840) precedes DATA - same as Firefox.
"""
import json
import sys
import time

FIRST_STREAM = 3
WINDOW_UPDATE = 12_451_840


def main() -> int:
    import caffeinate
    from caffeinate._curl_cffi import Curl, CurlOpt, __curl_version__
    from caffeinate._curl_cffi import __version__ as bundled_version
    from caffeinate._curl_cffi.requests import Session
    from caffeinate.core import curl as curl_mod
    from caffeinate.core.session import firefox_h2_options

    print("caffeinate", caffeinate.__version__, "from", caffeinate.__file__)
    print("bundled curl_cffi", bundled_version, "/", __curl_version__)
    assert curl_mod.BUNDLED, "caffeinate fell back to the external curl_cffi"
    assert CurlOpt.HTTP2_INITIAL_STREAM_ID == 1900 and CurlOpt.HTTP2_STREAM_WINDOW_UPDATE == 1901
    c = Curl()
    c.setopt(CurlOpt.HTTP2_INITIAL_STREAM_ID, FIRST_STREAM)  # raises CurlError if libcurl is unpatched
    c.setopt(CurlOpt.HTTP2_STREAM_WINDOW_UPDATE, WINDOW_UPDATE)
    c.close()
    assert firefox_h2_options(), "firefox_h2_options() is empty"
    print("OK: patched libcurl accepts options 1900/1901")
    if "--offline" in sys.argv:
        return 0

    opts = {CurlOpt.HTTP2_INITIAL_STREAM_ID: FIRST_STREAM, CurlOpt.HTTP2_STREAM_WINDOW_UPDATE: WINDOW_UPDATE}
    last_err: Exception | None = None
    # third-party server: retry transient failures with backoff
    # (v0.3.0 CI: one Linux job failed 3 immediate retries within 2 s on "Could not connect")
    for attempt, wait in enumerate((0, 5, 15, 30, 60)):
        if wait:
            print(f"retry {attempt} in {wait}s after: {last_err!r}")
            time.sleep(wait)
        try:
            with Session(impersonate="firefox147", curl_options=opts, timeout=30) as s:
                r = s.post("https://tls.peet.ws/api/all", data=b"caffeinate-smoke-test")
            data = r.json()
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
    else:
        raise RuntimeError(f"tls.peet.ws request failed: {last_err!r}")

    frames = data["http2"]["sent_frames"]
    print(json.dumps(frames, indent=1)[:3000])
    kinds = [(f.get("frame_type"), f.get("stream_id")) for f in frames]
    headers_idx = kinds.index(("HEADERS", FIRST_STREAM))
    wu_idx = next(
        i for i, f in enumerate(frames)
        if f.get("frame_type") == "WINDOW_UPDATE" and f.get("stream_id") == FIRST_STREAM
    )
    assert frames[wu_idx].get("increment") == WINDOW_UPDATE, frames[wu_idx]
    data_idx = [i for i, k in enumerate(kinds) if k == ("DATA", FIRST_STREAM)]
    assert data_idx, kinds
    assert headers_idx < wu_idx < data_idx[0], kinds
    print(f"OK: HEADERS on stream {FIRST_STREAM}, WINDOW_UPDATE({FIRST_STREAM}, {WINDOW_UPDATE}) before DATA: {kinds}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
