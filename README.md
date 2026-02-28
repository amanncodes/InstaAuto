# 🤖 InstaBot — Multi-Account Instagram Automation

A powerful, modular Python system for automating multiple Instagram accounts using [instagrapi](https://github.com/subzeroid/instagrapi).

---

## 📁 Project Structure

```
insta_bot/
├── cli.py                  # Interactive CLI menu — run this
├── bot_engine.py           # Core automation logic per account
├── account_manager.py      # Multi-account concurrency manager
├── scheduler.py            # Cron-like task scheduler
├── config_loader.py        # YAML config loader + validator
├── requirements.txt
├── config/
│   ├── config.example.yaml # Template — copy to config.yaml
│   └── config.yaml         # Your actual config (gitignored)
├── sessions/               # Saved login sessions (auto-created)
└── logs/                   # Per-account + system logs (auto-created)
```

---

## 🚀 Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> Also requires `ffmpeg` for story video building (optional):  
> `sudo apt install ffmpeg` or `brew install ffmpeg`

### 2. Configure your accounts

```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml`:
- Add your Instagram accounts (username + password)
- Optionally add per-account proxies
- Configure comment pools, DM replies, tasks, and schedule

### 3. Run

```bash
python cli.py
```

---

## 🎛️ Features

### Actions Available

| Action | Description |
|---|---|
| Like posts | Like recent posts from a user or hashtag |
| Comment | Comment with rotating messages on posts |
| Follow | Follow a list of users or followers of a target |
| Unfollow | Unfollow a list, or auto-unfollow non-followers |
| Watch stories | View stories from a user or your feed |
| Send DMs | Send direct messages individually or in bulk |
| Auto-reply DMs | Keyword-based auto-reply to unread DMs |
| Hashtag engage | Full engagement: like + comment + follow from a hashtag |

### Multi-Account Concurrency

All actions can run across **all accounts simultaneously** using threads, or on a single account at a time.

### Scheduler

Define recurring tasks in `config.yaml` with either:
- `interval_minutes: 60` — run every N minutes
- `run_at: "08:00"` — run daily at a specific time

### Session Persistence

Sessions are saved in `sessions/<username>.json` so you don't have to re-login every run.

---

## ⚙️ Config Reference

### Accounts
```yaml
accounts:
  - username: "myaccount"
    password: "mypassword"
    proxy: "http://user:pass@host:port"  # optional
```

### Tasks (run once via CLI)
```yaml
tasks:
  - action: "like_hashtag"
    hashtag: "photography"
    count: 15

  - action: "follow_followers_of"
    target: "some_influencer"
    count: 30

  - action: "engage_hashtag"
    hashtag: "travel"
    count: 20
    like: true
    comment: true
    follow: false
    comments: ["Amazing! 🔥", "So beautiful! 😍"]
```

### Schedule (automated recurring)
```yaml
schedule:
  - task:
      action: "like_hashtag"
      hashtag: "streetphotography"
      count: 20
    interval_minutes: 90

  - task:
      action: "watch_feed_stories"
      count: 30
    run_at: "09:00"
```

### All Supported Actions

| Action | Required Keys | Optional Keys |
|---|---|---|
| `like_user_posts` | `target` | `count` |
| `like_hashtag` | `hashtag` | `count` |
| `comment_user_posts` | `target`, `comments` | `count` |
| `comment_hashtag` | `hashtag`, `comments` | `count` |
| `follow_users` | `usernames` | — |
| `follow_followers_of` | `target` | `count` |
| `unfollow_users` | `usernames` | — |
| `unfollow_non_followers` | — | `limit` |
| `watch_stories` | `target` | — |
| `watch_feed_stories` | — | `count` |
| `send_dms` | `usernames`, `messages` | — |
| `auto_reply_dms` | `reply_map` | `max_threads` |
| `engage_hashtag` | `hashtag` | `count`, `like`, `comment`, `follow`, `comments` |

---

## ⚠️ Safety Tips

1. **Use proxies** — assign a unique proxy per account to avoid IP bans
2. **Keep action counts low** — Instagram rate-limits aggressively:
   - Likes: ~60/hour
   - Comments: ~20/hour
   - Follows: ~60/hour
   - DMs: ~50/day
3. **Use `human_delay`** — already built-in, adds random pauses between actions
4. **Don't run 24/7 immediately** — warm up new accounts slowly
5. **Session files** — reuse sessions instead of logging in fresh every time

---

## 📝 Logs

- `logs/system.log` — global system log
- `logs/<username>.log` — per-account log with full action history

---

## 🧪 Running a Quick Test (No Full Login)

You can test the config loading without logging in:

```python
from config_loader import load_config
cfg = load_config("config/config.yaml")
print(cfg["accounts"])
```