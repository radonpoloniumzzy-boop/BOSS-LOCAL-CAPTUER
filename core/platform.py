from __future__ import annotations

from urllib.parse import urlparse


_BOSS_HOSTS = ("zhipin.com", "bosszhipin.com")
_BOSS_RECOMMENDATION_PATHS = {
    "/web/chat/recommend",
    "/web/frame/recommend",
    "/web/geek/recommend",
}


def is_boss_recommendation_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    is_boss_host = any(host == root or host.endswith(f".{root}") for root in _BOSS_HOSTS)
    return is_boss_host and parsed.path.rstrip("/") in _BOSS_RECOMMENDATION_PATHS
