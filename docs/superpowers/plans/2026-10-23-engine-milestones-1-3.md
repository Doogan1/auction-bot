# Auction Engine (Milestones 1–3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and fully test the Discord-free auction engine: pure rules, deterministic simulator, SQLite storage, and `AuctionService`.

**Architecture:** `core` holds frozen dataclasses and pure functions that take `now` as a parameter. `storage` persists them through one `aiosqlite` connection guarded by a write lock. `service` composes the two with a `Clock`. `sim` drives `core` with seeded fake bidders on a `FakeClock`. No Discord code in this plan (milestones 4–8 are a later plan).

**Tech Stack:** Python 3.12+, `aiosqlite`, `pytest`, `pytest-asyncio`, `hypothesis`, `python-dotenv` (declared now, used in milestone 4).

**Spec:** `SPEC.md` (sections 3–6, 8–10). Decisions taken on its section 12 are listed under "Decisions" below and recorded in `SPEC.md` by Task 1.

## Global Constraints

- Python 3.12+; src layout, package `auctionbot` under `src/`. Never name a module `discord`.
- `core/` imports stdlib only. Import direction: `storage`→`core`; `service`→`core`,`storage`; `sim`→`core`. `clock.py` is outside `core`.
- No function in `core` calls `time.time()` or reads a clock; time is `now: float` epoch seconds.
- Money is `int`, never `float`. Domain objects are frozen dataclasses; transitions return new objects.
- A rejected bid returns the **unchanged** auction (same object equality).
- `place_bid` evaluation order, first failure wins: closed → invalid amount → seller → already high bidder → below minimum → accept.
- Bid at exactly `now == ends_at` is rejected; equal amounts are never accepted; the deadline never moves earlier.
- Dependencies are limited to those in the spec's stack table; ask before adding any.
- Every behavior change in `core/rules.py` gets a test; new invariants go in `tests/test_properties.py`. Run `pytest` before finishing each task.
- Each commit message ends with the line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Decisions (spec section 12, plus calls made while planning)

1. Bids are honor-system integers; no balances.
2. Self-outbid stays rejected (`ALREADY_HIGH_BIDDER`).
3. Anti-snipe extends to `now + extension_s`, capped at `AuctionConfig.max_extensions` (default 10) extensions per auction. Once capped, bids are still accepted but the deadline stays put (`extended=False`).
4. Anyone may start an auction (enforced in the bot layer, not here).
5. Items have a title plus an optional `description` (default `""`). No images.
6. Many open auctions per channel.

Planning calls (mine, not from the spec):
- `extended` is true only if the deadline actually moved (`new ends_at > old ends_at`); only those bids count toward the cap. A bid exactly at the window edge with `window == extension` therefore reports `extended=False`.
- `amount > MAX_AMOUNT` (`10**12`, in `core/rules.py`) returns `INVALID_AMOUNT`, so a huge number can never overflow SQLite's 64-bit integer.
- `cancel` is allowed with bids present, by seller or admin, only while `status == OPEN and now < ends_at`; otherwise `NOT_OPEN` / `NOT_ALLOWED` (not-open is checked first).
- `sim/invariants.py` is added (not in the spec layout) so the property tests and the simulator share one invariant checker.
- The simulator in this plan is pure (drives `rules` directly). The in-bot `/simulate` is milestone 8.
- One `aiosqlite` connection cannot interleave transactions, so the repository serializes all access with one `asyncio.Lock`. The service's per-auction locks (spec section 6) stay, but the repository lock is what protects the data.
- The auction's Discord location lives in storage only (`AuctionRef`), not in the `core` model.

## Review Focus

Failure modes the spec implies but never states; each is pinned by a test in the named task.

1. Absurdly large bid amount (`2**70`) must be rejected, not crash SQLite. → Task 3, Task 8
2. Empty, whitespace-only, or over-long title (>256 chars), or description over 1000 chars (Discord embed limits). → Task 8
3. Non-positive `starting_bid`, `duration_s`, or `min_increment`. → Task 8
4. Bid or cancel on an auction id that does not exist. → Task 8
5. `close_due` run twice (loop plus restart overlap) must close and report each auction once; bids on a cancelled auction are rejected as `AUCTION_CLOSED`. → Tasks 4, 8, 9

---

### Task 1: Scaffold, spec decisions, and clock

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md` (title and one-line description only), `AGENTS.md`, `src/auctionbot/__init__.py`, `src/auctionbot/clock.py`, `tests/test_clock.py`
- Modify: `SPEC.md` (section 12)

**Interfaces:**
- Produces: `class Clock(Protocol): def now(self) -> float`; `class SystemClock` (wraps `time.time`); `class FakeClock(start: float = 0.0)` with `now() -> float`, `advance(seconds: float) -> None` (rejects negative), `set(t: float) -> None` (rejects going backwards).

- [ ] **Step 1:** Write `pyproject.toml`: project `auctionbot`, `requires-python = ">=3.12"`, dependencies `discord.py>=2.3`, `aiosqlite`, `python-dotenv`; optional `dev` extra with `pytest`, `pytest-asyncio`, `hypothesis`; setuptools src layout; pytest config `asyncio_mode = "auto"`, `testpaths = ["tests"]`. Write `.gitignore` (`.venv/`, `.env`, `__pycache__/`, `*.db`, `.hypothesis/`, `.pytest_cache/`), `.env.example` (`DISCORD_TOKEN=`, `DEV_GUILD_ID=`, `DB_PATH=auctions.db`), and `AGENTS.md` containing spec section 11 verbatim.
- [ ] **Step 2:** Create `.venv`, `pip install -e ".[dev]"`, and confirm `python --version` is ≥ 3.12 and `pytest` runs (no tests collected is fine).
- [ ] **Step 3:** Replace the "Open decisions" list in `SPEC.md` section 12 with a "Decisions" list matching this plan's Decisions 1–6 (keep the numbering).
- [ ] **Step 4: Write failing tests** in `tests/test_clock.py`: `test_fake_clock_starts_at_given_time`, `test_advance_moves_forward` (`FakeClock(10).advance(2.5)` → `now() == 12.5`), `test_advance_negative_raises` (`ValueError`), `test_set_backwards_raises` (`ValueError`), `test_system_clock_is_close_to_time_time` (within 1s). Run `pytest tests/test_clock.py -v`; expect FAIL (import error).
- [ ] **Step 5:** Implement `clock.py` per Interfaces. Run the tests; expect PASS.
- [ ] **Step 6: Commit** everything including `SPEC.md`: `chore: scaffold project, record spec decisions, add clock`.

---

### Task 2: Domain models and results

**Files:**
- Create: `src/auctionbot/core/__init__.py`, `core/models.py`, `core/results.py`, `tests/test_models.py`

**Interfaces:**
- Produces in `models.py`:
  - `class Status(Enum)`: `OPEN="open"`, `CLOSED="closed"`, `CANCELLED="cancelled"`.
  - `AuctionConfig(min_increment: int = 1, anti_snipe_window_s: int = 30, extension_s: int = 30, max_extensions: int = 10)`, frozen.
  - `Bid(bidder_id: int, amount: int, placed_at: float)`, frozen.
  - `Auction(id, seller_id, title, starting_bid, config, ends_at, status, bids: tuple[Bid, ...] = (), description: str = "", extensions_used: int = 0)`, frozen. Properties: `high_bid -> int | None`, `high_bidder_id -> int | None`, `minimum_next_bid -> int` (`starting_bid` with no bids, else `high_bid + config.min_increment`). Method `winning_bid() -> Bid | None` (the max bid; `None` with no bids).
- Produces in `results.py`:
  - `class RejectReason(Enum)`: `AUCTION_CLOSED`, `INVALID_AMOUNT`, `SELLER_CANNOT_BID`, `ALREADY_HIGH_BIDDER`, `BELOW_MINIMUM`.
  - `BidAccepted(extended: bool, new_ends_at: float)`, `BidRejected(reason: RejectReason)`; `BidResult = BidAccepted | BidRejected`.
  - `class CancelRejectReason(Enum)`: `NOT_OPEN`, `NOT_ALLOWED`. `Cancelled()`, `CancelRejected(reason: CancelRejectReason)`; `CancelResult = Cancelled | CancelRejected`.

- [ ] **Step 1: Write failing tests** in `tests/test_models.py` using a small `make_auction(**overrides)` helper (put it in `tests/conftest.py`: seller 1, starting_bid 10, `min_increment` 5, `ends_at` 1000.0, status OPEN): `test_minimum_next_bid_is_starting_bid_when_no_bids` (10), `test_minimum_next_bid_adds_increment` (bid 10 → 15), `test_high_bid_and_bidder`, `test_winning_bid_none_without_bids`, `test_auction_is_frozen` (assigning raises `dataclasses.FrozenInstanceError`).
- [ ] **Step 2:** Run; expect FAIL. Implement both modules per Interfaces. Run; expect PASS.
- [ ] **Step 3: Commit** `feat(core): add domain models and result types`.

---

### Task 3: `place_bid`

**Files:**
- Create: `src/auctionbot/core/rules.py`, `tests/test_rules.py`

**Interfaces:**
- Consumes: Task 2 models and results; `make_auction` from `conftest.py`.
- Produces: `MAX_AMOUNT: int = 10**12`; `place_bid(auction: Auction, bidder_id: int, amount: int, now: float) -> tuple[Auction, BidResult]`. On accept, the returned auction has the bid appended (`Bid(bidder_id, amount, now)`), possibly a new `ends_at` and `extensions_used + 1`.

- [ ] **Step 1: Write failing tests** in `tests/test_rules.py` (one per line; "rejected" means `BidRejected(reason)` and returned auction `==` the input):
  - Order: `test_closed_status_rejected_first` (status CLOSED, amount 0, bidder is seller → `AUCTION_CLOSED`); `test_invalid_amount_before_seller` (amount 0 by seller → `INVALID_AMOUNT`); `test_seller_before_already_high` ; `test_already_high_before_below_minimum`.
  - Each reason alone: cancelled auction → `AUCTION_CLOSED`; negative amount → `INVALID_AMOUNT`; `MAX_AMOUNT + 1` and `2**70` → `INVALID_AMOUNT`; `MAX_AMOUNT` itself accepted on an auction with a low start; seller → `SELLER_CANNOT_BID`; current high bidder → `ALREADY_HIGH_BIDDER`.
  - Minimums: first bid equal to `starting_bid` accepted; `starting_bid - 1` → `BELOW_MINIMUM`; after a bid of 10 with increment 5, 14 → `BELOW_MINIMUM`, 15 accepted; equal amount to high bid rejected.
  - Time boundaries (`ends_at=1000.0`): `now=999.999` accepted; `now=1000.0` → `AUCTION_CLOSED`; `now=1000.5` → `AUCTION_CLOSED`.
  - Anti-snipe (window 30, extension 30 unless stated): bid at `now=900` → `extended=False`, `ends_at` unchanged; at `now=980` → `extended=True`, `new_ends_at == 1010.0`; at `now=970` (exact window edge, `ends_at - now == 30`) → accepted, `extended=False`, `ends_at` unchanged; with `extension_s=5, anti_snipe_window_s=30` a bid at `now=990` leaves `ends_at == 1000.0` (never earlier) and `extended=False`; with `max_extensions=2` and `extensions_used=2`, a bid at `now=995` is accepted with `extended=False` and unchanged `ends_at`; an extending bid increments `extensions_used`.
- [ ] **Step 2:** Run `pytest tests/test_rules.py -v`; expect FAIL (import error).
- [ ] **Step 3: Implement `place_bid`** following the Global Constraints order; document the order in the docstring. Use `dataclasses.replace`.
- [ ] **Step 4:** Run; expect PASS. **Step 5: Commit** `feat(core): add place_bid with anti-snipe extension and cap`.

---

### Task 4: `close_if_due` and `cancel`

**Files:**
- Modify: `src/auctionbot/core/rules.py`, `tests/test_rules.py`

**Interfaces:**
- Consumes: Task 3 module.
- Produces: `close_if_due(auction: Auction, now: float) -> tuple[Auction, bool]` (True only on the OPEN→CLOSED transition, when `status == OPEN and now >= ends_at`); `cancel(auction: Auction, actor_id: int, is_admin: bool, now: float) -> tuple[Auction, CancelResult]` per the planning call above.

- [ ] **Step 1: Write failing tests:** `close_if_due`: before `ends_at` → unchanged, False; at `ends_at` → CLOSED, True; already closed → False and unchanged (idempotent); cancelled → False; closing with bids keeps them and `winning_bid()` is the max bid; closing with no bids gives CLOSED and `winning_bid() is None`. `cancel`: seller cancels → `Cancelled`, status CANCELLED, bids retained; admin non-seller cancels → `Cancelled`; other user → `NOT_ALLOWED`, unchanged; closed auction → `NOT_OPEN` (even for a non-seller); `now >= ends_at` while OPEN → `NOT_OPEN`; after cancel, `place_bid` → `AUCTION_CLOSED`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement both. **Step 4:** Run; expect PASS. **Step 5: Commit** `feat(core): add close_if_due and cancel`.

---

### Task 5: Invariant checker and property tests

**Files:**
- Create: `src/auctionbot/sim/__init__.py`, `src/auctionbot/sim/invariants.py`, `tests/test_properties.py`

**Interfaces:**
- Consumes: `rules.place_bid`, `close_if_due`, `cancel`, models, results.
- Produces in `invariants.py` (all raise `AssertionError` with a descriptive message):
  - `check_bid_step(before: Auction, after: Auction, result: BidResult, bidder_id: int, amount: int, now: float) -> None`. Rejected → `after == before`. Accepted → `before.status is OPEN`, `now < before.ends_at`, `amount >= before.minimum_next_bid`, `after.high_bid == amount`, `after.ends_at >= before.ends_at`, `result.new_ends_at == after.ends_at`, `after.extensions_used <= after.config.max_extensions`, and `result.extended` iff `after.ends_at > before.ends_at`.
  - `check_auction(auction: Auction) -> None`: bid amounts strictly increasing; if CLOSED with bids, `winning_bid()` is the single maximum.

- [ ] **Step 1: Write the property tests** in `tests/test_properties.py`:
  - `test_invariants_hold_over_random_bid_sequences`: Hypothesis builds a config (increment 1–20, window 0–60, extension 0–60, max_extensions 0–5) and a list of `(dt >= 0, bidder_id in 1..6, amount in -5..300)` actions; seller is bidder 0; apply via `place_bid` with cumulative `now`, calling `check_bid_step` and `check_auction` after every step; finish with `close_if_due` at `ends_at` and check again.
  - `test_high_bid_and_ends_at_never_decrease` (explicit trajectory assertion, independent of the checker).
  - `AuctionMachine(RuleBasedStateMachine)` with rules `bid(bidder, amount)`, `advance(dt)`, `close()`, `cancel(actor, is_admin)`; invariants call `check_auction`; assert terminal statuses never revert to OPEN and no bid is accepted after CLOSED/CANCELLED. Expose via `TestAuctionMachine = AuctionMachine.TestCase`.
- [ ] **Step 2:** Run `pytest tests/test_properties.py -v`; expect FAIL (no `invariants`). **Step 3:** Implement `invariants.py`. **Step 4:** Run; expect PASS. If Hypothesis finds a counterexample, fix the rule (and add an example test to `test_rules.py`), not the checker, unless the checker is wrong.
- [ ] **Step 5: Commit** `test: add invariant checker and property-based tests`.

---

### Task 6: Simulator

**Files:**
- Create: `src/auctionbot/sim/strategies.py`, `src/auctionbot/sim/runner.py`, `tests/test_sim.py`

**Interfaces:**
- Consumes: `rules`, `FakeClock`, `invariants`.
- Produces in `strategies.py`: `BidIntent(at: float, amount: int)` (frozen); `class Strategy(Protocol)` with `bidder_id: int` and `plan(auction: Auction, now: float, rng: random.Random) -> BidIntent | None` (`None` = nothing more to do). Classes, each constructed with `bidder_id` (negative ints in tests): `Incrementer(ceiling: int)`, `Sniper(lead_s: float, ceiling: int)`, `BiddingWar(ceiling: int)` (use two instances with different ids), `Chaos()` (random amounts and times including `<= 0` and below-minimum), `Simultaneous(at: float, ceiling: int)` (all instances plan the same `at`).
- Produces in `runner.py`: `SimEvent(at: float, bidder_id: int, amount: int, result: BidResult)`; `SimResult(auction: Auction, events: tuple[SimEvent, ...])`; `run_simulation(auction: Auction, strategies: Sequence[Strategy], rng: random.Random, max_steps: int = 10_000) -> SimResult`.
- Runner semantics: loop: gather intents; the next event is the earliest `(at, bidder_id)` intent, unless `auction.ends_at` is not later than it (or there are none), in which case advance the `FakeClock` to `ends_at`, call `close_if_due`, and stop. Otherwise set the clock to the intent time (never earlier than now), call `place_bid`, call `check_bid_step` and `check_auction`, log the event. Exceeding `max_steps` raises `RuntimeError`. Same seed → identical `SimResult`.

- [ ] **Step 1: Write failing tests** in `tests/test_sim.py`: `test_same_seed_same_result` (run Chaos + Incrementer twice with `random.Random(42)`; results equal); `test_different_seed_can_differ`; `test_incrementer_pair_ends_closed_with_winner`; `test_sniper_bids_inside_final_seconds_and_extends` (Sniper `lead_s=5` against a 100s auction → deadline extended, sniper wins when ceiling highest); `test_bidding_war_terminates_within_cap` (two BiddingWar with high ceilings; `extensions_used <= max_extensions` and run finishes under `max_steps`); `test_chaos_never_violates_invariants` (20 seeds); `test_simultaneous_first_by_bidder_id_wins` (five bidders, same `at`, same amount: the lowest bidder id accepted, the rest `BELOW_MINIMUM`); `test_max_steps_guard_raises` (a strategy that always plans an immediate bid with a tiny increment ceiling of 10**12 and `max_steps=5`).
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement strategies, then runner. **Step 4:** Run; expect PASS. **Step 5: Commit** `feat(sim): add deterministic simulator and bidder strategies`.

---

### Task 7: Schema and repository

**Files:**
- Create: `src/auctionbot/storage/__init__.py`, `storage/schema.sql`, `storage/repository.py`, `tests/test_repository.py`

**Interfaces:**
- Consumes: `core` models; `aiosqlite`.
- Produces: `AuctionRef(guild_id: int, channel_id: int, message_id: int | None)` (frozen). `class Repository` with `@classmethod async def open(cls, path: str) -> Repository` (applies `schema.sql`, enables `PRAGMA foreign_keys=ON`, accepts `":memory:"`), `async def close()`. `@asynccontextmanager async def transaction(self) -> AsyncIterator[RepoTx]`: acquires the repository's single `asyncio.Lock`, runs `BEGIN IMMEDIATE`, commits on success and rolls back on exception, releases the lock. `RepoTx` methods (all `async`): `create(*, guild_id, channel_id, seller_id, title, description, starting_bid, config, ends_at) -> Auction`; `get(auction_id) -> Auction | None`; `get_ref(auction_id) -> AuctionRef | None`; `save(auction) -> None` (writes the auction row and inserts only the bids beyond those already stored, in order); `list_open(guild_id) -> list[Auction]`; `list_due(now) -> list[Auction]` (OPEN and `ends_at <= now`); `list_unannounced() -> list[Auction]` (CLOSED or CANCELLED with `closed_announced = 0`); `set_message_id(auction_id, message_id) -> None`; `mark_announced(auction_id) -> None`. `Repository` also exposes each of these as a direct method that opens its own short transaction.
- The `auctions` table is the spec's DDL plus `description TEXT NOT NULL DEFAULT ''`, `max_extensions INTEGER NOT NULL`, `extensions_used INTEGER NOT NULL DEFAULT 0`. `bids` and both indexes are as in the spec.

- [ ] **Step 1: Write failing tests** (`:memory:` repo fixture in the test file): `test_create_then_get_round_trips_all_fields` (including description, config, empty bids); `test_save_appends_only_new_bids` (save twice with one then two bids → exactly two rows, order kept); `test_get_missing_returns_none`; `test_list_open_filters_by_guild_and_status`; `test_list_due_boundary` (`ends_at == now` is due, `ends_at > now` is not, closed not due); `test_list_unannounced_and_mark_announced`; `test_set_message_id_and_get_ref`; `test_transaction_rolls_back_on_exception` (create inside a transaction that raises → nothing persisted); `test_transactions_do_not_interleave` (two coroutines each hold a transaction across an `await asyncio.sleep(0)`; no "transaction within a transaction" error and writes are applied in order).
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. Load `schema.sql` via `importlib.resources`; map rows to `Auction` with bids ordered by `id`. **Step 4:** Run; expect PASS. **Step 5: Commit** `feat(storage): add schema and repository with serialized transactions`.

---

### Task 8: `AuctionService`

**Files:**
- Create: `src/auctionbot/service.py`, `tests/test_service.py`

**Interfaces:**
- Consumes: `Repository`/`RepoTx`, `Clock`, `rules`.
- Produces: `class AuctionNotFound(Exception)`; `class AuctionService(repo: Repository, clock: Clock)` with:
  - `async create_auction(guild_id: int, channel_id: int, seller_id: int, title: str, starting_bid: int, duration_s: int, config: AuctionConfig = AuctionConfig(), description: str = "") -> Auction` — raises `ValueError` for blank/whitespace title, title > 256 chars, description > 1000 chars, `starting_bid` not in `1..MAX_AMOUNT`, `duration_s <= 0`, `config.min_increment < 1`. Title is stripped. `ends_at = clock.now() + duration_s`.
  - `async place_bid(auction_id: int, bidder_id: int, amount: int) -> BidResult` — per-auction `asyncio.Lock` (dict created lazily), then `repo.transaction()`: get → `rules.place_bid(..., now=clock.now())` → save only if accepted. Raises `AuctionNotFound`.
  - `async close_due() -> list[Auction]` — in one transaction: `list_due`, `close_if_due` each, `save`, return those that transitioned. Does not mark announced.
  - `async cancel(auction_id, actor_id, is_admin) -> CancelResult` — raises `AuctionNotFound`.
  - `async get(auction_id) -> Auction` (raises `AuctionNotFound`), `async list_open(guild_id) -> list[Auction]`, `async get_ref(auction_id) -> AuctionRef`, `async set_message_id(auction_id, message_id)`, `async list_unannounced() -> list[Auction]`, `async mark_announced(auction_id)`.

- [ ] **Step 1: Write failing tests** with a `FakeClock` and `:memory:` repo fixture: `test_create_sets_ends_at_from_clock`; `test_create_rejects_invalid_inputs` (parametrized over every ValueError case above, including a 257-char title and `starting_bid = MAX_AMOUNT + 1`); `test_create_strips_title`; `test_place_bid_accepted_persists` (reload via `get`); `test_rejected_bid_persists_nothing`; `test_huge_bid_rejected_not_crash` (`2**70` → `BidRejected(INVALID_AMOUNT)`); `test_place_bid_unknown_auction_raises` and `test_cancel_unknown_auction_raises`; `test_anti_snipe_extension_persists` (advance the clock into the window, bid, reload, check `ends_at` and `extensions_used`); `test_close_due_closes_only_expired` ; `test_close_due_is_idempotent` (second call returns `[]`); `test_cancel_then_bid_rejected_as_closed`; `test_cancelled_auction_appears_in_list_unannounced_not_list_open`; `test_mark_announced_removes_from_unannounced`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Run; expect PASS. **Step 5: Commit** `feat: add AuctionService`.

---

### Task 9: Concurrency and restart tests

**Files:**
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: Task 8 service; a file-backed repo via `tmp_path`.

- [ ] **Step 1: Write the tests** (they should pass against Task 8's implementation; if one fails, fix the service or repository and note the cause in the commit message):
  - `test_concurrent_bids_same_instant_exactly_one_winner`: 50 distinct bidders each bid the same amount via `asyncio.gather` at one fake instant; exactly one `BidAccepted`, 49 `BELOW_MINIMUM`, one stored bid.
  - `test_concurrent_distinct_amounts_no_lost_updates`: 30 bidders bid 11..40 (starting bid 10) concurrently; whatever order wins, stored bids are strictly increasing and the final high bid equals the maximum accepted amount from the results.
  - `test_concurrent_bids_on_different_auctions_do_not_block_or_corrupt`: two auctions, interleaved gathers, each ends with consistent state.
  - `test_restart_preserves_state`: file-backed DB; service A creates an auction and takes bids; discard A and close its repo; service B on the same path sees identical `Auction`; B accepts a further valid bid and rejects a below-minimum one.
  - `test_restart_close_due_closes_expired_while_offline`: A creates an auction, is discarded; the clock jumps past `ends_at`; B's `close_due()` returns it once, a second `close_due()` returns `[]`, and `list_unannounced()` has it until `mark_announced`.
- [ ] **Step 2:** Run `pytest -v` (the full suite); expect all PASS. **Step 3: Commit** `test(service): add concurrency and restart tests`.

---

## Self-review (done)

- **Spec coverage:** sections 3 (files; `config.py`, `bot/`, `__main__.py` deferred to milestones 4+), 4 (all rules, boundaries, invariants), 5 (schema plus the three added columns), 6 (all service methods), 8 (example, property, service, concurrency, restart), 9 (strategies and pure runner; `/simulate` deferred), 10 milestones 1–3 → Tasks 1–9.
- **Types:** `AuctionRef`, `RepoTx` methods, `CancelResult`, `MAX_AMOUNT`, and `extensions_used`/`max_extensions` are named identically wherever they appear.
- **Out of scope here:** Discord, `config.py`, scheduler, rendering, and the real-time `/simulate` command.
