"""
cli/menu_proxy.py  —  Proxy Management Menu

Covers:
  - Add / edit / remove proxy providers (Oxylabs, Brightdata, Smartproxy, manual)
  - Assign proxies to accounts (one-by-one or bulk from provider)
  - View current assignments
  - Health check (test a proxy's connectivity + show exit IP)
  - Apply stored proxies to all loaded bots live
"""

from rich.prompt import Prompt, Confirm
from rich.table  import Table
from rich.panel  import Panel
from rich        import box

from proxy_manager import (
    ProxyManager, get_proxy_manager,
    PROVIDER_TEMPLATES, parse_manual_url, _mask,
)
from cli.shared import console, hdr, rule, ok, info, warn


def menu_proxy(manager, cfg):
    pm = get_proxy_manager()

    while True:
        hdr("PROXY MANAGER")

        # ── Summary panel ────────────────────────────────────────────────────
        providers   = pm.list_providers()
        assignments = pm.list_assignments()
        n_assigned  = sum(1 for b in manager.bots if assignments.get(b.username))
        n_total     = len(manager.bots)

        console.print(Panel(
            f"  Providers configured:  [bold]{len(providers)}[/bold]\n"
            f"  Accounts with proxy:   [bold bright_cyan]{n_assigned}[/bold bright_cyan] / {n_total}\n"
            f"  Proxy config file:     [dim]config/proxies.yaml[/dim]",
            title="  PROXY STATUS", border_style="cyan", title_align="left",
        ))

        opts = [
            ("1", "Add / edit provider    Oxylabs, Brightdata, Smartproxy, or manual"),
            ("2", "Remove provider"),
            ("3", "View providers         show all configured providers"),
            ("4", "Assign to account      pick provider → assign sticky proxy to one account"),
            ("5", "Assign to all          bulk-assign proxies to every loaded account"),
            ("6", "Set manual proxy       paste a full proxy URL for one account"),
            ("7", "Remove assignment      clear proxy for an account"),
            ("8", "View assignments       see which account uses which proxy"),
            ("9", "Health check           test a proxy's connectivity + show exit IP"),
            ("A", "Apply to live bots     push stored proxies to currently loaded bots"),
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

        # ── 1. Add / edit provider ────────────────────────────────────────────
        elif choice == "1":
            hdr("ADD / EDIT PROVIDER")

            # Show provider type options
            t = Table(show_header=True, header_style="bold cyan",
                      box=box.SIMPLE_HEAD, title="  PROVIDER TYPES")
            t.add_column("Key",         style="bold white", width=14)
            t.add_column("Label",       min_width=22)
            t.add_column("Description", style="dim")
            for key, tmpl in PROVIDER_TEMPLATES.items():
                t.add_row(key, tmpl["label"], tmpl["description"])
            console.print(t)
            rule()

            ptype = Prompt.ask("  Provider type", choices=list(PROVIDER_TEMPLATES.keys()))
            tmpl  = PROVIDER_TEMPLATES[ptype]

            name = Prompt.ask(
                "  Provider name  [used to identify this config, e.g. 'oxylabs_us']",
                default=ptype,
            ).strip()

            if ptype == "static":
                # For static, just paste the full URL and we decompose it
                console.print("  [dim]Enter the full proxy URL (you can assign it to accounts later)[/dim]")
                raw_url = Prompt.ask("  Proxy URL  [http://user:pass@host:port]").strip()
                parsed  = parse_manual_url(raw_url)
                if not parsed:
                    warn("Invalid proxy URL format — expected http://user:pass@host:port"); continue
                host     = parsed["host"]
                port     = parsed["port"]
                username = parsed["username"]
                password = parsed["password"]
                country  = "US"
            else:
                # Pre-fill hints from template
                host    = Prompt.ask("  Host", default=tmpl["host_hint"]).strip()
                port    = int(Prompt.ask("  Port", default=str(tmpl["port"])))

                # Oxylabs: show the username format hint
                if ptype == "oxylabs":
                    console.print("  [dim]Oxylabs username format: customer-{id}-cc-{country}[/dim]")
                    console.print("  [dim]Example: customer-meldit_vAxIO-cc-US[/dim]")

                username = Prompt.ask("  Username  [base, without sessid suffix]").strip()
                password = Prompt.ask("  Password").strip()
                country  = Prompt.ask("  Country code  [2-letter, e.g. US, IN, GB]", default="US").strip().upper()

            pm.add_provider(name, host, port, username, password, country, ptype)
            ok(f"Provider '{name}' saved to config/proxies.yaml")

            # Offer to immediately assign to all accounts
            if manager.bots and ptype != "static":
                if Confirm.ask(f"  Assign '{name}' sticky proxies to all {len(manager.bots)} loaded accounts now?", default=True):
                    results = pm.assign_all_from_provider(
                        [b.username for b in manager.bots], name,
                    )
                    for uname, url in results.items():
                        ok(f"@{uname}  →  {_mask(url)}")
                    # Apply live
                    pm.apply_to_all_bots(manager)
                    ok("Proxies applied to all live bots")

        # ── 2. Remove provider ────────────────────────────────────────────────
        elif choice == "2":
            if not providers:
                warn("No providers configured"); continue
            name = Prompt.ask("  Remove provider", choices=[p["name"] for p in providers])
            if Confirm.ask(f"  Remove provider '{name}'?", default=False):
                pm.remove_provider(name)
                ok(f"Provider '{name}' removed")

        # ── 3. View providers ─────────────────────────────────────────────────
        elif choice == "3":
            if not providers:
                warn("No providers configured yet"); continue
            t = Table(title="  CONFIGURED PROVIDERS", show_header=True,
                      header_style="bold cyan", box=box.SIMPLE_HEAD)
            t.add_column("Name",     style="bold white", min_width=16)
            t.add_column("Type",     min_width=12)
            t.add_column("Host",     style="dim", min_width=22)
            t.add_column("Port",     justify="right")
            t.add_column("Username", style="dim", min_width=28)
            t.add_column("Country",  justify="center")
            for p in providers:
                t.add_row(
                    p["name"], p.get("type","?"),
                    p["host"], str(p["port"]),
                    p["username"][:36], p.get("country","?"),
                )
            console.print(t)

        # ── 4. Assign to one account ──────────────────────────────────────────
        elif choice == "4":
            if not providers:
                warn("No providers configured — add one first (option 1)"); continue
            if not manager.bots:
                warn("No accounts loaded"); continue

            usernames    = [b.username for b in manager.bots]
            provider_names = [p["name"] for p in providers]

            username = Prompt.ask("  Account", choices=usernames)
            provider = Prompt.ask("  Provider", choices=provider_names)

            url = pm.assign_from_provider(username, provider)
            ok(f"@{username}  →  {_mask(url)}")

            # Apply live if bot is loaded
            bot = next((b for b in manager.bots if b.username == username), None)
            if bot:
                pm.apply_to_bot(bot)
                ok(f"Proxy applied to live bot @{username}")

        # ── 5. Assign to all ──────────────────────────────────────────────────
        elif choice == "5":
            if not providers:
                warn("No providers configured — add one first (option 1)"); continue
            if not manager.bots:
                warn("No accounts loaded"); continue

            provider_names = [p["name"] for p in providers]
            provider = Prompt.ask("  Provider to use for all accounts", choices=provider_names)

            usernames = [b.username for b in manager.bots]
            info(f"Assigning '{provider}' sticky proxies to {len(usernames)} account(s)...")
            results = pm.assign_all_from_provider(usernames, provider)

            t = Table(title="  PROXY ASSIGNMENTS", show_header=True,
                      header_style="bold cyan", box=box.SIMPLE_HEAD)
            t.add_column("Account", style="bold white", min_width=20)
            t.add_column("Proxy URL  (password masked)", style="dim")
            for uname, url in results.items():
                t.add_row(f"@{uname}", _mask(url))
            console.print(t)

            if Confirm.ask("  Apply to live bots now?", default=True):
                pm.apply_to_all_bots(manager)
                ok("Proxies applied to all live bots")

        # ── 6. Set manual proxy for one account ───────────────────────────────
        elif choice == "6":
            if not manager.bots:
                warn("No accounts loaded"); continue
            username = Prompt.ask("  Account", choices=[b.username for b in manager.bots])
            console.print("  [dim]Format: http://user:pass@host:port  or  socks5://...[/dim]")
            raw_url = Prompt.ask("  Proxy URL").strip()
            if not parse_manual_url(raw_url):
                warn("Invalid URL format"); continue
            pm.assign(username, raw_url)
            ok(f"Proxy set for @{username}: {_mask(raw_url)}")
            bot = next((b for b in manager.bots if b.username == username), None)
            if bot:
                pm.apply_to_bot(bot)
                ok(f"Applied to live bot @{username}")

        # ── 7. Remove assignment ──────────────────────────────────────────────
        elif choice == "7":
            if not assignments:
                warn("No proxy assignments found"); continue
            username = Prompt.ask("  Remove proxy for account", choices=list(assignments.keys()))
            pm.remove_assignment(username)
            # Also clear from live bot
            bot = next((b for b in manager.bots if b.username == username), None)
            if bot:
                try:
                    bot.cl.set_proxy("")
                    bot.proxy = ""
                except Exception:
                    pass
            ok(f"Proxy removed for @{username}")

        # ── 8. View assignments ───────────────────────────────────────────────
        elif choice == "8":
            if not assignments and not manager.bots:
                warn("No assignments and no accounts loaded"); continue

            t = Table(title="  PROXY ASSIGNMENTS", show_header=True,
                      header_style="bold cyan", box=box.SIMPLE_HEAD)
            t.add_column("Account",    style="bold white", min_width=20)
            t.add_column("Assigned",   justify="center")
            t.add_column("Live Bot",   justify="center")
            t.add_column("Proxy URL   (password masked)", style="dim")

            all_usernames = set(assignments.keys()) | {b.username for b in manager.bots}
            for uname in sorted(all_usernames):
                stored_url = assignments.get(uname, "")
                bot        = next((b for b in manager.bots if b.username == uname), None)
                live_proxy = bot.proxy if bot else ""
                assigned   = "[bright_green]YES[/bright_green]" if stored_url else "[dim]none[/dim]"
                live_ok    = "[bright_green]YES[/bright_green]" if live_proxy else "[dim]none[/dim]"
                display_url = _mask(stored_url or live_proxy or "—")
                t.add_row(f"@{uname}", assigned, live_ok, display_url)
            console.print(t)

        # ── 9. Health check ───────────────────────────────────────────────────
        elif choice == "9":
            hdr("PROXY HEALTH CHECK")
            opts9 = [
                ("1", "Test a specific account's proxy"),
                ("2", "Test all assigned proxies"),
                ("3", "Test a custom URL"),
                ("0", "Back"),
            ]
            for k, v in opts9:
                console.print(f"  [{k}]  {v}")
            rule()
            c9 = Prompt.ask("  Select", choices=[o[0] for o in opts9])

            if c9 == "0":
                continue

            urls_to_test: list[tuple[str, str]] = []  # (label, url)

            if c9 == "1":
                if not manager.bots:
                    warn("No accounts loaded"); continue
                username  = Prompt.ask("  Account", choices=[b.username for b in manager.bots])
                proxy_url = assignments.get(username, "")
                if not proxy_url:
                    warn(f"@{username} has no proxy assigned"); continue
                urls_to_test = [(f"@{username}", proxy_url)]

            elif c9 == "2":
                if not assignments:
                    warn("No assignments found"); continue
                urls_to_test = [(f"@{u}", url) for u, url in assignments.items()]

            elif c9 == "3":
                raw = Prompt.ask("  Proxy URL").strip()
                if not raw:
                    continue
                urls_to_test = [("custom", raw)]

            t = Table(title="  HEALTH CHECK RESULTS", show_header=True,
                      header_style="bold cyan", box=box.SIMPLE_HEAD)
            t.add_column("Account / Label", style="bold white", min_width=20)
            t.add_column("Status",          justify="center")
            t.add_column("Exit IP",         style="dim", min_width=16)
            t.add_column("Latency",         justify="right")
            t.add_column("Proxy",           style="dim")

            for label, url in urls_to_test:
                info(f"Testing {label}...")
                with console.status(f"[bold cyan]  Checking {label}...[/bold cyan]"):
                    result = pm.check_proxy(url)
                if result["ok"]:
                    status  = "[bright_green]OK[/bright_green]"
                    ip      = result["ip"]
                    latency = f"{result['latency_ms']} ms"
                else:
                    status  = "[bright_red]FAIL[/bright_red]"
                    ip      = result.get("error","?")[:30]
                    latency = "—"
                t.add_row(label, status, ip, latency, _mask(url)[:50])
            console.print(t)

        # ── A. Apply to live bots ─────────────────────────────────────────────
        elif choice == "A":
            if not manager.bots:
                warn("No accounts loaded"); continue
            results = pm.apply_to_all_bots(manager)
            for uname, applied in results.items():
                if applied:
                    ok(f"@{uname}  proxy applied")
                else:
                    warn(f"@{uname}  no proxy assigned — use option 4 or 5 to assign one")