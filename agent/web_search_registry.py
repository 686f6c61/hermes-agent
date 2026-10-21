"""Web Search Provider Registry.

Populated by plugins via :meth:`PluginContext.register_web_search_provider`;
consumed by the ``web_search`` / ``web_extract`` wrappers in :mod:`tools.web_tools`.

Active selection, in precedence order (the ``supports_search`` /
``supports_extract`` capability filter applies at every step, so a search-only
provider configured as ``web.extract_backend`` falls through):

1. ``web.search_backend`` / ``web.extract_backend``, then ``web.backend``.
2. The single capability-eligible provider that is registered AND available.
3. Legacy preference walk (``_LEGACY_PREFERENCE``) filtered by availability —
   the historic ``tools.web_tools._get_backend()`` order, so installs that never
   set a config key keep landing on the same provider.
4. Keyless free-tier walk (``_KEYLESS_PREFERENCE``), last resort.
5. ``None`` — the tool points the user at ``hermes tools``.
"""

from __future__ import annotations

import logging
from typing import Optional

from agent.provider_registry import ProviderRegistry, is_available_safe
from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


_registry: ProviderRegistry[WebSearchProvider] = ProviderRegistry(
    label="Web", provider_cls=WebSearchProvider, logger=logger,
)
_registry.export(globals())

def _read_config_key(*path: str) -> Optional[str]:
    """Resolve a dotted config key from ``config.yaml``. Returns None on miss."""
    try:
        from hermes_cli.config import load_config_readonly

        cur = load_config_readonly()
        for segment in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(segment)
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    except Exception as exc:
        logger.debug("Could not read config %s: %s", ".".join(path), exc)
    return None


def _configured_backend(capability: str) -> Optional[str]:
    """``web.<capability>_backend`` (preferred) or ``web.backend`` (shared fallback). The managed ``nous``
    selection names no provider: it is served by Perplexity (search) and Firecrawl (extract)."""
    configured = _read_config_key("web", f"{capability}_backend") or _read_config_key("web", "backend")
    if configured and configured.lower() == "nous":
        return "perplexity" if capability == "search" else "firecrawl"
    return configured


# Paid providers first so existing paid setups don't get downgraded to a free
# tier on upgrade; filtered by ``is_available()`` at walk time.
_LEGACY_PREFERENCE = ("firecrawl", "parallel", "tavily", "perplexity", "exa", "searxng", "brave-free", "ddgs")

# Anonymous public free tiers (see plugins/web/keyless_mcp.py); strictly last
# resort, i.e. zero web credentials and no importable ddgs. Unpinned keyless
# traffic round-robins across the ring per request; an explicit `hermes tools`
# pick bypasses this walk. Disable with ``web.keyless_fallback: false``.
_KEYLESS_PREFERENCE = ("exa", "parallel", "firecrawl", "keenable")


def _keyless_preference() -> tuple:
    """Keyless walk order, starting at the ring cursor in
    :mod:`plugins.web.keyless_mcp` so resolution and dispatch agree on which
    vendor a fresh install starts at; the rest follow in ring order."""
    try:
        from plugins.web.keyless_mcp import _KEYLESS_RING, _ring_cursor

        start = _ring_cursor % len(_KEYLESS_RING)
        return tuple(_KEYLESS_RING[start:] + _KEYLESS_RING[:start])
    except Exception as exc:
        logger.debug("keyless ring order unavailable: %s", exc)
    return _KEYLESS_PREFERENCE


def _resolve(configured: Optional[str], *, capability: str) -> Optional[WebSearchProvider]:
    """Resolve the active provider for a capability ("search" | "extract").

    Rules, in order (see module docstring): explicit config wins even when
    ``is_available()`` is False (the dispatcher surfaces a precise
    "X_API_KEY is not set" error instead of a silent switch); then the single
    available capable provider; then the availability-filtered legacy walk;
    then the keyless free-tier walk; else None.
    """
    snapshot = _registry.merged()

    def _capable(p: WebSearchProvider) -> bool:
        return bool(
            p.supports_search() if capability == "search"
            else p.supports_extract() if capability == "extract" else False
        )

    def _available(p: WebSearchProvider) -> bool:
        return is_available_safe(p, logger, "provider %s.is_available() raised %s")

    if configured:
        provider = snapshot.get(configured)
        if provider is not None and _capable(provider):
            return provider
        if provider is None:
            logger.debug("web backend '%s' configured but not registered; falling back", configured)
        else:
            logger.debug(
                "web backend '%s' configured but does not support '%s'; falling back", configured, capability
            )

    # Fallbacks are availability-filtered so a registered-but-keyless provider
    # never becomes "active" on a fresh install.
    eligible = [p for p in snapshot.values() if _capable(p) and _available(p)]
    if len(eligible) == 1:
        return eligible[0]

    for legacy in _LEGACY_PREFERENCE:
        provider = snapshot.get(legacy)
        if provider is not None and provider in eligible:
            return provider

    # Keyless free tier (anonymous public MCP tiers) is last-resort only: it is
    # reachable solely when the legacy walk found nothing, never pre-empting a
    # keyed setup. Disabled via ``web.keyless_fallback: false``.
    if _keyless_tier_enabled():
        for name in _keyless_preference():
            provider = snapshot.get(name)
            if provider is None or not _capable(provider):
                continue
            try:
                if provider.is_keyless_available():
                    return provider
            except Exception as exc:
                logger.debug("provider %s.is_keyless_available() raised %s", name, exc)

    return None


def _keyless_tier_enabled() -> bool:
    """Read ``web.keyless_fallback`` from config.yaml (default: enabled)."""
    try:
        from hermes_cli.config import load_config

        web_cfg = load_config().get("web") or {}
        return bool(web_cfg.get("keyless_fallback", True))
    except Exception as exc:
        logger.debug("keyless_fallback config read failed: %s", exc)
        return True


def _norm_vendor(name: str) -> str:
    """Normalize a bundled web plugin dir or a provider name to one vendor string.

    Bundled web plugins live under ``web/<vendor>`` and their registered provider name differs from
    the directory only by hyphen/underscore, so both sides go through this.
    """
    return name.strip().lower().replace("-", "_")


def _configured_vendor(configured: Optional[str] = None, *, capability: Optional[str] = None) -> Optional[str]:
    """Normalized vendor of the configured backend (``web.<capability>_backend`` → ``web.backend``)."""
    if not configured and capability in ("search", "extract"):
        configured = _configured_backend(capability)
    return _norm_vendor(configured) if configured else None


def _iter_web_plugins():
    """Yield ``(plugin_key, loaded)`` for the bundled ``web/`` plugins.

    Yields nothing when the plugin manager is unavailable: a diagnostics lookup must never turn a
    missing provider into a raised exception.
    """
    try:
        from hermes_cli.plugins import get_plugin_manager

        items = list(get_plugin_manager()._plugins.items())
    except Exception as exc:
        logger.debug("web-plugin manager lookup failed: %s", exc)
        return
    for key, loaded in items:
        if isinstance(key, str) and key.startswith("web/"):
            yield key, loaded


def _disabled_web_plugin_for(configured: Optional[str] = None, *, capability: Optional[str] = None) -> Optional[str]:
    """Plugin key of a *disabled* bundled web plugin that would have provided
    the configured backend (``web.<capability>_backend`` → ``web.backend``), or None.

    Lets the dispatcher say "re-enable web-firecrawl" instead of "No web extract
    provider configured". Resolved from config.yaml rather than the resolved
    backend because a disabled provider fails the availability gate and silently
    drops to the default.

    When a user sets ``web.extract_backend: firecrawl`` (or the search equivalent) but also lists
    ``web-firecrawl`` in ``plugins.disabled``, the provider never registers and the dispatcher would
    otherwise emit a misleading "No web extract provider configured. Set web.extract_backend to ..." error —
    even though the backend IS configured correctly. This helper detects that case so the dispatcher can
    point the user at the actual cause (issue #40190 follow-up: pi314's disabled-plugin symptom).
    """
    want = _configured_vendor(configured, capability=capability)
    if not want:
        return None
    for key, loaded in _iter_web_plugins():
        if (
            not loaded.enabled and loaded.error == "disabled via config"
            and _norm_vendor(key.split("/", 1)[1]) == want
        ):
            return key
    return None


def _failed_web_plugin_for(
    configured: Optional[str] = None, *, capability: Optional[str] = None
) -> Optional[tuple[str, str]]:
    """``(plugin_key, error)`` of a bundled web plugin whose *load failed* in this process, or None.

    A failed load is a third state next to "enabled" and "disabled via config": the plugin is
    discovered, its import or ``register()`` raised (or overran its deadline), its registrations were
    swept and ``loaded.error`` holds the text, but ``plugins.disabled`` says nothing about it. The
    provider is therefore absent from the registry for the life of the process — ``discover_and_load()``
    returns early unless forced — while the config still names it correctly. Reporting that as "no
    registered provider has that name. Run 'hermes tools' to change it" sends the user to reconfigure a
    backend that is already right; the actionable line is "restart", and the load error says why.
    """
    want = _configured_vendor(configured, capability=capability)
    if not want:
        return None
    for key, loaded in _iter_web_plugins():
        if loaded.enabled or not loaded.error or loaded.error == "disabled via config":
            continue
        if _norm_vendor(key.split("/", 1)[1]) == want:
            return key, loaded.error
    return None


def get_active_search_provider() -> Optional[WebSearchProvider]:
    """Resolve the currently-active web search provider."""
    return _resolve(_configured_backend("search"), capability="search")


def get_active_extract_provider() -> Optional[WebSearchProvider]:
    """Resolve the currently-active web extract provider."""
    return _resolve(_configured_backend("extract"), capability="extract")
