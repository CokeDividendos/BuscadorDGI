# src/services/logos.py

from urllib.parse import urlparse
import requests

from src.services.cache_store import cache_get, cache_set


def _clean_domain(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    domain = parsed.netloc.lower().strip()
    return domain.replace("www.", "")


def _is_valid_image(url: str, timeout: float = 2.5) -> bool:
    """
    Verifica que la URL responda 200 y sea una imagen real.
    """
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True,
        )
        if r.status_code != 200:
            return False

        content_type = r.headers.get("Content-Type", "")
        return content_type.startswith("image/")
    except Exception:
        return False


def logo_candidates(company_website: str) -> list[str]:
    """
    Devuelve SOLO logos válidos (filtrados).
    Los resultados se cachean por 12 meses para optimizar el rendimiento.
    """
    domain = _clean_domain(company_website)
    if not domain:
        return []
    
    # Crear una clave de caché única por dominio
    cache_key = f"logo:candidates:{domain}"
    
    # Intentar obtener del caché (TTL: 12 meses = 31,536,000 segundos)
    cached_logos = cache_get(cache_key)
    if cached_logos is not None:
        # Verificar que sea una lista válida
        if isinstance(cached_logos, list):
            return cached_logos

    candidates = [
        # Mejor calidad (logo real)
        f"https://logo.clearbit.com/{domain}",
        # Favicon Google (fallback ultra estable)
        f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
        # Favicon DuckDuckGo (fallback extra)
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
        # Favicon clásico
        f"https://{domain}/favicon.ico",
    ]

    valid_logos = []
    for url in candidates:
        if _is_valid_image(url):
            valid_logos.append(url)
    
    # Cachear el resultado por 12 meses (365 días * 24 horas * 60 minutos * 60 segundos)
    ttl_12_months = 365 * 24 * 60 * 60
    cache_set(cache_key, valid_logos, ttl_seconds=ttl_12_months)

    return valid_logos
