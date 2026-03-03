"""
proxy_manager.py  —  Proxy Configuration and Per-Account Assignment Engine

Supports:
  - Oxylabs residential/datacenter rotating proxies (and similar providers)
  - Static proxies (one fixed IP per account)
  - Per-account sticky sessions (username suffix: customer-X-sessid-ACCOUNT)
  - Manual single-proxy entry
  - Proxy health checking (connect test)
  - Persistent storage in config/proxies.yaml

Proxy URL formats supported:
  http://user:pass@host:port                    static / manual
  http://user-sessid-{account}:pass@host:port   sticky session (auto-generated)
  socks5://user:pass@host:port                  SOCKS5

Oxylabs sticky session format:
  username: customer-{username}-cc-{country}-sessid-{session_id}
  e.g.    : customer-meldit_vAxIO-cc-US-sessid-dhuniwaalebaba
"""

import re
import time
import random
import string
import logging
from pathlib import Path

log = logging.getLogger(__name__)

PROXIES_FILE = Path("config/proxies.yaml")

# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

PROVIDER_TEMPLATES = {
    "oxylabs": {
        "label":       "Oxylabs Residential",
        "host_hint":   "pr.oxylabs.io",
        "port":        7777,
        "url_pattern": "http://{username}:{password}@{host}:{port}",
        "sticky_user": "customer-{base_user}-cc-{country}-sessid-{session_id}",
        "description": "Rotating residential. Sticky session per account via sessid suffix.",
    },
    "brightdata": {
        "label":       "Bright Data (Luminati)",
        "host_hint":   "zproxy.lum-superproxy.io",
        "port":        22225,
        "url_pattern": "http://{username}-session-{session_id}:{password}@{host}:{port}",
        "sticky_user": "{base_user}-session-{session_id}",
        "description": "Rotating residential. Sticky session via session suffix.",
    },
    "smartproxy": {
        "label":       "Smartproxy",
        "host_hint":   "gate.smartproxy.com",
        "port":        7000,
        "url_pattern": "http://{username}:{password}@{host}:{port}",
        "sticky_user": "{base_user}-sessid-{session_id}",
        "description": "Rotating residential. Sticky via sessid suffix.",
    },
    "static": {
        "label":       "Static / Manual proxy",
        "host_hint":   "",
        "port":        0,
        "url_pattern": "http://{username}:{password}@{host}:{port}",
        "sticky_user": None,
        "description": "One fixed IP. Enter the full URL manually.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def _load_proxies_file() -> dict:
    """Load config/proxies.yaml. Returns {} if missing."""
    try:
        import yaml
        if PROXIES_FILE.exists():
            with open(PROXIES_FILE, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception as e:
        log.warning(f"Could not load proxies.yaml: {e}")
    return {}


def _save_proxies_file(data: dict):
    """Write config/proxies.yaml atomically."""
    import yaml
    PROXIES_FILE.parent.mkdir(exist_ok=True)
    tmp = PROXIES_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    tmp.replace(PROXIES_FILE)


# ─────────────────────────────────────────────────────────────────────────────
# PROXY MANAGER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class ProxyManager:
    """
    Central proxy store. Manages provider configs and account→proxy assignments.

    Storage layout in config/proxies.yaml:
        providers:
          oxylabs:
            host:     pr.oxylabs.io
            port:     7777
            username: customer-meldit_vAxIO-cc-US
            password: zoXsKa8Is=Lm4b
            country:  US
            type:     oxylabs

        assignments:
          dhuniwaalebaba: http://customer-...-sessid-dhuniwaalebaba:pass@host:port
          alice:          http://...
    """

    def __init__(self):
        self._data = _load_proxies_file()
        if "providers"   not in self._data: self._data["providers"]   = {}
        if "assignments" not in self._data: self._data["assignments"] = {}

    def _save(self):
        _save_proxies_file(self._data)

    # ── Provider CRUD ─────────────────────────────────────────────────────────

    def list_providers(self) -> list[dict]:
        """Return list of configured provider dicts with name included."""
        result = []
        for name, cfg in self._data["providers"].items():
            result.append({"name": name, **cfg})
        return result

    def get_provider(self, name: str) -> dict | None:
        return self._data["providers"].get(name)

    def add_provider(
        self,
        name:     str,
        host:     str,
        port:     int,
        username: str,
        password: str,
        country:  str = "US",
        ptype:    str = "oxylabs",
    ):
        """Add or update a provider config."""
        self._data["providers"][name] = {
            "host":     host,
            "port":     int(port),
            "username": username,
            "password": password,
            "country":  country.upper(),
            "type":     ptype,
        }
        self._save()
        log.info(f"Provider '{name}' saved")

    def remove_provider(self, name: str):
        self._data["providers"].pop(name, None)
        self._save()

    # ── URL generation ────────────────────────────────────────────────────────

    def build_proxy_url(
        self,
        provider_name: str,
        account_username: str = "",
        session_id: str = "",
    ) -> str:
        """
        Build a fully-formed proxy URL for a given account.

        For rotating providers (oxylabs, brightdata, smartproxy):
          - Uses account_username as the sticky session ID suffix
          - This means each account always gets routed through the same
            residential IP pool endpoint, helping Instagram fingerprinting

        For static providers:
          - Returns the raw URL (account_username is ignored)
        """
        cfg = self._data["providers"].get(provider_name)
        if not cfg:
            raise ValueError(f"Provider '{provider_name}' not found")

        ptype    = cfg.get("type", "static")
        template = PROVIDER_TEMPLATES.get(ptype, PROVIDER_TEMPLATES["static"])
        host     = cfg["host"]
        port     = cfg["port"]
        password = cfg["password"]
        base_user = cfg["username"]
        country   = cfg.get("country", "US")

        # Determine session_id: use account username, or random if not provided
        sid = session_id or account_username or _random_session_id()

        sticky_tmpl = template.get("sticky_user")
        if sticky_tmpl:
            username = sticky_tmpl.format(
                base_user  = base_user,
                session_id = sid,
                country    = country,
            )
        else:
            username = base_user

        url = template["url_pattern"].format(
            username = username,
            password = password,
            host     = host,
            port     = port,
        )
        return url

    # ── Account assignments ───────────────────────────────────────────────────

    def assign(self, account_username: str, proxy_url: str):
        """Directly assign a fully-formed proxy URL to an account."""
        self._data["assignments"][account_username] = proxy_url
        self._save()

    def assign_from_provider(
        self,
        account_username: str,
        provider_name:    str,
    ) -> str:
        """
        Generate and assign a sticky-session proxy URL for account_username
        using the named provider. Returns the generated URL.
        """
        url = self.build_proxy_url(provider_name, account_username)
        self.assign(account_username, url)
        log.info(f"Assigned {provider_name} sticky proxy to @{account_username}")
        return url

    def assign_all_from_provider(self, usernames: list[str], provider_name: str) -> dict:
        """Assign sticky proxies to every account in the list. Returns {username: url}."""
        result = {}
        for uname in usernames:
            result[uname] = self.assign_from_provider(uname, provider_name)
        return result

    def get_for_account(self, account_username: str) -> str:
        """Return the assigned proxy URL for an account, or '' if none."""
        return self._data["assignments"].get(account_username, "")

    def remove_assignment(self, account_username: str):
        self._data["assignments"].pop(account_username, None)
        self._save()

    def list_assignments(self) -> dict:
        return dict(self._data["assignments"])

    # ── Apply to loaded bots ──────────────────────────────────────────────────

    def apply_to_bot(self, bot) -> bool:
        """
        Look up the proxy for bot.username and apply it via cl.set_proxy().
        Returns True if a proxy was found and applied.
        """
        url = self.get_for_account(bot.username)
        if not url:
            return False
        try:
            bot.cl.set_proxy(url)
            bot.proxy = url
            log.info(f"Proxy applied to @{bot.username}: {_mask(url)}")
            return True
        except Exception as e:
            log.warning(f"Could not apply proxy to @{bot.username}: {e}")
            return False

    def apply_to_all_bots(self, manager) -> dict:
        """Apply stored proxies to every bot in manager. Returns {username: ok}."""
        results = {}
        for bot in manager.bots:
            results[bot.username] = self.apply_to_bot(bot)
        return results

    # ── Health check ──────────────────────────────────────────────────────────

    def check_proxy(self, proxy_url: str, timeout: int = 10) -> dict:
        """
        Send a lightweight HTTPS request through the proxy to check:
        - Is the proxy reachable?
        - What exit IP does it use?
        - How fast is it?

        Returns:
            {"ok": True,  "ip": "1.2.3.4", "latency_ms": 320}
            {"ok": False, "error": "Connection refused"}
        """
        import urllib.request
        import urllib.error
        import json

        handler = urllib.request.ProxyHandler({
            "http":  proxy_url,
            "https": proxy_url,
        })
        opener  = urllib.request.build_opener(handler)
        start   = time.time()
        try:
            with opener.open("https://api.ipify.org?format=json", timeout=timeout) as resp:
                body    = resp.read().decode()
                latency = int((time.time() - start) * 1000)
                ip      = json.loads(body).get("ip", "?")
                return {"ok": True, "ip": ip, "latency_ms": latency}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _random_session_id(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _mask(url: str) -> str:
    """Replace password in URL with *** for safe logging."""
    return re.sub(r'(:)([^:@]+)(@)', r'\1***\3', url)


def parse_manual_url(url: str) -> dict | None:
    """
    Parse a proxy URL like http://user:pass@host:port into components.
    Returns None if the URL is malformed.
    """
    m = re.match(
        r'^(https?|socks5)://([^:]+):([^@]+)@([^:]+):(\d+)$',
        url.strip()
    )
    if not m:
        return None
    return {
        "scheme":   m.group(1),
        "username": m.group(2),
        "password": m.group(3),
        "host":     m.group(4),
        "port":     int(m.group(5)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL SINGLETON  (import and use directly)
# ─────────────────────────────────────────────────────────────────────────────

_proxy_manager: ProxyManager | None = None


def get_proxy_manager() -> ProxyManager:
    """Return the module-level singleton ProxyManager (lazy init)."""
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager()
    return _proxy_manager