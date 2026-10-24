# auction-bot

A Discord bot that runs timed auctions inside a server. Members bid with slash commands or
buttons, the bot tracks the high bid, and the deadline extends when someone bids near the
end (anti-sniping). Auctions survive bot restarts.

Bids are honor-system numbers: no real money, no balances. The auction logic is pure Python
that can be tested and simulated without Discord (see `SPEC.md` for the design).

## Setup

You need Python 3.12+ and a Discord account.

1. **Install**

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e ".[dev]"
   ```

2. **Make a test server.** In Discord, click **+** (Add a Server), then *Create My Own*.
3. **Enable Developer Mode** (User Settings > Advanced), then right-click your server icon and
   choose *Copy Server ID*.
4. **Create the application** at <https://discord.com/developers/applications> (*New Application*).
5. **Get the bot token.** Open the *Bot* tab and click *Reset Token*. Copy it; Discord shows it
   once. Leave all three *Privileged Gateway Intents* off, because slash commands do not need them.
6. **Invite the bot.** Open *OAuth2 > URL Generator*. Tick the scopes `bot` and
   `applications.commands`, and the permissions *View Channels*, *Send Messages*,
   *Embed Links* and *Read Message History*. Open the generated URL and add the bot to your server.
7. **Configure.** Copy `.env.example` to `.env` and fill it in:

   ```
   DISCORD_TOKEN=<token from step 5>
   DEV_GUILD_ID=<server id from step 3>
   DB_PATH=auctions.db
   ```

   `.env` is git-ignored. Never commit the token, and reset it in the portal if it leaks.

## Run

```bash
.venv/bin/python -m auctionbot
```

Commands are synced to the server in `DEV_GUILD_ID` on startup (global sync is slow, so this
project only syncs to the dev server). If `DISCORD_TOKEN` is missing the bot exits with a
message saying so.

## Commands

| Command | What it does |
|---|---|
| `/auction start title starting_bid duration [min_increment] [description]` | Posts an auction in the current channel. `duration` looks like `90s`, `10m`, `1h30m`, `2d` (10 seconds to 7 days). |
| `/bid auction amount` | Place a bid. `auction` autocompletes from open auctions. |
| `/auction status [auction]` | Show an auction (default: the newest open one). Only you see the reply. |
| `/auction list` | List open auctions in the server. |
| `/auction cancel auction` | Cancel an auction. Seller or server admin only. |
| `/simulate` | Admin only. Runs a 30-second demo auction with simulated bidders, clearly labeled `SimBidder-N (simulated)`. |
| `/ping` | Check the bot is alive. |

Each auction message has **Bid +N** and **Custom bid** buttons. They keep working after a
bot restart. A bid in the last 30 seconds extends the deadline (up to 10 times). The bot
closes auctions on a 2-second timer and announces the result; auctions that ended while the
bot was offline are closed and announced on the next start.

## Tests

```bash
.venv/bin/pytest
```

The tests cover the rules (example-based and property-based), the simulator, storage and
service (including concurrency and restart), and the Discord-free parts of the bot layer.
Anything that needs real Discord (permissions, rate limits, button clicks) is checked by hand.

## Layout

```
src/auctionbot/
  core/      pure auction rules (stdlib only)
  storage/   SQLite repository
  service.py AuctionService: the only thing the bot calls
  sim/       deterministic simulator and bidder strategies
  bot/       discord.py layer: commands, buttons, rendering, scheduler
```

Design: `SPEC.md`. Plans: `docs/superpowers/plans/`.

## Manual verification (milestone 8 checklist)

Checked by hand against a real Discord test server on 2026-10-24:

| Item | Result |
|---|---|
| Buttons and the custom-bid modal work | Verified |
| Buttons still work after a bot restart | Verified (old message, after restart) |
| Auction that expires while the bot is down is closed and announced on startup | Verified |
| Cancel announces exactly once | Verified |
| Non-seller cannot cancel | Verified (second account refused) |
| Seller can cancel | Verified |
| `/simulate` runs and finishes | Verified; no unexpected errors in the log |
| No rate-limit trouble during `/simulate` | Verified: zero rate-limit messages in the log |
| Bot lacking Send Messages in a channel | Verified: failures are logged (`403 Missing Permissions`), the auction is marked announced instead of retried forever, and the bot keeps running. Slash command replies still appear, because interaction replies do not need Send Messages. |
| Admin who is not the seller can cancel | Not verified by hand |
| Two accounts bidding at the same instant | Not verified by hand; covered by the automated concurrency tests |
