"""
Persistent Stats Store  —  SQLite backend
Replaces the flat JSON file with a proper relational database.
Database lives at data/instabot.db  (single file, zero config).

PUBLIC API  (identical to the old JSON version — bot_engine.py and cli.py
             need zero changes):

    record_action(username, action_type, count=1)
    record_snapshot(username, followers, following, media_count)
    get_account_history(username)       -> dict
    get_all_accounts_summary()          -> list
    get_daily_series(username, days=14) -> list
    get_follower_growth(username)       -> list

EXTRA QUERY HELPERS  (new — not possible with the old JSON file):

    query(sql, params)                              -> list[dict]
    get_all_usernames()                             -> list[str]
    get_best_days(username, n=5)                    -> list
    get_action_totals_by_week(username, weeks=8)    -> list
    search_actions(username, action_type, from_date, to_date, limit) -> list
    get_follow_back_rate(username)                  -> dict

SCHEMA
──────
  accounts   — one row per Instagram account
  actions    — append-only event log (one row per recorded action)
  snapshots  — follower/following/media_count over time

Migrating from the old JSON file
──────────────────────────────────
  If data/stats.json still exists, call migrate_from_json() once to
  import all historical data, then delete the JSON file.

Swapping to PostgreSQL later
─────────────────────────────
  1. Replace _get_conn() with a psycopg2 / asyncpg connection pool.
  2. Change INTEGER PRIMARY KEY AUTOINCREMENT  →  SERIAL PRIMARY KEY.
  3. Change ON CONFLICT ... DO NOTHING / DO UPDATE  →  same syntax (PG supports it).
  4. Change ? placeholders  →  %s.
  5. Everything else — schema, queries, public API — stays identical.
"""

import sqlite3
import threading
import json
from contextlib import contextmanager
from pathlib    import Path
from datetime   import datetime, date, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

DATA_DIR = Path("data")
DB_PATH  = DATA_DIR / "instabot.db"

ACTION_KEYS = ["likes", "comments", "follows", "unfollows", "dms", "story_views"]

# One connection per thread — SQLite connections must not be shared across threads
_local = threading.local()


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION & SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    """
    Return a thread-local SQLite connection.
    Creates the database file and schema on very first call.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        DATA_DIR.mkdir(exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row           # rows behave like dicts
        conn.execute("PRAGMA journal_mode=WAL")  # safe concurrent writes
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL") # good balance of speed/safety
        _create_schema(conn)
        _local.conn = conn
    return _local.conn


@contextmanager
def _tx():
    """Yield a cursor inside a committed transaction. Rolls back on error."""
    conn = _get_conn()
    cur  = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def _create_schema(conn: sqlite3.Connection):
    """Create all tables and indexes if they don't exist yet."""
    conn.executescript("""
        -- ── ACCOUNTS ──────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS accounts (
            username    TEXT PRIMARY KEY,
            first_seen  TEXT NOT NULL,
            last_active TEXT NOT NULL,
            proxy       TEXT
        );

        -- ── ACTIONS  (append-only event log) ──────────────────────────────
        -- Never updated, only inserted. One row per recorded action.
        -- action_type: likes | comments | follows | unfollows | dms | story_views
        CREATE TABLE IF NOT EXISTS actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    NOT NULL,
            action_type TEXT    NOT NULL,
            count       INTEGER NOT NULL DEFAULT 1,
            ts          TEXT    NOT NULL,    -- full ISO-8601 timestamp
            date        TEXT    NOT NULL     -- YYYY-MM-DD  for fast daily GROUP BY
        );

        -- ── SNAPSHOTS  (follower count over time) ─────────────────────────
        CREATE TABLE IF NOT EXISTS snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    NOT NULL,
            ts          TEXT    NOT NULL,
            followers   INTEGER,
            following   INTEGER,
            media_count INTEGER
        );

        -- ── POSTS  (publish history) ──────────────────────────────────────
        -- One row per published post/story. post_type: photo | carousel | story_photo | story_video
        CREATE TABLE IF NOT EXISTS posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    NOT NULL,
            post_type   TEXT    NOT NULL,
            caption     TEXT    NOT NULL DEFAULT '',
            location    TEXT    NOT NULL DEFAULT '',
            media_pk    TEXT    NOT NULL DEFAULT '',
            has_music   INTEGER NOT NULL DEFAULT 0,
            ts          TEXT    NOT NULL,
            date        TEXT    NOT NULL
        );

        -- ── INDEXES ───────────────────────────────────────────────────────
        CREATE INDEX IF NOT EXISTS idx_actions_username      ON actions(username);
        CREATE INDEX IF NOT EXISTS idx_actions_date          ON actions(date);
        CREATE INDEX IF NOT EXISTS idx_actions_username_date ON actions(username, date);
        CREATE INDEX IF NOT EXISTS idx_actions_type          ON actions(username, action_type);
        CREATE INDEX IF NOT EXISTS idx_snapshots_username    ON snapshots(username);
        CREATE INDEX IF NOT EXISTS idx_snapshots_ts          ON snapshots(username, ts);
        CREATE INDEX IF NOT EXISTS idx_posts_username        ON posts(username);
        CREATE INDEX IF NOT EXISTS idx_posts_date            ON posts(username, date);
    """)
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _empty_counters() -> dict:
    return {k: 0 for k in ACTION_KEYS}


def _ensure_account(cur: sqlite3.Cursor, username: str):
    """Insert account row if it doesn't exist yet. No-op if it does."""
    now = datetime.now().isoformat(timespec="seconds")
    cur.execute("""
        INSERT INTO accounts (username, first_seen, last_active)
        VALUES (?, ?, ?)
        ON CONFLICT(username) DO NOTHING
    """, (username, now, now))


def _touch_account(cur: sqlite3.Cursor, username: str):
    """Stamp last_active with the current time."""
    now = datetime.now().isoformat(timespec="seconds")
    cur.execute(
        "UPDATE accounts SET last_active = ? WHERE username = ?",
        (now, username)
    )


def _rows_to_dicts(rows) -> list:
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API  —  drop-in replacement for the old JSON version
# ─────────────────────────────────────────────────────────────────────────────

def record_action(username: str, action_type: str, count: int = 1):
    """
    Record one or more successful actions to the database.
    Thread-safe — WAL mode allows concurrent writers from bot threads.
    """
    if action_type not in ACTION_KEYS:
        return

    now = datetime.now().isoformat(timespec="seconds")
    day = date.today().isoformat()

    with _tx() as cur:
        _ensure_account(cur, username)
        cur.execute(
            "INSERT INTO actions (username, action_type, count, ts, date) VALUES (?, ?, ?, ?, ?)",
            (username, action_type, count, now, day)
        )
        _touch_account(cur, username)


def record_snapshot(username: str, followers: int, following: int, media_count: int):
    """
    Save a follower/following/media_count snapshot.
    Called from bot_engine.get_account_stats() after every API fetch.
    """
    now = datetime.now().isoformat(timespec="seconds")

    with _tx() as cur:
        _ensure_account(cur, username)
        cur.execute(
            "INSERT INTO snapshots (username, ts, followers, following, media_count) VALUES (?, ?, ?, ?, ?)",
            (username, now, followers, following, media_count)
        )
        _touch_account(cur, username)


def get_account_history(username: str) -> dict:
    """
    Return a structured dict for one account — matches the old JSON shape
    so cli.py needs no changes.
    """
    conn = _get_conn()
    cur  = conn.cursor()

    cur.execute("SELECT * FROM accounts WHERE username = ?", (username,))
    acc = cur.fetchone()
    if not acc:
        cur.close()
        return {
            "all_time":    _empty_counters(),
            "daily":       {},
            "snapshots":   [],
            "first_seen":  None,
            "last_active": None,
        }

    # All-time totals
    cur.execute("""
        SELECT action_type, SUM(count) AS total
        FROM   actions
        WHERE  username = ?
        GROUP  BY action_type
    """, (username,))
    all_time = _empty_counters()
    for row in cur.fetchall():
        if row["action_type"] in all_time:
            all_time[row["action_type"]] = row["total"]

    # Daily breakdown — last 90 days
    since = (date.today() - timedelta(days=90)).isoformat()
    cur.execute("""
        SELECT date, action_type, SUM(count) AS total
        FROM   actions
        WHERE  username = ? AND date >= ?
        GROUP  BY date, action_type
        ORDER  BY date
    """, (username, since))
    daily: dict = {}
    for row in cur.fetchall():
        d = row["date"]
        if d not in daily:
            daily[d] = _empty_counters()
        if row["action_type"] in daily[d]:
            daily[d][row["action_type"]] = row["total"]

    # Snapshots — most recent 30, returned oldest-first
    cur.execute("""
        SELECT ts, followers, following, media_count
        FROM   snapshots
        WHERE  username = ?
        ORDER  BY ts DESC
        LIMIT  30
    """, (username,))
    snapshots = list(reversed([dict(r) for r in cur.fetchall()]))

    cur.close()
    return {
        "all_time":    all_time,
        "daily":       daily,
        "snapshots":   snapshots,
        "first_seen":  acc["first_seen"],
        "last_active": acc["last_active"],
    }


def get_all_accounts_summary() -> list:
    """
    Return one summary dict per known account.
    Powers the [A] All-Time Stats overview table in cli.py.
    """
    conn = _get_conn()
    cur  = conn.cursor()

    cur.execute("SELECT username, first_seen, last_active FROM accounts ORDER BY last_active DESC")
    accounts = _rows_to_dicts(cur.fetchall())

    if not accounts:
        cur.close()
        return []

    since_7d   = (date.today() - timedelta(days=7)).isoformat()
    summaries  = []

    for acc in accounts:
        username = acc["username"]

        # All-time totals
        cur.execute("""
            SELECT action_type, SUM(count) AS total
            FROM   actions
            WHERE  username = ?
            GROUP  BY action_type
        """, (username,))
        all_time = _empty_counters()
        for row in cur.fetchall():
            if row["action_type"] in all_time:
                all_time[row["action_type"]] = row["total"]

        # Last 7 days
        cur.execute("""
            SELECT action_type, SUM(count) AS total
            FROM   actions
            WHERE  username = ? AND date >= ?
            GROUP  BY action_type
        """, (username, since_7d))
        week_totals = _empty_counters()
        for row in cur.fetchall():
            if row["action_type"] in week_totals:
                week_totals[row["action_type"]] = row["total"]

        # Latest follower snapshot
        cur.execute("""
            SELECT followers, following, media_count
            FROM   snapshots
            WHERE  username = ?
            ORDER  BY ts DESC
            LIMIT  1
        """, (username,))
        snap = cur.fetchone()

        summaries.append({
            "username":    username,
            "first_seen":  acc["first_seen"],
            "last_active": acc["last_active"],
            "followers":   snap["followers"]   if snap else "—",
            "following":   snap["following"]   if snap else "—",
            "media_count": snap["media_count"] if snap else "—",
            "all_time":    all_time,
            "last_7_days": week_totals,
        })

    cur.close()
    return summaries


def get_daily_series(username: str, days: int = 14) -> list:
    """
    Return one dict per calendar day for the last N days (oldest first).
    Days with no activity are included as zero-filled rows — ensures
    the CLI table always shows a complete, gapless date range.
    """
    conn  = _get_conn()
    cur   = conn.cursor()
    since = (date.today() - timedelta(days=days - 1)).isoformat()

    cur.execute("""
        SELECT date, action_type, SUM(count) AS total
        FROM   actions
        WHERE  username = ? AND date >= ?
        GROUP  BY date, action_type
        ORDER  BY date
    """, (username, since))

    raw: dict = {}
    for row in cur.fetchall():
        d = row["date"]
        if d not in raw:
            raw[d] = _empty_counters()
        if row["action_type"] in raw[d]:
            raw[d][row["action_type"]] = row["total"]
    cur.close()

    # Fill every day in range, even days with zero activity
    series = []
    for i in range(days):
        day = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        series.append({"date": day, **raw.get(day, _empty_counters())})

    return series


def get_follower_growth(username: str) -> list:
    """Return up to 30 follower snapshots for an account, oldest first."""
    conn = _get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT ts, followers, following, media_count
        FROM   snapshots
        WHERE  username = ?
        ORDER  BY ts DESC
        LIMIT  30
    """, (username,))
    rows = list(reversed([dict(r) for r in cur.fetchall()]))
    cur.close()
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# EXTRA QUERY HELPERS  —  only possible because we're on SQLite now
# ─────────────────────────────────────────────────────────────────────────────

def query(sql: str, params: tuple = ()) -> list:
    """
    Run arbitrary read-only SQL, get back a list of dicts.
    Useful for ad-hoc exploration and future CLI features.

    Example:
        from stats_store import query
        query(
            "SELECT date, SUM(count) AS total FROM actions "
            "WHERE username=? GROUP BY date ORDER BY total DESC LIMIT 5",
            ("myaccount",)
        )
    """
    conn = _get_conn()
    cur  = conn.cursor()
    cur.execute(sql, params)
    rows = _rows_to_dicts(cur.fetchall())
    cur.close()
    return rows


def get_all_usernames() -> list:
    """Return all known usernames, most recently active first."""
    rows = query("SELECT username FROM accounts ORDER BY last_active DESC")
    return [r["username"] for r in rows]


def get_best_days(username: str, n: int = 5) -> list:
    """
    Return the N most active days ever for an account, ordered by total
    actions descending. Each entry includes a per-action-type breakdown.
    """
    return query("""
        SELECT
            date,
            SUM(count)                                                      AS total,
            SUM(CASE WHEN action_type='likes'       THEN count ELSE 0 END)  AS likes,
            SUM(CASE WHEN action_type='comments'    THEN count ELSE 0 END)  AS comments,
            SUM(CASE WHEN action_type='follows'     THEN count ELSE 0 END)  AS follows,
            SUM(CASE WHEN action_type='unfollows'   THEN count ELSE 0 END)  AS unfollows,
            SUM(CASE WHEN action_type='dms'         THEN count ELSE 0 END)  AS dms,
            SUM(CASE WHEN action_type='story_views' THEN count ELSE 0 END)  AS story_views
        FROM   actions
        WHERE  username = ?
        GROUP  BY date
        ORDER  BY total DESC
        LIMIT  ?
    """, (username, n))


def get_action_totals_by_week(username: str, weeks: int = 8) -> list:
    """
    Return weekly aggregated totals for the last N weeks, oldest first.
    Each entry: {week, week_start, likes, comments, follows, ..., total}
    """
    since = (date.today() - timedelta(weeks=weeks)).isoformat()
    return query("""
        SELECT
            strftime('%Y-W%W', date)                                        AS week,
            date(date, 'weekday 1', '-7 days')                              AS week_start,
            SUM(CASE WHEN action_type='likes'       THEN count ELSE 0 END)  AS likes,
            SUM(CASE WHEN action_type='comments'    THEN count ELSE 0 END)  AS comments,
            SUM(CASE WHEN action_type='follows'     THEN count ELSE 0 END)  AS follows,
            SUM(CASE WHEN action_type='unfollows'   THEN count ELSE 0 END)  AS unfollows,
            SUM(CASE WHEN action_type='dms'         THEN count ELSE 0 END)  AS dms,
            SUM(CASE WHEN action_type='story_views' THEN count ELSE 0 END)  AS story_views,
            SUM(count)                                                       AS total
        FROM   actions
        WHERE  username = ? AND date >= ?
        GROUP  BY week
        ORDER  BY week
    """, (username, since))


def search_actions(
    username:    str,
    action_type: str = None,
    from_date:   str = None,
    to_date:     str = None,
    limit:       int = 100,
) -> list:
    """
    Filtered action log search. All filters except username are optional.

    Args:
        username:    account to search (required)
        action_type: 'likes' | 'comments' | 'follows' | etc.  (None = all)
        from_date:   'YYYY-MM-DD'  inclusive lower bound       (None = no limit)
        to_date:     'YYYY-MM-DD'  inclusive upper bound       (None = today)
        limit:       max rows returned, newest first           (default 100)

    Returns list of {id, username, action_type, count, ts, date} dicts.
    """
    clauses = ["username = ?"]
    params  = [username]

    if action_type:
        clauses.append("action_type = ?")
        params.append(action_type)
    if from_date:
        clauses.append("date >= ?")
        params.append(from_date)
    if to_date:
        clauses.append("date <= ?")
        params.append(to_date)

    params.append(limit)
    return query(
        f"SELECT id, username, action_type, count, ts, date "
        f"FROM actions WHERE {' AND '.join(clauses)} ORDER BY ts DESC LIMIT ?",
        tuple(params)
    )


def get_follow_back_rate(username: str) -> dict:
    """
    Estimate follow-back rate: followers gained ÷ follows sent.
    Uses the delta between first and latest snapshot for follower gain.

    Returns:
        follows_made        — total follows recorded all time
        follower_gain       — followers(latest) - followers(first snapshot)
        estimated_rate_pct  — (follower_gain / follows_made) * 100
        snapshots_available — False if not enough snapshots to calculate
    """
    conn = _get_conn()
    cur  = conn.cursor()

    cur.execute(
        "SELECT SUM(count) AS total FROM actions WHERE username=? AND action_type='follows'",
        (username,)
    )
    row          = cur.fetchone()
    follows_made = row["total"] or 0 if row else 0

    cur.execute(
        "SELECT followers FROM snapshots WHERE username=? ORDER BY ts ASC  LIMIT 1",
        (username,)
    )
    first = cur.fetchone()
    cur.execute(
        "SELECT followers FROM snapshots WHERE username=? ORDER BY ts DESC LIMIT 1",
        (username,)
    )
    latest = cur.fetchone()
    cur.close()

    if not first or not latest or follows_made == 0:
        return {
            "follows_made":        follows_made,
            "follower_gain":       None,
            "estimated_rate_pct":  None,
            "snapshots_available": bool(first and latest),
        }

    gain = (latest["followers"] or 0) - (first["followers"] or 0)
    rate = round((gain / follows_made) * 100, 1)

    return {
        "follows_made":        follows_made,
        "follower_gain":       gain,
        "estimated_rate_pct":  rate,
        "snapshots_available": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ONE-TIME MIGRATION FROM OLD JSON FILE
# ─────────────────────────────────────────────────────────────────────────────

def migrate_from_json(json_path: str = "data/stats.json") -> dict:
    """
    Import all historical data from the old stats.json into SQLite.
    Safe to run multiple times — skips duplicate rows gracefully.

    Returns a summary dict: {accounts_imported, action_rows, snapshot_rows, errors}

    After a successful migration you can safely delete data/stats.json.
    """
    p = Path(json_path)
    if not p.exists():
        return {"error": f"{json_path} not found — nothing to migrate"}

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"error": f"Could not parse JSON: {e}"}

    accounts_data = raw.get("accounts", {})
    summary = {
        "accounts_imported": 0,
        "action_rows":       0,
        "snapshot_rows":     0,
        "errors":            [],
    }

    conn = _get_conn()
    cur  = conn.cursor()

    for username, acc in accounts_data.items():
        try:
            # Upsert account row
            cur.execute("""
                INSERT INTO accounts (username, first_seen, last_active)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    last_active = excluded.last_active
            """, (
                username,
                acc.get("first_seen",  datetime.now().isoformat(timespec="seconds")),
                acc.get("last_active", datetime.now().isoformat(timespec="seconds")),
            ))
            summary["accounts_imported"] += 1

            # Migrate daily action data
            # Each day in the JSON has already-aggregated counts, so we
            # insert one synthetic row per (day, action_type) at noon.
            for day, counters in acc.get("daily", {}).items():
                for action_type, count in counters.items():
                    if count > 0 and action_type in ACTION_KEYS:
                        ts = f"{day}T12:00:00"
                        cur.execute(
                            "INSERT INTO actions (username, action_type, count, ts, date) VALUES (?, ?, ?, ?, ?)",
                            (username, action_type, count, ts, day)
                        )
                        summary["action_rows"] += 1

            # Migrate snapshots
            for snap in acc.get("snapshots", []):
                cur.execute(
                    "INSERT INTO snapshots (username, ts, followers, following, media_count) VALUES (?, ?, ?, ?, ?)",
                    (
                        username,
                        snap.get("ts", datetime.now().isoformat(timespec="seconds")),
                        snap.get("followers",   0),
                        snap.get("following",   0),
                        snap.get("media_count", 0),
                    )
                )
                summary["snapshot_rows"] += 1

            conn.commit()

        except Exception as e:
            conn.rollback()
            summary["errors"].append(f"{username}: {e}")

    cur.close()
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# POSTS  —  publish history
# ─────────────────────────────────────────────────────────────────────────────

def record_post(
    username:  str,
    post_type: str,
    caption:   str = "",
    location:  str = "",
    media_pk:  str = "",
    has_music: bool = False,
):
    """
    Record a successful publish event to the posts table.
    Called by poster.Publisher._record_post() after every upload.
    post_type: photo | carousel | story_photo | story_video
    """
    now = datetime.now().isoformat(timespec="seconds")
    day = date.today().isoformat()

    with _tx() as cur:
        _ensure_account(cur, username)
        cur.execute(
            """INSERT INTO posts
               (username, post_type, caption, location, media_pk, has_music, ts, date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (username, post_type, caption[:200], location[:100],
             media_pk, int(has_music), now, day)
        )
        _touch_account(cur, username)


def get_post_history(username: str, limit: int = 50) -> list:
    """
    Return the last N posts for an account, newest first.
    Each entry: {id, post_type, caption, location, media_pk, has_music, ts, date}
    """
    return query(
        """SELECT id, post_type, caption, location, media_pk, has_music, ts, date
           FROM posts WHERE username = ?
           ORDER BY ts DESC LIMIT ?""",
        (username, limit)
    )


def get_post_summary(username: str) -> dict:
    """
    Return aggregate post counts per type for an account.
    {total, photo, carousel, story_photo, story_video, last_7_days}
    """
    conn = _get_conn()
    cur  = conn.cursor()

    cur.execute(
        "SELECT post_type, COUNT(*) as cnt FROM posts WHERE username=? GROUP BY post_type",
        (username,)
    )
    by_type = {r["post_type"]: r["cnt"] for r in cur.fetchall()}

    since_7d = (date.today() - timedelta(days=7)).isoformat()
    cur.execute(
        "SELECT COUNT(*) as cnt FROM posts WHERE username=? AND date >= ?",
        (username, since_7d)
    )
    row   = cur.fetchone()
    week  = row["cnt"] if row else 0
    cur.close()

    return {
        "total":       sum(by_type.values()),
        "photo":       by_type.get("photo", 0),
        "carousel":    by_type.get("carousel", 0),
        "story_photo": by_type.get("story_photo", 0),
        "story_video": by_type.get("story_video", 0),
        "last_7_days": week,
    }


def get_all_post_summaries() -> list:
    """
    Return post summary dicts for all known accounts.
    Used by the CLI publishing stats view.
    """
    usernames = get_all_usernames()
    return [
        {"username": u, **get_post_summary(u)}
        for u in usernames
        if get_post_summary(u)["total"] > 0
    ]