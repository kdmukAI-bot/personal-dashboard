from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid


def _generate_vapid(args: argparse.Namespace) -> int:
    env_path = Path.cwd() / ".env"
    if env_path.exists() and not args.force:
        existing = env_path.read_text()
        if "VAPID_PRIVATE_KEY" in existing or "VAPID_PUBLIC_KEY" in existing:
            print(
                f"Refusing to overwrite VAPID keys in {env_path}. Use --force to overwrite.",
                file=sys.stderr,
            )
            return 1

    vapid = Vapid()
    vapid.generate_keys()

    raw_priv = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    raw_pub = vapid.public_key.public_bytes(
        encoding=Encoding.X962,
        format=PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
    private_b64 = base64.urlsafe_b64encode(raw_priv).rstrip(b"=").decode()

    if args.write_env:
        lines = []
        if env_path.exists():
            lines = [
                ln
                for ln in env_path.read_text().splitlines()
                if not ln.startswith("VAPID_PRIVATE_KEY=")
                and not ln.startswith("VAPID_PUBLIC_KEY=")
            ]
        lines.append(f"VAPID_PRIVATE_KEY={private_b64}")
        lines.append(f"VAPID_PUBLIC_KEY={public_b64}")
        env_path.write_text("\n".join(lines) + "\n")
        print(f"Wrote VAPID keys to {env_path}")
    else:
        print("VAPID_PRIVATE_KEY (b64url):")
        print(private_b64)
        print()
        print("Add the above to your .env (or pass --write-env).")

    print()
    print(f"VAPID_PUBLIC_KEY={public_b64}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="personal-dashboard")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gv = sub.add_parser("generate-vapid", help="Generate a VAPID keypair for Web Push")
    gv.add_argument("--force", action="store_true", help="Overwrite existing keys in .env")
    gv.add_argument(
        "--write-env",
        action="store_true",
        help="Write VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY into ./.env",
    )
    gv.set_defaults(func=_generate_vapid)

    args = parser.parse_args()
    return args.func(args)


def _read_token_from_config() -> str | None:
    cfg_path = Path.home() / ".config" / "personal-dashboard" / "config.toml"
    if not cfg_path.is_file():
        return None
    try:
        import sys as _sys

        if _sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib  # type: ignore
        with cfg_path.open("rb") as f:
            data = tomllib.load(f)
        return data.get("core", {}).get("notify_api_key") or None
    except Exception:
        return None


def notify_cli() -> int:
    parser = argparse.ArgumentParser(prog="pd-notify")
    parser.add_argument("title")
    parser.add_argument("body", nargs="?", default=None)
    parser.add_argument("--image-url", default=None)
    parser.add_argument("--click-url", default=None)
    parser.add_argument("--source", default=None)
    parser.add_argument("--server", default=None)
    args = parser.parse_args()

    token = os.environ.get("NOTIFY_API_KEY") or _read_token_from_config()
    if not token:
        print(
            "No bearer token. Set NOTIFY_API_KEY or [core] notify_api_key in "
            "~/.config/personal-dashboard/config.toml",
            file=sys.stderr,
        )
        return 1

    server = args.server or "http://localhost:8421"
    url = server.rstrip("/") + "/api/notify"

    payload = {"title": args.title}
    if args.body:
        payload["body"] = args.body
    if args.image_url:
        payload["image_url"] = args.image_url
    if args.click_url:
        payload["click_url"] = args.click_url
    if args.source:
        payload["source"] = args.source

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        print(f"network error: {exc}", file=sys.stderr)
        return 2

    if resp.status_code == 401:
        print("auth failed (401)", file=sys.stderr)
        return 1
    if resp.status_code >= 400:
        print(f"server error {resp.status_code}: {resp.text}", file=sys.stderr)
        return 2

    print(resp.text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
