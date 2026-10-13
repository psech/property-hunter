# property-hunter

A weekly sweep of Sutherland Shire real estate agencies for houses near Kirrawee High School.
It collects listings from agency websites and from agencies' off-market alert emails, works out
walking, driving and train distance to the school, filters by suburb, size and budget, and sends
an email digest plus a WhatsApp ping. It remembers what it has sent, so you only hear about a
property again when something material changes (price, status, address revealed).

Off-market listings always come first in the digest.

```
agency sites ─┐                 ┌─ geocode + walk/drive/train to KHS (OpenRouteService)
Gmail inbox ──┼─► extract ──► enrich ─► filter ─► diff vs memory ─► email + WhatsApp
              │   JSON-LD → selectors → Gemini                         │
              └────────────────────────────────────── state branch ◄───┘
```

Runs on GitHub Actions every Sunday at 06:17 Sydney time. Every service it uses is free.

## How it decides what to send

| Step | Rule |
|---|---|
| Suburb | One of `suburbs` in `config/criteria.yaml`. Off-market listings with no suburb pass. |
| Property | `property.types`, `min_beds`, `min_baths`, `min_land_m2`. Unknown values pass. |
| Distance | Passes if **any** `distance_rules` entry matches: walk minutes, drive minutes, or "within N train stops of Kirrawee and a short walk to that station". |
| Budget | An advertised price must be ≤ `BUDGET_MAX`. Guides, ranges and estimates may go up to `BUDGET_MAX × (1 + tolerance)`. With no price at all, a listing passes when `include_unknown_price` is set. |
| Memory | Sent when it's new to you, or when price, status, address, beds, baths or land changed since it was last sent. |

## Setup

1. **Gmail:** create a dedicated account for agency alerts and register it on each agency's buyer
   or off-market list. The pipeline reads it, and sends your digest from it, through the Gmail API:
   1. In [Google Cloud Console](https://console.cloud.google.com/), signed in as the alerts
      account, create a project and enable the **Gmail API**.
   2. **Google Auth Platform → Branding:** fill in an app name and your email. Under
      **Audience**, choose *External*, then click **Publish app** so the status is
      *In production*. Leaving it in *Testing* makes the token expire after 7 days.
   3. **Clients → Create client → Desktop app.** Copy the client ID and secret.
   4. On your machine, run `uv run hunter-gmail-auth --client-id … --client-secret …`, sign
      in as the alerts account, and click through the "Google hasn't verified this app"
      warning (*Advanced → Go to …*). It prints a refresh token.

   The token lasts as long as the weekly job keeps using it. It's revoked if you change the
   account's password or remove the app's access; run step 4 again if that happens.
2. **Keys:** get a Gemini key from [Google AI Studio](https://aistudio.google.com/apikey) (free
   tier) and an [OpenRouteService](https://openrouteservice.org/dev/#/signup) key (free).
3. **WhatsApp:** follow [CallMeBot's setup](https://www.callmebot.com/blog/free-api-whatsapp-messages/)
   to get an API key for your phone.
4. **Repository secrets** (Settings → Secrets and variables → Actions). Personal values live
   here, never in the repo:

   | Secret | Example |
   |---|---|
   | `BUDGET_MAX` | `1500000` |
   | `GEMINI_API_KEY` | |
   | `ORS_API_KEY` | |
   | `GMAIL_CLIENT_ID` | `…apps.googleusercontent.com` |
   | `GMAIL_CLIENT_SECRET` | |
   | `GMAIL_REFRESH_TOKEN` | from `hunter-gmail-auth` |
   | `NOTIFY_EMAIL` | where the digest goes |
   | `CALLMEBOT_PHONE` | `+614xxxxxxxx` |
   | `CALLMEBOT_APIKEY` | |

5. **First run:** Actions → weekly → Run workflow with mode **seed**. This records everything
   currently listed without notifying you, so the first real digest isn't a flood. Use mode
   **normal** if you want everything sent the first time instead.

## Memory

`listings.json` on the `state` branch holds every property seen: first and last seen dates,
weekly price and status history, and what was last sent. The workflow commits it after each
run, so `git log state` is an audit trail. It holds only facts extracted from public listings,
never your budget or contact details.

## Running locally

```sh
uv sync
uv run playwright install chromium
cp .env.example .env   # fill in, then: set -a; source .env; set +a
uv run hunter --dry-run --source ray-white-sutherland-shire   # one source, print the digest
uv run hunter --dry-run                                       # everything
uv run pytest
```

`--dry-run` sends nothing and saves nothing; the rendered email is written to `debug/digest.html`.
`--where local` runs only the sources marked `run_on: local`. These are sites that block GitHub's
datacenter IPs, and running them from home with the same `--state` file merges their results.

## Adding an agency

Use a coding agent with the Playwright CLI to work out how the site lists properties, then add an
entry to `config/sources.yaml`:

```yaml
- name: example-agency          # used with --source
  agency: Example Agency        # shown in the digest
  fetch: httpx                  # or playwright for JS-rendered sites
  adapter: generic              # or a site-specific adapter in src/hunter/adapters/
  list_urls: [https://example.com.au/buy]
  detail_link_selector: "a.listing-card"   # omit to read the index page with the LLM
  kind_hint: off_market         # only when every listing on these pages is off-market
```

Per listing page, the generic adapter tries JSON-LD first and falls back to Gemini. Unchanged
pages are cached by content hash and never re-sent to the LLM. When a page can't be parsed, its
HTML and a screenshot are uploaded as a workflow artifact.

Respect each site's `robots.txt` and terms. The fetcher checks `robots.txt`, waits between
requests and identifies itself. Don't add realestate.com.au or Domain listing pages.

## Not built yet

- **Price estimates** for listings with no price (`valuation.py`). The plan is comparable sales
  from the NSW Valuer General weekly bulk sales data, adjusted by Gemini. Until then these
  listings show "Price not disclosed".
