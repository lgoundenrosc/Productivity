# DC events tracker

Every Monday at about 7am ET this emails a digest of upcoming DC events worth
attending: think tank panels, defense and space industry events, congressional
hearings, and federal industry days. Claude reads each events page, pulls out
the events, scores each one against `config/profile.yaml`, and groups them by
topic. Every event is labeled IN PERSON, HYBRID, ONLINE ONLY or FORMAT NOT
LISTED. In-person events get a one-point score bonus and are listed first in
each section; online-only events lose a point. Each event has an "Add to calendar" link that opens it prefilled in
Google Calendar; clicking Save adds it.

It runs on GitHub Actions on a schedule (`.github/workflows/weekly-digest.yml`).
Nothing needs approval at run time.

## How a run works

Nine workers run in parallel, each with its own Claude calls so no single
call has to hold every page:

| Worker | Sources | Method |
|---|---|---|
| `think_tanks_defense` | CSIS, CNAS, Hudson, Atlantic Council, AEI, Mitchell, Reagan Institute | page text, Claude extracts |
| `think_tanks_tech_policy` | CSET, SCSP, RAND (DC only), Brookings, Carnegie | page text, Claude extracts |
| `other_orgs` | SpaceNews and DARPA (headless browser), AFCEA, Potomac Officers Club | page text, Claude extracts |
| `networking` | Defense Tech DC, STATION DC and Luma DC calendars, Silicon Nation newsletter, Meetup and Eventbrite searches | happy hours, meetups and VC/investor events |
| `universities` | GWU calendar API, plus a search agent for Georgetown, SAIS, the Bush School in DC, GW, GMU, UMD and UVA startup events | API and Claude web search |
| `military` | Search agent for DIU, CDAO, OSC, AFWERX, SpaceWERX, Army, Navy, Space Force, DTRA and other DoD events | Claude web search |
| `general_search` | Search agent for anything the named sources miss | Claude web search |
| `hill` | Congress.gov committee meetings, filtered to the committees in `config/sources.yaml` | API |
| `industry` | SAM.gov special notices titled "industry day" or "proposers day" | API |

Search agents use Claude's web search and page-fetch tools, then the same
extraction step as the page scrapers. Networking events aimed at affinity
groups, student-only and members-only events are filtered out or scored down.
Each worker then scores its own events. Events seen in an earlier digest are
recorded in `data/seen.json`, which the workflow commits back, so new ones get
a NEW tag. Any source that fails is listed at the bottom of the email.

AUSA, Heritage, FDD, CSBA, Axios and NDIA block automated access with
Cloudflare or Incapsula challenges, so they aren't scraped.

## Setup: secrets

Add these under the repo's Settings > Secrets and variables > Actions >
New repository secret.

| Secret | What it is | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Pays for the Claude calls that read pages and score events | console.anthropic.com > API keys (needs a payment method) |
| `CONGRESS_API_KEY` | Free key for the Library of Congress hearing schedule | api.congress.gov/sign-up |
| `SAM_API_KEY` | Free key for federal contracting notices | sam.gov > sign in > Account Details > API Key. Keys for non-government users expire every 90 days |
| `GMAIL_ADDRESS` | The Gmail account the digest is sent from | your address |
| `GMAIL_APP_PASSWORD` | A 16-character password that lets this script send mail as you | myaccount.google.com/apppasswords (needs 2-Step Verification) |
| `DIGEST_TO` | Where the digest goes | defaults to `GMAIL_ADDRESS` |

## Running by hand

```
pip install -r requirements.txt
python -m playwright install chromium
python -m tracker.main --fetch-only          # check every source loads; no Claude calls
python -m tracker.main --dry-run             # write out/digest.html; sends nothing
python -m tracker.main --only hill,industry  # run some workers only
python -m pytest tests                       # offline tests
```

To trigger a real send from GitHub: Actions > Weekly DC events digest > Run workflow.

## Tuning

- `config/profile.yaml`: interests, what to score up or down, the categories,
  the in-person bonus (`format_bonus`), the score cutoff and how far ahead to look.
- `config/sources.yaml`: sources, worker groups, the committee filter and the
  SAM.gov phrases.
- `TRACKER_MODEL` env var: the Claude model (default `claude-sonnet-5-5`).
