#!/usr/bin/env python3
"""
Delta FLL -> SEA price watcher for 2026-09-11.

Stateless design: each run looks up the current lowest Delta fare and, if it's
at or below your TARGET_PRICE, opens a GitHub issue (which the GitHub mobile app
pushes to you). It will NOT open a second issue while an alert issue is still
open, so you won't get spammed. Close the issue once you've seen it to re-arm.

No files are written and nothing is committed back to the repo, so there is no
git push step that can fail.

SETUP
  pip install requests
  Set SERPAPI_KEY (your SerpApi key). In GitHub Actions, add it as a repo secret.
  GITHUB_TOKEN and GITHUB_REPOSITORY are provided automatically by Actions.
  Edit TARGET_PRICE below to the number you want to be alerted at.
"""

import os
import sys
import requests

# ----------------------------- CONFIG ------------------------------------
ORIGIN = "FLL"
DESTINATION = "SEA"
DEPART_DATE = "2026-09-11"      # YYYY-MM-DD
AIRLINE = "DL"                  # Delta. Remove from params for any airline.
CURRENCY = "USD"
TRIP_TYPE = 2                   # SerpApi: 1=round trip, 2=one-way

# >>> Alert when the fare is at or below this price. Change it to your target.
TARGET_PRICE = 250

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "PUT_YOUR_KEY_HERE")
# -------------------------------------------------------------------------

# A stable string put in every alert title so we can detect an existing alert.
MARKER = f"{ORIGIN}->{DESTINATION} {DEPART_DATE}"


def fetch_lowest_price():
    """Return (price_float, summary_str) for the cheapest matching flight."""
    params = {
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": DEPART_DATE,
        "type": TRIP_TYPE,
        "currency": CURRENCY,
        "include_airlines": AIRLINE,
        "api_key": SERPAPI_KEY,
    }
    resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
    data = resp.json()

    # SerpApi reports errors inside the JSON (often with HTTP 200), so check
    # this first, otherwise a bad key looks like "no flights".
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"SerpApi error: {data['error']}")
    resp.raise_for_status()

    flights = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    if not flights:
        raise RuntimeError(
            "No flights in response. Likely no Delta options on this date, "
            "or the route/date params need adjusting."
        )
    priced = [f for f in flights if isinstance(f.get("price"), (int, float))]
    if not priced:
        raise RuntimeError("Flights returned but none had a price field.")

    cheapest = min(priced, key=lambda f: f["price"])
    price = cheapest["price"]
    legs = cheapest.get("flights", [])
    dep = legs[0]["departure_airport"]["time"] if legs else "?"
    stops = "nonstop" if len(legs) == 1 else f"{len(legs) - 1} stop(s)"
    summary = f"${price} | departs {dep} | {stops}"
    return float(price), summary


def github(method, path, token, **kw):
    return requests.request(
        method,
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=20,
        **kw,
    )


def alert_already_open(token, repo):
    """True if there's already an open alert issue for this route/date."""
    resp = github("GET", f"/repos/{repo}/issues?state=open&per_page=100",
                  token)
    resp.raise_for_status()
    return any(MARKER in (issue.get("title") or "") for issue in resp.json())


def open_alert(token, repo, price, summary):
    owner = repo.split("/")[0]
    title = f"\u2708\ufe0f {MARKER}: ${price:.0f}"
    body = (f"@{owner}\n\n"
            f"Delta {ORIGIN}->{DESTINATION} on {DEPART_DATE} is **${price:.0f}**, "
            f"at or below your ${TARGET_PRICE} target.\n\n"
            f"Details: {summary}\n\n"
            f"_Close this issue once you've seen it to re-arm the alert._")
    resp = github("POST", f"/repos/{repo}/issues", token,
                  json={"title": title, "body": body})
    resp.raise_for_status()
    print(f"Opened issue: {resp.json().get('html_url')}")


def main():
    try:
        price, summary = fetch_lowest_price()
    except Exception as e:
        print(f"Error fetching price: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Current lowest: {summary}  (target: ${TARGET_PRICE})")

    if price > TARGET_PRICE:
        print("Above target. No alert.")
        return

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")  # e.g. "you/flight-tracker"
    if not token or not repo:
        print("[notify] Missing GITHUB_TOKEN/GITHUB_REPOSITORY; "
              "is this running in GitHub Actions?", file=sys.stderr)
        sys.exit(1)

    if alert_already_open(token, repo):
        print("An alert issue is already open. Not opening another.")
        return

    open_alert(token, repo, price, summary)


if __name__ == "__main__":
    main()
