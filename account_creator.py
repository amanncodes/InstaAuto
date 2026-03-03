"""
account_creator.py  —  Instagram Account Registration Engine

Drives the instagrapi signup flow to create fresh Instagram accounts
directly from the CLI without opening a browser.

FLOW
────
  1.  Collect account details from user (name, username, email, password, DOB)
  2.  Validate inputs locally before hitting the API
  3.  Check username availability via instagrapi
  4.  Optionally use a proxy for the signup request (recommended)
  5.  Send signup request via instagrapi's account_create()
  6.  Handle any email verification challenge automatically
  7.  Save credentials + session to disk
  8.  Return account_cfg dict ready to pass to AccountManager

NOTES
─────
- Instagram restricts signups aggressively: use a fresh proxy per account
- New accounts should warm up slowly: 3–5 days of human browsing before
  any follow/like actions
- DOB must be >= 18 years ago (Instagram requirement)
- Username: 1–30 chars, letters/numbers/periods/underscores only
- Password: >= 6 chars

IMPORTANT
─────────
Mass automated account creation violates Instagram's Terms of Service.
This module exists to help developers and operators create a small number
of legitimate managed accounts. Use responsibly.
"""

import re
import random
import string
import logging
from datetime import datetime, date
from pathlib  import Path

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

USERNAME_RE = re.compile(r'^[a-zA-Z0-9._]{1,30}$')
EMAIL_RE    = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def validate_username(username: str) -> str | None:
    """Returns error string or None if valid."""
    if not username:
        return "Username cannot be empty"
    if not USERNAME_RE.match(username):
        return "Username may only contain letters, numbers, periods, and underscores (max 30 chars)"
    if username.startswith(".") or username.endswith("."):
        return "Username cannot start or end with a period"
    if ".." in username:
        return "Username cannot contain consecutive periods"
    return None


def validate_password(password: str) -> str | None:
    if len(password) < 6:
        return "Password must be at least 6 characters"
    if password.lower() == password:
        return "Password should contain at least one uppercase letter"
    if not any(c.isdigit() for c in password):
        return "Password should contain at least one number"
    return None


def validate_email(email: str) -> str | None:
    if not EMAIL_RE.match(email):
        return "Invalid email address format"
    return None


def validate_dob(year: int, month: int, day: int) -> str | None:
    try:
        dob = date(year, month, day)
    except ValueError as e:
        return f"Invalid date: {e}"
    today    = date.today()
    age_days = (today - dob).days
    if age_days < 18 * 365:
        return "Must be at least 18 years old (Instagram requirement)"
    if age_days > 120 * 365:
        return "Date of birth seems too far in the past"
    return None


def suggest_usernames(full_name: str, count: int = 5) -> list[str]:
    """
    Generate username suggestions from a full name.
    Returns a list of up to `count` suggestions.
    """
    base = full_name.lower().replace(" ", "")
    base = re.sub(r'[^a-z0-9]', '', base)
    if not base:
        base = "user"

    parts  = full_name.lower().split()
    first  = re.sub(r'[^a-z]', '', parts[0])   if parts     else base
    last   = re.sub(r'[^a-z]', '', parts[-1])  if len(parts) > 1 else ""

    suggestions = []
    rand_num = lambda: random.randint(10, 9999)

    candidates = [
        base,
        f"{base}{rand_num()}",
        f"{first}.{last}" if last else f"{first}{rand_num()}",
        f"{first}_{last}" if last else f"{first}_{rand_num()}",
        f"_{base}_",
        f"{base}.official",
        f"{first}{last}{rand_num()}" if last else f"{first}{rand_num()}",
    ]

    seen = set()
    for c in candidates:
        c = c[:30]
        if c and c not in seen and not validate_username(c):
            suggestions.append(c)
            seen.add(c)
        if len(suggestions) >= count:
            break

    return suggestions


def generate_password(length: int = 12) -> str:
    """Generate a secure random password meeting Instagram's requirements."""
    chars = string.ascii_letters + string.digits + "!@#$"
    while True:
        pwd = ''.join(random.choices(chars, k=length))
        if (any(c.isupper() for c in pwd) and
                any(c.islower() for c in pwd) and
                any(c.isdigit() for c in pwd)):
            return pwd


# ─────────────────────────────────────────────────────────────────────────────
# CORE CREATOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class AccountCreator:
    """
    Drives the instagrapi signup API to register new Instagram accounts.

    Usage:
        creator = AccountCreator(proxy="http://user:pass@host:port")
        result  = creator.create(
            full_name = "Priya Sharma",
            username  = "priya.sharma.ig",
            email     = "priya@example.com",
            password  = "Secret123!",
            year=2000, month=6, day=15,
        )
        if result["ok"]:
            account_cfg = result["account_cfg"]  # ready for AccountManager
    """

    def __init__(self, proxy: str = ""):
        self.proxy = proxy
        self._cl   = None  # instagrapi Client, created on demand

    def _build_client(self):
        from instagrapi import Client
        cl = Client()
        cl.delay_range = [2, 5]
        if self.proxy:
            cl.set_proxy(self.proxy)
        return cl

    def check_username_available(self, username: str) -> bool:
        """
        Returns True if the username appears available.
        Makes a lightweight API call — does NOT require being logged in.
        """
        try:
            cl = self._build_client()
            # check_username returns True if taken, False if available
            taken = cl.username_is_available(username)
            return not taken
        except Exception as e:
            log.warning(f"Could not check username availability: {e}")
            return True   # assume available if check fails

    def create(
        self,
        full_name: str,
        username:  str,
        email:     str,
        password:  str,
        year:      int,
        month:     int,
        day:       int,
        challenge_handler=None,
    ) -> dict:
        """
        Register a new Instagram account.

        challenge_handler: optional callable(username, choice) -> code str
            Called if Instagram sends an email verification code.
            If None, raises on challenge.

        Returns:
            {"ok": True,  "account_cfg": {...}, "username": str}
            {"ok": False, "error": str}
        """
        # ── Local validation ──────────────────────────────────────────────────
        for check, value in [
            (validate_username, username),
            (validate_password, password),
            (validate_email,    email),
        ]:
            err = check(value)
            if err:
                return {"ok": False, "error": err}

        dob_err = validate_dob(year, month, day)
        if dob_err:
            return {"ok": False, "error": dob_err}

        try:
            from instagrapi import Client
            from instagrapi.exceptions import (
                ChallengeRequired, BadPassword, LoginRequired,
            )

            cl = self._build_client()

            if challenge_handler:
                cl.challenge_code_handler = challenge_handler

            log.info(f"Sending signup request for @{username}  email={email}")

            result = cl.account_register(
                username   = username,
                password   = password,
                email      = email,
                full_name  = full_name,
                year       = year,
                month      = month,
                day        = day,
            )

            if not result:
                return {"ok": False, "error": "Signup returned empty response — Instagram may have rejected the request"}

            # Save session immediately
            session_file = Path(f"sessions/{username}.json")
            session_file.parent.mkdir(exist_ok=True)
            cl.dump_settings(str(session_file))

            log.info(f"Account @{username} created and session saved")

            account_cfg = {
                "username":          username,
                "password":          password,
                "behaviour_profile": "conservative",   # new accounts should start slow
            }
            if self.proxy:
                account_cfg["proxy"] = self.proxy

            return {
                "ok":          True,
                "username":    username,
                "account_cfg": account_cfg,
                "session_file": str(session_file),
            }

        except ChallengeRequired:
            return {"ok": False, "error": "Instagram sent a challenge but no handler was registered. Use set_challenge_code_handler first."}
        except Exception as e:
            err_str = str(e)
            # Translate common instagrapi error codes
            if "checkpoint_required" in err_str.lower():
                return {"ok": False, "error": "Checkpoint required — Instagram wants phone/email verification. Try a different IP or proxy."}
            if "username_is_taken" in err_str.lower():
                return {"ok": False, "error": f"Username @{username} is already taken"}
            if "email_is_taken" in err_str.lower():
                return {"ok": False, "error": f"Email {email} is already registered"}
            if "signup_block" in err_str.lower():
                return {"ok": False, "error": "Instagram blocked this signup — try a fresh proxy or wait before retrying"}
            return {"ok": False, "error": str(e)}