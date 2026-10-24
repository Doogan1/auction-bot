# Discord Layer (Milestones 4–8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the tested engine behind a Discord bot: slash commands, buttons and a bid modal, a closing scheduler with restart recovery, and an admin `/simulate` demo.

**Architecture:** `bot/` is a thin layer over `AuctionService`. Everything that can be decided without Discord (text rendering, input parsing, debouncing, the announce-once loop, the live simulation driver) is a pure or injectable function with unit tests. Code that touches Discord objects stays small and is verified by manual checkpoints against the real test server.

**Tech Stack:** discord.py 2.7.1 (installed; the APIs below were checked against it), `python-dotenv`, existing engine from `docs/superpowers/plans/2026-10-23-engine-milestones-1-3.md`.

**Spec:** `SPEC.md` sections 7, 8 (manual checklist), 9 (`/simulate`), 10 (milestones 4–8). Decisions are in "Decisions" below.

## Global Constraints

- Slash commands only; no prefix commands. Request `discord.Intents.default()` only; **never** enable `message_content` or other privileged intents.
- Import rules: `bot` imports `service` (and `core`/`storage` types); nothing imports `bot` except `__main__`. Never name a module `discord`.
- The token comes from the environment only; fail fast with a clear message if missing. Never print or log the token. `.env` is git-ignored and already holds `DISCORD_TOKEN`, `DEV_GUILD_ID=1563552966890491904`, `DB_PATH`.
- Sync commands to the dev guild only (`DEV_GUILD_ID`); global sync is out of scope.
- Rejections are ephemeral; accepted bids and deadline extensions are announced in-channel.
- Auction message edits are debounced to at most one per ~2 seconds per message.
- Every message the bot sends passes `allowed_mentions=discord.AllowedMentions.none()` (user-supplied titles must never ping anyone).
- Simulated bidders use negative ids and are always labeled `SimBidder-N (simulated)`.
- Verify discord.py behavior against the installed version (`help(...)`, `inspect`) before relying on memory. Keep dependencies as they are; ask before adding any.
- Run `pytest` before declaring a task done. Each commit message ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Decisions

Spec choices kept: single bot process, polling scheduler (`tasks.loop(seconds=2)`), buttons "Bid +{min_increment}" and "Custom bid".

Calls made while planning (mine):
- **Persistent buttons use `discord.ui.DynamicItem`** with a `custom_id` template `auction:bid:<id>` / `auction:custom:<id>`, registered once in `setup_hook` via `add_dynamic_items`. This replaces the spec's "re-attach a view per open auction on startup": every button, on any past message, works after a restart with no per-auction bookkeeping.
- **Announcements are at-least-once.** The scheduler marks an auction announced only after the post succeeds, so a crash in between can post twice on restart, but a winner is never silently lost. Permanent failures (message or channel deleted, missing permissions) are logged and marked announced so they are not retried forever.
- **One announcement path.** `/auction cancel` only cancels and acks the canceller ephemerally; the scheduler announces cancellations the same way it announces closes.
- **Startup recovery is the scheduler's first tick** (it runs right after login), so there is no separate recovery code.
- **Duration grammar:** one or more `<int><s|m|h|d>` parts, e.g. `90s`, `10m`, `1h30m`, `2d`; total between 10 seconds and 7 days. **Amount grammar:** digits only, up to 13 digits.
- `/auction start` options: `title`, `starting_bid`, `duration`, optional `min_increment` (default 1), optional `description`.
- `/simulate` is admin-only (`default_permissions` administrator plus a runtime check), runs one simulation per guild at a time, and uses a 30-second auction (`min_increment=5`, window 5s, extension 5s, `max_extensions=3`), the invoker as seller, and `Incrementer`, `Incrementer`, `Sniper`, `Chaos` bidders (no `BiddingWar`, to stay clear of rate limits). Only accepted simulated bids are announced.

## Review Focus

Failure modes the spec implies but never states; each is pinned in the named task.

1. Garbage in the bid modal or `/bid` amount (`""`, `abc`, `1e5`, `10.5`, `-3`, 30 digits) must produce a friendly ephemeral error, never a traceback. → Task 3, Task 7
2. Garbage durations (`0`, `-5m`, `abc`, `99999d`, `5` with no unit) must be refused with a clear message. → Task 3
3. A title like `@everyone` or `<@123>` must not ping anyone. → Tasks 3, 5, 6
4. Announcing into a deleted channel/message or without permissions must not kill the scheduler or retry forever; a transient error must retry. → Task 6
5. Clicking a stale button (auction closed, cancelled, or unknown) or an unexpected exception in any handler must answer the user ephemerally. → Tasks 2, 7

---

### Task 1: Settings loader and entrypoint config (milestone 4)

**Files:**
- Create: `src/auctionbot/config.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `class ConfigError(Exception)`; `@dataclass(frozen=True) class Settings: token: str; dev_guild_id: int | None; db_path: str`; `load_settings(env: Mapping[str, str]) -> Settings`.

- [ ] **Step 1: Write failing tests** in `tests/test_config.py`: `test_loads_all_values` (token `"t"`, guild `"123"`, db `"x.db"` → `Settings("t", 123, "x.db")`); `test_db_path_defaults_to_auctions_db`; `test_blank_dev_guild_is_none`; `test_missing_token_raises_with_hint` (`ConfigError`, message contains `DISCORD_TOKEN` and `.env`); `test_blank_token_raises`; `test_non_integer_guild_raises_config_error`; `test_error_message_never_contains_token` (bad guild id with token `"SECRET"` → `"SECRET"` not in `str(err)`).
- [ ] **Step 2:** Run `pytest tests/test_config.py -v`; expect FAIL (no module).
- [ ] **Step 3:** Implement per Interfaces in `config.py`. Run; expect PASS.
- [ ] **Step 4: Commit** `feat: add settings loader`.

---

### Task 2: Bot skeleton, `/ping`, error handler, entrypoint (milestone 4)

**Files:**
- Create: `src/auctionbot/bot/__init__.py`, `bot/client.py`, `bot/commands.py`, `src/auctionbot/__main__.py`, `tests/test_bot_skeleton.py`

**Interfaces:**
- Consumes: `Settings`, `AuctionService`, `Repository`, `SystemClock`.
- Produces in `client.py`: `build_intents() -> discord.Intents` (`Intents.default()`, nothing privileged); `class AuctionBot(discord.Client)` with `__init__(self, settings: Settings, service: AuctionService)`, attributes `settings`, `service`, `tree: app_commands.CommandTree`; `async setup_hook()` calls `commands.register(self)`, then syncs to the dev guild (`tree.copy_global_to(guild=discord.Object(id))` then `await tree.sync(guild=...)`; with no dev guild, it logs a warning and does not sync). The tree's `on_error` sends an ephemeral "Something went wrong" (via `response.send_message` or `followup.send` depending on `response.is_done()`) and logs the exception with traceback.
- Produces in `commands.py`: `register(bot: AuctionBot) -> None` adding `/ping` (replies `Pong! {latency_ms}ms`, ephemeral).
- `__main__.py`: `load_dotenv()`, `load_settings(os.environ)` (print the `ConfigError` message and exit with status 1), open `Repository`, build `AuctionService(repo, SystemClock())`, `AuctionBot(...).run(settings.token)`, close the repo on shutdown, `logging.basicConfig(level=INFO)`.

- [ ] **Step 1: Write failing tests:** `test_intents_have_no_privileged_flags` (`message_content`, `members`, `presences` all false); `test_ping_command_registered_after_register` (build `AuctionBot` with a stub service, call `register`, assert `bot.tree.get_command("ping")` is not None); `test_package_main_fails_fast_without_token` (run `python -m auctionbot` in a subprocess with `DISCORD_TOKEN` unset and `cwd=tmp_path` so no `.env` is found: exit code 1, stderr or stdout mentions `DISCORD_TOKEN`).
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Run `pytest -q`; expect PASS.
- [ ] **Step 5: Manual checkpoint (ask the user to do the Discord part).** Run `.venv/bin/python -m auctionbot` in the background and watch its log for the login line. Ask the user to open their test server in the browser, type `/ping`, and report the reply. Expected: the bot shows online and `/ping` replies `Pong!`. If `/ping` is missing from the picker, check the dev-guild sync log line and the invite scopes (`applications.commands`). Stop the bot afterwards.
- [ ] **Step 6: Commit** `feat(bot): add skeleton, /ping, error handler and entrypoint`.

---

### Task 3: Pure rendering and parsing (milestone 5)

**Files:**
- Create: `src/auctionbot/bot/render.py`, `src/auctionbot/bot/parsing.py`, `tests/test_render.py`, `tests/test_parsing.py`

**Interfaces:**
- Consumes: `Auction`, `Status`, `Bid`, `RejectReason`, `CancelRejectReason`.
- Produces in `parsing.py`: `parse_duration(text: str) -> int` and `parse_amount(text: str) -> int`, both raising `ValueError` with a message safe to show the user (per the grammars in Decisions).
- Produces in `render.py`:
  - `bidder_label(bidder_id: int) -> str`: `<@id>` for ids `>= 0`, `SimBidder-N (simulated)` for negative ids.
  - `format_amount(n: int) -> str` (thousands separators).
  - `auction_embed(auction: Auction) -> discord.Embed`: title is the auction title; OPEN shows high bid and bidder (or "No bids yet"), minimum next bid, deadline as `<t:{int(ends_at)}:R>`; CLOSED shows winner and winning amount or "No bids"; CANCELLED says cancelled. Footer `Auction #{id}`.
  - `reject_message(reason: RejectReason, auction: Auction) -> str`; `cancel_reject_message(reason: CancelRejectReason) -> str`.
  - `bid_announcement(auction: Auction, bidder_id: int, amount: int, extended: bool, window_s: int) -> str`; when `extended`, a second line `Bid landed in the final {window_s} seconds. Deadline extended.`
  - `closed_announcement(auction: Auction) -> str`; `cancelled_announcement(auction: Auction) -> str`.
  - `auction_choice_label(auction: Auction) -> str`: `#{id} {title} - {high bid or starting bid}`, truncated to at most 100 characters.

- [ ] **Step 1: Write failing tests.** `test_parsing.py`: `parse_duration` accepts `"90s"→90`, `"10m"→600`, `"1h30m"→5400`, `"2d"→172800`, `" 5m "→300`; rejects (parametrized) `""`, `"0"`, `"5"`, `"-5m"`, `"abc"`, `"9s"`, `"8d"`, `"99999d"`, `"1.5h"`, `"5m5"`. `parse_amount` accepts `"15"→15`, `" 15 "→15`; rejects `""`, `"abc"`, `"1e5"`, `"10.5"`, `"-3"`, `"0"`, `"1" * 14`. Every `ValueError` message is non-empty. `test_render.py`: `bidder_label(5) == "<@5>"`, `bidder_label(-3) == "SimBidder-3 (simulated)"`; `format_amount(1234567) == "1,234,567"`; embed contains `<t:1000:R>` for `ends_at=1000.0`; embed for an auction with bids shows the high bid and bidder; embed for no bids contains "No bids yet"; closed embed names the winner; `bid_announcement(..., extended=True, window_s=30)` contains `Bid landed in the final 30 seconds. Deadline extended.`; `extended=False` does not; every `RejectReason` and `CancelRejectReason` has a non-empty message; a title of 300 characters yields `auction_choice_label` of length `<= 100`; a title `"@everyone"` appears only inside the text and no function builds a mention (assert the announcement strings contain no `@` besides the `<@id>` form).
- [ ] **Step 2:** Run both files; expect FAIL. **Step 3:** Implement. **Step 4:** Run; expect PASS. **Step 5: Commit** `feat(bot): add rendering and input parsing`.

---

### Task 4: Debounced message refresher (milestone 7, needed by Task 5)

**Files:**
- Create: `src/auctionbot/bot/refresher.py`, `tests/test_refresher.py`

**Interfaces:**
- Consumes: `Clock` (`auctionbot.clock`).
- Produces: `class MessageRefresher` with `__init__(self, edit: Callable[[int], Awaitable[None]], clock: Clock, min_interval: float = 2.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep)`; `request(self, auction_id: int) -> None` (synchronous, safe to call from handlers); `async aclose(self) -> None` (cancels pending trailing edits). Semantics per auction id: if at least `min_interval` has passed since its last edit, edit immediately (scheduled as a task); otherwise schedule exactly one trailing edit at `last_edit + min_interval`; further requests while one is pending are coalesced. Exceptions from `edit` are logged and never raised or fatal to later edits.

- [ ] **Step 1: Write failing tests** using `FakeClock` and a `sleep` that advances the clock (`clock.advance(s); await asyncio.sleep(0)`), and a recording `edit`: `test_first_request_edits_immediately`; `test_burst_of_ten_requests_coalesces_to_one_leading_and_one_trailing_edit`; `test_trailing_edit_happens_min_interval_after_leading`; `test_requests_for_different_auctions_are_independent`; `test_edit_error_is_swallowed_and_next_edit_still_runs`; `test_aclose_cancels_pending_trailing_edit`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement (one dict of last-edit time and one of pending tasks, keyed by auction id). **Step 4:** Run; expect PASS. **Step 5: Commit** `feat(bot): add debounced message refresher`.

---

### Task 5: Shared bid action and the commands (milestone 5)

**Files:**
- Modify: `src/auctionbot/bot/client.py`, `src/auctionbot/bot/commands.py`
- Create: `src/auctionbot/bot/actions.py`, `tests/test_commands.py`

**Interfaces:**
- Consumes: `render`, `parsing`, `MessageRefresher`, `AuctionService`, `AuctionNotFound`.
- Produces on `AuctionBot` (client.py): `refresher: MessageRefresher` (created in `setup_hook`, `edit=self.refresh_message`, `SystemClock`); `async refresh_message(self, auction_id: int) -> None` (loads the auction and its `AuctionRef`, edits the original message via `get_partial_messageable(channel_id).get_partial_message(message_id).edit(embed=auction_embed(a), view=<view from Task 7, or None until then>, allowed_mentions=none)`; a missing `message_id` is a no-op); `async close()` override that awaits `refresher.aclose()`.
- Produces in `actions.py`: `async perform_bid(interaction: discord.Interaction, auction_id: int, amount: int) -> None`: calls `service.place_bid(auction_id, interaction.user.id, amount)`; `AuctionNotFound` → ephemeral "That auction no longer exists."; `BidRejected` → ephemeral `reject_message`; `BidAccepted` → public `bid_announcement` (after fetching the updated auction) and `refresher.request(auction_id)`. All sends use `allowed_mentions=none`.
- Produces in `commands.py` (all `guild_only`): group `/auction` with `start(title, starting_bid, duration, min_increment=1, description="")` (parse duration, build `AuctionConfig(min_increment=...)`, `service.create_auction`, send the embed, fetch `interaction.original_response()`, `service.set_message_id`; `ValueError` from parsing or the service → ephemeral message with the error text), `status(auction: int | None)` (defaults to the most recent open auction in the channel's guild; ephemeral embed), `list()` (ephemeral list of open auctions in the guild via `auction_choice_label`), `cancel(auction: int)` (`is_admin = interaction.user.guild_permissions.administrator`; ephemeral result; the scheduler announces); and top-level `/bid(auction: int, amount: str)` (amount parsed with `parse_amount`, then `perform_bid`). `auction` parameters on `status`, `cancel` and `bid` autocomplete from `service.list_open(guild_id)` using `autocomplete_choices`.
- Also produce in `commands.py`: `autocomplete_choices(auctions: Sequence[Auction], current: str) -> list[app_commands.Choice[int]]`: at most 25 choices, name `auction_choice_label`, value the auction id, filtered by case-insensitive substring of `current` against title or `#id`.

- [ ] **Step 1: Write failing tests** in `tests/test_commands.py`: `test_autocomplete_filters_by_title_and_id`, `test_autocomplete_caps_at_25_and_names_at_100_chars`, `test_register_adds_auction_group_with_start_status_list_cancel`, `test_register_adds_bid_command`, `test_commands_are_guild_only` (each top-level command/group `guild_only` is true). Interaction handlers themselves are exercised by the manual checkpoint.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Run `pytest -q`; expect PASS.
- [ ] **Step 5: Manual checkpoint.** Run the bot; ask the user to: run `/auction start` with a 3-minute duration; `/bid` below the minimum (expect an ephemeral rejection); `/bid` a valid amount (expect a public announcement and the embed updating within ~2s); try `/bid` as the seller account if available (expect rejection); `/auction list`, `/auction status`; start a titled `@everyone` auction (expect no ping). Record what happened; fix any failures before committing.
- [ ] **Step 6: Commit** `feat(bot): add auction and bid commands`.

---

### Task 6: Announcer, scheduler, and restart recovery (milestone 6)

**Files:**
- Create: `src/auctionbot/bot/scheduler.py`, `tests/test_scheduler.py`
- Modify: `src/auctionbot/bot/client.py`

**Interfaces:**
- Consumes: `AuctionService.close_due`, `list_unannounced`, `get_ref`, `mark_announced`; `render.closed_announcement`, `cancelled_announcement`, `auction_embed`.
- Produces in `scheduler.py`: `class Unannounceable(Exception)` (a permanent failure); `class Announcer(Protocol)` with `async announce(self, auction: Auction, ref: AuctionRef) -> None`; `async announce_pending(service: AuctionService, announcer: Announcer) -> int` (returns how many were announced): for each auction from `list_unannounced()`: call `announce`; on success `mark_announced`; on `Unannounceable` log a warning and `mark_announced`; on any other exception log it and leave the auction unannounced for the next tick (and continue with the others); `async tick(service, announcer) -> None` = `close_due()` then `announce_pending`.
- Produces in `client.py`: `class DiscordAnnouncer` implementing `Announcer`: edits the auction message to the final embed with disabled buttons (the view from Task 7, or `view=None` until then), then posts `closed_announcement`/`cancelled_announcement` to the channel as a reply when `message_id` is known; `discord.NotFound` and `discord.Forbidden` → `Unannounceable`; other `discord.HTTPException` propagate (retry). `AuctionBot` owns a `tasks.loop(seconds=2)` that awaits `wait_until_ready()` in `before_loop`, runs `tick` inside `try/except Exception` that logs and continues, and is started in `setup_hook`; `close()` cancels it.

- [ ] **Step 1: Write failing tests** with a real in-memory service plus `FakeClock` and a recording fake announcer: `test_closed_auction_announced_once`; `test_second_tick_does_not_reannounce`; `test_cancelled_auction_is_announced`; `test_unannounceable_marks_announced_and_continues_with_others`; `test_transient_error_leaves_unannounced_and_retries_next_tick` (fake raises once, then succeeds; first tick count 0, second count 1); `test_one_failing_auction_does_not_block_the_next`; `test_auction_closed_while_offline_is_announced_on_first_tick` (create, advance clock past `ends_at`, new service on the same file DB, `tick` announces it); `test_open_auctions_untouched`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. **Step 4:** Run `pytest -q`; expect PASS.
- [ ] **Step 5: Manual checkpoint.** Ask the user to start a `30s` auction, bid, and let it expire: expect the message edited with the winner and a closing post. Then: start another 60-second auction, stop the bot, wait past the deadline, restart the bot: expect it to be closed and announced on startup. Also cancel an auction with `/auction cancel` and expect one cancellation announcement. Record results.
- [ ] **Step 6: Commit** `feat(bot): add scheduler with announce-once recovery`.

---

### Task 7: Buttons and the custom-bid modal (milestone 7)

**Files:**
- Create: `src/auctionbot/bot/views.py`, `tests/test_views.py`
- Modify: `src/auctionbot/bot/client.py`, `src/auctionbot/bot/commands.py`

**Interfaces:**
- Consumes: `perform_bid`, `parse_amount`, `AuctionBot`.
- Produces in `views.py`: `class BidButton(discord.ui.DynamicItem[discord.ui.Button], template=r"auction:bid:(?P<id>[0-9]+)")` with `__init__(self, auction_id: int, min_increment: int = 1, disabled: bool = False)` (label `Bid +{min_increment}`; `custom_id` `auction:bid:{auction_id}`), classmethod `from_custom_id(cls, interaction, item, match)`, and a callback that loads the auction via `interaction.client.service.get`, answers ephemerally if it is no longer open (or not found), and otherwise calls `perform_bid(interaction, id, auction.minimum_next_bid)`; `class CustomBidButton(discord.ui.DynamicItem[discord.ui.Button], template=r"auction:custom:(?P<id>[0-9]+)")` (label `Custom bid`) whose callback sends `BidModal(auction_id)`; `class BidModal(discord.ui.Modal)` with a single `TextInput` labeled `Amount`; `on_submit` parses with `parse_amount` (a `ValueError` is answered ephemerally with its message) then calls `perform_bid`; `auction_view(auction: Auction, *, disabled: bool = False) -> discord.ui.View` (`timeout=None`, containing both buttons; `disabled` forced true when the auction is not OPEN).
- `client.py`: `setup_hook` calls `self.add_dynamic_items(BidButton, CustomBidButton)`; `refresh_message` and `DiscordAnnouncer` use `auction_view`. `commands.py`: `/auction start` and `/simulate` (Task 8) post with `view=auction_view(auction)`.

- [ ] **Step 1:** Before writing code, read `help(discord.ui.DynamicItem)` in the venv and confirm the `template`/`from_custom_id` signature; if it differs from this plan, rule on the smallest change and ledger it.
- [ ] **Step 2: Write failing tests:** `test_custom_ids_encode_auction_id`; `test_bid_button_template_matches_only_its_custom_id` (`BidButton.__discord_ui_compiled_template__` or the regex used, matches `auction:bid:42` with `id == "42"`, not `auction:custom:42`); `test_custom_bid_button_template_matches_its_custom_id`; `test_auction_view_has_two_items_enabled_for_open_auction`; `test_auction_view_disabled_when_closed_or_cancelled`; `test_button_label_shows_min_increment`; `test_view_has_no_timeout`.
- [ ] **Step 3:** Run; expect FAIL. **Step 4:** Implement. **Step 5:** Run `pytest -q`; expect PASS.
- [ ] **Step 6: Manual checkpoint.** Start an auction; ask the user to click **Bid +N** (expect the announcement and embed update), click **Custom bid** and submit `abc` (expect an ephemeral error), then a valid amount; stop and restart the bot and click the buttons on the old message (expect them to still work); click a button on an expired auction's message (expect an ephemeral "closed" answer, and the buttons shown disabled). Record results.
- [ ] **Step 7: Commit** `feat(bot): add persistent bid buttons and custom-bid modal`.

---

### Task 8: Live simulation driver and `/simulate` (milestone 8)

**Files:**
- Create: `src/auctionbot/sim/live.py`, `tests/test_sim_live.py`
- Modify: `src/auctionbot/bot/commands.py`

**Interfaces:**
- Consumes: strategies from `sim/strategies.py`, `AuctionService`, `Clock`.
- Produces in `live.py`: `async def run_live(service: AuctionService, auction_id: int, strategies: Sequence[Strategy], rng: random.Random, clock: Clock, on_accepted: Callable[[Auction, int, int, BidAccepted], Awaitable[None]], sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, max_steps: int = 1000) -> None`. Loop: fetch the auction; stop if not OPEN; ask every strategy to `plan` against the live auction and `clock.now()`; stop if none, or if the earliest intent is at or past `ends_at` (the scheduler closes it); `await sleep(max(0, at - now))`; place all intents at that instant via `service.place_bid` in ascending bidder id; call `on_accepted(auction_after, bidder_id, amount, result)` for each `BidAccepted`; raise `RuntimeError` past `max_steps`.
- `/simulate` in `commands.py` (admin-only, `guild_only`) per Decisions: create the auction (seller = invoker), post it with the view, set the message id, start `run_live` as a task kept in a bot-level set (strong reference), announce accepted bids with `bid_announcement` using `bidder_label` and call `refresher.request`; a second `/simulate` in the same guild while one runs is refused ephemerally; the task's exception is logged.

- [ ] **Step 1: Write failing tests** with a real in-memory service, `FakeClock`, and a `sleep` that advances the clock: `test_run_live_places_only_negative_id_bids`; `test_run_live_stops_at_deadline_and_leaves_closing_to_scheduler` (status still OPEN until `service.close_due()` is called, then CLOSED); `test_run_live_stops_when_auction_is_cancelled`; `test_on_accepted_called_once_per_accepted_bid_in_order`; `test_run_live_is_deterministic_for_a_seed` (two runs, same seed, same stored bids); `test_max_steps_guard_raises`; `test_rejected_chaos_bids_are_not_reported`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement `live.py`, then wire `/simulate` (also add `test_simulate_command_is_admin_only_and_guild_only` to `tests/test_commands.py`: `default_permissions.administrator` true). **Step 4:** Run `pytest -q`; expect PASS.
- [ ] **Step 5: Manual checkpoint.** Ask the user to run `/simulate`: expect a 30-second auction, public announcements for each accepted bid labeled `SimBidder-N (simulated)`, the embed updating at most about every 2 seconds, anti-snipe callouts if a bid lands late, and the winner announced at the end. A second `/simulate` mid-run must be refused. Record results.
- [ ] **Step 6: Commit** `feat: add live simulation and /simulate command`.

---

### Task 9: README and final manual checklist (milestone 8)

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** Write the README: what the bot does; setup (Python 3.12+, venv and `pip install -e ".[dev]"`, Developer Portal steps from creating the application through the invite URL with scopes `bot` + `applications.commands` and permissions View Channels / Send Messages / Embed Links / Read Message History, no privileged intents, copying `.env.example` to `.env`, getting the guild id with Developer Mode); run (`python -m auctionbot`); command reference; how to run tests; where the design lives (`SPEC.md`, `docs/superpowers/`). No token or ids in the README.
- [ ] **Step 2:** Walk the spec section 8 manual checklist with the user: two accounts bidding at once; buttons after restart; auction expiring while the bot is down; no rate-limit errors in the log during a `/simulate` run; cancel permissions (non-seller refused, admin allowed); bot lacking channel permissions (ask the user to deny Send Messages for the bot in one channel, start an auction there, and confirm the bot logs the failure and keeps running). Record which items were verified and which were not.
- [ ] **Step 3:** Run `pytest -q`; expect all tests pass. **Step 4: Commit** `docs: add README and record manual verification`.

---

## Self-review (done)

- **Spec coverage:** section 7 commands (`/auction start|status|list|cancel`, `/bid`, `/simulate`), embed, buttons, modal, debounce, ephemeral rejections, extension callouts, scheduler, recovery, persistent buttons, dev-guild sync, intents → Tasks 2–8; section 8 manual checklist → Task 9; section 9 `/simulate` labeling and negative ids → Task 8; section 10 milestones 4–8 → Tasks 1–9.
- **Deviations from spec:** `DynamicItem` instead of per-auction view re-attachment; at-least-once announcements; startup recovery is the first scheduler tick. All are listed under Decisions.
- **Types:** `AuctionRef`, `AuctionService` methods, `MessageRefresher.request`, `auction_view`, `perform_bid` and `Unannounceable` are named identically wherever used.
- **Known limit:** interaction handlers cannot be unit-tested without Discord, so correctness there rests on the manual checkpoints; everything decidable without Discord is covered by unit tests.
