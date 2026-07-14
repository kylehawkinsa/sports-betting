# ERRORS.md — append-only

Wrong is logged, silent, and moved past. Entries below are appended by the
system (source failures, sanity-check suppressions, model input rejections)
and are never edited or removed. Pre-game numbers are never backfilled
after results are known.

---
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: odds_mlb (THE_ODDS_API_KEY not set)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: fangraphs_pitching (HTTPError: Error accessing 'https://www.fangraphs.com/leaders-legacy.aspx'. Received status code 403)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: park_factors (ParserError: Error tokenizing data. C error: Expected 1 fields in line 38, saw 4
)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: wx_12 (ConnectTimeout: _ssl.c:999: The handshake operation timed out)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: wx_4169 (ConnectTimeout: _ssl.c:999: The handshake operation timed out)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: wx_2394 (ConnectTimeout: _ssl.c:999: The handshake operation timed out)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: wx_2 (ConnectTimeout: _ssl.c:999: The handshake operation timed out)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: wx_5325 (ConnectTimeout: _ssl.c:999: The handshake operation timed out)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: wx_2602 (ConnectTimeout: _ssl.c:999: The handshake operation timed out)
- `2026-07-11T14:49:22Z` **daily run 2026-07-11** — source FAIL: odds_tennis (THE_ODDS_API_KEY not set)
- `2026-07-12T14:50:57Z` **daily run 2026-07-12** — source FAIL: odds_mlb (THE_ODDS_API_KEY not set)
- `2026-07-12T14:50:57Z` **daily run 2026-07-12** — source FAIL: fangraphs_pitching (HTTPError: Error accessing 'https://www.fangraphs.com/leaders-legacy.aspx'. Received status code 403)
- `2026-07-12T14:50:57Z` **daily run 2026-07-12** — source FAIL: park_factors (ParserError: Error tokenizing data. C error: Expected 1 fields in line 38, saw 4
)
- `2026-07-12T14:50:57Z` **daily run 2026-07-12** — source FAIL: odds_tennis (THE_ODDS_API_KEY not set)
- `2026-07-13T16:26:08Z` **daily run 2026-07-13** — source FAIL: odds_mlb (THE_ODDS_API_KEY not set)
- `2026-07-13T16:26:08Z` **daily run 2026-07-13** — source FAIL: odds_tennis (THE_ODDS_API_KEY not set)
- `2026-07-14T15:20:14Z` **daily run 2026-07-14** — source FAIL: odds_mlb (THE_ODDS_API_KEY not set)
- `2026-07-14T15:20:14Z` **daily run 2026-07-14** — source FAIL: fangraphs_pitching (HTTPError: Error accessing 'https://www.fangraphs.com/leaders-legacy.aspx'. Received status code 403)
- `2026-07-14T15:20:14Z` **daily run 2026-07-14** — source FAIL: park_factors (ParserError: Error tokenizing data. C error: Expected 1 fields in line 38, saw 4
)
- `2026-07-14T15:20:14Z` **daily run 2026-07-14** — source FAIL: odds_tennis (THE_ODDS_API_KEY not set)
