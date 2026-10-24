# Discord Auction Bot: Project Spec

A Discord bot that runs timed auctions inside a server. Members bid with slash commands or buttons, the bot tracks the high bid, and the deadline extends when someone bids near the end (anti-sniping). The core design goal is that **all auction behavior is testable without Discord and without real time**, so the bot can be verified and demoed without a crowd of real users.

## 1. Goals and non-goals

**Goals (v1)**
- Start an auction with a title, starting bid, duration, and minimum increment.
- Place bids via `/bid` and via buttons on the auction message.
- Live countdown shown to users, anti-snipe deadline extension, automatic close with winner announcement.
- Survive bot restarts without losing or double-closing auctions.
- A deterministic simulator that drives the auction logic with fake bidders, used both in tests and as an admin demo command.

**Non-goals (v1)**
- Real money or payments of any kind.
- A web dashboard (possible later as a small FastAPI app sharing the same SQLite file).
- Multi-process or multi-host deployment. One bot process, one SQLite file.
- Per-user balances or escrow. Bids are an honor-system number in v1 (see open decisions).

## 2. Stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | |
| Discord | `discord.py` 2.x | async, native slash commands (`app_commands`), buttons/modals (`discord.ui`) |
| Storage | SQLite via `aiosqlite` | single-file, restart-safe, plenty for this scale |
| Domain model | stdlib `dataclasses` | core has zero third-party imports |
| Scheduling | `discord.ext.tasks` polling loop | state lives in the DB, so no lost-timer bugs |
| Tests | `pytest`, `pytest-asyncio`, `hypothesis` | property-based tests suit the invariants |
| Config | `python-dotenv` | keeps the token out of the code |

No Django, no Celery, no DI framework. **Note for the implementer:** verify all discord.py API usage against the current 2.x docs rather than relying on memory; the library has changed across versions.

## 3. Layout

```
auction-bot/
├── pyproject.toml
├── README.md
├── SPEC.md
├── AGENTS.md                  # conventions for coding agents (section 11)
├── .env.example               # DISCORD_TOKEN=, DEV_GUILD_ID=, DB_PATH=
├── src/auctionbot/
│   ├── __main__.py            # entrypoint: load config, build service, run bot
│   ├── config.py              # settings dataclass loaded from env
│   ├── clock.py               # Clock protocol, SystemClock, FakeClock
│   ├── core/                  # PURE LOGIC. stdlib imports only.
│   │   ├── models.py          # Auction, Bid, AuctionConfig, Status
│   │   ├── results.py         # BidAccepted, BidRejected, RejectReason
│   │   └── rules.py           # place_bid, close_if_due, cancel
│   ├── storage/
│   │   ├── schema.sql
│   │   └── repository.py      # async CRUD + transaction helper
│   ├── service.py             # AuctionService: repo + core + locks. No discord imports.
│   ├── bot/                   # NOT named `discord/` (would shadow the library)
│   │   ├── client.py          # bot setup, command sync, startup recovery
│   │   ├── commands.py        # slash commands
│   │   ├── views.py           # buttons, bid modal
│   │   ├── render.py          # Auction -> embed/message text
│   │   └── scheduler.py       # tasks.loop that closes due auctions
│   └── sim/
│       ├── strategies.py      # bidder strategies
│       └── runner.py          # discrete-event simulation on a FakeClock
└── tests/
    ├── test_rules.py          # example-based tests for core
    ├── test_properties.py     # hypothesis invariants and stateful test
    ├── test_service.py        # repo + service against :memory: SQLite
    └── test_sim.py            # strategies run clean, invariants hold
```

**Import rules (enforce in review):** `core` imports nothing outside the stdlib. `storage` imports `core`. `service` imports `core` and `storage`. `bot` imports `service`. `sim` imports `core` and `service`. Nothing imports `bot` except `__main__`.

## 4. Domain model (`core`)

Time is passed in explicitly as `now: float` (epoch seconds). **No function in `core` calls `time.time()` or reads a clock.** Money is `int` (whole units), never `float`. Domain objects are frozen dataclasses; transitions return new objects.

```python
class Status(Enum): OPEN, CLOSED, CANCELLED

@dataclass(frozen=True)
class AuctionConfig:
    min_increment: int = 1
    anti_snipe_window_s: int = 30    # bids within this many seconds of ends_at extend the deadline
    extension_s: int = 30            # deadline becomes now + extension_s after an extending bid

@dataclass(frozen=True)
class Bid:
    bidder_id: int
    amount: int
    placed_at: float

@dataclass(frozen=True)
class Auction:
    id: int
    seller_id: int
    title: str
    starting_bid: int
    config: AuctionConfig
    ends_at: float
    status: Status
    bids: tuple[Bid, ...] = ()
    # derived: high_bid, high_bidder_id, winning_bid()
```

### Rules (`core/rules.py`)

```python
place_bid(auction, bidder_id, amount, now) -> tuple[Auction, BidResult]
close_if_due(auction, now) -> tuple[Auction, bool]     # True if it transitioned to CLOSED
cancel(auction, actor_id, is_admin, now) -> tuple[Auction, CancelResult]
```

`BidResult` is `BidAccepted(extended: bool, new_ends_at: float)` or `BidRejected(reason: RejectReason)`. A rejected bid returns the **unchanged** auction.

**`place_bid` evaluation order** (first failure wins; document the order in code):
1. `status != OPEN` or `now >= ends_at` → `AUCTION_CLOSED`
2. `amount <= 0` → `INVALID_AMOUNT`
3. `bidder_id == seller_id` → `SELLER_CANNOT_BID`
4. `bidder_id == current high bidder` → `ALREADY_HIGH_BIDDER` (prevents bumping your own bid to extend the timer)
5. `amount < minimum_next_bid` → `BELOW_MINIMUM`, where `minimum_next_bid = starting_bid` if no bids yet, else `high_bid + min_increment`
6. Otherwise accept. If `ends_at - now <= anti_snipe_window_s`, set `ends_at = max(ends_at, now + extension_s)` and report `extended=True`.

**Boundary decisions (pin these with tests):** a bid at exactly `now == ends_at` is rejected. Equal amounts are never accepted (rule 5), so there are no ties; whichever bid is serialized first wins. The deadline never moves earlier.

**Invariants** (asserted by property tests, section 8):
- `high_bid` is non-decreasing over the life of an auction.
- `ends_at` is non-decreasing.
- Every accepted bid is `>= minimum_next_bid` at the moment it was accepted.
- No bid is accepted when `now >= ends_at` or status is not OPEN.
- After close, the winner is the bidder of the maximum bid, and there is exactly one.
- Rejected bids never change the auction.

## 5. Storage (`storage`)

```sql
CREATE TABLE auctions (
  id INTEGER PRIMARY KEY,
  guild_id INTEGER NOT NULL,
  channel_id INTEGER NOT NULL,
  message_id INTEGER,                -- the live auction message, set after posting
  seller_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  starting_bid INTEGER NOT NULL,
  min_increment INTEGER NOT NULL,
  anti_snipe_window_s INTEGER NOT NULL,
  extension_s INTEGER NOT NULL,
  ends_at REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open','closed','cancelled')),
  closed_announced INTEGER NOT NULL DEFAULT 0   -- guards against double announcements
);
CREATE TABLE bids (
  id INTEGER PRIMARY KEY,
  auction_id INTEGER NOT NULL REFERENCES auctions(id),
  bidder_id INTEGER NOT NULL,
  amount INTEGER NOT NULL,
  placed_at REAL NOT NULL
);
CREATE INDEX idx_bids_auction ON bids(auction_id, amount DESC);
CREATE INDEX idx_auctions_open_due ON auctions(status, ends_at);
```

The repository exposes `get(id)`, `create(...)`, `save(auction)` (writes auction row plus any new bids), `list_open(guild_id)`, `list_due(now)`, `set_message_id(...)`, and an async context manager for a transaction. Use `BEGIN IMMEDIATE` for the bid path so the read-modify-write cannot interleave with another writer.

## 6. Service layer (`service.py`)

`AuctionService(repo, clock)` is the only thing the bot calls. It has **no discord imports**, and its methods return plain results the bot can render.

```python
create_auction(guild_id, channel_id, seller_id, title, starting_bid, duration_s, config) -> Auction
place_bid(auction_id, bidder_id, amount) -> BidResult        # takes a per-auction asyncio.Lock, then a DB transaction
close_due() -> list[Auction]                                  # closes everything past ends_at, marks closed_announced only when asked to
cancel(auction_id, actor_id, is_admin) -> CancelResult
get(auction_id) / list_open(guild_id)
```

`place_bid` flow: acquire the auction's lock → open transaction → load → `rules.place_bid(auction, ..., now=clock.now())` → save if accepted → commit. The lock handles same-process races; the transaction protects the data.

## 7. Discord layer (`bot`)

**Commands (slash only, no prefix commands):**
- `/auction start title starting_bid duration [min_increment]`: posts the auction message in the current channel and stores its `message_id`.
- `/bid auction amount`: places a bid. `auction` autocompletes from open auctions in the guild.
- `/auction status [auction]`, `/auction list`
- `/auction cancel auction`: seller or admin only.
- `/simulate` (admin only, see section 9).

**Auction message:** an embed showing title, current high bid and bidder, minimum next bid, and the deadline as a Discord timestamp (`<t:{int(ends_at)}:R>`), which counts down client-side with no edits. Buttons: "Bid +{min_increment}" (bids `minimum_next_bid`) and "Custom bid" (opens a modal with a number field). Re-render the message on each accepted bid, **debounced to at most one edit per ~2 seconds per message** to stay inside rate limits.

**Responses:** rejections are ephemeral (only the bidder sees them) with a human-readable reason. Accepted bids are announced in-channel. Deadline extensions are called out ("Bid landed in the final 30 seconds. Deadline extended.").

**Scheduler:** a `tasks.loop(seconds=2)` calls `service.close_due()`, then for each newly closed auction edits the message (disable buttons, show winner) and posts the result. Use the `closed_announced` flag so an auction is announced exactly once even if the loop and a restart overlap.

**Startup recovery:** in `setup_hook`/`on_ready`, run `close_due()` immediately so auctions that expired while the bot was offline are closed and announced, and re-attach persistent button views for auctions still open (buttons need stable `custom_id`s that encode the auction id, and views registered on startup, or they stop working after a restart).

**Dev workflow:** during development, sync commands to a single test guild (`DEV_GUILD_ID`) because global sync propagates slowly. Request only the intents actually needed; slash commands do not need the privileged message-content intent.

## 8. Testing

**Example-based (`test_rules.py`):** each rule in the evaluation order, plus boundaries: bid at `ends_at - 0.001` accepted, at `ends_at` rejected; bid exactly at the anti-snipe window edge; equal-amount bid rejected; seller bid rejected; first bid equals starting bid accepted, one below rejected.

**Property-based (`test_properties.py`):** use Hypothesis to generate sequences of `(dt, bidder_id, amount)` actions, apply them via `rules.place_bid` with a monotonically advancing `now`, and assert all invariants from section 4 after every step. Add a `RuleBasedStateMachine` that interleaves bids, time advances, closes, and cancels.

**Service (`test_service.py`):** run against an in-memory SQLite database with a `FakeClock`. Include a concurrency test: `asyncio.gather` many `place_bid` calls at the same fake instant and assert exactly the expected winner and no lost updates. Include a restart test: build a service, place bids, discard it, build a new one on the same DB, and confirm state and `close_due` behave correctly.

**Manual checklist (the part that needs real Discord):** two or three accounts bid at once; buttons still work after a bot restart; auction that expires while the bot is down gets closed on startup; rate limits are not hit during a bidding war; permissions for cancel; behavior when the bot lacks channel permissions.

## 9. Simulator (`sim`)

A discrete-event runner: given an auction, a list of bidder strategies, and a seeded `random.Random`, it advances a `FakeClock` and calls `service.place_bid` (or `rules.place_bid` directly for pure runs). It returns the final auction and a full event log, and asserts the section 4 invariants at every step. Same seed → identical run.

**Strategies:** `Incrementer` (always bid `minimum_next_bid`), `Sniper` (wait until a few seconds before `ends_at`, then bid), `BiddingWar` (two bidders answering each other; verifies the extension logic terminates or is capped), `Chaos` (random amounts and times, including invalid ones), `Simultaneous` (many bidders at the same timestamp).

**`/simulate` demo command (admin only):** runs the same strategies in real time inside the bot process using fake user ids and a compressed config (e.g. 30-second auction). Simulated bidders must be **clearly labeled** in all announcements (e.g. "SimBidder-3 (simulated)") so nobody mistakes the demo for real activity. Fake ids must not collide with real Discord ids (use negative integers).

## 10. Build order (each milestone ends with passing tests)

1. **Core + unit tests.** `models`, `results`, `rules`, `clock`; example-based tests.
2. **Property tests + simulator.** Hypothesis invariants; `sim/` against pure rules with `FakeClock`.
3. **Storage + service.** Schema, repository, `AuctionService`; service tests including concurrency and restart.
4. **Bot skeleton.** Config, client, dev-guild command sync, a `/ping`-level smoke test against the real Discord API.
5. **Auction commands.** `/auction start`, `/bid`, rendering, ephemeral rejections.
6. **Scheduler and recovery.** Close loop, announcements, startup recovery, persistent buttons.
7. **Buttons, modal, debounced edits.**
8. **`/simulate` demo mode** and a README with setup steps (portal, token, invite URL, `.env`).

## 11. Conventions for coding agents (copy into `AGENTS.md` / `CLAUDE.md`)

- Never put Discord, SQLite, or clock calls inside `core/`. If a rule needs the time, it takes `now` as a parameter.
- Money is `int`. Time is `float` epoch seconds. No `float` currency, no naive datetimes.
- Every behavior change in `core/rules.py` needs a test, and any new invariant goes in `test_properties.py`.
- Never commit the bot token; read it from the environment only. Fail fast with a clear message if it's missing.
- Don't name any package or module `discord`.
- Keep dependencies minimal; ask before adding any.
- Run `pytest` before declaring a milestone done.

## 12. Open decisions (resolve before or during milestone 3)

1. **What are bids denominated in?** v1 default: honor-system numbers with no balances. Alternative: a virtual points ledger with per-user balances, which adds escrow-on-high-bid and refund-on-outbid logic to `core`.
2. **Self-outbid.** Spec rejects a bid from the current high bidder. Alternative: allow it as a "raise max" feature, which implies proxy/max-bid auctions (a larger change).
3. **Anti-snipe policy.** Spec: extend to `now + extension_s` when a bid lands inside the window. Alternatives: fixed cap on total extensions, or a hard maximum end time.
4. **Who can start auctions?** Anyone, a specific role, or admins only.
5. **Item content.** Title only, or description/image attachments, which affects the embed and the schema.
6. **One active auction per channel, or many?** The spec assumes many; it affects autocomplete and message layout.
