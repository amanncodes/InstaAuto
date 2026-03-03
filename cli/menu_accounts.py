"""
cli/menu_accounts.py  —  Account Manager and Account Creator menus.

Account Manager: add, remove, login, logout, relogin, keep-alive, ping sessions.
Account Creator: register brand-new Instagram accounts via the instagrapi signup API.
"""

from rich.prompt import Prompt, Confirm
from rich.table  import Table
from rich.panel  import Panel
from rich        import box

from cli.shared import (
    console, hdr, rule, ok, info, warn,
    print_accounts_table, ask_concurrent, run_on_bots,
    save_config, register_challenge_handler,
)


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT MANAGER
# ─────────────────────────────────────────────────────────────────────────────

def menu_account_manager(manager, cfg):
    while True:
        hdr("ACCOUNT MANAGER")
        print_accounts_table(manager)
        rule()

        opts = [
            ("1", "Add account          username + password  [saves to config.yaml]"),
            ("2", "Remove account       delete from config + logout"),
            ("3", "Login account        login a specific offline account"),
            ("4", "Logout account       clear session for a specific account"),
            ("5", "Relogin account      refresh session without full re-auth"),
            ("6", "Login all offline    attempt login on every OFFLINE account"),
            ("7", "Account status       detailed info on a specific account"),
            ("8", "Keep-alive           start / stop / status of session heartbeat"),
            ("9", "Ping sessions        manual one-shot session health check all accounts"),
            ("N", "New account          register a brand-new Instagram account"),
            ("0", "Back"),
        ]
        for k, v in opts:
            console.print(f"  [{k}]  {v}")
        rule()
        choice = Prompt.ask(
            "  Select",
            choices=[o[0] for o in opts] + [o[0].lower() for o in opts if o[0].isalpha()],
        ).upper()

        if choice == "0":
            break

        # ── 1. Add existing account ───────────────────────────────────────────
        elif choice == "1":
            hdr("ADD ACCOUNT")
            username = Prompt.ask("  Instagram username").strip().lstrip("@")
            if not username:
                warn("Username cannot be empty"); continue

            if any(b.username == username for b in manager.bots):
                warn(f"@{username} is already loaded in this session"); continue

            password = Prompt.ask("  Password", password=True)
            proxy    = Prompt.ask("  Proxy  [http://user:pass@host:port, blank to skip]", default="").strip()
            profile  = Prompt.ask("  Behaviour profile", choices=["active","moderate","conservative"], default="active")

            account_cfg = {"username": username, "password": password, "behaviour_profile": profile}
            if proxy:
                account_cfg["proxy"] = proxy

            info(f"Creating bot for @{username}...")
            from bot_engine import InstagramBot
            from proxy_manager import get_proxy_manager as _gpm
            _pm = _gpm()
            # Auto-fill proxy from proxy_manager if one is assigned
            stored_proxy = _pm.get_for_account(username)
            if stored_proxy:
                account_cfg["proxy"] = stored_proxy
                info(f"Using stored proxy for @{username}")
            elif not account_cfg.get("proxy"):
                # Offer quick assignment from a provider if any exist
                providers = _pm.list_providers()
                if providers:
                    pnames = [p['name'] for p in providers]
                    console.print(f"  [dim]No proxy assigned. Providers available: {', '.join(pnames)}[/dim]")
                    if Confirm.ask("  Assign a proxy from a provider now?", default=True):
                        pname = Prompt.ask("  Provider", choices=pnames)
                        url   = _pm.assign_from_provider(username, pname)
                        account_cfg["proxy"] = url
                        ok(f"Proxy assigned: {url[:40]}...")
            bot = InstagramBot(account_cfg)
            if account_cfg.get("proxy"):
                _pm.apply_to_bot(bot)
            register_challenge_handler(bot)

            info(f"Logging in @{username}...")
            success = bot.login()

            if success:
                manager.bots.append(bot)
                ok(f"@{username} added and logged in")
                if Confirm.ask("  Save to config.yaml so it loads on next startup?", default=True):
                    cfg["accounts"].append(account_cfg)
                    try:
                        save_config(cfg)
                        ok(f"Saved @{username} to config/config.yaml")
                    except Exception as e:
                        warn(f"Could not save config: {e}")
            else:
                warn(f"Login failed for @{username} — not added. Check credentials.")

        # ── 2. Remove account ─────────────────────────────────────────────────
        elif choice == "2":
            if not manager.bots:
                warn("No accounts loaded"); continue

            username = Prompt.ask("  Remove account", choices=[b.username for b in manager.bots])
            bot      = next(b for b in manager.bots if b.username == username)

            if not Confirm.ask(f"  Remove @{username}? This will logout and delete from config.", default=False):
                info("Cancelled"); continue

            if bot.logged_in:
                try:
                    bot.cl.logout()
                except Exception:
                    pass
            if bot.session_file.exists():
                bot.session_file.unlink()

            manager.bots = [b for b in manager.bots if b.username != username]
            cfg["accounts"] = [a for a in cfg["accounts"] if a["username"] != username]
            try:
                save_config(cfg)
            except Exception as e:
                warn(f"Removed from session but could not update config: {e}")
            ok(f"@{username} removed")

        # ── 3. Login specific account ─────────────────────────────────────────
        elif choice == "3":
            offline = [b for b in manager.bots if not b.logged_in]
            if not offline:
                ok("All accounts are already logged in"); continue

            username = Prompt.ask("  Login which account", choices=[b.username for b in offline])
            bot      = next(b for b in offline if b.username == username)

            register_challenge_handler(bot)
            info(f"Logging in @{username}...")
            success = bot.login()
            ok(f"@{username} is now logged in") if success else warn(f"Login failed for @{username}")

        # ── 4. Logout specific account ────────────────────────────────────────
        elif choice == "4":
            active = [b for b in manager.bots if b.logged_in]
            if not active:
                warn("No accounts are currently logged in"); continue

            username = Prompt.ask("  Logout which account", choices=[b.username for b in active])
            bot      = next(b for b in active if b.username == username)

            try:
                with console.status(f"[bold cyan]  Logging out @{username}...[/bold cyan]"):
                    bot.cl.logout()
                bot.logged_in = False
                if bot.session_file.exists():
                    bot.session_file.unlink()
                ok(f"@{username} logged out and session cleared")
            except Exception as e:
                warn(f"Logout error: {e}")
                bot.logged_in = False
                info("Marked as offline regardless")

        # ── 5. Relogin ────────────────────────────────────────────────────────
        elif choice == "5":
            if not manager.bots:
                warn("No accounts loaded"); continue

            username = Prompt.ask("  Relogin which account", choices=[b.username for b in manager.bots])
            bot      = next(b for b in manager.bots if b.username == username)

            info("Using cl.relogin() — reuses existing device fingerprint, less suspicious than fresh login")
            register_challenge_handler(bot)
            with console.status(f"[bold cyan]  Relogging in @{username}...[/bold cyan]"):
                success = bot._do_relogin()
            ok(f"@{username} session refreshed") if success else warn("Relogin failed — try option 3 (Login)")

        # ── 6. Login all offline ──────────────────────────────────────────────
        elif choice == "6":
            offline = [b for b in manager.bots if not b.logged_in]
            if not offline:
                ok("All accounts are already logged in"); continue

            info(f"Attempting login on {len(offline)} offline account(s)...")

            def _login(b):
                register_challenge_handler(b)
                info(f"Logging in @{b.username}...")
                success = b.login()
                ok(f"@{b.username} logged in") if success else warn(f"@{b.username} login failed")

            run_on_bots(offline, _login, concurrent=False)   # sequential — OTP prompts must not overlap
            print_accounts_table(manager)

        # ── 7. Account status ─────────────────────────────────────────────────
        elif choice == "7":
            if not manager.bots:
                warn("No accounts loaded"); continue

            username = Prompt.ask("  Account", choices=[b.username for b in manager.bots])
            bot      = next(b for b in manager.bots if b.username == username)

            status_color = "[bright_green]ONLINE[/bright_green]" if bot.logged_in else "[bright_red]OFFLINE[/bright_red]"
            device  = f"{bot._device['manufacturer']} {bot._device['model']}" if hasattr(bot,"_device") else "—"
            locale  = bot._locale["locale"] if hasattr(bot,"_locale") else "—"
            tz      = f"UTC{bot._locale['tz_offset']//3600:+d}" if hasattr(bot,"_locale") else "—"
            today   = bot.session.actions_today
            limits  = bot.session.daily_limits

            console.print(Panel(
                f"  Status:    {status_color}\n"
                f"  Username:  [bold white]@{bot.username}[/bold white]\n"
                f"  Profile:   {bot.session.profile}\n"
                f"  Device:    [dim]{device}[/dim]\n"
                f"  Locale:    [dim]{locale}  {tz}[/dim]\n"
                f"  Proxy:     [dim]{bot.proxy or 'none'}[/dim]\n"
                f"  Session:   [dim]{bot.session_file}  "
                f"({'exists' if bot.session_file.exists() else 'not saved'})[/dim]\n"
                f"  Fatigue:   [cyan]{bot.session.fatigue_level:.0%}[/cyan]\n\n"
                f"  Today's actions\n"
                f"  [dim]{'─'*40}[/dim]\n"
                f"  Likes:       {today.get('likes',0)} / {limits.get('likes',0)}\n"
                f"  Comments:    {today.get('comments',0)} / {limits.get('comments',0)}\n"
                f"  Follows:     {today.get('follows',0)} / {limits.get('follows',0)}\n"
                f"  Unfollows:   {today.get('unfollows',0)} / {limits.get('unfollows',0)}\n"
                f"  DMs:         {today.get('dms',0)} / {limits.get('dms',0)}\n"
                f"  Story views: {today.get('story_views',0)} / {limits.get('story_views',0)}",
                title=f"  ACCOUNT STATUS  @{bot.username}",
                border_style="cyan", title_align="left",
            ))

        # ── 8. Keep-alive ─────────────────────────────────────────────────────
        elif choice == "8":
            if not manager.bots:
                warn("No accounts loaded"); continue

            t = Table(title="  KEEP-ALIVE STATUS", show_header=True,
                      header_style="bold cyan", box=box.SIMPLE_HEAD)
            t.add_column("Account",    style="bold white", min_width=18)
            t.add_column("Status",     justify="center")
            t.add_column("Interval",   justify="center")
            t.add_column("Last Ping",  style="dim")
            t.add_column("Fail Count", justify="center")
            for bot in manager.bots:
                alive  = bot._keepalive_thread and bot._keepalive_thread.is_alive()
                status = "[bright_green]RUNNING[/bright_green]" if alive else "[dim]stopped[/dim]"
                ivl    = f"{bot._keepalive_interval}h" if alive else "—"
                fails  = str(bot._ping_fails) if bot._ping_fails else "—"
                t.add_row(f"@{bot.username}", status, ivl, bot._last_ping, fails)
            console.print(t)
            rule()

            ka_opts = [
                ("1", "Start keep-alive    for one account"),
                ("2", "Start keep-alive    for ALL logged-in accounts"),
                ("3", "Stop keep-alive     for one account"),
                ("4", "Stop keep-alive     for ALL accounts"),
                ("0", "Back"),
            ]
            for k, v in ka_opts:
                console.print(f"  [{k}]  {v}")
            rule()
            ka = Prompt.ask("  Select", choices=[o[0] for o in ka_opts])

            if ka == "0":
                continue
            elif ka in ("1", "3"):
                username = Prompt.ask("  Account", choices=[b.username for b in manager.bots])
                bot      = next(b for b in manager.bots if b.username == username)
                if ka == "1":
                    if not bot.logged_in:
                        warn(f"@{username} is not logged in — login first"); continue
                    hrs = int(Prompt.ask("  Ping interval (hours)", default="2"))
                    bot.start_keepalive(hrs)
                    ok(f"Keep-alive started for @{username}  every {hrs}h")
                else:
                    bot.stop_keepalive()
                    ok(f"Keep-alive stopped for @{username}")
            elif ka == "2":
                active = [b for b in manager.bots if b.logged_in]
                if not active:
                    warn("No logged-in accounts"); continue
                hrs = int(Prompt.ask("  Ping interval (hours)", default="2"))
                for bot in active:
                    bot.start_keepalive(hrs)
                ok(f"Keep-alive started for {len(active)} account(s)  every {hrs}h")
            elif ka == "4":
                for bot in manager.bots:
                    bot.stop_keepalive()
                ok("Keep-alive stopped for all accounts")

        # ── 9. Ping sessions ──────────────────────────────────────────────────
        elif choice == "9":
            active = [b for b in manager.bots if b.logged_in]
            if not active:
                warn("No logged-in accounts"); continue

            info(f"Pinging {len(active)} session(s)...")
            t = Table(title="  SESSION HEALTH CHECK", show_header=True,
                      header_style="bold cyan", box=box.SIMPLE_HEAD)
            t.add_column("Account",   style="bold white", min_width=18)
            t.add_column("Result",    justify="center")
            t.add_column("Last Ping", style="dim")
            for bot in active:
                alive  = bot.ping_session()
                result = "[bright_green]ALIVE[/bright_green]" if alive else "[bright_red]DEAD[/bright_red]"
                t.add_row(f"@{bot.username}", result, bot._last_ping)
            console.print(t)

        # ── N. New account (create) ───────────────────────────────────────────
        elif choice == "N":
            menu_create_account(manager, cfg)


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT CREATOR MENU
# ─────────────────────────────────────────────────────────────────────────────

def _pick_proxy(pm, username: str = "") -> str:
    """
    Smart proxy picker used throughout account creation.
    If providers are configured, shows a clean menu.
    If none, asks for a manual URL (or none).
    Returns either a full proxy URL, a __provider__NAME sentinel, or "".
    """
    providers = pm.list_providers()

    if not providers:
        console.print("  [dim]No providers configured yet. You can set one up in [R] Proxy Manager.[/dim]")
        raw = Prompt.ask("  Proxy URL  [http://user:pass@host:port, blank to skip]", default="").strip()
        return raw

    pnames = [p["name"] for p in providers]
    console.print(f"  [dim]Configured providers: {', '.join(pnames)}[/dim]")
    src = Prompt.ask(
        "  Proxy source",
        choices=["provider", "manual", "none"],
        default="provider",
    )
    if src == "provider":
        pname = pnames[0] if len(pnames) == 1 else Prompt.ask("  Provider", choices=pnames)
        if len(pnames) == 1:
            info(f"Using provider '{pnames[0]}'")
        return f"__provider__{pname}"
    elif src == "manual":
        return Prompt.ask("  Proxy URL  [http://user:pass@host:port]").strip()
    return ""


def menu_create_account(manager, cfg):
    hdr("CREATE NEW INSTAGRAM ACCOUNT")
    console.print("[dim]  Registers a brand-new account via the Instagram API.[/dim]")
    console.print("[dim]  Use a fresh proxy per account for best success rate.[/dim]\n")

    from account_creator import (
        AccountCreator, validate_username, validate_password,
        validate_email, validate_dob, suggest_usernames, generate_password,
    )
    from proxy_manager import get_proxy_manager as _gpm_c
    pm = _gpm_c()

    opts = [
        ("1", "Create account       step-by-step guided setup"),
        ("2", "Quick create         generate username + password automatically"),
        ("3", "Check username       verify if a username is available"),
        ("0", "Back"),
    ]
    for k, v in opts:
        console.print(f"  [{k}]  {v}")
    rule()
    choice = Prompt.ask("  Select", choices=[o[0] for o in opts])
    if choice == "0":
        return

    # ── 3. Check username availability ───────────────────────────────────────
    if choice == "3":
        username = Prompt.ask("  Username to check").strip().lstrip("@")
        err = validate_username(username)
        if err:
            warn(f"Invalid username: {err}"); return
        # Use a provider proxy for the check if available
        providers = pm.list_providers()
        if providers:
            try:
                check_url = pm.build_proxy_url(providers[0]["name"], username)
            except Exception:
                check_url = ""
        else:
            check_url = ""
        with console.status("[bold cyan]  Checking...[/bold cyan]"):
            available = AccountCreator(check_url).check_username_available(username)
        if available:
            ok(f"@{username} appears to be available")
        else:
            warn(f"@{username} is already taken")
        return

    # ── Proxy selection (shared for options 1 and 2) ──────────────────────────
    console.print("\n  [dim]Proxy is strongly recommended for account creation.[/dim]")
    console.print("  [dim]Instagram flags multiple signups from the same IP.[/dim]\n")
    proxy_sentinel = _pick_proxy(pm)

    creator = AccountCreator("")   # actual proxy URL resolved in _do_create

    # ── 2. Quick create ───────────────────────────────────────────────────────
    if choice == "2":
        hdr("QUICK CREATE")
        full_name = Prompt.ask("  Full name  [e.g. Priya Sharma]").strip()
        if not full_name:
            warn("Full name cannot be empty"); return

        suggestions = suggest_usernames(full_name, count=6)
        console.print("\n  [dim]Suggested usernames:[/dim]")
        for i, s in enumerate(suggestions, 1):
            console.print(f"  [{i}]  {s}")
        console.print("  [M]  Enter manually")
        rule()
        sug_choice = Prompt.ask(
            "  Pick a username",
            choices=[str(i) for i in range(1, len(suggestions)+1)] + ["m", "M"],
        ).upper()
        username = (Prompt.ask("  Username").strip().lstrip("@")
                    if sug_choice == "M" else suggestions[int(sug_choice) - 1])

        err = validate_username(username)
        if err:
            warn(f"Invalid username: {err}"); return

        with console.status("[bold cyan]  Checking username availability...[/bold cyan]"):
            available = creator.check_username_available(username)
        if not available:
            warn(f"@{username} is already taken — try a different one"); return
        ok(f"@{username} is available")

        email = Prompt.ask("  Email address")
        err   = validate_email(email)
        if err:
            warn(f"Invalid email: {err}"); return

        password = generate_password()
        info(f"Generated password: [bold]{password}[/bold]  (save this!)")
        if not Confirm.ask("  Use this password?", default=True):
            password = Prompt.ask("  Enter your own password", password=False)
            err = validate_password(password)
            if err:
                warn(f"Weak password: {err}"); return

        console.print("\n  [dim]Date of birth — must be 18+ years old[/dim]")
        year  = int(Prompt.ask("  Birth year  [e.g. 2000]"))
        month = int(Prompt.ask("  Birth month [1-12]"))
        day   = int(Prompt.ask("  Birth day   [1-31]"))
        err   = validate_dob(year, month, day)
        if err:
            warn(f"Invalid DOB: {err}"); return

        _do_create(creator, manager, cfg,
                   full_name, username, email, password, year, month, day,
                   proxy_sentinel=proxy_sentinel)
        return

    # ── 1. Guided step-by-step ────────────────────────────────────────────────
    hdr("GUIDED ACCOUNT CREATION")

    full_name = Prompt.ask("  Full name  [shown on profile, e.g. Priya Sharma]").strip()
    if not full_name:
        warn("Full name cannot be empty"); return

    suggestions = suggest_usernames(full_name, count=5)
    console.print(f"\n  [dim]Username suggestions based on '{full_name}':[/dim]")
    for i, s in enumerate(suggestions, 1):
        console.print(f"  [{i}]  {s}")
    console.print("  [M]  Enter manually")
    rule()
    while True:
        sug_choice = Prompt.ask(
            "  Pick a username",
            choices=[str(i) for i in range(1, len(suggestions)+1)] + ["m", "M"],
        ).upper()
        username = (suggestions[int(sug_choice)-1] if sug_choice != "M"
                    else Prompt.ask("  Custom username").strip().lstrip("@"))
        err = validate_username(username)
        if err:
            warn(f"Invalid username: {err}"); continue
        with console.status("[bold cyan]  Checking availability...[/bold cyan]"):
            available = creator.check_username_available(username)
        if available:
            ok(f"@{username} is available"); break
        warn(f"@{username} is taken — try another")

    while True:
        email = Prompt.ask("  Email address").strip()
        err   = validate_email(email)
        if err:
            warn(f"Invalid email: {err}"); continue
        break

    console.print("\n  [dim]Password requirements: 6+ chars, 1 uppercase, 1 number[/dim]")
    gen_pwd = generate_password()
    info(f"Generated password: [bold]{gen_pwd}[/bold]")
    if Confirm.ask("  Use generated password?", default=True):
        password = gen_pwd
    else:
        while True:
            password = Prompt.ask("  Password", password=False)
            err      = validate_password(password)
            if err:
                warn(f"Weak password: {err}"); continue
            break

    console.print("\n  [dim]Date of birth — Instagram requires 18+[/dim]")
    while True:
        year  = int(Prompt.ask("  Birth year  [e.g. 1998]"))
        month = int(Prompt.ask("  Birth month [1-12]"))
        day   = int(Prompt.ask("  Birth day   [1-31]"))
        err   = validate_dob(year, month, day)
        if err:
            warn(f"Invalid DOB: {err}"); continue
        break

    # Resolve proxy display label for the review panel
    proxy_display = (proxy_sentinel.replace("__provider__", "provider: ")
                     if proxy_sentinel.startswith("__provider__")
                     else proxy_sentinel or "none")

    console.print(Panel(
        f"  Full name:  [bold]{full_name}[/bold]\n"
        f"  Username:   [bold bright_cyan]@{username}[/bold bright_cyan]\n"
        f"  Email:      [dim]{email}[/dim]\n"
        f"  Password:   [bold]{password}[/bold]  [dim](save this!)[/dim]\n"
        f"  DOB:        [dim]{year}-{month:02d}-{day:02d}[/dim]\n"
        f"  Proxy:      [dim]{proxy_display}[/dim]",
        title="  REVIEW ACCOUNT DETAILS",
        border_style="cyan", title_align="left",
    ))

    if not Confirm.ask("\n  Proceed with account creation?", default=True):
        info("Cancelled"); return

    _do_create(creator, manager, cfg,
               full_name, username, email, password, year, month, day,
               proxy_sentinel=proxy_sentinel)


def _do_create(creator, manager, cfg,
               full_name, username, email, password, year, month, day,
               proxy_sentinel: str = ""):
    """
    Shared logic: attempt creation, handle challenge, add to manager,
    offer to save to config.yaml.
    proxy_sentinel: either a full URL, a '__provider__name' sentinel, or empty.
    """
    from account_creator import AccountCreator

    # ── Resolve proxy sentinel ───────────────────────────────────────────
    from proxy_manager import get_proxy_manager as _gpm_dc
    _pm_dc    = _gpm_dc()
    proxy_url = ""
    if proxy_sentinel.startswith("__provider__"):
        pname = proxy_sentinel.replace("__provider__", "")
        try:
            proxy_url = _pm_dc.assign_from_provider(username, pname)
            ok(f"Assigned sticky proxy from '{pname}' for @{username}")
        except Exception as e:
            warn(f"Could not assign proxy from provider: {e}")
    elif proxy_sentinel:
        proxy_url = proxy_sentinel
        _pm_dc.assign(username, proxy_url)

    if proxy_url:
        creator.proxy = proxy_url
        creator._cl   = None   # force rebuild with new proxy

    # Register challenge handler for email verification
    challenge_code = [None]

    def _challenge_handler(uname, choice):
        try:
            from instagrapi.mixins.challenge import ChallengeChoice as CC
            kind = "EMAIL" if choice == CC.EMAIL else "SMS"
        except Exception:
            kind = "EMAIL/SMS"
        console.print(
            f"\n  [bold bright_yellow]Verification required for @{uname}[/bold bright_yellow]\n"
            f"  Instagram sent a [bold]{kind}[/bold] code to {email}.\n"
            f"  Check your inbox and enter the 6-digit code.\n"
        )
        from rich.prompt import Prompt as P
        code = P.ask(f"  Enter code for @{uname}").strip()
        challenge_code[0] = code
        return code

    info(f"Sending signup request for @{username}...")
    with console.status("[bold cyan]  Creating account...[/bold cyan]"):
        result = creator.create(
            full_name        = full_name,
            username         = username,
            email            = email,
            password         = password,
            year             = year,
            month            = month,
            day              = day,
            challenge_handler= _challenge_handler,
        )

    if not result["ok"]:
        warn(f"Account creation failed: {result['error']}")
        console.print("\n  [dim]Common causes:[/dim]")
        console.print("  [dim]· Same IP/proxy used for too many signups — use a fresh proxy[/dim]")
        console.print("  [dim]· Email already registered — use a different email[/dim]")
        console.print("  [dim]· Username taken — try a different username[/dim]")
        console.print("  [dim]· Instagram rate-limit — wait 30+ minutes before retrying[/dim]")
        return

    ok(f"Account @{username} created successfully!")
    info(f"Session saved to {result['session_file']}")

    console.print(Panel(
        f"  Username:  [bold bright_cyan]@{username}[/bold bright_cyan]\n"
        f"  Password:  [bold]{password}[/bold]\n"
        f"  Email:     [dim]{email}[/dim]\n"
        f"  Session:   [dim]{result['session_file']}[/dim]\n\n"
        f"  [yellow]Save these credentials somewhere safe![/yellow]\n"
        f"  [dim]New account starts on 'conservative' behaviour profile.[/dim]\n"
        f"  [dim]Run Human Behaviour sessions for 3-5 days before automating.[/dim]",
        title="  ACCOUNT CREATED",
        border_style="bright_green", title_align="left",
    ))

    # Add to live session
    from bot_engine import InstagramBot
    from proxy_manager import get_proxy_manager as _gpm2
    account_cfg = result["account_cfg"]
    # Ensure proxy is stored in proxy_manager for the new account
    _pm2 = _gpm2()
    if account_cfg.get("proxy"):
        _pm2.assign(account_cfg["username"], account_cfg["proxy"])
    bot = InstagramBot(account_cfg)
    # Session file was already saved by the creator, so login will auto-restore it
    from cli.shared import register_challenge_handler
    register_challenge_handler(bot)
    with console.status(f"[bold cyan]  Loading @{username} into session...[/bold cyan]"):
        bot_ok = bot.login()

    if bot_ok:
        manager.bots.append(bot)
        ok(f"@{username} loaded into session and ready")
    else:
        warn("Could not load into session automatically — restart the bot to load this account")

    # Save to config.yaml
    if Confirm.ask("  Save to config.yaml so it loads on next startup?", default=True):
        cfg["accounts"].append(account_cfg)
        try:
            save_config(cfg)
            ok(f"@{username} saved to config/config.yaml")
        except Exception as e:
            warn(f"Could not save config: {e}")