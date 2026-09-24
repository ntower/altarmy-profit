"""Check whether Blizzard's Game Data API serves auction house data for TBC Anniversary realms.

Needs a Battle.net API client (https://develop.battle.net/access/clients, "Create client"; any redirect URL):
    set BLIZZARD_CLIENT_ID=...   and   set BLIZZARD_CLIENT_SECRET=...
Usage: python scripts/probe_blizzard_api.py [--region us] [--realm Dreamscythe --realm Nightslayer]

For each candidate namespace it lists connected realms, finds the named realms, and asks for their auction
house index and first auction house. It prints HTTP statuses only; nothing is stored. Record the outcome in
docs/HOSTED_PLAN.md ("Phase 0 findings").
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

NAMESPACES = ("dynamic-classicann", "dynamic-classic1x", "dynamic-classic")  # + "-<region>"


def token(region: str, client_id: str, secret: str) -> str:
    auth = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    req = urllib.request.Request(
        f"https://{region}.battle.net/oauth/token",
        data=b"grant_type=client_credentials",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return str(json.load(resp)["access_token"])


def get(url: str, tok: str) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--region", default="us")
    p.add_argument("--realm", action="append", help="realm name to look for (repeatable)")
    args = p.parse_args()
    realms = {r.lower() for r in (args.realm or ["Dreamscythe", "Nightslayer"])}
    client_id, secret = os.environ.get("BLIZZARD_CLIENT_ID"), os.environ.get("BLIZZARD_CLIENT_SECRET")
    if not client_id or not secret:
        sys.exit("Set BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET (see this script's docstring).")
    tok = token(args.region, client_id, secret)
    api = f"https://{args.region}.api.blizzard.com"
    for base in NAMESPACES:
        ns = f"{base}-{args.region}"
        q = "?" + urllib.parse.urlencode({"namespace": ns, "locale": "en_US"})
        status, index = get(f"{api}/data/wow/connected-realm/index{q}", tok)
        print(f"{ns}: connected-realm index -> {status}")
        if status != 200:
            continue
        for link in index.get("connected_realms", []):
            status, cr = get(link["href"], tok)
            names = {
                r["name"].lower() for r in (cr or {}).get("realms", []) if isinstance(r.get("name"), str)
            }
            if status != 200 or not names & realms:
                continue
            cid = cr["id"]
            status, houses = get(f"{api}/data/wow/connected-realm/{cid}/auctions/index{q}", tok)
            print(
                f"  {', '.join(sorted(names & realms))} (connected realm {cid}): auctions index -> {status}"
            )
            for house in (houses or {}).get("auctions", [])[:1]:
                hid = house.get("id")
                status, body = get(f"{api}/data/wow/connected-realm/{cid}/auctions/{hid}{q}", tok)
                count = len((body or {}).get("auctions", []))
                print(f"    auction house {hid} ({house.get('name')}): {status}, {count} auctions")


if __name__ == "__main__":
    main()
