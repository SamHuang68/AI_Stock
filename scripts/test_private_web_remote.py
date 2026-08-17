"""End-to-end smoke test for the private Web ST HTTPS endpoint."""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import ssl
import sys
import urllib.error
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]


def open_url(
    url: str,
    *,
    context: ssl.SSLContext,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
):
    request = urllib.request.Request(
        url,
        headers=headers or {},
        data=data,
        method=method,
    )
    return urllib.request.urlopen(request, timeout=15, context=context)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://evo-t1-st.tailbc3519.ts.net",
        help="Private Web ST base URL",
    )
    args = parser.parse_args()
    base_url = args.url.rstrip("/")
    context = ssl.create_default_context()

    owner_token = (ROOT / "data" / "private_web_owner.token").read_text(
        encoding="utf-8"
    ).strip()
    read_token = (ROOT / "data" / "private_web_read.token").read_text(
        encoding="utf-8"
    ).strip()
    result: dict[str, object] = {}

    with open_url(base_url + "/gateway/health", context=context) as response:
        health = json.load(response)
        result.update(
            tls_verified=True,
            gateway_status=response.status,
            gateway_ok=health.get("ok"),
            mode=health.get("mode"),
            upstream=health.get("upstream"),
        )

    try:
        open_url(base_url + "/", context=context)
    except urllib.error.HTTPError as error:
        result["unauthenticated_root"] = error.code
        result["basic_challenge"] = error.headers.get(
            "WWW-Authenticate", ""
        ).startswith("Basic")

    with open_url(
        base_url + "/",
        context=context,
        headers={"Accept": "text/html"},
    ) as response:
        login_page = response.read().decode(errors="replace")
        result.update(
            browser_login_page=response.status,
            browser_login_redirect="/gateway/login?next=/" in response.geturl(),
            persistent_login_notice="登入狀態會持續保留" in login_page,
            remember_option='name="remember"' in login_page,
            login_help='/gateway/help' in login_page,
        )

    basic_value = base64.b64encode(f"owner:{owner_token}".encode()).decode()
    with open_url(
        base_url + "/",
        context=context,
        headers={"Authorization": "Basic " + basic_value},
    ) as response:
        page = response.read().decode(errors="replace")
        compact_page = "".join(page.split())
        result.update(
            owner_page=response.status,
            private_profile='id="st-private-web-profile"' in page,
            wavedeck_disabled="wavedeck:false" in compact_page,
        )

    with open_url(
        base_url + "/health/live",
        context=context,
        headers={"Authorization": "Bearer " + read_token},
    ) as response:
        result["reader_liveness"] = json.load(response).get("ok")

    try:
        open_url(
            base_url + "/notify",
            context=context,
            headers={
                "Authorization": "Bearer " + owner_token,
                "Content-Type": "application/json",
            },
            data=b"{}",
            method="POST",
        )
    except urllib.error.HTTPError as error:
        result["blocked_notify"] = error.code

    expected = {
        "tls_verified": True,
        "gateway_status": 200,
        "gateway_ok": True,
        "mode": "isolated-host",
        "upstream": True,
        "unauthenticated_root": 401,
        # Browsers use the signed form-login flow; omitting the Basic challenge
        # prevents Chrome from replacing it with the native credential dialog.
        "basic_challenge": False,
        "browser_login_page": 200,
        "browser_login_redirect": True,
        "persistent_login_notice": True,
        "remember_option": False,
        "login_help": True,
        "owner_page": 200,
        "private_profile": True,
        "wavedeck_disabled": True,
        "reader_liveness": True,
        "blocked_notify": 403,
    }
    failures = {
        key: {"expected": value, "actual": result.get(key)}
        for key, value in expected.items()
        if result.get(key) != value
    }
    result["ok"] = not failures
    if failures:
        result["failures"] = failures
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
