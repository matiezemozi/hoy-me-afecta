"""Cortes *programados* de EDESA (Salta, Argentina).

No son cortes actuales ni cubren cortes imprevistos. El colector falla de forma
explícita cuando cambia el formato de la página. Fuente: EDESA, página pública.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.request import Request, urlopen

URL = "https://www.edesa.com.ar/widgets/cortes.php"
ARG_TZ = timezone(timedelta(hours=-3))
MAX_BYTES = 1_500_000


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bits = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.ignored += 1
        elif not self.ignored and tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "br", "li", "tr"):
            self.bits.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.ignored = max(0, self.ignored - 1)
        elif not self.ignored and tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "li", "tr"):
            self.bits.append(" ")

    def handle_data(self, data):
        if not self.ignored:
            self.bits.append(data)


# The public page labels each card: fecha + hora, Duración, Zona, Estado, Motivo.
# We never infer an interruption from a date without all those fields.
_CARD = re.compile(
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?P<time>\d{1,2}:\d{2})\s*"
    r"Duraci[oó]n\s*(?P<duration>\d{1,2}:\d{2}:\d{2})\s*"
    r"Zona\s*(?P<zone>.*?)\s*"
    r"Estado\s*(?P<state>PUBLICADO|EN EJECUCI[OÓ]N|EJECUTADO|CANCELADO)\s*"
    r"Motivo\s*",
    flags=re.IGNORECASE | re.DOTALL,
)


def _parse_start(value, hour):
    return datetime.strptime(value + " " + hour, "%d/%m/%Y %H:%M").replace(tzinfo=ARG_TZ)


def _compact(value, limit=650):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _hint(area):
    # Only explicit "LOCALIDAD: X" can be used as an exact locality hint.
    m = re.search(r"\bLOCALIDAD\s*:\s*([A-Za-zÁÉÍÓÚÑáéíóúñ\s.]{3,48}?)\s*(?:-|;|,|\.|$)", area, re.I)
    return _compact(m.group(1), 48) if m else None


def parse_official_html(html, checked_at, *, max_days=14):
    """Return (notices, cards_seen). Future PUBLICADO cards only.

    All dates are in Argentina time. Existing past/cancelled records are not
    treated as new, live or current. Parsing failure is distinct from zero.
    """
    if not isinstance(html, str) or len(html) > MAX_BYTES:
        raise ValueError("HTML de EDESA vacío o demasiado grande")
    parser = _VisibleText()
    parser.feed(html)
    visible = _compact(" ".join(parser.bits), MAX_BYTES)
    now = datetime.fromisoformat(checked_at.replace("Z", "+00:00")).astimezone(ARG_TZ)
    found = list(_CARD.finditer(visible))
    if not found:
        if re.search(r"no (?:hay|se registran|existen) cortes programados", visible, re.I):
            return [], 0
        raise ValueError("No se reconocieron fichas completas de EDESA")
    notices = []
    seen = set()
    for match in found:
        try:
            start = _parse_start(match.group("date"), match.group("time"))
            status = _compact(match.group("state")).upper()
            zone = _compact(match.group("zone"))
            duration = match.group("duration")
            h, m, s = [int(x) for x in duration.split(":")]
            if h > 24 or m > 59 or s > 59 or not zone or len(zone) < 10:
                continue
            if status != "PUBLICADO" or not (now <= start <= now + timedelta(days=max_days)):
                continue
            identifier = sha256(f"{start.isoformat()}|{zone}|{duration}".encode("utf-8")).hexdigest()[:18]
            if identifier in seen:
                continue
            seen.add(identifier)
            notices.append({
                "id": "edesa-" + identifier,
                "province": "Salta", "company": "EDESA",
                "kind": "planned_electricity_work", "status": "scheduled_not_confirmed",
                "scheduled_start": start.isoformat(timespec="minutes"),
                "scheduled_end": (start + timedelta(hours=h, minutes=m, seconds=s)).isoformat(timespec="minutes"),
                "zone_detail": zone,
                "locality_hint": _hint(zone),
                "source_url": URL,
                "message": "Trabajo programado publicado; no confirma que exista un corte en este momento.",
            })
        except (ValueError, OverflowError):
            continue
    notices.sort(key=lambda item: item["scheduled_start"])
    return notices, len(found)


def fetch_html():
    request = Request(URL, headers={"User-Agent": "HoyMeAfecta/0.5 (fuente EDESA, piloto Argentina)"})
    with urlopen(request, timeout=18) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Fuente EDESA demasiado grande")
    return raw.decode("utf-8-sig", errors="replace")


def collect_edesa_salta(checked_at, fetcher=None):
    """One HTTPS fetch. Never present failed collection as no interruptions."""
    result = {
        "status": "unverified", "province": "Salta", "country": "Argentina",
        "company": "EDESA", "source_url": URL, "checked_at": checked_at,
        "coverage_kind": "planned_outages_only", "notices": [],
        "message": "Cortes programados, no estado eléctrico en tiempo real.",
    }
    try:
        html = (fetcher or fetch_html)()
        items, card_count = parse_official_html(html, checked_at)
        result.update(status="ok", notices=items, records_checked=card_count)
        if not items:
            result["message"] = "Sin trabajos FUTUROS verificados en la página. No implica servicio normal."
    except Exception as exc:
        result["message"] = "No se pudieron verificar cortes programados de EDESA: " + type(exc).__name__
    return result
