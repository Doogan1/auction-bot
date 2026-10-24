CREATE TABLE IF NOT EXISTS auctions (
  id INTEGER PRIMARY KEY,
  guild_id INTEGER NOT NULL,
  channel_id INTEGER NOT NULL,
  message_id INTEGER,                -- the live auction message, set after posting
  seller_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  starting_bid INTEGER NOT NULL,
  min_increment INTEGER NOT NULL,
  anti_snipe_window_s INTEGER NOT NULL,
  extension_s INTEGER NOT NULL,
  max_extensions INTEGER NOT NULL,
  extensions_used INTEGER NOT NULL DEFAULT 0,
  ends_at REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open','closed','cancelled')),
  closed_announced INTEGER NOT NULL DEFAULT 0   -- guards against double announcements
);
CREATE TABLE IF NOT EXISTS bids (
  id INTEGER PRIMARY KEY,
  auction_id INTEGER NOT NULL REFERENCES auctions(id),
  bidder_id INTEGER NOT NULL,
  amount INTEGER NOT NULL,
  placed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bids_auction ON bids(auction_id, amount DESC);
CREATE INDEX IF NOT EXISTS idx_auctions_open_due ON auctions(status, ends_at);
