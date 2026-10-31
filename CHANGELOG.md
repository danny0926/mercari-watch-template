# Changelog

## 0.7.0

- Make project-local, pinned CloakBrowser headless mode the primary Suruga-ya reader; keep headed Patchright as an explicit manual alternative.
- Fix mixed regular and time-sale new/used offers by binding each direct price pair to its sale period, preserving condition identities and deadlines.
- Add a project-only installer, contained browser/cache/profile/temp paths and browser-child credential filtering without redistributing browser binaries.
- Add DOM regression coverage for both mixed-condition orders and verify native search, stock/order controls and public images through the same production reader.

## 0.6.2

- Allow controlled local maintenance restarts to retain saved histories and cloud ownership without a cloud handback.
- Show the effective local wait interval in runtime status and preserve sequential, non-overlapping scans.

## 0.6.1

- Add a graceful stop command for a local monitor running in the background, preserving the active round and encrypted handback.
- Record the last completed local cycle and source error count in local status.

## 0.6.0

- Add a local monitor launcher that pauses the cloud clock, drains active cloud searches and resumes the original cloud setting on graceful exit.
- Exchange both source histories through authenticated, encrypted, session-bound Artifacts and Secrets while retaining existing cache formats and deduplication identities.
- Add a local process lock, persistent recovery journal, explicit cloud recovery and a handoff-only mode without searches or product notifications.
- Block cloud product jobs while local ownership is active; keep CI independent and document manual recovery after abrupt termination.

## 0.5.1

- Read verified direct-store time-sale prices separately from crossed-out regular prices, retail prices, shipping thresholds and marketplace offers.
- Validate sale periods in Japanese time and label their deadlines while preserving existing condition identities and encrypted deduplication history.
- Report predefined Suruga-ya failure reasons without exposing private queries or browser exception details.

## 0.5.0

- Support optional title/description matching on verified Mercari listings, with shared detail caching and explicitly labeled review candidates.
- Add controlled, one-time catchup references that retain normal quiet baselines and retry failed delivery.
- Record recent successful notification receipts separately from previously known/baselined identities.
- Add a read-only encrypted history audit without exposing private listing references or search conditions.

## 0.4.6

- Recognize the Taiwan storefront's native empty-results component instead of relying on incomplete text patterns.
- Stop treating valid zero-result searches as browser timeouts; continue rejecting unverified filters, blank pages and failed loads.
- Add cloud diagnostics for populated, empty and privately configured Taiwan queries without exposing query text or sending notifications.
- Report timeout loading stages while preserving encrypted history and source failure handling.

## 0.4.5

- Use Mercari's explicit Japanese item and Shops routes in notification links to bypass the verified region-cookie redirect.
- Preserve original listing URLs, IDs, query strings, Taiwan source links and encrypted history.
- Cover native routes in Discord and LINE while retaining explicit opt-in proxy mode.
- Document the reproduced HTTP 307 redirect caused by the regional preference cookie.

## 0.4.4

- Distinguish Mercari listing sources from optional Buyee proxy destinations in notifications.
- Label Shops original links correctly in original mode and retain direct, clickable source links.
- Clarify that selecting a proxy service does not fix Mercari's own regional redirection.

## 0.4.3

- Support verified Mercari Shops identities on Buyee's native Mercari item route.
- Use Buyee for primary Discord and LINE links while retaining original item identities and history.
- Keep region-sensitive original URLs as copyable text in Buyee mode, with plain source labels, to avoid ambiguous direct-source links.
- Reject mismatched Shops IDs and external source URLs instead of guessing a proxy destination.

## 0.4.2

- Forward an optional third independent Discord destination to source jobs, connection tests and clock alerts.

- Replace the unverified native cron with a GitHub-hosted environment wait timer and automatic workflow handoff.
- Verify timer configuration before dispatching; refuse missing timers and required-reviewer gates instead of creating a rapid loop.
- Trace automatic monitor runs to their parent clock and report clock failures to configured Discord destinations.
- Preserve separate encrypted source caches and fixed-sale filtering across the workflow registration change.
- Document cloud-clock setup, stopping, restarting and actual automatic-run evidence.

## 0.4.1

- Remove auction websites from supported monitor sources and workflow choices.
- Exclude Mercari auction items by default and disable them in the shipped example.
- Preserve encrypted listing history while limiting monitoring to fixed-sale sources.

## 0.4.0

- Add the Japanese Suruga-ya storefront using Patchright and a dedicated browser profile.
- Verify native updated-first ordering and sold-out exclusion, then retain confirmed direct-store offers.
- Separate condition branches and new/used identities; label price ranges and exclude reservation or marketplace-only goods.
- Resolve actual public CDN image redirects before notifications; preserve names and links if images are unavailable.
- Add an optional runner probe without private search rules or notification credentials.
- Run Suruga-ya on Windows/Edge with a separate encrypted state cache; preserve the existing Linux sources and history.
- Support selective source runs and one unattended attempt at a visible verification checkbox.
- Retry a Taiwan page timeout once; allow manual source selection without replaying other providers.
- Correct the comparison assessment: semantic product matching, Taiwan price extraction and landed-cost calculation are not implemented.
- Describe evidence-based multimodal matching and abstention instead of claiming unmeasured zero-token matching quality.

## 0.3.1

- Add an optional Buyee destination for Mercari notification titles and LINE buttons.
- Preserve original listing links, copyable item IDs and existing deduplication history.
- Leave Yahoo, Shops and listings without a verified original Mercari ID on their source URLs.

## 0.3.0

- Add public Yahoo! Fleamarket and Yahoo! Auctions searches with verified newest and active filters.
- Canonicalize mirrored Yahoo listings to one identity across sources and notification rounds.
- Preserve auction current prices, deadlines and bid counts; keep fixed-price listings distinct.
- Reuse existing encrypted history and quietly baseline newly enabled sources.
- Document local-stock comparison, landed-cost estimates and a rules-first design without runtime AI calls.
- Record Suruga-ya access restrictions; keep unverifiable sources outside production monitoring.

## 0.2.0

- Route private watch rules to independently configured Discord webhooks.
- Keep deduplication and delivery retries separate for each destination.
- Migrate existing single-destination history without replaying known listings.
- Send provider health alerts to the affected destination.
- Test all configured Discord destinations with clearly marked test messages.
- Refresh the fork's schedule registration while retaining a 30-minute interval.

## 0.1.0

- Add independent Japan and Taiwan searches using newest and available filters.
- Merge matching listings by their original item identity across sources and runs.
- Include item names, large product images, and direct links in Discord alerts.
- Support Discord, LINE, or both, with isolated notification test commands.
- Load private watch rules and credentials from environment variables or .env.
- Encrypt persistent deduplication state before storing it in Actions Cache.
- Document setup, privacy boundaries, failure handling, and upstream license scope.
