# Hosted transition plan

How `altarmy-profit` becomes a hosted, multi-user web app covering both **TBC Anniversary** and
**WoW: Forever**, while the single-user local mode described in [README.md](../README.md) keeps working.
Feature ideas that do not depend on hosting live in [ROADMAP_IDEAS.md](ROADMAP_IDEAS.md). Written
2026-09-24; each phase below is meant to be picked up on its own.

## 1. Goals and decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Stack | Firebase Auth, FastAPI on Cloud Run, Postgres (Cloud SQL), Firebase Hosting | Keeps the Python engine and most of `api.py` / `service.py`; Firebase is familiar; Postgres suits price history and joins |
| Modes | One codebase, `ALTARMY_MODE=local` (SQLite, file watcher, no login) or `hosted` | Fast tests, offline and privacy fallback, and the local sync loop becomes the uploader |
| Game versions | `tbc` and `forever`, selectable in the UI | The two clients the [Alt Army](../../altarmy_tbc) addon supports |
| Price sources | Addon snapshots uploaded by users are primary; third-party feeds are added as they exist | Blizzard's Classic AH endpoints have been 404 since late 2024, NexusHub is gone, Undermine Exchange is retail-only |
| Access | Firebase **anonymous** auth on first visit; prices for items with a required level of 30 or below are free; linking the account unlocks everything | Low-friction first experience that still identifies the visitor and converts them later |
| Uploaders | Browser file upload and CLI watcher first; packaged tray app and Alt Army paste export later | Cheapest paths first; the watcher is the existing sync code with a remote sink |

## 2. Architecture

```
Browser (React + Firebase JS SDK)
   |  static files                      |  /api/**  (Firebase Hosting rewrite)
   v                                    v
Firebase Hosting                    Cloud Run: FastAPI (engine, parsers, tiers)
                                        |
                                        v
                                    Cloud SQL Postgres

Inputs                                  Scheduled jobs (Cloud Scheduler -> Cloud Run endpoints)
- browser upload of SavedVariables      - daily game-data update per version (wago.tools builds/latest)
- CLI watcher / tray app (API key)      - hourly snapshot merge and daily aggregation
- Alt Army paste export (later)         - hourly Blizzard API poll where a namespace works
- AHDB snapshots, Blizzard API (later)  - daily retention of raw observations
```

Local mode is the same FastAPI process with SQLite, the auth dependency returning a fixed local user, and
the existing file watcher (`service.sync`) turned on.

## 3. Game versions

Done in Phase 1 (`src/altarmy_profit/versions.py`); Phase 2 made `game_version` a column in the one
schema local and hosted mode share.

- `game_version` (`tbc` | `forever`) is a parameter on every per-game API route and a column on every
  game-data table and on local state (settings, characters, `ah_blocked`); price tables carry it through
  their auction house. Local mode keeps both versions in `data/altarmy-profit.sqlite`; `legacy.py`
  imports Phase 1's per-version files (`data/altarmy-profit-<version>.db`) into it once.
- Ingest takes the wago.tools product: `tbc` -> `wow_anniversary` (2.5.6, Interface 20506),
  `forever` -> `wow_classic_beta` (1.60.x, Interface 16001). The pinned build is per version; the DB2
  table list is the same for both.
- Per-version hand data: `data/<version>/disenchant.csv` and `data/<version>/vendor_items.csv`. TBC vendor
  items come from cmangos' `tbc-db` SQLite release (`cmangos.py`); `vmangos.py` stays the vanilla reader.
  TBC disenchant rates are generated from Auctionator's brackets (`scripts/build_disenchant.py`).
- The AH cut and postage per attachment are per-version settings passed into `Market`; `PROFESSIONS`
  includes Jewelcrafting.
- Alt Army writes the same `AltArmy_TBC.lua` on both clients and does not record the client per character.
  Uploaders infer the version from the WoW flavor folder (`_anniversary_` -> tbc, `_classic_beta_` ->
  forever); the browser upload asks. Addon follow-up: record the interface/build per character so uploads
  self-identify.
- Front end: a version switch at the top level; realm lists, characters and prices are all per version.

## 4. Data model

Postgres in hosted mode, SQLite in local mode and tests, through SQLAlchemy Core (no ORM) with Alembic
migrations. `db.py` becomes the engine factory; `store.py` and `prices.py` use Core statements.

Game data, keyed `(game_version, id)`:

- `game_versions(id, wago_product, build, interface)`
- `items`, `recipes`, `recipe_reagents`, `disenchant`, `vendor_items` as today plus `game_version`

Realms and prices:

- `auction_houses(id, game_version, realm, faction, region)` replaces "one realm at a time". The key is
  `(game_version, realm, faction)`: Blizzard has kept realm names unique across regions and the plan
  assumes that continues. `region` is informational, filled when known (the client's `WTF/Config.wtf`
  `SET portal` value via the watcher, later the addon); the Forever beta has a single region, `test`
- `realm_aliases(auction_house_id, kind, value)`: Auctionator key, addon realm name, Blizzard connected-realm id
- `price_snapshots(id, auction_house_id, source, uploader_uid, scanned_at, received_at, item_count, status)`;
  `source` is `auctionator | ahdb | blizzard_api | csv`, `status` is `accepted | quarantined`
- `price_observations(snapshot_id, item_id, min_buyout, quantity, listings)`, partitioned by month, kept ~90 days
- `price_current(auction_house_id, item_id, price, seen_at, snapshot_id, median_7d, avail_7d, scans_7d)`:
  what `store.load_market` reads; rebuilt by the merge job
- `price_daily(auction_house_id, item_id, day, low, median, high, available)` for charts and stale checks

Users:

- `users(uid, created_at, linked_at, tier, trust_score)`; `api_keys(id, user_uid, key_hash, prefix, label, created_at, last_used_at)`
- `characters(user_uid, game_version, realm, faction, name, class_file, level, updated_at)`,
  `character_professions`, `character_recipes`: today's tables plus owner and version
- `user_settings(user_uid, game_version, selected_realm, selected_faction, data_version)`;
  `ah_blocked(user_uid, game_version, item_id)`
- `uploads(id, user_uid, game_version, kind, via, size, received_at, outcome, detail)`
- `rank_cache(key, uid, auction_house_id, price_version, params_hash, results jsonb, computed_at)`

Money stays integer copper everywhere.

Phase 2 status (done): `schema.py` holds the game data, local state and price tables above as SQLAlchemy
Core tables, Alembic revision `0001` creates them, and the same pytest suite passes on SQLite and
Postgres. Differences from the list above:

- `price_snapshots.source` also allows `manual` (CLI `set-price`); `recipe_reagents` has a `slot` column
  (DB2 reagent order, which the flow chart's choice paths depend on); `disenchant` has a surrogate id.
- A snapshot writes observations only for news (no current price, a later day, or a different price
  seen no earlier), so an unchanged re-sync adds nothing; `item_count` records the scan's size.
- `price_daily` is filled from Auctionator's per-day fields (`h`/`l`/`a`), not aggregated; `median` and
  `price_current`'s 7-day columns stay NULL until the Phase 6 merge job.
- Monthly partitioning of `price_observations` is Postgres-only and moves to Phase 5.
- A realm name of `""` is the unnamed auction house that CLI prices use before any characters exist.

Phase 3 status (done): Alembic revision `0002` adds `users`, typed `user_settings`, `local_sync` and the
owner column, and moves everything stored so far to the local user (`uid` `local`, linked tier).
Differences from the list above:

- Every owner column is `user_uid` (a foreign key to `users`, cascading).
- `user_settings` holds the selection as `selected_realm`/`selected_faction`, not an auction house id. A
  selection is a group of characters, and on Forever both factions share one auction house.
- The local file sync's state (addon paths, mtimes, last sync, the Auctionator key) is in its own
  `local_sync(user_uid, game_version, ...)` table, which hosted mode never writes.
- `price_snapshots.uploader_uid` stays a plain string. On SQLite, a foreign key would mean rebuilding
  the table, and dropping the old copy cascades into `price_observations`.
- On SQLite, 0002 rebuilds `characters` and puts the professions and recipes back, because the drop of
  the old table cascades into them. A test seeds 0001-shaped data and checks it survives on both
  databases.

## 5. Auth and access tiers

- The front end signs in anonymously on first visit. Linking an email and password uses
  `linkWithCredential`, which keeps the uid, so uploads, settings and trust carry over. Email/password is
  the only account type (decided in Phase 4: no Google), so the site also has sign-in for an existing
  account, password reset and sign-out (back to a new anonymous session). Signing in on a browser that
  already has a guest session leaves that guest's data behind; merging accounts is not planned yet.
- Firebase project: `alt-army-prod`, with the Anonymous and Email/Password providers. Its public web config
  is in `hosted.env`. Its browser API key is restricted (done after Phase 4, with `gcloud services api-keys
  update`; see README) to the Identity Toolkit and Token Service APIs, called from localhost:5173/8600,
  127.0.0.1:5173/8600, `alt-army-prod.firebaseapp.com` and `alt-army-prod.web.app`. Phase 5 adds any custom
  hosting domain to both that list and the Auth authorized domains.
- A FastAPI dependency verifies the Firebase ID token with `firebase-admin` and yields `User(uid, tier)`.
  `tier` is `linked` when the token's `firebase.sign_in_provider` is not `anonymous`, else `free`.
- Free tier: price routes and item pages are filtered to `items.required_level <= FREE_TIER_MAX_LEVEL`
  (30); no rankings, no characters. Reagents such as cloth and ore have a required level of zero, so the
  free tier includes every raw material; gear, potions and recipes above level 30 are what the gate holds
  back. Anonymous users may still upload, since that is how they contribute and
  get identified. Linked tier: everything.
- Local mode: the dependency returns a fixed local user with the linked tier.
- Phase 3 wiring: `ALTARMY_MODE` picks the mode. Hosted mode reads `FIREBASE_PROJECT_ID`,
  `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN` and optionally `FIREBASE_AUTH_EMULATOR_HOST`; the front end
  learns them from the public `GET /api/config`. The front end's `AuthProvider` signs in before rendering
  and sends the ID token as a bearer token.
- Linked-only routes answer 403 to a free user: characters, selection, rank, evaluate and ah-blocked.
  The local file sync, source-file lookups, game data update and reload answer 404 in hosted mode.
  `/api/prices` and `/api/prices/{item_id}` apply the level gate: the list is filtered, and one item
  above the level gets 403.
- CLI and tray uploaders authenticate with per-user API keys minted on the site (`POST /api/keys`), not
  Firebase tokens. Only linked accounts can mint keys (an anonymous uid is lost when the browser's data
  is cleared). Keys are `ak_` + 32 random bytes, stored as SHA-256 hashes, and only `POST /api/uploads`
  accepts them.

## 6. API changes

New routes: `/api/me`, `/api/config` (Phase 3), `/api/versions`, `/api/realms` (Phase 3),
`/api/prices` and `/api/prices/{item_id}` (tiered, Phase 3),
`/api/uploads` (multipart `altarmy | auctionator`, later `ahdb`, plus `game_version`; also takes the
watcher's gzipped files, Phase 4), `/api/keys` (Phase 4), `/api/characters` (per user),
`/api/coverage` (freshness per realm). The planned `/api/snapshots` is dropped: the watcher uploads the raw
files like the browser, so the server stays the only parser.

Changed: `rank` and `evaluate` take `game_version` and `auction_house_id`; `/api/status` stops syncing files
in hosted mode and `data_version` becomes per user, bumped on upload or merge. Handlers stay plain `def`
with a connection per request. `scripts/check.py` keeps regenerating `frontend/openapi.json` and
`frontend/src/api/schema.d.ts`.

## 7. Uploaders

1. **Browser upload.** Drop `AltArmy_TBC.lua` and `Auctionator.lua` on an Upload page. The server parses
   them with `altarmy.parse_characters` and `auctionator.parse_price_database`, stores only the extracted
   fields and discards the file. Size limit, progress, and a result summary.
2. **CLI watcher.** `altarmy-profit watch --server URL --key KEY` (`watch.py`). It finds the files with
   `prices.find_*`, keeps what it sent in a JSON state file of mtimes, and POSTs changed files gzipped to
   `/api/uploads`. The flavor folder decides `game_version`. Local mode's `service.sync` stays as it is;
   the two share the finders and the parsers.

Phase 4 status (done): browser upload (Upload tab, hosted mode, every tier), the watcher, API keys
(Manage tab), revision `0003` (`uploads`, `api_keys`). Differences and limits:

- An Auctionator upload records every realm in the file with prices, not just the uploader's. A realm key
  first resolves to an auction house that already has it as an alias, then to one of the uploader's
  character groups (named after their realm), then to a name parsed from the key. That way one realm
  never splits into two auction houses, whichever upload came first; characters find an auction house
  named after the key through `prices.find_auction_house_by_alias`.
- `scanned_at` is the file's modified time, clamped to the 30 days before receipt. Auctionator counts
  days in the player's local time, but the server decides "is the item's last day the scan day?" in its
  own timezone. Near midnight an item can get the start of its day instead of the scan time. A later
  fix: send the uploader's UTC offset.
- Uploads bump only the uploader's `data_version` and invalidate only this process's cached markets. Other
  users and other instances see pooled prices on their next refetch or cache rebuild (Phase 6's price
  version).
- Limits: 32 MB decompressed per file, 60 uploads per user per hour (rejected ones count). The parsers
  cap nesting depth and turn malformed input into `ValueError` (400); a seeded fuzz test holds them to it.
- Uploads are accepted as they come. Quarantine and trust are Phase 6.
3. **Tray app** (later). A PyInstaller build of the watcher with auto-start.
4. **Alt Army paste export** (later). The addon shows a compressed string (LibDeflate + base64) of the
   characters; the site has a paste box. Live data, no `/reload`.
5. **Other sources** (later). An AHDB SavedVariables parser (timestamped full snapshots with quantities), a
   Blizzard API poller for `wow_anniversary` if its namespace works, and for Forever when one appears.

## 8. Pooling and data quality

- Current price per (auction house, item) is the observation with the newest `scanned_at`. Auctionator only
  keeps per-day fields, so a snapshot's `scanned_at` is the file mtime or the upload time.
- A snapshot is quarantined when a large share of its prices deviate wildly from the 7-day median; each uid
  carries a trust score that quarantines feed back into.
- The UI shows price freshness and scan counts, and a coverage page lists each realm's last scan and item
  count so users can see where uploads are needed.

## 9. Compute and performance

- One `engine.Market` per (game_version, auction house), cached in process and keyed by the price version;
  Cloud Run min-instances 1 with several uvicorn workers. `Market` is read-only, so sharing it is safe.
- Per-user rankings are computed on request behind `rank_cache`, keyed on uid, auction house, price version
  and the request parameters. Phase 0 adds `scripts/bench_rank.py`; the target is under two seconds for a
  realistic set of crafters.
- If that misses: precompute a per-auction-house "universal" ranking (one unnamed crafter) for cold starts
  and the free tier and personalize on demand; move long rankings to Cloud Tasks with a job id the client
  polls. Engine candidates: share the memo across crafters when nothing is mailed, and skip the crafter loop
  for recipes with a single learner. `engine.py` stays pure throughout.

## 10. Hosting and ops

- Cloud Run service (FastAPI under uvicorn), Cloud SQL Postgres via the connector, Secret Manager for the
  Firebase admin credentials and Blizzard client id/secret.
- Cloud Scheduler jobs hitting authenticated endpoints: daily game-data update per version, hourly merge
  and daily aggregation, hourly Blizzard poll, daily retention.
- Firebase Hosting serves `frontend/dist` and rewrites `/api/**` to Cloud Run. `deploy/` holds the gcloud or
  Terraform scripts. GitHub Actions runs `scripts/check.py`, builds the image and deploys.
- Rate limiting per uid and per IP. Privacy: only extracted fields are stored, raw uploads are discarded, an
  account-deletion endpoint exists, and the site carries a short privacy note.

## 11. Phases

Each phase ships on its own and local mode keeps working throughout.

0. **Investigate and benchmark** (done, apart from the manual checks in section 14). Flavor folders,
   Auctionator realm keys, DB2 differences and `scripts/bench_rank.py` numbers.
1. **Multi-version foundation** (done, local only). One SQLite file per version, per-version ingest
   product and build, per-version data files, AH cut and postage per version, UI version switch.
2. **Storage layer** (done). SQLAlchemy Core plus Alembic, Postgres support, the snapshot/observation/
   current/daily price tables; local mode moved to one SQLite file and imports the per-version files.
3. **Auth and tenancy** (done). Firebase anonymous sign-in and linking, `users`, per-user characters and
   settings, tiers and the required-level gate, a Prices tab for the free tier; the file sync is local
   only. Tests use a fake token verifier; hosted mode was checked against the Firebase Auth emulator
   (sign in anonymously, gated prices, link an email, same uid now linked).
4. **Uploaders** (done). Browser upload, CLI watcher, API keys; email sign-in, password reset and sign-out.
   Checked with the real files through the emulator (uploads, linking, the watcher's first and repeat
   runs) and against `alt-army-prod` (anonymous and email sign-up, tokens verified by `firebase-admin`).
5. **Deploy.** Cloud Run, Cloud SQL, Firebase Hosting, scheduler jobs, deploy from CI; monthly partitions
   for `price_observations`.
6. **Pooling quality and performance.** Merge job, quarantine and trust, coverage page, rank cache and
   precompute if the benchmark demands it.
7. **More sources and uploaders.** Blizzard API poller, AHDB parser, tray app, Alt Army paste export.

## 12. Verification per phase

- `python scripts/check.py` green on SQLite for every phase.
- From Phase 2, a Postgres CI job (`.github/workflows/check.yml`, a postgres:16 service) runs pytest
  with `TEST_DATABASE_URL` set; locally, the same with any throwaway Postgres database.
- Phase 0 and 6: benchmark numbers recorded in this file's changelog.
- Phase 5: a staging Cloud Run deploy against a test Firebase project.
- End-to-end, manual: an anonymous visit sees only prices for items with required level 30 and below; link the
  account; upload both files; rank; change a file locally and see the watcher POST it.

## 13. Open questions

- Region is not part of the auction house key (decided: realm names are assumed unique across regions).
  If a future realm list breaks that, add `region` to the key and a realm directory to resolve it; until
  then the merge job only logs when one realm name arrives tagged with two regions.
- Retention window for raw observations: decided in Phase 2, 90 days (`prices.KEEP_DAYS`, pruned at each
  local sync; the hosted daily job will call the same `prices.prune`). `price_daily` is kept indefinitely.
- Whether the TBC Anniversary realms will ever expose a Blizzard AH endpoint; the plan does not depend on it.

## 14. Phase 0 findings (2026-09-24)

From the maintainer's installs and wago.tools.

- **Addon files.** `_anniversary_` and `_classic_beta_` each hold `AltArmy_TBC.lua` and `Auctionator.lua`
  under `WTF/Account/<account>/SavedVariables`. TBC characters carry Jewelcrafting and Riding.
- **Auctionator realm keys.** TBC keys realm plus faction (`Dreamscythe Horde`, `Nightslayer Alliance`)
  because its auction houses are split by faction. Forever keys the realm without spaces and no faction
  (`ClassicBetaPvE`, `ClassicBetaPvP2`). `service.match_auctionator_realm` handles both.
- **DB2.** Every column ingest reads exists in both builds. TBC leaves `SpellEffect.EffectBasePointsF` at
  0 and encodes the output count as `EffectBasePoints` plus a 1..`EffectDieSides` roll; `ingest.output_count`
  handles both (random counts are averaged, matching Forever's float).
- **Vendor data.** cmangos publishes `tbc-sqlite-db.zip` in its `latest` release: 1,668 unlimited,
  unconditional, gold-priced vendor items (vanilla via vmangos: 1,393).
- **Disenchant data.** Auctionator's `Source_Classic/Enchant/DisenchantingProbabilities.lua` gives 245 TBC
  rows (brackets starting at item level 164 or below).

Ranking time (`python scripts/bench_rank.py`, best of 3, local SQLite, one core):

| Version | Items / recipes / prices | Characters | Learned | With unlearned |
|---------|--------------------------|------------|---------|----------------|
| Forever | 19,171 / 2,025 / 2,136 | 5 | 0.007 s (87 results) | 0.128 s (877) |
| TBC | 30,132 / 2,015 / 9,431 | 19 | 0.167 s (536) | 1.075 s (1,121) |

`load_market` takes 0.13 to 0.16 s. Ranking is fine for one user; with the widest search at about a second,
the Phase 6 rank cache matters once many users share an instance.

Still to check by hand:

- **AH cut and postage** on both clients (the app assumes 5% and 30c per attachment). Change
  `GameVersion.ah_cut` or `mail_postage` in `versions.py` if either differs.
- **Blizzard API for Anniversary realms.** Create a client at https://develop.battle.net/access/clients, set
  `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET`, run `python scripts/probe_blizzard_api.py`, and record
  which namespace (if any) answers with auctions.
- **Output counts.** TBC's data says the Major protection potions make 5 per craft; confirm one in game.
- **Price outliers.** TBC rankings surface single overpriced listings (a 49s gem "selling" for 333g). That is
  the snapshot-pricing limit the Phase 6 merge job and the price-history ideas in
  [ROADMAP_IDEAS.md](ROADMAP_IDEAS.md) address.
