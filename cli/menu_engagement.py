"""
cli/menu_engagement.py  —  Engagement action menus.

Covers: Human Behaviour, Like Posts, Comment, Follow/Unfollow,
        Watch Stories, Direct Messages, Hashtag Engagement.
"""

from rich.prompt  import Prompt, Confirm
from rich.table   import Table
from rich         import box

from cli.shared import (
    console, hdr, rule, ok, info, warn, done,
    pick_accounts, run_on_bots, ask_concurrent,
)


def menu_human_behaviour(manager, cfg):
    hdr("HUMAN BEHAVIOUR SIMULATION")
    console.print("[dim]  Mimics real Instagram use: warmup, feed, explore, reels, stories.[/dim]")
    console.print("[dim]  Typing simulation, fatigue modelling, activity windows, random breaks.[/dim]\n")
    opts = [
        ("1", "Full human session  [warmup + feed + explore + reels]"),
        ("2", "Scroll home feed only"),
        ("3", "Browse explore page only"),
        ("4", "Watch reels only"),
        ("5", "Watch feed stories passively"),
        ("0", "Back"),
    ]
    for k, v in opts:
        console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0":
        return

    bots       = pick_accounts(manager)
    if not bots: return
    engage     = Confirm.ask("  Allow incidental likes while browsing?", default=True)
    concurrent = ask_concurrent()

    if   choice == "1": fn = lambda b: b.run_human_session(engage=engage)
    elif choice == "2":
        n  = int(Prompt.ask("  Posts to scroll", default="10"))
        fn = lambda b: b.scroll_feed(posts=n, engage=engage)
    elif choice == "3":
        n  = int(Prompt.ask("  Posts to browse", default="15"))
        fn = lambda b: b.browse_explore(posts=n, engage=engage)
    elif choice == "4":
        n  = int(Prompt.ask("  Reels to watch", default="10"))
        fn = lambda b: b.browse_reels(count=n, engage=engage)
    elif choice == "5":
        n  = int(Prompt.ask("  Accounts' stories to watch", default="10"))
        fn = lambda b: b.watch_following_stories(count=n)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_like(manager, cfg):
    hdr("LIKE POSTS")
    console.print("  [1]  Like posts from a user")
    console.print("  [2]  Like posts from a hashtag")
    console.print("  [0]  Back")
    rule()
    choice = Prompt.ask("  Select", choices=["1", "2", "0"])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()

    if choice == "1":
        target = Prompt.ask("  Target username")
        count  = int(Prompt.ask("  Posts to like", default="5"))
        fn = lambda b: b.like_user_posts(target, count)
    else:
        hashtag = Prompt.ask("  Hashtag  [without #]")
        count   = int(Prompt.ask("  Posts to like", default="10"))
        fn = lambda b: b.like_hashtag_posts(hashtag, count)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_comment(manager, cfg):
    hdr("COMMENT ON POSTS")
    console.print("  [1]  Comment on a user's posts")
    console.print("  [2]  Comment on hashtag posts")
    console.print("  [0]  Back")
    rule()
    choice = Prompt.ask("  Select", choices=["1", "2", "0"])
    if choice == "0": return

    pool = cfg.get("defaults", {}).get("comments", ["Great content!", "Really inspiring!"])
    if Confirm.ask(f"  Use default comment pool?  [{len(pool)} comments]", default=True):
        comments = pool
    else:
        raw      = Prompt.ask("  Enter comments separated by  |")
        comments = [c.strip() for c in raw.split("|") if c.strip()]

    bots = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()

    if choice == "1":
        target = Prompt.ask("  Target username")
        count  = int(Prompt.ask("  Posts to comment on", default="3"))
        fn = lambda b: b.comment_on_user_posts(target, comments, count)
    else:
        hashtag = Prompt.ask("  Hashtag  [without #]")
        count   = int(Prompt.ask("  Posts to comment on", default="5"))
        fn = lambda b: b.comment_on_hashtag_posts(hashtag, comments, count)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_follow(manager, cfg):
    hdr("FOLLOW / UNFOLLOW")
    opts = [
        ("1", "Follow a list of users"),
        ("2", "Follow followers of a target account"),
        ("3", "Unfollow a list of users"),
        ("4", "Unfollow non-followers  [cleanup]"),
        ("0", "Back"),
    ]
    for k, v in opts:
        console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()

    if choice == "1":
        usernames = [u.strip() for u in Prompt.ask("  Usernames  [comma-separated]").split(",")]
        fn = lambda b: b.follow_users(usernames)
    elif choice == "2":
        target = Prompt.ask("  Target username")
        count  = int(Prompt.ask("  How many followers", default="20"))
        fn = lambda b: b.follow_user_followers(target, count)
    elif choice == "3":
        usernames = [u.strip() for u in Prompt.ask("  Usernames  [comma-separated]").split(",")]
        fn = lambda b: b.unfollow_users(usernames)
    elif choice == "4":
        limit = int(Prompt.ask("  Max unfollows", default="50"))
        fn = lambda b: b.unfollow_non_followers(limit)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_stories(manager, cfg):
    hdr("WATCH STORIES")
    console.print("  [1]  Watch stories from a specific user")
    console.print("  [2]  Watch stories from your feed")
    console.print("  [0]  Back")
    rule()
    choice = Prompt.ask("  Select", choices=["1", "2", "0"])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()

    if choice == "1":
        target = Prompt.ask("  Target username")
        fn = lambda b: b.watch_user_stories(target)
    else:
        count = int(Prompt.ask("  Accounts' stories to watch", default="20"))
        fn = lambda b: b.watch_following_stories(count)

    run_on_bots(bots, fn, concurrent)
    done()


def menu_dms(manager, cfg):
    hdr("DIRECT MESSAGES")
    opts = [
        ("1", "Send DM to one user"),
        ("2", "Bulk send to a list  [rotating messages]"),
        ("3", "Auto-reply to unread DMs  [keyword matching]"),
        ("4", "View inbox summary"),
        ("0", "Back"),
    ]
    for k, v in opts:
        console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0": return

    bots = pick_accounts(manager)
    if not bots: return

    if choice == "1":
        target = Prompt.ask("  Target username")
        msg    = Prompt.ask("  Message")
        fn = lambda b: b.send_dm(target, msg)
        run_on_bots(bots, fn, concurrent=False)

    elif choice == "2":
        usernames = [u.strip() for u in Prompt.ask("  Usernames  [comma-separated]").split(",")]
        messages  = [m.strip() for m in Prompt.ask("  Messages  [pipe-separated |]").split("|")]
        fn = lambda b: b.send_dm_to_list(usernames, messages)
        run_on_bots(bots, fn, concurrent=False)

    elif choice == "3":
        reply_map  = cfg.get("defaults", {}).get("dm_replies", {"_default": "Thanks for reaching out!"})
        info(f"Reply map loaded  {len(reply_map)} keyword(s)")
        concurrent = ask_concurrent()
        fn = lambda b: b.auto_reply_dms(reply_map)
        run_on_bots(bots, fn, concurrent)

    elif choice == "4":
        for bot in bots:
            summary = bot.get_inbox_summary()
            t = Table(title=f"  INBOX  @{bot.username}", box=box.SIMPLE_HEAD,
                      show_header=True, header_style="bold cyan")
            t.add_column("Thread",      style="dim")
            t.add_column("Users")
            t.add_column("Last Message")
            t.add_column("Unread",      justify="center")
            for thread in summary.get("threads", []):
                users   = ", ".join(thread["users"])
                preview = (thread["last_message"] or "")[:60]
                unread  = "[bright_cyan]YES[/bright_cyan]" if thread["unread"] else "—"
                t.add_row(str(thread["id"])[:12], users, preview, unread)
            console.print(t)
            info(f"Total: {summary.get('total_threads',0)}  Unread: {summary.get('unread_threads',0)}")

    done()


def menu_hashtag(manager, cfg):
    hdr("HASHTAG ENGAGEMENT")
    hashtag    = Prompt.ask("  Hashtag  [without #]")
    count      = int(Prompt.ask("  Posts to process", default="10"))
    do_like    = Confirm.ask("  Like posts?",     default=True)
    do_comment = Confirm.ask("  Comment?",        default=False)
    do_follow  = Confirm.ask("  Follow posters?", default=False)

    comments = []
    if do_comment:
        pool = cfg.get("defaults", {}).get("comments", ["Great content!"])
        if Confirm.ask(f"  Use default comment pool?  [{len(pool)} comments]", default=True):
            comments = pool
        else:
            comments = [c.strip() for c in Prompt.ask("  Comments  [pipe |]").split("|")]

    actions    = {"like": do_like, "comment": do_comment, "follow": do_follow,
                  "count": count, "comments": comments}
    bots       = pick_accounts(manager)
    if not bots: return
    concurrent = ask_concurrent()
    run_on_bots(bots, lambda b: b.engage_hashtag(hashtag, actions), concurrent)
    done()