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

- `game_version` (`tbc` | `forever`) is a column on every game-data and price table and a parameter on
  every API route that reads them.
- Ingest takes the wago.tools product: `tbc` -> `wow_anniversary` (2.5.6, Interface 20506),
  `forever` -> `wow_classic_beta` (1.60.x, Interface 16001). `DEFAULT_BUILD` in `ingest.py` becomes a
  per-version table; the DB2 table list is the same for both.
- Per-version hand data: `data/<version>/disenchant.csv` and `data/<version>/vendor_items.csv`. TBC vendor
  items come from a TBC world database (cmangos `mangos-tbc`) through a sibling of
  `scripts/build_vendor_items.py`; `vmangos.py` stays the vanilla reader.
- Engine constants become per-version config passed into `Market`: `PROFESSIONS` gains Jewelcrafting for
  TBC; AH cut and postage are verified per client (Phase 0).
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

- `users(uid, created_at, linked_at, tier, trust_score)`; `api_keys(uid, key_hash, label, created_at)`
- `characters(user_uid, game_version, realm, faction, name, class_file, level, updated_at)`,
  `character_professions`, `character_recipes`: today's tables plus owner and version
- `user_settings(uid, game_version, selected_auction_house_id)`; `ah_blocked(uid, game_version, item_id)`
- `uploads(id, uid, kind, size, received_at, outcome)`
- `rank_cache(key, uid, auction_house_id, price_version, params_hash, results jsonb, computed_at)`

Money stays integer copper everywhere.

## 5. Auth and access tiers

- The front end signs in anonymously on first visit. Linking with Google or email uses
  `linkWithCredential`, which keeps the uid, so uploads, settings and trust carry over.
- A FastAPI dependency verifies the Firebase ID token with `firebase-admin` and yields `User(uid, tier)`.
  `tier` is `linked` when the token's `firebase.sign_in_provider` is not `anonymous`, else `free`.
- Free tier: price routes and item pages are filtered to `items.required_level <= FREE_TIER_MAX_LEVEL`
  (30); no rankings, no characters. Reagents such as cloth and ore have a required level of zero, so the
  free tier includes every raw material; gear, potions and recipes above level 30 are what the gate holds
  back. Anonymous users may still upload, since that is how they contribute and
  get identified. Linked tier: everything.
- Local mode: the dependency returns a fixed local user with the linked tier.
- CLI and tray uploaders authenticate with per-user API keys minted on the site (`POST /api/keys`), not
  Firebase tokens.

## 6. API changes

New routes: `/api/me`, `/api/versions`, `/api/realms`, `/api/prices/{item_id}` (tiered),
`/api/uploads` (multipart `altarmy | auctionator | ahdb` plus `game_version`), `/api/snapshots` (JSON from
the watcher), `/api/keys`, `/api/characters` (per user), `/api/coverage` (freshness per realm).

Changed: `rank` and `evaluate` take `game_version` and `auction_house_id`; `/api/status` stops syncing files
in hosted mode and `data_version` becomes per user, bumped on upload or merge. Handlers stay plain `def`
with a connection per request. `scripts/check.py` keeps regenerating `frontend/openapi.json` and
`frontend/src/api/schema.d.ts`.

## 7. Uploaders

1. **Browser upload.** Drop `AltArmy_TBC.lua` and `Auctionator.lua` on an Upload page. The server parses
   them with `altarmy.parse_characters` and `auctionator.parse_price_database`, stores only the extracted
   fields and discards the file. Size limit, progress, and a result summary.
2. **CLI watcher.** `altarmy-profit watch --server URL --key KEY`. Refactor `service.sync` into pure steps
   (find files via `prices.find_*`, detect mtime change, parse, build a snapshot) plus two sinks: the local
   SQLite store and a remote POST to `/api/snapshots`. The flavor folder decides `game_version`.
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

0. **Investigate and benchmark.** Confirm the flavor folder names and Auctionator realm keys on the TBC
   client, find the Blizzard namespace for `wow_anniversary` realms and whether its AH endpoints answer,
   verify the AH cut and postage on Forever, and record `bench_rank.py` numbers.
1. **Multi-version foundation** (local only). `game_version` column, ingest product flag, per-version data
   files, engine config per version, UI version switch.
2. **Storage layer.** SQLAlchemy Core plus Alembic, Postgres support, the snapshot/observation/current price
   tables; local mode migrates its SQLite file.
3. **Auth and tenancy.** Firebase anonymous sign-in and linking, `users`, per-user characters and settings,
   tiers and the item-level gate.
4. **Uploaders.** Browser upload, CLI watcher, API keys.
5. **Deploy.** Cloud Run, Cloud SQL, Firebase Hosting, scheduler jobs, CI.
6. **Pooling quality and performance.** Merge job, quarantine and trust, coverage page, rank cache and
   precompute if the benchmark demands it.
7. **More sources and uploaders.** Blizzard API poller, AHDB parser, tray app, Alt Army paste export.

## 12. Verification per phase

- `python scripts/check.py` green on SQLite for every phase.
- From Phase 2, a Postgres CI job (Docker service) runs pytest with `DATABASE_URL` set.
- Phase 0 and 6: benchmark numbers recorded in this file's changelog.
- Phase 5: a staging Cloud Run deploy against a test Firebase project.
- End-to-end, manual: an anonymous visit sees only prices for items with required level 30 and below; link the
  account; upload both files; rank; change a file locally and see the watcher POST it.

## 13. Open questions

- Region is not part of the auction house key (decided: realm names are assumed unique across regions).
  If a future realm list breaks that, add `region` to the key and a realm directory to resolve it; until
  then the merge job only logs when one realm name arrives tagged with two regions.
- Retention window for raw observations (plan: about 90 days).
- Whether the TBC Anniversary realms will ever expose a Blizzard AH endpoint; the plan does not depend on it.
