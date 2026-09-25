"""Set the public API origin and its exact CSP allowlist before Pages deployment."""

import argparse
import json
import re
from urllib.parse import urlsplit

from chipjev.paths import ROOT


def configure(api, public_url=None):
    parsed = urlsplit(api)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or not re.fullmatch(r"[a-zA-Z0-9.:-]+", parsed.netloc)):
        raise ValueError("API must be one HTTPS origin without credentials, paths or queries")
    origin = f"https://{parsed.netloc}"
    site = ROOT / "website"
    (site / "config.json").write_text(json.dumps({"apiBase": origin}, indent=2) + "\n")
    page = (site / "index.html").read_text()
    page = re.sub(r"connect-src [^;]+;", f"connect-src 'self' {origin} wss://{parsed.netloc};", page)
    if public_url:
        public = urlsplit(public_url)
        if (public.scheme != "https" or not public.hostname or public.username or public.password
                or public.query or public.fragment or any(c in public_url for c in '\"<>')):
            raise ValueError("Public URL must be an HTTPS page URL")
        page = re.sub(r'(<link rel="canonical" href=")[^"]+("\s*/?>)',
                      lambda match: match[1] + public_url + match[2], page)
    (site / "index.html").write_text(page)
    print(f"Website API and CSP configured for {origin}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--public-url")
    args = parser.parse_args()
    configure(args.api, args.public_url)
