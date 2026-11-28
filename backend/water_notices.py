"""Conservative public water-service bulletin collectors for Argentina (v5.87).

No report is a live outage confirmation. No credentials, service identifiers or
unofficial APIs are used. Completely independent of provincial_electricity.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET
from time import sleep, monotonic
from concurrent.futures import ThreadPoolExecutor
import calendar
import re

ART = timezone(timedelta(hours=-3))
HORIZON_DAYS = 14
MAX_PAGE_BYTES = 1_500_000
# v5.83: Bounds for each independent official source, not a limit on alerts.
# Parallelism is across different source collectors, never article requests
# inside a single source (preserves per-site rate-limit avoidance).
MAX_PARALLEL_SOURCES = 4
MAX_NETWORK_FETCHES_PER_SOURCE = 16
MAX_SOURCE_NETWORK_SECONDS = 90


class SourceFetchBudgetExceeded(RuntimeError):
    """A public source exhausted its conservative per-run query budget."""


def _budgeted_fetcher(fetch, *, max_fetches=MAX_NETWORK_FETCHES_PER_SOURCE,
                      max_seconds=MAX_SOURCE_NETWORK_SECONDS, clock=monotonic):
    """No more network calls once a collector exceeds count or elapsed budget.

    This is a cooperative budget checked BEFORE each request; the standard
    urlopen socket timeout still bounds each individual request. A DNS or
    remote server outside Python's control can still run longer than desired.
    """
    started = clock()
    requests = 0

    def limited(url):
        nonlocal requests
        if requests >= max_fetches or clock() - started >= max_seconds:
            raise SourceFetchBudgetExceeded('Limite de consultas/tiempo de la fuente')
        requests += 1
        return fetch(url)

    return limited

SOURCES = {
    'absa_buenos_aires': ('ABSA', 'Buenos Aires', 'https://www.aguasbonaerenses.com.ar/noticias/'),
    'aguas_del_norte_salta': ('Aguas del Norte', 'Salta', 'https://www.aguasdelnortesalta.com.ar/cortes.php'),
    'aysam_mendoza': ('AYSAM', 'Mendoza', 'https://aysam.com.ar/cortes/'),
    'aguas_cordobesas': ('Aguas Cordobesas', 'Córdoba', 'https://www.aguascordobesas.com.ar/CanalSaladePrensa/HomeSalaPrensa/'),
    'aguas_santafesinas': ('Aguas Santafesinas', 'Santa Fe', 'https://www.aguassantafesinas.com.ar/portal/noticias'),
    'aguas_rionegrinas_arsa': ('Aguas Rionegrinas', 'Río Negro', 'https://aguasrionegrinas.com/category/interrupciones/'),
    'aguas_catamarca': ('Aguas de Catamarca SAPEM', 'Catamarca', 'https://www.adcsapem.com.ar/?page_id=240'),
    'aysa_amba': ('AySA', 'Buenos Aires / CABA', 'https://www.aysa.com.ar/usuarios/interrupcion_servicio'),
    'aysa_public_bulletins_amba': ('AySA', 'Buenos Aires / CABA', 'https://www.aysa.com.ar/usuarios/Novedades'),
    'sameep_chaco': ('SAMEEP', 'Chaco', 'https://sameep.gob.ar/noticias/'),
    'edos_concordia': ('EDOS Concordia', 'Entre Ríos', 'https://www.concordia.gob.ar/noticias?area=obras-sanitarias'),
    'osse_mar_del_plata': ('OSSE Mar del Plata', 'Buenos Aires', 'https://www.osmgp.gov.ar/osse/noticias/'),
    'samsa_misiones': ('SAMSA', 'Misiones', 'https://samsa.com.ar/noticias/'),
    'agua_potable_jujuy_prensa': ('Agua Potable de Jujuy', 'Jujuy', 'https://prensa.jujuy.gob.ar/agua-potable-a48'),
    'scpl_comodoro_chubut': ('SCPL Comodoro Rivadavia', 'Chubut', 'https://scpl.coop/index.php/site/ver-seccion?id=2'),
    'epas_neuquen_noticias': ('EPAS Neuquen', 'Neuquen', 'https://www.epas.gov.ar/comunidad/noticias/'),
    'sat_tucuman_noticias': ('Sociedad Aguas del Tucumán', 'Tucumán', 'https://aguasdeltucuman.com.ar/noticias'),
    'aguas_santiago_novedades': ('Aguas de Santiago', 'Santiago del Estero', 'https://aguasdesantiago.com.ar/categoria/4/novedades'),
    'san_luis_serba_municipal': ('SerBa / Municipio de San Luis', 'San Luis', 'https://sanluislaciudad.gob.ar/feed/'),
    'santa_rosa_municipal_lp': ('Municipalidad de Santa Rosa', 'La Pampa', 'https://www.santarosa.gob.ar/rss.xml'),
    'dposs_tierra_del_fuego_reparaciones': ('DPOSS Tierra del Fuego', 'Tierra del Fuego', 'https://dposs.gob.ar/reparaciones/'),
    'aosc_corrientes_regulador': ('AOSC / Ente Regulador', 'Corrientes', 'https://aosc.gob.ar/noticias'),
    'parana_radio_municipal_agua': ('Radio Costa Parana / Municipalidad', 'Entre Rios', 'https://costa.parana.gob.ar/noticias/'),
    'aguas_corrientes_prestador': ('Aguas de Corrientes S.A.', 'Corrientes', 'https://www.aguasdecorrientes.com/noticias'),
    'osse_san_juan_prensa': ('OSSE Obras Sanitarias San Juan', 'San Juan', 'https://www.ossesanjuan.com.ar/'),
    'spse_santa_cruz_prensa': ('SPSE / Prensa Santa Cruz', 'Santa Cruz', 'https://noticias.santacruz.gob.ar/organismos/entes-publicos/servicios-publicos'),
    'la_rioja_ministerio_agua': ('Ministerio de Agua y Energia / La Rioja', 'La Rioja', 'https://aguayenergia.larioja.gob.ar/'),
    'sameep_chaco_prensa_gobierno': ('SAMEEP / Gobierno del Chaco', 'Chaco', 'https://chaco.gob.ar/'),
    'gualeguaychu_obras_sanitarias': ('Obras Sanitarias / Municipalidad de Gualeguaychú', 'Entre Ríos', 'https://gualeguaychu.gov.ar/'),
    'corpico_general_pico_agua': ('CORPICO / General Pico', 'La Pampa', 'https://www.corpico.com.ar/novedades'),
}
WEEKDAY = {'lunes':0, 'martes':1, 'miercoles':2, 'jueves':3, 'viernes':4,
           'sabado':5, 'domingo':6}
MONTH = {'enero':1, 'febrero':2, 'marzo':3, 'abril':4, 'mayo':5, 'junio':6,
         'julio':7, 'agosto':8, 'septiembre':9, 'setiembre':9,
         'octubre':10, 'noviembre':11, 'diciembre':12}


def clean(value, length=650):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:length]


def folded(value):
    return str(value or '').translate(str.maketrans('áéíóúÁÉÍÓÚüÜñÑ',
                                                   'aeiouAEIOUuUnN')).lower()


def checked_instant(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('checked_at debe incluir una zona horaria')
    return parsed.astimezone(ART)


def fetch_html(url):
    if urlsplit(url).scheme != 'https':
        raise ValueError('Solo HTTPS')
    req = Request(url, headers={'User-Agent':'HoyMeAfecta/5.37 (public notice reader)',
                                'Accept':'text/html,application/xhtml+xml,application/rss+xml,application/xml;q=0.9'})
    with urlopen(req, timeout=13) as response:
        if urlsplit(response.geturl()).scheme != 'https':
            raise ValueError('Redireccion fuera de HTTPS')
        raw = response.read(MAX_PAGE_BYTES + 1)
        if len(raw) > MAX_PAGE_BYTES:
            raise ValueError('Página demasiado grande')
        charset = response.headers.get_content_charset() or 'utf-8'
    return raw.decode(charset, errors='replace')


class VisiblePage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.bits = []
        self.anchors = []
        self._anchor = None
        self.paragraphs = []
        self._p = None
        self.headings = []
        self._heading = None
        self.rows = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript','svg'):
            self.ignored += 1
            return
        if self.ignored:
            return
        attrs = dict(attrs)
        if tag == 'a':
            self._anchor = [attrs.get('href') or '', []]
        if tag == 'p':
            self._p = []
        if tag in ('h1','h2','h3'):
            self._heading = []
        if tag == 'tr':
            self._row = []
        if tag in ('th','td') and self._row is not None:
            self._cell = []
        if tag in ('br','div','p','li','tr','td','h1','h2','h3'):
            self.bits.append(' ')

    def handle_data(self, text):
        if self.ignored:
            return
        self.bits.append(text)
        if self._anchor is not None:
            self._anchor[1].append(text)
        if self._p is not None:
            self._p.append(text)
        if self._heading is not None:
            self._heading.append(text)
        if self._cell is not None:
            self._cell.append(text)

    def handle_endtag(self, tag):
        if tag in ('script','style','noscript','svg'):
            self.ignored = max(0,self.ignored-1)
            return
        if self.ignored:
            return
        if tag == 'a' and self._anchor is not None:
            self.anchors.append((self._anchor[0], clean(' '.join(self._anchor[1]),240)))
            self._anchor = None
        if tag == 'p' and self._p is not None:
            self.paragraphs.append(clean(' '.join(self._p),1600))
            self._p = None
        if tag in ('h1','h2','h3') and self._heading is not None:
            self.headings.append(clean(' '.join(self._heading),250))
            self._heading = None
        if tag in ('td','th') and self._cell is not None:
            self._row.append(clean(' '.join(self._cell),1100))
            self._cell = None
        if tag == 'tr' and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        if tag in ('div','p','li','tr','td','h1','h2','h3'):
            self.bits.append(' ')


def page(html):
    if not isinstance(html,str) or not html.strip() or len(html.encode('utf-8'))>MAX_PAGE_BYTES:
        raise ValueError('HTML vacío o demasiado grande')
    parser=VisiblePage()
    parser.feed(html)
    return parser,clean(' '.join(parser.bits),MAX_PAGE_BYTES)


def excerpt(text, limit=950):
    """Preserve words and show when source details have been shortened."""
    value = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(value) <= limit:
        return value
    prefix = value[:limit - 2].rsplit(' ', 1)[0]
    return (prefix if len(prefix) >= limit // 2 else value[:limit - 2]) + '…'


def mk_notice(company, province, locality, url, kind, status, zone, **kwargs):
    key='|'.join([company,locality,url,kind,str(kwargs.get('scheduled_date') or kwargs.get('published_on'))])
    item={'id':'agua-'+sha256(key.encode('utf-8')).hexdigest()[:18],
          'category':'agua','country':'Argentina','province':province,'company':company,
          'kind':kind,'status':status,'locality_hint':clean(locality,100),
          'zone_detail':excerpt(zone,950),'source_url':url,
          'notification_allowed':False,
          'message':'Comunicado oficial; no acredita el estado del suministro en tiempo real.'}
    item.update(kwargs)
    return item


def _ddmmyyyy(value):
    d=datetime.strptime(value.replace('/','-'),'%d-%m-%Y').date()
    return d


def _weekday_date(fragment, published):
    """Accept a dated weekday only if calendar and publication agree."""
    text=folded(fragment)
    match=re.search(r'\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+(\d{1,2})(?:\s+de\s+([a-z]+))?',text)
    if not match:
        return None
    weekday,day,month=match.groups()
    day=int(day)
    if month and month not in MONTH:
        return None
    for add_months in range(0,3):
        y=published.year+(published.month-1+add_months)//12
        m=(published.month-1+add_months)%12+1
        if month and m!=MONTH[month]:
            continue
        try:
            d=date(y,m,day)
        except ValueError:
            continue
        if d>=published and d.weekday()==WEEKDAY[weekday] and (d-published).days<=35:
            return d
    return None


def _absa_explicit_weekday_dates(paragraphs, published, now, include_elapsed=False):
    """Read independently verified weekday/day pairs, without guessed dates.

    include_elapsed=True retains elapsed days from an otherwise still-current
    multi-day schedule. Never mark an elapsed one-day plan as a current event.
    """
    pairs = re.compile(
        r'\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+'
        r'\d{1,2}(?:\s+de\s+[a-z]+)?\b')
    found = set()
    for paragraph in paragraphs:
        for match in pairs.finditer(folded(paragraph)):
            d = _weekday_date(match.group(0), published)
            if d is not None and (include_elapsed or d >= now.date()) and d <= now.date() + timedelta(days=HORIZON_DAYS):
                found.add(d)
    return sorted(found)


def _absa_start_clock(paragraph):
    """Return a *stated* start clock, never infer a time from an end hour.

    Intended for a single confirmed calendar day and its own zone text. If
    multiple distinct start times occur, leave the time unknown rather than
    associating an unrelated schedule with the entire locality.
    """
    text = folded(paragraph)
    patterns = (
        r'\b(?:comenzaran|comenzara|iniciaran|iniciara|arrancaran|arrancara|daran comienzo)'
        r'\s+(?:a\s+partir\s+de\s+)?(?:a\s+)?las\s+(\d{1,2})(?::(\d{2}))?\b',
        r'\b(?:desde|a\s+partir\s+de)\s+las\s+(\d{1,2})(?::(\d{2}))?\b',
    )
    values = set()
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            hour, minute = int(m.group(1)), int(m.group(2) or '0')
            if hour < 24 and minute < 60:
                values.add((hour, minute))
    return next(iter(values)) if len(values) == 1 else None


def _absa_stated_end_after_start(paragraph, stated_start, day):
    """Read an end tied to the *same* stated start, without inventing one.

    In official ABSA releases like 'a partir de las 8:00 y hasta las
    11:00 horas, aproximadamente', the published end is an ESTIMATE.
    An estimated upper bound must not be treated as confirmed restoration.
    Return an empty dict when the wording is not locally unambiguous.
    """
    if stated_start is None:
        return {}
    text=folded(paragraph)
    pattern=(r'\b(?:desde|a\s+partir\s+de)\s+las\s+'
             r'(\d{1,2})(?::(\d{2}))?\s+(?:y\s+)?hasta\s+las\s+'
             r'(\d{1,2})(?::(\d{2}))?\b')
    matches=list(re.finditer(pattern,text))
    if len(matches)!=1:
        return {}
    m=matches[0]
    h1,mi1,h2,mi2=int(m[1]),int(m[2] or 0),int(m[3]),int(m[4] or 0)
    if ((h1,mi1)!=stated_start or h2>23 or mi2>59):
        return {}
    a=datetime(day.year,day.month,day.day,h1,mi1,tzinfo=ART)
    b=datetime(day.year,day.month,day.day,h2,mi2,tzinfo=ART)
    if not a<b<=a+timedelta(hours=18):
        return {}
    # Do not mistake office hours for work or supply impact hours.
    near=text[max(0,m.start()-115):m.end()+60]
    if re.search(r'horario de atencion|atencion al publico|\boficina\b',near):
        return {}
    after=text[m.end():m.end()+70]
    if re.search(r'\baproximad|\bestimad|\bprevist',after):
        return {'scheduled_end':None,
                'scheduled_end_estimate':b.isoformat(timespec='minutes'),
                'time_precision':'start_known_end_estimated'}
    return {'scheduled_end':b.isoformat(timespec='minutes'),
            'time_precision':'start_and_end_published'}


def _absa_work_duration_estimate(paragraph, stated_start, day):
    """Keep the *estimated works duration*, not an assumed water restoration.

    A duration belongs only to an explicit clock within the same phrase.
    In particular, a stated 18-hour pumping shutdown does not prove that
    distribution pressures will have normalized 18 hours later.
    """
    if stated_start is None:
        return {}
    f = folded(paragraph)
    if re.search(r'horario de atencion|atencion al publico|\boficina\b', f):
        return {}
    pattern = (r'\b(?:desde|a partir de)\s+las\s+(\d{1,2})(?::(\d{2}))?'
               r'\s+(?:de\s+la\s+(?:manana|tarde|noche)\s*,?\s*)?'
               r'por\s+(?:un\s+)?plazo\s+estimado\s+de\s+(\d{1,2})\s+horas\b')
    matches = list(re.finditer(pattern, f))
    if len(matches) != 1:
        return {}
    m = matches[0]
    hour, minute, duration = int(m[1]), int(m[2] or 0), int(m[3])
    if (hour, minute) != stated_start or hour > 23 or minute > 59 or not 1 <= duration <= 48:
        return {}
    # Sanity-check the local context, not the entire publisher's news page.
    prefix = f[max(0, m.start()-140):m.start()]
    if not re.search(r'trabaj|tarea|perforacion|captacion|pozo|bombeo', prefix):
        return {}
    planned_stop = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ART)
    return {
        'reported_work_duration_estimate_hours': duration,
        'reported_work_end_estimate': (planned_stop + timedelta(hours=duration)).isoformat(timespec='minutes'),
    }


def _absa_same_day_pressure_end_estimate(paragraphs,published):
    """Record an approximate limit for announced low pressure, not recovery.

    ABSA may say "Esta manana ... se registra baja presion ... hasta
    aproximadamente las 13:30". The independent publication date anchors
    "esta manana"; a clock value by itself must never imply a restored
    water supply, a future outage, or a definite end.
    """
    candidates=[]
    pattern=re.compile(
        r'\besta manana\b.{0,240}\bse registra baja presion\b'
        r'.{0,180}\bhasta aproximadamente las\s+'
        r'(\d{1,2})(?::(\d{2}))?\b')
    for paragraph in paragraphs:
        f=folded(paragraph)
        if re.search(r'\boficina\b|horario de atencion|atencion al publico',f):
            continue
        if re.search(r'\bno se registra baja presion\b',f):
            continue
        if not re.search(r'\bsuministro de energia electrica\b|'
                         r'\bperforaciones\b|\bred de agua\b|\bagua potable\b',f):
            continue
        for m in pattern.finditer(f):
            h,minute=int(m[1]),int(m[2] or 0)
            if h>23 or minute>59:
                continue
            candidates.append(datetime(published.year,published.month,published.day,
                                       h,minute,tzinfo=ART))
    if len(candidates)!=1:
        return {}
    return {
        'reported_low_pressure_end_estimate':candidates[0].isoformat(timespec='minutes'),
        'reported_estimate_does_not_confirm_water_recovery':True,
    }


def _absa_shared_street_address(zone):
    """Require the exact three-part street reference for cross-release matching."""
    m=re.search(r'\bcalle\s+([a-z]+(?:\s+[a-z]+){0,3})\s+'
                r'entre\s+([a-z]+(?:\s+[a-z]+){0,2})\s+y\s+([a-z]+)\b',
                folded(zone))
    return m.groups() if m else None


def _absa_cross_reference_city(notices):
    """Resolve a neighborhood only from ANOTHER fetched official ABSA notice.

    A later bulletin can omit the municipality, although an independently
    retrieved official bulletin identifies the same neighborhood AND the
    identical three-street location. Without both matches, do not guess.
    """
    for target in notices:
        named=folded(target['locality_hint'])
        if not named.startswith('barrio '):
            continue
        address=_absa_shared_street_address(target['zone_detail'])
        if not address:
            continue
        matches=[]
        for ref in notices:
            if ref is target or ref['source_url']==target['source_url']:
                continue
            area=ref.get('area_hint')
            if (not area or folded(area)!=named or
                    _absa_shared_street_address(ref['zone_detail'])!=address):
                continue
            try:
                dd=abs((date.fromisoformat(ref['published_on'])-
                        date.fromisoformat(target['published_on'])).days)
            except (KeyError,ValueError,TypeError):
                continue
            if dd<=2 and folded(ref['locality_hint'])!=named:
                matches.append(ref)
        distinct={folded(r['locality_hint']) for r in matches}
        if len(distinct)!=1:
            continue
        ref=matches[0]
        city=ref['locality_hint']
        target['locality_hint']=city
        target['area_hint']=ref['area_hint']
        target['locality_resolution']='matched_official_absa_article_same_address'
        target['locality_evidence_source_url']=ref['source_url']
        # The stable notice ID is defined by company, city, article, kind,
        # scheduled or publication date. Recompute it after resolving city.
        key='|'.join([target['company'],city,target['source_url'],target['kind'],
                      str(target.get('scheduled_date') or target.get('published_on'))])
        target['id']='agua-'+sha256(key.encode('utf-8')).hexdigest()[:18]
    return notices


def _absa_article(html,url,now):
    dom,visible=page(html)
    title=next((x for x in dom.headings if x and x.lower()!='noticias'), '')
    if not title or ':' not in title:
        return [],None
    relevant=visible.split('Relacionado')[0]
    match=re.search(r'\b(\d{2}-\d{2}-\d{4})\b',relevant)
    if not match:
        return [],None
    published=_ddmmyyyy(match.group(1))
    if published>now.date()+timedelta(days=1):
        return [],None
    # General news expires quickly, but an older official multi-day work
    # schedule may still contain verifiable future dates. Defer the short
    # freshness check until those dates are parsed, with a bounded lookback.
    if published<now.date()-timedelta(days=7):
        return [],published
    article_paragraphs=[]
    for paragraph in dom.paragraphs:
        # Stop at explicit related-content boundaries; news recommendations may
        # contain unrelated future dates and must not affect this article.
        if re.search(r'\brelacionad[oa]s?\b|\bte puede interesar\b', folded(paragraph)):
            break
        article_paragraphs.append(paragraph)
    content=clean(' '.join(p for p in article_paragraphs if len(p)>=45),2800)
    f=folded(title+' '+content)
    if not re.search(r'agua|suministro|presion|acueducto|caneria|red',f):
        return [],published
    if re.search(r'\bfinalizaron|\bnormalizad[oa]|\bse restablecio|\bconcluyeron',folded(title)):
        return [],published
    locality=clean(title.split(':')[0],90)
    if folded(locality)=='patagones' and 'carmen de patagones' in f:
        locality='Carmen de Patagones'
    # A neighbourhood in a headline is not a separate city. Only remap the
    # known case if the SAME official article names its municipality.
    absa_area_hint = None
    if folded(locality) in ('mil viviendas','barrio mil viviendas') and re.search(
        r'\b(?:barrio mil viviendas de|en) san fernando\b', f):
        locality='San Fernando'
        absa_area_hint='Barrio Mil Viviendas'
    # Same-article identification of the city (not a city guessed from a title).
    if folded(locality) in ('lubo','barrio lubo') and re.search(
        r'\bbarrio lubo\s*,\s*en campana\b', f):
        locality='Campana'
        absa_area_hint='Barrio Lubo'
    notices=[]
    # A multi-day list with different intersections is not a single-day outage.
    # Keep its explicitly named days, but without an invented continuous period.
    full_explicit_days = _absa_explicit_weekday_dates(
        article_paragraphs, published, now, include_elapsed=True)
    explicit_days = [d for d in full_explicit_days if d >= now.date()]
    future_day = explicit_days[0] if len(full_explicit_days) == 1 and explicit_days else None
    scheduling_terms = bool(re.search(
        r'programad|se realizaran trabajos|se llevaran adelante tareas|'
        r'se preve[n ]|cronograma de tareas|cronograma de trabajos', f))
    possible_pressure_only = bool(
        re.search(r'no implican interrupciones|no implica interrupciones|sin cortes de agua', f)
        and re.search(r'posible|podria|baja presion', f))
    impact_terms = bool(re.search(
        r'afectara|afectar|interrumpir|faltante|interrupcion|suministro|baja presion', f))
    if published<now.date()-timedelta(days=2) and not (
            len(full_explicit_days)>1 and explicit_days and scheduling_terms and impact_terms):
        # Do not revive ordinary historical news or old one-day plans. Only
        # multi-day schedules with independently verified dates may outlive the
        # two-day publication freshness period, up to seven days of lookback.
        return [],published
    if full_explicit_days and not explicit_days and scheduling_terms:
        # A scheduled repair whose entire date range passed is not an outage
        # currently in progress, even if its old announcement says "afectara".
        return [], published
    if len(full_explicit_days) > 1 and scheduling_terms and impact_terms:
        item = mk_notice(
            'ABSA', 'Buenos Aires', locality, url,
            'multi_day_water_works_bulletin', 'publication_only_not_live', content,
            published_on=published.isoformat(),
            scheduled_dates=[d.isoformat() for d in full_explicit_days],
            scheduled_date=None, scheduled_start=None, scheduled_end=None,
            time_precision='multiple_explicit_dates_no_continuous_outage',
            impact_type='possible_low_pressure_only' if possible_pressure_only else 'works_with_reported_possible_impact')
        item['message'] = ('Cronograma de obras para varias fechas. No presupone corte continuo '
                           'ni servicio afectado en todas las zonas o fechas.')
        notices.append(item)
    elif (future_day is not None and scheduling_terms and impact_terms):
        parts=[]
        if 'general daniel cerri' in f and 'bahia blanca' in folded(title):
            parts=[('General Daniel Cerri', 'En General Daniel Cerri', 'En tanto'),
                   ('Bahía Blanca', 'En tanto', 'Por esta razón')]
        else:
            parts=[(locality,None,None)]
        for loc,opening,closing in parts:
            zone=content
            if opening and opening.lower() in content.lower():
                zone=re.split(re.escape(opening),content,maxsplit=1,flags=re.I)[1].lstrip(' ,;:')
                if closing and re.search(re.escape(closing),zone,re.I):
                    zone=re.split(re.escape(closing),zone,maxsplit=1,flags=re.I)[0]
            if not zone.strip():
                continue
            start=None
            end_fields={'scheduled_end':None,'time_precision':'date_only'}
            # Only a time attached to this locality, not a date in the shared intro.
            stated_clock = _absa_start_clock(zone)
            if stated_clock is not None:
                hour, minute = stated_clock
                start = datetime(future_day.year, future_day.month, future_day.day,
                                 hour, minute, tzinfo=ART).isoformat(timespec='minutes')
                end_fields={'scheduled_end':None,'time_precision':'start_known_end_unknown'}
                end_fields.update(_absa_stated_end_after_start(zone,stated_clock,future_day))
                # A duration of works is separate from the water-service
                # schedule and never fills scheduled_end(_estimate).
                end_fields.update(_absa_work_duration_estimate(zone,stated_clock,future_day))
            # A published estimate in the past does not verify restoration.
            # It does make the original *future plan* historical rather than
            # a still-pending scheduled event. Keep it as read-only evidence.
            status='scheduled_not_confirmed'
            recorded_end=(end_fields.get('scheduled_end_estimate') or
                          end_fields.get('scheduled_end'))
            if recorded_end and datetime.fromisoformat(recorded_end)<now:
                status='publication_only_not_live'
            item=mk_notice('ABSA','Buenos Aires',loc,url,'planned_water_service_impact',
                           status,zone,scheduled_date=future_day.isoformat(),
                           scheduled_start=start,**end_fields,
                           published_on=published.isoformat(),
                           impact_type=('possible_low_pressure_only' if possible_pressure_only
                                        else 'works_with_reported_possible_impact'))
            if status=='publication_only_not_live':
                item['message']=('El horario publicado ya transcurrió. '
                                 'No confirma finalización de obras ni normalización del suministro.')
            notices.append(item)
    elif re.search(r'\b(se estan registrando|se registra|afecta el suministro|afectando|falta[s]? de agua|baja presion)\b',f):
        # Recent news is not evidence that the problem remains ongoing.
        pressure_estimate=_absa_same_day_pressure_end_estimate(article_paragraphs,published)
        notices.append(mk_notice('ABSA','Buenos Aires',locality,url,'water_service_bulletin',
                                  'publication_only_not_live',content,published_on=published.isoformat(),
                                  scheduled_start=None,scheduled_end=None,**pressure_estimate))
    if absa_area_hint:
        for notice in notices:
            notice['area_hint'] = absa_area_hint
    return notices,published


def _collect_absa(checked_at,now,fetch):
    company,province,url=SOURCES['absa_buenos_aires']
    base=_result('absa_buenos_aires',checked_at)
    base['parser_revision']='ABSA-CROSSREF-TIMES-v5.60'
    base['time_metadata_revision']='ABSA-WORK-DURATION-v5.86'
    base['pressure_metadata_revision']='ABSA-SAME-DAY-PRESSURE-ESTIMATE-v5.87'
    seen=[];newest=None;article_count=0;errors=[]
    try:
        dom,_=page(fetch(url))
        urls=[]
        for href,_label in dom.anchors:
            absolute=urljoin(url,href)
            parsed=urlsplit(absolute)
            if parsed.hostname not in ('www.aguasbonaerenses.com.ar','aguasbonaerenses.com.ar'):
                continue
            if re.fullmatch(r'/noticias/\d+/?',parsed.path) and absolute not in urls:
                urls.append(absolute)
        base['article_links_seen']=len(urls)
        for article_url in urls[:12]:
            article_count+=1
            try:
                notes,published=_absa_article(fetch(article_url),article_url,now)
                if published:
                    newest=max(newest,published) if newest else published
                seen.extend(notes)
            except Exception as exc:
                errors.append(type(exc).__name__)
        base['articles_checked']=article_count
    except Exception as exc:
        errors.append(type(exc).__name__)
    seen=_absa_cross_reference_city(seen)
    unique={x['id']:x for x in seen}
    base['notices']=list(unique.values())
    base['records_checked']=article_count
    if newest:
        base['latest_published_date']=newest.isoformat()
    if base['notices']:
        base['status']='ok'
        base['message']='Noticias oficiales fechadas; no garantizan que la afectación continúe.'
    elif newest and newest<now.date()-timedelta(days=2):
        base['status']='stale'
        base['message']='Solo hay comunicados antiguos; no implica servicio normal.'
    else:
        base['message']='Sin avisos completos recientes verificables. '+('Errores: '+','.join(errors[:3]) if errors else '')
    return base


def _result(key,checked_at):
    company,province,url=SOURCES[key]
    return {'status':'unverified','company':company,'province':province,'country':'Argentina',
            'source_url':url,'checked_at':checked_at,
            'coverage_kind':'public_water_bulletins_only',
            'notifications_enabled':False,'parser_revision':'WATER-v5.35',
            'notices':[],'message':'No se ha verificado un aviso completo.'}


def _parse_aysam(html,now,url):
    dom,_=page(html)
    found=[];checked=0;newest=None
    for cells in dom.rows:
        if len(cells)!=7:
            continue
        zone,department,typ,start_day,start_hr,end_day,end_hr=[clean(x) for x in cells]
        if not re.match(r'^\d{2}[-/]\d{2}[-/]\d{4}$',start_day):
            continue
        try:
            d1=_ddmmyyyy(start_day)
            d2=_ddmmyyyy(end_day)
            h1=datetime.strptime(start_hr,'%H:%M').time()
            h2=datetime.strptime(end_hr,'%H:%M').time()
            start=datetime.combine(d1,h1,ART)
            end=datetime.combine(d2,h2,ART)
        except ValueError:
            continue
        if not zone or len(zone)<8 or end<=start or end-start>timedelta(days=3):
            continue
        checked+=1
        newest=max(newest,d1) if newest else d1
        if folded(typ).strip()!='programado':
            continue
        if not now<=start<=now+timedelta(days=HORIZON_DAYS):
            continue
        found.append(mk_notice('AYSAM','Mendoza',department,url,'planned_water_interruption',
                               'scheduled_not_confirmed',zone,scheduled_date=d1.isoformat(),
                               scheduled_start=start.isoformat(timespec='minutes'),
                               scheduled_end=end.isoformat(timespec='minutes'),
                               time_precision='start_and_end_published',water_service_type=typ))
    return found,checked,newest


def _collect_aysam(checked_at,now,fetch):
    result=_result('aysam_mendoza',checked_at)
    current=result['source_url']
    legacy='https://www.aysam.com.ar/cortes/index.html'
    attempts=[]
    for url in (current,legacy):
        try:
            html=fetch(url)
            notes,checked,newest=_parse_aysam(html,now,url)
            # Report the actual official page that was successfully read,
            # not the preceding URL which may have returned an HTTP error.
            result['source_url']=url
            dom,visible=page(html)
            norm=folded(visible)
            attempts.append({'url':url,'records_checked':checked,'result':'page_read'})
            result['records_checked']=checked
            if newest:
                result['latest_published_date']=newest.isoformat()
            if notes:
                result.update(status='ok',source_url=url,notices=notes,
                              message='Cortes programados con zona y horarios publicados en tabla oficial.')
                break
            # The modern public list explicitly says there are no cuts;
            # do not infer live supply or future schedules from that statement.
            if checked==0 and re.search(r'\bno hay cortes\b',norm):
                result.update(status='ok',source_url=url,coverage_horizon='current_listings_only',
                              message=('El listado público oficial dice «No hay cortes». '
                                       'No acredita servicio normal ni ausencia de fallas imprevistas.'))
                attempts[-1]['result']='explicit_no_listed_cuts'
                break
            if newest and newest<now.date()-timedelta(days=2):
                result.update(status='stale',source_url=url,
                              message='Solo hay registros antiguos; no implica suministro normal.')
                break
            if url==legacy:
                result['message']='Página consultada, pero sin filas futuras completas legibles; puede cargar datos dinámicamente.'
        except Exception as exc:
            attempts.append({'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__})
    result['source_attempts']=attempts
    if result['status']=='unverified' and attempts and all(x['result']=='fetch_or_parse_error' for x in attempts):
        result['message']='No se pudieron consultar ambas páginas oficiales de AYSAM.'
    return result


def _collect_salta(checked_at,now,fetch):
    result=_result('aguas_del_norte_salta',checked_at)
    try:
        _,text=page(fetch(result['source_url']))
        if ('cortes programados' in folded(text) and
                'los trabajos en desarrollo no afectan el servicio' in folded(text)):
            result.update(status='ok',records_checked=0,coverage_horizon='works_in_progress_only',
                          message=('La página oficial indica que los trabajos en desarrollo no afectan el servicio. '
                                   'No implica ausencia de cortes imprevistos ni servicio normal.'))
        else:
            result['message']='Sin declaración inequívoca o cronograma completo en la página.'
    except Exception as exc:
        result['message']='Error consultando sitio: '+type(exc).__name__
    return result


def _collect_diagnostic(key,checked_at,now,fetch):
    result=_result(key,checked_at)
    try:
        dom,text=page(fetch(result['source_url']))
        # No false positives from a generic archive, navigation, or account lookup.
        dates=[]
        for match in re.finditer(r'\b(\d{2})[-/](\d{2})[-/](20\d{2})\b',text):
            try:
                dates.append(date(int(match.group(3)),int(match.group(2)),int(match.group(1))))
            except ValueError:
                continue
        result['date_markers_checked']=len(dates)
        if dates and max(dates)<now.date()-timedelta(days=2):
            result.update(status='stale',message='Se reconocen fechas solo antiguas; falta validar avisos nuevos.')
        else:
            result['message']='Portal accesible, sin aviso futuro completo con localidad y horario verificables.'
        # Some sites require a supply ID; never try to guess or enumerate them.
        if key in ('aguas_cordobesas','aguas_santafesinas'):
            result['account_lookup_required_for_address']=True
    except Exception as exc:
        result['message']='No se pudo verificar fuente: '+type(exc).__name__
    return result



def _parse_official_day(text):
    """Return a calendar date from an explicit published-date label, not a weekday guess."""
    raw=folded(text)
    m=re.search(r'\b(\d{1,2})\s+(?:de\s+)?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s*,?\s*(?:de\s+)?(20\d{2})\b',raw)
    if not m:
        return None
    try:
        return date(int(m.group(3)),MONTH[m.group(2)],int(m.group(1)))
    except ValueError:
        return None


def _published_date_from_meta(html):
    """WordPress article metadata (publication only; never an outage timestamp)."""
    class MetaDates(HTMLParser):
        def __init__(self):
            super().__init__();self.values=[]
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=='meta':
                key=attrs.get('property','') or attrs.get('name','') or attrs.get('itemprop','')
                if key.lower() in ('article:published_time','datepublished','pubdate','date'):
                    self.values.append(attrs.get('content',''))
            elif tag=='time':
                self.values.append(attrs.get('datetime',''))
    parser=MetaDates();parser.feed(html)
    # JSON-LD datePublished is still a publication date only. It may be within a
    # script tag and is never treated as scheduled work timing.
    parser.values += re.findall(r'["\']datePublished["\']\s*:\s*["\'](20\d{2}-\d\d-\d\d)[^"\']*["\']',html,re.I)
    for value in parser.values:
        match=re.match(r'^\s*(20\d{2})-(\d{2})-(\d{2})(?:T|\s|$)',value)
        if match:
            try:return date(*map(int,match.groups()))
            except ValueError:continue
    return None


def _month_date_near_title(visible,title,html=None):
    """Find a publication date attached to the article title, not sidebar dates.

    The ARSA layout can repeat a title in neighboring navigation before the
    article heading. Examining only the first occurrence silently dropped the
    real notices in v5.33. Scan EVERY occurrence, nearest date first. HTML
    publication metadata is a fallback only, not a reason to assume a cut.
    """
    positions=[m.start() for m in re.finditer(re.escape(title),visible,re.I)] if title else []
    for pos in reversed(positions):
        # The date may be just before or after the actual H1 depending on theme.
        after=visible[pos+len(title):pos+len(title)+310]
        day=_parse_official_day(after)
        if day:return day
        before=visible[max(0,pos-95):pos]
        day=_parse_official_day(before)
        if day:return day
    return _published_date_from_meta(html) if html else None


def _arsa_article_title(dom,html,url):
    """Prefer the article heading and require locality evidence in the URL."""
    all_headings=[h for h in dom.headings if ':' in h and 25<len(h)<250]
    # Some WP themes render the real article title as H4, not H1. In that
    # case recover a semantic heading only if the official page URL agrees.
    if not all_headings:
        m=re.search(r'<h[1-5]\b[^>]*>(.*?)</h[1-5]>',html,re.I|re.S)
        if m:
            candidate=page(m.group(1))[1]
            if ':' in candidate and 25<len(candidate)<250:
                all_headings=[candidate]
    slug=urlsplit(url).path.strip('/').split('/')[-1]
    for heading in all_headings:
        locality=folded(heading.split(':',1)[0]).replace(' ','-')
        if locality in slug or locality.replace('n','') in slug:
            return heading
    if len(all_headings)==1:
        return all_headings[0]
    return ''


def _arsa_water_topic(text):
    """Recognize water infrastructure without calling ordinary civil works an outage.

    ARSA sometimes writes about interrupted cistern pumping without repeating
    the phrase 'agua potable'. Such notices still require an explicit impact.
    """
    return bool(re.search(
        r'agua potable|servicio de agua|suministro de agua|acueducto|red de agua|'
        r'planta potabilizadora|sistema de bombeo|cisterna|sistema de abastecimiento|'
        r'purgado de (?:la )?red|purga de (?:la )?red|red de distribucion',
        folded(text)))


def _arsa_explicit_service_impact(text):
    """Require an affirmative impact in the article, not a negated assertion.

    Examining sentences individually allows an explicit positive notice even
    if another sentence explains that unaffected neighborhoods are normal.
    """
    pattern=re.compile(
        r'\b(?:baja presion|falta de (?:suministro|agua)|afectad[oa]|afectar|'
        r'interrumpir|interrupcion|turbiedad|turbidez|corte de agua|'
        r'corte del suministro|afecta (?:a los barrios|a las zonas|el suministro|el servicio))\b')
    for sentence in re.split(r'(?<=[.!?;])\s+',folded(text)):
        if _REGIONAL_NEGATIVE.search(sentence) or re.search(
            r'\b(?:sin baja presion|no (?:hay|habra|se registrara) baja presion|'
            r'no (?:se )?afectara (?:el )?(?:servicio|suministro))\b',sentence):
            continue
        # An external electric outage does NOT prove a water outage. In
        # Valcheta a paragraph says "se vera afectado el servicio de energia
        # electrica" while a later paragraph must independently establish
        # possible low water pressure. Never promote the electrical statement
        # alone to an affirmative water-service impact.
        if re.search(r'\b(?:servicio|suministro)\s+(?:de\s+)?(?:energia\s+electrica|electrico|electricidad)\b',sentence):
            explicit_water_effect = re.search(
                r'\b(?:baja presion|falta de agua|falta de suministro|'
                r'(?:afectara|afecta|afectado|afectada|interrumpira|interrumpido)'
                r'.{0,60}(?:suministro de agua|servicio de agua|agua potable))\b',sentence)
            if not explicit_water_effect:
                continue
        if pattern.search(sentence):
            return True
    return False


def _arsa_failure_hint(html,url,now):
    """A limited, non-sensitive diagnostic for failed public-article parsing."""
    try:
        dom,visible=page(html)
        title=_arsa_article_title(dom,html,url)
        d=_month_date_near_title(visible,title,html) if title else None
        if not title:return 'no_locality_title_matching_url'
        if not d:return 'publication_date_not_found'
        if d>now.date()+timedelta(days=1):return 'publication_in_future'
        if d<now.date()-timedelta(days=2):return 'publication_too_old'
        paragraphs=' '.join(p for p in dom.paragraphs if len(p)>=42)
        if not paragraphs:return 'no_article_paragraphs'
        if not _arsa_water_topic(title+' '+paragraphs):return 'water_topic_not_identified'
        if not _arsa_explicit_service_impact(paragraphs):return 'water_service_impact_not_explicit'
        return 'notice_rejected_by_validation'
    except Exception as exc:
        return 'diagnostic_'+type(exc).__name__



def _arsa_index_date(index_visible,label):
    """A date published directly beside an article link in ARSA's official index.

    This is a fallback for article pages with unparseable theme metadata, not
    permission to infer scheduled hours or the current water-supply state.
    """
    if not label or len(label)<25:
        return None
    positions=[m.start() for m in re.finditer(re.escape(label),index_visible,re.I)]
    for pos in reversed(positions):
        excerpt=index_visible[max(0,pos-230):pos]
        # The date of this item is the last date preceding this title. A
        # preceding title before the date is harmless; a different title
        # *after* the date means it belongs to the earlier article instead.
        # This avoids both false borrowing and missing valid dates in a dense
        # news index where many titles fit inside the 230-character window.
        date_parts=list(re.finditer(r'\b\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s*,?\s*(?:de\s+)?20\d{2}\b',folded(excerpt)))
        if date_parts:
            latest=date_parts[-1]
            text_after_date=excerpt[latest.end():]
            if re.search(r'\b[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ ]{3,45}:',text_after_date):
                continue
            return _parse_official_day(latest.group(0))
    return None

def _arsa_times_from_dated_paragraphs(paragraphs, published, scheduled):
    """Extract only explicitly attached work times; never infer an end hour.

    The actual 12 Nov Bariloche article publishes the date in paragraph 1,
    the affected zone in paragraph 2, and the hours in paragraph 3. Search
    at most two following paragraphs of the *same dated work*, stopping at
    another explicitly dated notice or office-hours content. Do not look
    further into site navigation or unrelated announcements.
    """
    for index, paragraph in enumerate(paragraphs):
        if _weekday_date(paragraph, published) != scheduled:
            continue
        scoped = [paragraph]
        for next_paragraph in paragraphs[index+1:index+3]:
            normalized = folded(next_paragraph)
            neighbor_day = _weekday_date(next_paragraph, published)
            if neighbor_day is not None and neighbor_day != scheduled:
                break
            # A different weekday/date is a boundary even if it is malformed
            # or outside the publication horizon; never borrow its times.
            has_explicit_date = re.search(
                r'\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+'
                r'\d{1,2}\b', normalized)
            if has_explicit_date and neighbor_day != scheduled:
                break
            if re.search(r'\boficina\b|atencion al publico|horario de atencion', normalized):
                break
            scoped.append(next_paragraph)
        flat = folded(' '.join(scoped))
        start_match = re.search(
            r'\b(?:desde|a partir de|entre)\s+las\s+(\d{1,2})(?::(\d{2}))?\b'
            r'|\b(?:comenzaran|comenzara|iniciaran|iniciara)\s+a\s+las\s+(\d{1,2})(?::(\d{2}))?\b',
            flat)
        if not start_match:
            continue
        captured = start_match.groups()
        hour = int(captured[0] or captured[2])
        minute = int(captured[1] or captured[3] or 0)
        if hour > 23 or minute > 59:
            continue
        start = datetime(scheduled.year, scheduled.month, scheduled.day, hour, minute, tzinfo=ART)
        result = {'scheduled_start': start.isoformat(timespec='minutes'),
                  'scheduled_end': None, 'time_precision': 'start_known_end_unknown'}
        after = flat[start_match.end():]
        # An end must be tied to the SAME scheduled work, not to unrelated
        # office hours or an adjacent news article.
        end_match = re.search(
            r'\b(?:y\s+las|hasta\s+(?:aproximadamente\s+)?las|finalizaran\s+a\s+las|finalizara\s+a\s+las)\s+'
            r'(\d{1,2})(?::(\d{2}))?\b', after[:230])
        if not end_match:
            return result
        end_hour = int(end_match.group(1))
        end_minute = int(end_match.group(2) or 0)
        if end_hour > 23 or end_minute > 59:
            return result
        end = datetime(scheduled.year, scheduled.month, scheduled.day, end_hour, end_minute, tzinfo=ART)
        if not start < end <= start + timedelta(hours=18):
            return result
        near_end = after[max(0,end_match.start()-40):end_match.end()+55]
        if re.search(r'\baproximad|\bestimad|\bprevist', near_end):
            result['scheduled_end_estimate'] = end.isoformat(timespec='minutes')
            result['time_precision'] = 'start_known_end_estimated'
        else:
            result['scheduled_end'] = end.isoformat(timespec='minutes')
            result['time_precision'] = 'start_and_end_published'
        return result
    return {'scheduled_start':None,'scheduled_end':None,'time_precision':'date_only'}



def _arsa_reported_two_day_water_windows(paragraphs, published):
    """Preserve two distinct reported water-impact windows, not a live status.

    A publication dated Thursday can say "hoy de 13:00 a 18:00 y el
    viernes de 00:00 a 07:00 horas se registrara baja presion". Both
    clock intervals belong to water distribution work, but neither is
    evidence that water is *currently* interrupted or restored.

    This deliberately narrow grammar requires the SAME paragraph to link
    the windows to water-network works and a positive impact statement.
    "hoy" is anchored to the independently verified publication day and
    the second named weekday must be the immediately following calendar day.
    Ambiguous, negated, duplicate, or office-hour ranges are discarded.
    """
    pattern = re.compile(
        r'\bhoy\s+de\s+(\d{1,2})(?::(\d{2}))?\s+a\s+'
        r'(\d{1,2})(?::(\d{2}))?\s+y\s+el\s+'
        r'(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+de\s+'
        r'(\d{1,2})(?::(\d{2}))?\s+a\s+'
        r'(\d{1,2})(?::(\d{2}))?\s*(?:horas|hs\.?)?\s+'
        r'(?:se\s+registrara|podra\s+registrarse)\s+'
        r'(?:baja\s+presion|falta\s+de\s+(?:agua|suministro))\s+'
        r'en\s+(?:el\s+)?(?:servicio|suministro|red)\b'
    )
    candidates = []
    for paragraph in paragraphs:
        f = folded(paragraph)
        if re.search(r'\boficina\b|horario de atencion|atencion al publico', f):
            continue
        for m in pattern.finditer(f):
            before = f[:m.start()]
            if not re.search(r'\bmaniobras\b|\btrabajos\b|\btareas\b', before):
                continue
            if not re.search(r'\bred de distribucion\b|\bred de agua\b|'
                             r'\bservicio de agua\b|\bagua potable\b', before):
                continue
            next_day = published + timedelta(days=1)
            if WEEKDAY[m[5]] != next_day.weekday():
                continue
            values = [(m[1], m[2], m[3], m[4]),
                      (m[6], m[7], m[8], m[9])]
            windows = []
            for day, (start_h, start_m, end_h, end_m) in zip((published, next_day),values):
                sh, sm = int(start_h), int(start_m or 0)
                eh, em = int(end_h), int(end_m or 0)
                if sh>23 or eh>23 or sm>59 or em>59:
                    break
                a=datetime(day.year,day.month,day.day,sh,sm,tzinfo=ART)
                b=datetime(day.year,day.month,day.day,eh,em,tzinfo=ART)
                if not a < b <= a+timedelta(hours=18):
                    break
                windows.append({
                    'start':a.isoformat(timespec='minutes'),
                    'end':b.isoformat(timespec='minutes'),
                    'impact':'reported_possible_water_low_pressure_not_live',
                })
            if len(windows)==2:
                candidates.append(windows)
    if len(candidates)!=1:
        return None
    return {
        'scheduled_start':None, 'scheduled_end':None,
        'reported_water_impact_windows':candidates[0],
        'time_precision':'two_published_water_impact_windows_not_live',
    }


def _arsa_reported_same_day_work_window(paragraphs, published):
    """Preserve an explicitly dated work window without implying a live outage.

    A press release published on Wednesday may say 'este miércoles' instead
    of 'miércoles 18'. Accept that ONLY when its weekday agrees with its
    independently established publication date. Both bounds must be stated
    together in the same paragraph that describes water works.
    """
    weekday = next((name for name, num in WEEKDAY.items() if num == published.weekday()), None)
    if not weekday:
        return None
    for paragraph in paragraphs:
        f=folded(paragraph)
        if not re.search(r'\beste\s+'+weekday+r'\b',f):
            continue
        if not re.search(r'\btareas\b|\btrabajos\b|\bintervencion\b', f):
            continue
        if not re.search(r'\bplanta\b|\bdecantador\b|\bagua\b|\bred\b',f):
            continue
        if not re.search(r'\bse realizaran\b|\bse llevaran a cabo\b|\bprevist',f):
            continue
        windows=list(re.finditer(
            r'\bentre\s+las\s+(\d{1,2})(?::(\d{2}))?\s+y\s+las\s+'
            r'(\d{1,2})(?::(\d{2}))?\s*(?:horas|hs)?\b',f))
        if len(windows)!=1:
            continue
        m=windows[0]
        before_window=f[max(0,m.start()-120):m.start()]
        # The work paragraph can also mention a separate office schedule.
        # Don't attach that schedule to water supply operations.
        if re.search(r'horario de atencion|atencion al publico|oficina',before_window):
            continue
        h1,mi1,h2,mi2=int(m[1]),int(m[2] or 0),int(m[3]),int(m[4] or 0)
        if h1>23 or h2>23 or mi1>59 or mi2>59:
            continue
        a=datetime(published.year,published.month,published.day,h1,mi1,tzinfo=ART)
        b=datetime(published.year,published.month,published.day,h2,mi2,tzinfo=ART)
        if not a<b<=a+timedelta(hours=18):
            continue
        return {'scheduled_date':published.isoformat(),
                'scheduled_start':a.isoformat(timespec='minutes'),
                'scheduled_end':b.isoformat(timespec='minutes'),
                'time_precision':'published_same_day_work_window_not_live'}
    return None



def _arsa_reported_hours_without_confirmed_day(paragraphs):
    """Preserve reported work hours when the article does not establish a day.

    Example from an official Bariloche release: the article states repairs
    have begun and that *desde las 12 y hasta aproximadamente las 19* water
    supply may be affected. Its publication date alone does NOT prove the
    work took place that date. Keep only local clock values, not scheduled
    timestamps or a claim of an active outage.

    The hours and explicit impact must occur in the SAME paragraph, supported
    by water-repair context in that or its immediately preceding paragraph.
    Never borrow office hours, unrelated article hours, or a second window.
    """
    candidates=[]
    pattern=re.compile(
        r'\bdesde\s+las\s+(\d{1,2})(?::(\d{2}))?\s+'
        r'(?:y\s+)?hasta\s+(?:(aproximadamente|aprox\.?|cerca de)\s+)?'
        r'(?:las\s+)?(\d{1,2})(?::(\d{2}))?\b'
    )
    for i, paragraph in enumerate(paragraphs):
        text=folded(paragraph)
        if re.search(r'horario de atencion|atencion al publico|\boficina\b|horario comercial',text):
            continue
        if not re.search(r'\bbaja presion\b|\bfalta (?:de agua|de suministro)\b|'
                         r'\bfaltas de suministro\b|\bservicio intermitente\b|'
                         r'\binterrupcion del suministro\b',text):
            continue
        prev=folded(paragraphs[i-1]) if i>0 else ''
        work=r'\btrabajos\b|\btareas\b|\breparacion\b|\bintervencion\b'
        infrastructure=r'\bcaneria\b|\bplanta\b|\bpotabiliz|\bred de agua\b'
        # The work and the water infrastructure must be identified together
        # in one paragraph; do not combine a municipal plaza construction
        # from the previous paragraph with water-impact hours here.
        if not ((re.search(work,text) and re.search(infrastructure,text)) or
                (re.search(work,prev) and re.search(infrastructure,prev))):
            continue
        for m in pattern.finditer(text):
            h1,mi1,approx,h2,mi2=int(m[1]),int(m[2] or 0),m[3],int(m[4]),int(m[5] or 0)
            if h1>23 or mi1>59 or h2>23 or mi2>59:
                continue
            if not (0 < ((h2*60+mi2)-(h1*60+mi1)) <= 18*60):
                continue
            # Approximation after the time is equally authoritative as before it.
            right=text[m.end():m.end()+40]
            estimated=bool(approx or re.match(r'\s*(?:horas\s*,?\s*)?(?:aproximadamente|aprox\.?)\b',right))
            candidates.append((f'{h1:02d}:{mi1:02d}',f'{h2:02d}:{mi2:02d}',estimated))
    if len(candidates)!=1:
        return None
    start,end,estimated=candidates[0]
    result={'scheduled_start':None,'scheduled_end':None,
            'reported_start_local_time':start,
            'time_precision':'reported_hours_day_unverified_not_live'}
    result['reported_end_local_time_estimate' if estimated else 'reported_end_local_time']=end
    return result

def _arsa_work_already_started(paragraphs, published, scheduled):
    """Read explicit dated *started* work, not a future outage announcement.

    The 22 Nov El Bolson release says staff "trabaja desde las 9 de este
    domingo 22" and *estimates* pressure normalization "a partir de las
    14 hs". Preserve both as reported facts, not a scheduled end or a
    confirmation of normal supply. Never borrow an office-hour or different
    dated work as a service-restoration forecast.
    """
    weekdays='|'.join(WEEKDAY)
    start_pattern=re.compile(
        r'\b(?:trabaja|trabajan|se trabaja|viene trabajando)\s+desde\s+las\s+'
        r'(\d{1,2})(?::(\d{2}))?\s+(?:de\s+)?este\s+'
        r'('+weekdays+r')\s+(\d{1,2})\b')
    prediction=re.compile(
        r'\b(?:se preve|se estima)\s+que\s+a\s+partir\s+de\s+las\s+'
        r'(\d{1,2})(?::(\d{2}))?\s*(?:hs|horas)?\s+'
        r'(.{0,85}?)\bnormalizad[oa]\b')
    for i,p in enumerate(paragraphs):
        if _weekday_date(p,published)!=scheduled:
            continue
        f=folded(p)
        m=start_pattern.search(f)
        if not m or not re.search(r'\breparacion\b|\breparaciones\b',f):
            continue
        if not re.search(r'\bcaneria\b|\bred de agua\b|\bred de distribucion\b',f):
            continue
        if re.search(r'\bno\s+(?:se\s+)?(?:trabaja|trabajan)\s+desde\b',f):
            continue
        hour,minute=int(m[1]),int(m[2] or 0)
        if hour>23 or minute>59:
            continue
        # Require this particular weekday and day, not merely a date
        # somewhere else in the article or a title about future works.
        if WEEKDAY[m[3]]!=scheduled.weekday() or int(m[4])!=scheduled.day:
            continue
        started=datetime(scheduled.year,scheduled.month,scheduled.day,hour,minute,tzinfo=ART)
        info={'reported_work_date':scheduled.isoformat(),
              'reported_work_started_at':started.isoformat(timespec='minutes'),
              'scheduled_start':None,'scheduled_end':None,
              'time_precision':'reported_work_started_not_live'}
        candidates=[]
        for next_p in paragraphs[i:i+3]:
            normalized=folded(next_p)
            if (re.search(r'\boficina\b|atencion al publico|horario de atencion',normalized)
                or (_weekday_date(next_p,published) not in (None,scheduled))):
                break
            for match in prediction.finditer(normalized):
                # An explicitly negated forecast is not an estimate.
                preceding=normalized[max(0,match.start()-4):match.start()]
                if re.search(r'\bno\s*$',preceding):
                    continue
                context=normalized[match.start():match.end()+95]
                if re.search(r'\bno\s+(?:este|estara|se encuentre)\s+normalizad[oa]',context):
                    continue
                if not re.search(r'\bpresion\b|\bsuministro\b|\bservicio\b',context):
                    continue
                h2,m2=int(match[1]),int(match[2] or 0)
                if h2>23 or m2>59:
                    continue
                estimated=datetime(scheduled.year,scheduled.month,scheduled.day,h2,m2,tzinfo=ART)
                if started < estimated <= started+timedelta(hours=18):
                    candidates.append(estimated)
        # Multiple distinct predictions do not establish a single estimate.
        if len(set(candidates))==1:
            info['reported_pressure_normalization_estimate']=candidates[0].isoformat(timespec='minutes')
            info['time_precision']='reported_started_work_normalization_estimated_not_live'
        return info
    return None


def _arsa_reported_electricity_outage_window(paragraphs, published):
    """Record a dated external power outage affecting the water system.

    The 12-16h energy outage in Valcheta is NOT a prediction that water
    pressure will recover at 16h. Preserve the source's electric window
    separately and never fill water scheduled_end from it.
    """
    found = []
    for paragraph in paragraphs:
        f = folded(paragraph)
        d = _weekday_date(paragraph, published)
        if not d or d > published + timedelta(days=HORIZON_DAYS):
            continue
        if not re.search(r'energia electrica|servicio electrico|suministro electrico', f):
            continue
        if not re.search(r'se vera afectad|se interrumpira|corte programado|se registrara un corte|sera suspendido', f):
            continue
        if re.search(r'no se vera afectad|no se interrumpira|no habra corte|sin corte|se descarta', f):
            continue
        windows = list(re.finditer(
            r'\bentre\s+las\s+(\d{1,2})(?::(\d{2}))?'
            r'\s+y\s+las\s+(\d{1,2})(?::(\d{2}))?\s+horas\b', f))
        if len(windows) != 1:
            continue
        m = windows[0]
        h1, mi1, h2, mi2 = int(m[1]), int(m[2] or 0), int(m[3]), int(m[4] or 0)
        if h1 > 23 or h2 > 23 or mi1 > 59 or mi2 > 59:
            continue
        a = datetime(d.year,d.month,d.day,h1,mi1,tzinfo=ART)
        b = datetime(d.year,d.month,d.day,h2,mi2,tzinfo=ART)
        if not a < b <= a + timedelta(hours=18):
            continue
        found.append((a,b))
    if len(set(found)) != 1:
        return {}
    start, end = found[0]
    return {
        'reported_electricity_outage_start':start.isoformat(timespec='minutes'),
        'reported_electricity_outage_end':end.isoformat(timespec='minutes'),
        'reported_electricity_end_does_not_confirm_water_recovery':True,
    }


def _arsa_article(html,url,now,index_published=None):
    dom,visible=page(html)
    title=_arsa_article_title(dom,html,url)
    if not title:
        return [],None
    article_published=_month_date_near_title(visible,title,html)
    # If both official article and category show a date, they must agree.
    if article_published and index_published and article_published!=index_published:
        return [],None
    published=article_published or index_published
    if not published or published>now.date()+timedelta(days=1):
        return [],None
    if published<now.date()-timedelta(days=2):
        return [],published
    locality=clean(title.split(':')[0],90)
    # Never infer location from generic organizational or site-navigation titles.
    if len(locality)<3 or folded(locality) in ('noticias','interrupciones del servicio'):
        return [],published
    paragraphs=[p for p in dom.paragraphs if len(p)>=42]
    content=' '.join(paragraphs)
    f=folded(content)
    # The provider may identify 'purgado de red' only in its locality heading.
    # A matching title establishes the water TOPIC, never the service impact:
    # an explicit positive impact is still mandatory in article paragraphs.
    if not _arsa_water_topic(title+' '+content):
        return [],published
    if re.search(r'oficina|atencion al publico|factura|cobranz',folded(title)):
        return [],published
    if re.search(r'finalizaron|normalizad[oa]|restablecido|concluyeron',folded(title)):
        return [],published
    # A generic announcement about works is not evidence of affected supply.
    if not _arsa_explicit_service_impact(content):
        return [],published
    external_power_window = _arsa_reported_electricity_outage_window(paragraphs,published)
    # Preserve explicitly reported start/normalization times after the day
    # of publication. Earlier versions only tried parsing a started repair
    # when its dated work day was >= today's date, so the same article lost
    # factual metadata at midnight. Do NOT treat it as an active outage.
    # Publication-day anchoring also prevents reclassifying a future plan
    # published on an earlier date as work already started.
    if published<=now.date():
        already_started=_arsa_work_already_started(paragraphs,published,published)
        if already_started:
            return [mk_notice('Aguas Rionegrinas','Río Negro',locality,url,
                'water_service_bulletin','publication_only_not_live',content,
                published_on=published.isoformat(),**already_started,
                **external_power_window)],published
    scheduled=None
    for p in paragraphs:
        d=_weekday_date(p,published)
        if d and now.date()<=d<=now.date()+timedelta(days=HORIZON_DAYS):
            scheduled=d
            break
    title_fold=folded(title)
    future_verb=bool(re.search(r'se realizaran|se llevaran adelante|se preve|realizara|tareas programadas|trabajos programados|esta previsto',f+' '+title_fold))
    # An explicit "trabaja desde las 9 de este domingo 22" describes work
    # already underway, even if another sentence says "se preve" about its
    # estimated normalization. Never misclassify it as a future scheduled cut.
    # A planned weekday on a later date cannot establish that work started.
    # Started-work metadata is parsed above, strictly on publication day.
    # Past-tense completed/same-day works are publication-only, not plans.
    if scheduled and future_verb and not re.search(r'inicio trabajos|iniciaron los trabajos|tareas comenzaron',title_fold):
        times=_arsa_times_from_dated_paragraphs(paragraphs,published,scheduled)
        return [mk_notice('Aguas Rionegrinas','Río Negro',locality,url,
                  'planned_water_service_impact','scheduled_not_confirmed',content,
                  published_on=published.isoformat(),scheduled_date=scheduled.isoformat(),
                  **times,**external_power_window)],published
    # Same-day planned work may have explicit clock hours but no numeric day.
    # Preserve them as dated bulletin metadata, NEVER as a live outage status.
    reported_multi_window = _arsa_reported_two_day_water_windows(paragraphs,published)
    reported_window = (_arsa_reported_same_day_work_window(paragraphs,published)
                       if reported_multi_window is None else None)
    time_fields = (reported_multi_window if reported_multi_window is not None
                   else reported_window if reported_window is not None
                   else _arsa_reported_hours_without_confirmed_day(paragraphs)
                   or {'scheduled_start':None,'scheduled_end':None})
    return [mk_notice('Aguas Rionegrinas','Río Negro',locality,url,
                      'water_service_bulletin','publication_only_not_live',content,
                      published_on=published.isoformat(),**time_fields,
                      **external_power_window)],published


def _collect_arsa(checked_at,now,fetch):
    """Rotating, conservative ARSA sampling; HTTP 429 stops this host.

    Don't claim complete coverage: some items may be deferred by the request
    budget. Older, explicitly dated index entries need not be fetched again.
    """
    result=_result('aguas_rionegrinas_arsa',checked_at)
    result['parser_revision']='ARSA-STARTED-WORK-ESTIMATES-v5.70'
    result['time_metadata_revision']='ARSA-ELECTRIC-WINDOW-v5.86'
    result['multi_window_metadata_revision']='ARSA-TWO-DAY-IMPACT-WINDOWS-v5.87'
    result['rate_limited']=False
    result['article_links_skipped_after_rate_limit']=0
    result['article_links_skipped_old']=0
    result['articles_deferred_by_budget']=0
    result['max_article_requests_per_run']=2
    result['sampling_strategy']='newest_plus_fresh_hourly_rotating_secondary'
    result['sampling_rotation_utc_hour']=int(now.astimezone(timezone.utc).timestamp() // 3600)
    result['article_links_selected']=[]
    url=result['source_url']
    seen=[];attempts=[];checked=0;newest=None
    links=[]
    index_read=False
    result['index_attempts']=[]
    result['index_mode']='category'
    result['index_warning']=None
    try:
        index_html=fetch(url)
        dom,index_visible=page(index_html)
        index_read=True
        links=[]
        link_dates={}
        def add_links(dom, visible, root, fallback=False):
            for href,label in dom.anchors:
                link=urljoin(root,href)
                parsed=urlsplit(link)
                if parsed.scheme!='https' or parsed.hostname not in ('aguasrionegrinas.com','www.aguasrionegrinas.com'):
                    continue
                if not re.fullmatch(r'/[a-z0-9-]{20,}/?',parsed.path):
                    continue
                if ':' not in label or len(label)<25 or link in links:
                    continue
                # The homepage mixes all departments; only read water-related
                # headings if the category index became unavailable.
                if fallback and not re.search(r'agua|arsa|suministro|turbiedad|presion|corte|acueducto|bombeo',folded(label)):
                    continue
                links.append(link)
                link_dates[link]=_arsa_index_date(visible,label)
        add_links(dom,index_visible,url)
        result['index_attempts'].append({
            'url':url,'result':'article_links_found' if links else 'no_recognizable_links',
            'html_anchors_seen':len(dom.anchors),'visible_text_characters':len(index_visible),
            'html_bytes':len(index_html.encode('utf-8'))})
        if not links:
            home='https://aguasrionegrinas.com/'
            try:
                home_html=fetch(home)
                home_dom,home_visible=page(home_html)
                add_links(home_dom,home_visible,home,fallback=True)
                result['index_attempts'].append({
                    'url':home,'result':'article_links_found' if links else 'no_recognizable_links',
                    'html_anchors_seen':len(home_dom.anchors),
                    'visible_text_characters':len(home_visible),
                    'html_bytes':len(home_html.encode('utf-8'))})
                result['index_mode']='homepage_fallback'
            except Exception as exc:
                result['index_attempts'].append({
                    'url':home,'result':'fetch_or_parse_error','error_type':type(exc).__name__})
        if not links:
            result['index_warning']='Ni el indice de interrupciones ni la portada ofrecieron enlaces reconocibles. Lectura sin verificar; no significa suministro normal.'
        result['article_links_seen']=len(links)

        # Keep the same newest-first category window. Only *reliably dated*
        # articles older than our bulletin horizon can be skipped without an
        # extra request; undated items still count towards the request budget.
        candidates=[]
        for link in links[:9]:
            day=link_dates.get(link)
            if day and day < now.date()-timedelta(days=2):
                result['article_links_skipped_old']+=1
            else:
                candidates.append(link)
        # Prefer a secondary article with the newest reliable index date.
        # Older items (even those still inside the two-day bulletin horizon)
        # need not take turns from newer same-day announcements. Undated
        # articles remain eligible: an absent date is not proof of staleness.
        # If all secondaries are older, retain the old rotation as a fallback.
        # The primary newest-first index item is always checked as before.
        selected=candidates[:1]
        secondary_indexes=list(range(1,len(candidates)))
        if secondary_indexes:
            dated=[link_dates.get(link) for link in candidates]
            reliable=[d for d in dated if d is not None and d <= now.date()+timedelta(days=1)]
            newest_day=max(reliable) if reliable else None
            if newest_day:
                fresh_indexes=[i for i in secondary_indexes
                               if dated[i] is None or dated[i]>=newest_day]
                if fresh_indexes:
                    secondary_indexes=fresh_indexes
            second_index=secondary_indexes[result['sampling_rotation_utc_hour'] % len(secondary_indexes)]
            selected.append(candidates[second_index])
            result['sampling_secondary_index']=second_index
        else:
            result['sampling_secondary_index']=None
        result['sampling_secondary_pool_size']=len(secondary_indexes)
        result['sampling_older_secondary_deprioritized']=max(0,len(candidates)-1-len(secondary_indexes))
        result['article_links_selected']=list(selected)
        result['articles_deferred_by_budget']=max(0,len(candidates)-len(selected))
        for position,link in enumerate(selected):
            # Requests are deliberately spread out for production collection.
            # Offline fixture-based unit tests do not sleep.
            if position and (fetch is fetch_html or
                             getattr(fetch, '_production_network_fetch', False)):
                sleep(2.25)
            checked+=1
            try:
                transient_retry=False
                try:
                    article_html=fetch(link)
                except HTTPError as http_exc:
                    # Never retry HTTP 429 immediately. A few transient 5xx
                    # responses may be retried only once, as before.
                    if http_exc.code not in (500,502,503,504):
                        raise
                    transient_retry=True
                    article_html=fetch(link)
                index_day=link_dates.get(link)
                notices,published=_arsa_article(article_html,link,now,index_published=index_day)
                if published:
                    newest=max(newest,published) if newest else published
                seen.extend(notices)
                attempt={'url':link,'result':'parsed' if notices else 'no_recent_service_notice'}
                if transient_retry:attempt['transient_http_retry_succeeded']=True
                if not notices:attempt['reason']=_arsa_failure_hint(article_html,link,now)
                if index_day:attempt['category_published_on']=index_day.isoformat()
                attempts.append(attempt)
            except Exception as exc:
                failed={'url':link,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
                if isinstance(exc,HTTPError):failed['http_status']=exc.code
                attempts.append(failed)
                if isinstance(exc,HTTPError) and exc.code==429:
                    result['rate_limited']=True
                    result['article_links_skipped_after_rate_limit']=len(selected)-position-1
                    break
    except Exception as exc:
        attempt={'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
        result['index_warning']='Fallo el indice de interrupciones; no se pudo verificar su contenido.'
        if isinstance(exc,HTTPError):
            attempt['http_status']=exc.code
            if exc.code==429:result['rate_limited']=True
        attempts.append(attempt)
    result['source_attempts']=attempts
    result['articles_checked']=checked
    result['records_checked']=checked
    result['notices']=list({n['id']:n for n in seen}.values())
    if newest:
        result['latest_published_date']=newest.isoformat()
    error_count=sum(1 for attempt in attempts if attempt['result']=='fetch_or_parse_error')
    partial=bool(error_count or result['rate_limited'] or result['articles_deferred_by_budget']
                 or result['index_mode']=='homepage_fallback')
    result['article_fetch_completeness']=(
        'unverified' if not index_read or not links else
        'partial' if partial else 'selected_articles_checked')
    if result['notices']:
        result['status']='ok'
        result['message']='Comunicados de ARSA fechados; no confirman la situación en tiempo real.'
        if result['index_mode']=='homepage_fallback':
            result['message']+=' Indice principal sin enlaces: consulta PARCIAL desde la portada oficial.'
        if result['rate_limited']:
            result['message']+=' Consulta PARCIAL por límite HTTP 429; no se verificaron todos los artículos.'
        elif error_count:
            result['message']+=f' Consulta PARCIAL: {error_count} artículo(s) inaccesible(s).'
    elif result['rate_limited']:
        result['message']=('La fuente impuso un límite HTTP 429; no hay avisos recuperados '
                           'de forma verificable en esta consulta. No significa suministro normal.')
    elif newest and newest<now.date()-timedelta(days=2):
        result.update(status='stale',message='Solo publicaciones antiguas verificables.')
    else:
        result['message']='No se recuperaron artículos recientes con localidad y afectación verificables.'
        if error_count:
            result['message']+=f' {error_count} artículo(s) no pudieron consultarse; no implica servicio normal.'
    if result.get('index_warning'):
        result['message']+=' '+result['index_warning']
    if result['articles_deferred_by_budget']:
        result['message']+=(' Consulta PARCIAL: se pospusieron '
                            f"{result['articles_deferred_by_budget']} artículo(s) para reducir el riesgo de HTTP 429.")
    return result


def _collect_catamarca(checked_at,now,fetch):
    # The official page is currently an empty heading, not a trustworthy status.
    result=_result('aguas_catamarca',checked_at)
    result['parser_revision']='CATAMARCA-STATUS-v5.33'
    try:
        dom,visible=page(fetch(result['source_url']))
        result['page_read']=True
        result['records_checked']=0
        result['message']=('Página pública de suspensiones consultada; no hay registros '
                           'con fecha, localidad y estado suficientes. No confirma servicio normal.')
        # Intentionally no success state or notices until a structured row is available.
    except Exception as exc:
        result['message']='No se pudo verificar portal de Catamarca: '+type(exc).__name__
    return result


# Account-specific AySA lookups require a service account and must NEVER be
# queried or synthesized by the public bulletin collector.
def _collect_aysa(checked_at,now,fetch):
    result=_result('aysa_amba',checked_at)
    result['parser_revision']='AYSA-ACCOUNT-ONLY-v5.41'
    result['coverage_kind']='address_account_lookup_only'
    result['account_lookup_required']=True
    result['subscription_url']='https://cortes.web.aysa.com.ar/'
    result['notices']=[]
    result['notifications_enabled']=False
    result['message']='AySA exige consulta por cuenta de servicio para verificar un domicilio. No se consultan datos personales ni se infiere un corte por localidad.'
    try:
        _,visible=page(fetch(result['source_url']))
        lowered=folded(visible)
        if 'cuenta' in lowered and ('interrupcion' in lowered or 'servicio' in lowered):
            result['status']='unverified'
            result['access_mode']='account_required'
            result['portal_reachable']=True
        else:
            result['portal_reachable']=True
            result['message']='Portal de AySA accesible sin criterios publicos suficientes para verificar domicilio; requiere consulta del titular.'
    except Exception as exc:
        result['portal_reachable']=False
        result['message']='No se pudo verificar portal de AySA: '+type(exc).__name__+'. Requiere consulta por cuenta, no implica servicio normal.'
    return result


# The public AySA news section is entirely separate from account-specific checks.
# A news article does not establish that a particular home has lost water.
_AYSA_BA_LOCALITIES = (
    'Tigre','San Fernando','San Martin','Vicente Lopez','San Isidro',
    'Tres de Febrero','Hurlingham','Moron','Ituzaingo','Merlo','La Matanza',
    'Quilmes','Bernal','Avellaneda','Lanus','Lomas de Zamora',
    'Temperley','Banfield','Adrogue','Burzaco','Ezeiza','Berazategui',
    'Pilar','Jose C. Paz','Malvinas Argentinas','San Miguel',
)
_AYSA_CABA_BARRIOS = (
    'Recoleta','Palermo','Belgrano','Caballito','Almagro','Balvanera',
    'Villa Crespo','San Nicolas','Retiro','Constitucion','San Telmo',
    'Monserrat','Barracas','Parque Patricios','Villa Urquiza','Saavedra',
    'Nunez','Flores','Floresta','Villa Devoto','Villa del Parque',
    'Colegiales','Chacarita','La Boca','Puerto Madero',
)
_AYSA_NEWS_TERMS = (
    'agua','servicio','inspeccion','reparacion','mantenimiento',
    'interrupcion','estacion elevadora','rios subterraneos',
    'corte','operativo','valvulas',
)
_AYSA_IMPACT = re.compile(
    r'(?:baja\s+presion|falta\s+de\s+agua|podri[aa]\s+(?:verse\s+)?afectad[oa]|'
    r'podria\s+haber\s+una\s+afectacion|posible\s+afectacion|afectacion\s+(?:en|del)\s+(?:el\s+)?servicio|'
    r'servicio\s+de\s+agua\s+(?:potable\s+)?(?:se\s+vera\s+afectado|podria\s+verse\s+afectado)|'
    r'se\s+ver[aa]\s+afectad[oa]|'
    r'interrupcion\s+del\s+(?:suministro|servicio)|'
    r'reduccion\s+(?:de\s+)?(?:la\s+)?presion|'
    r'se\s+registrar[aa]\s+(?:una\s+)?(?:baja|falta))'
)
_AYSA_CLEAR_LOCATION_GROUP = re.compile(
    r'(?:localidades|partidos|barrios|zonas|sectores)\s+(?:de|del|en)\s+', re.I
)


def _aysa_news_date(visible):
    match=re.search(r'\b(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(20\d{2})\b',folded(visible[:6000]))
    if not match or match.group(2) not in MONTH:
        return None
    try:
        return date(int(match.group(3)),MONTH[match.group(2)],int(match.group(1)))
    except ValueError:
        return None


def _aysa_news_article(html,url,now):
    dom,visible=page(html)
    published=_aysa_news_date(visible)
    if not published:
        return [],None
    if published>now.date() or published<now.date()-timedelta(days=3):
        return [],published
    title=next((h for h in dom.headings if len(h)>12 and folded(h) not in ('novedades','aysa')), '')
    title_f=folded(title)
    if not title or re.search(r'finalizo|finalizaron|normalizad[oa]|restablecido|concluyeron',title_f):
        return [],published
    # Only text from actual news paragraphs; no footer or contact-hours text.
    body=[]
    for para in dom.paragraphs:
        f=folded(para)
        if 'atencion comercial' in f or 'atencion tecnica' in f:
            break
        if len(para)>45:
            body.append(para)
    if not body:
        return [],published
    impact_sentences=[]
    for para in body:
        for sentence in re.split(r'(?<=[.!?])\s+',para):
            normal=folded(sentence)
            # A negated impact must never become an affected-locality bulletin.
            if re.search(r'\b(?:no\s+(?:se\s+)?ver[aa]\s+afectad[oa]|sin\s+afectar|sin\s+cortes|no\s+habr[aa]\s+(?:cortes|baja\s+presion)|no\s+se\s+registrar[aa]\s+(?:baja|falta))', normal):
                continue
            if _AYSA_IMPACT.search(normal):
                impact_sentences.append(sentence)
    if not impact_sentences:
        return [],published
    candidates=list(_AYSA_BA_LOCALITIES)+list(_AYSA_CABA_BARRIOS)
    unique={}
    for sentence in impact_sentences:
        f=folded(sentence)
        # A precise named city must be described as potentially affected, not
        # merely mentioned as a plant, headquarters, district or article title.
        scopes=[]
        for match in _AYSA_CLEAR_LOCATION_GROUP.finditer(f):
            scopes.append(f[match.end():match.end()+230])
        if re.search(r'\b(?:en|de)\s+(?:el\s+)?(?:barrio|localidad|partido|ciudad)\s+(?:de\s+)?',f):
            scopes.append(f)
        for name in candidates:
            exact=r'(?<![a-z])'+re.escape(folded(name))+r'(?![a-z])'
            if any(re.search(exact,scope) for scope in scopes):
                unique[folded(name)]=name
    if not unique:
        return [],published
    content=excerpt(' '.join(impact_sentences),950)
    result=[]
    for name in sorted(unique.values(),key=folded):
        province='CABA' if name in _AYSA_CABA_BARRIOS else 'Buenos Aires'
        result.append(mk_notice('AySA',province,name,url,
                                'water_service_bulletin','publication_only_not_live',
                                content,published_on=published.isoformat(),
                                area_precision='partes_de_localidad_segun_comunicado',
                                scheduled_start=None,scheduled_end=None))
    return result,published


def _collect_aysa_public(checked_at,now,fetch):
    result=_result('aysa_public_bulletins_amba',checked_at)
    result['parser_revision']='AYSA-NEWS-v5.42'
    result['coverage_limitation']='Las noticias publicas de AySA pueden no incluir todos sus comunicados de emergencia ni verificar domicilios.'
    result['coverage_kind']='public_dated_articles_only_not_account_status'
    result['account_lookup_required_for_address']=True
    result['article_links_seen']=0
    result['articles_checked']=0
    result['source_attempts']=[]
    newest=None
    latest_index_date=None
    try:
        dom,_=page(fetch(result['source_url']))
        urls=[]
        for href,label in dom.anchors:
            absolute=urljoin(result['source_url'],href)
            parsed=urlsplit(absolute)
            if parsed.scheme!='https' or parsed.hostname not in ('www.aysa.com.ar','aysa.com.ar'):
                continue
            if not re.fullmatch(r'/usuarios/Novedades/20\d{2}/\d{2}/[a-zA-Z0-9_-]+/?',parsed.path,re.I):
                continue
            if not any(term in folded(label) for term in _AYSA_NEWS_TERMS):
                continue
            listing_date=_aysa_news_date(label)
            if listing_date:
                if latest_index_date is None or listing_date>latest_index_date:
                    latest_index_date=listing_date
                if listing_date>now.date() or listing_date<now.date()-timedelta(days=3):
                    continue
            if absolute not in urls:
                urls.append(absolute)
        result['article_links_seen']=len(urls)
        for url in urls[:8]:
            try:
                notes,pub=_aysa_news_article(fetch(url),url,now)
                result['articles_checked']+=1
                if pub and (newest is None or pub>newest):
                    newest=pub
                result['notices'].extend(notes)
                result['source_attempts'].append({'url':url,'result':'parsed' if notes else 'no_precise_recent_impact'})
            except Exception as exc:
                result['source_attempts'].append({'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__})
        if newest or latest_index_date:
            result['latest_published_date']=max(x for x in (newest,latest_index_date) if x).isoformat()
        if result['notices']:
            result['status']='ok'
            result['message']='Comunicados publicos fechados con localidades mencionadas como posiblemente afectadas. No garantizan afectacion de domicilios.'
        elif (newest or latest_index_date) and (newest or latest_index_date)<now.date()-timedelta(days=3):
            result['status']='stale'
            result['message']='Noticias antiguas sin avisos recientes precisos; el estado del servicio es desconocido.'
        else:
            result['message']='Sin avisos recientes con afectacion y localidad verificables. Para domicilios, usar consulta por cuenta de AySA.'
        if any(a['result']=='fetch_or_parse_error' for a in result['source_attempts']):
            result['message']+=' Algunos articulos no pudieron abrirse.'
    except Exception as exc:
        result['message']='No se pudo consultar novedades publicas de AySA: '+type(exc).__name__
    return result


_SAMEEP_LOCALITIES=(
    'Resistencia','Barranqueras','Fontana','Puerto Tirol','Villa Angela',
    'Presidencia Roque Saenz Pena','Concepcion del Bermejo',
    'Juan Jose Castelli','Puerto Lavalle','Corzuela','Charata',
    'Quitilipi','La Leonesa','General San Martin','Campo Largo',
)

def _sameep_article(html,url,now):
    dom,visible=page(html)
    head=visible.split('Noticias relacionadas')[0]
    match=re.search(r'\b(\d{2}/\d{2}/\d{4})\b',head)
    if not match:
        return None,None
    try:
        published=_ddmmyyyy(match.group(1))
    except ValueError:
        return None,None
    if published>now.date()+timedelta(days=1):
        return None,None
    if published < now.date()-timedelta(days=3):
        return None,published
    heading=next((h for h in dom.headings if h and folded(h) not in ('novedades','noticias')), '')
    body=' '.join(x for x in dom.paragraphs if len(x)>40).split('Noticias relacionadas')[0]
    if not heading or not body:
        return None,published
    normal_heading=folded(heading)
    normal_body=folded(body)
    if re.search(r'\b(sin cortes|no afectara|no se vera afectado|sin afectar|ya se restablecio)\b',normal_heading+' '+normal_body[:350]):
        return None,published
    if re.search(r'\b(finalizo|finalizaron|se restablecio|se recupero|normalizo)\b',normal_heading):
        return None,published
    if not re.search(r'(baja presion|falta de agua|afectad[oa] el servicio|se vera afectad[oa]|interrupcion del servicio|reduc(?:cion|ira) (?:en )?(?:el )?(?:servicio|suministro)|corte de agua|sin suministro)',normal_body):
        return None,published
    names=[n for n in _SAMEEP_LOCALITIES if re.search(r'(?<![a-z])'+re.escape(folded(n))+r'(?![a-z])',normal_heading)]
    if len(names)!=1:
        return None,published
    return mk_notice('SAMEEP','Chaco',names[0],url,
                     'water_service_bulletin','publication_only_not_live',body,
                     published_on=published.isoformat(),
                     scheduled_start=None,scheduled_end=None),published


def _collect_sameep(checked_at,now,fetch):
    result=_result('sameep_chaco',checked_at)
    result['parser_revision']='SAMEEP-ARTICLES-v5.41'
    result['coverage_kind']='dated_official_public_bulletins_only'
    result['article_links_seen']=0
    result['articles_checked']=0
    result['source_attempts']=[]
    last=None
    try:
        dom,_=page(fetch(result['source_url']))
        urls=[]
        for href,label in dom.anchors:
            link=urljoin(result['source_url'],href)
            parsed=urlsplit(link)
            if parsed.hostname not in ('sameep.gob.ar','www.sameep.gob.ar'):
                continue
            if not re.fullmatch(r'/noticias/detalle/\d+/?',parsed.path):
                continue
            if len(label)<12 or link in urls:
                continue
            urls.append(link)
        result['article_links_seen']=len(urls)
        for link in urls[:6]:
            try:
                notice,published=_sameep_article(fetch(link),link,now)
                result['articles_checked']+=1
                if published is not None and (last is None or published>last):last=published
                if notice is not None:
                    result['notices'].append(notice)
                    result['source_attempts'].append({'url':link,'result':'parsed'})
                else:
                    result['source_attempts'].append({'url':link,'result':'no_recent_service_notice'})
            except Exception as exc:
                result['source_attempts'].append({'url':link,'result':'fetch_or_parse_error','error_type':type(exc).__name__})
        if last is not None:
            result['latest_published_date']=last.isoformat()
        if result['notices']:
            result['status']='ok'
            result['message']='Comunicados oficiales fechados; no confirman el estado del suministro en tiempo real.'
        elif result['articles_checked'] and last is not None and last<now.date()-timedelta(days=3):
            result['status']='stale'
            result['message']='Solo se encontraron publicaciones antiguas o sin afectacion verificable; no significa suministro normal.'
        else:
            result['message']='No se recuperaron comunicados recientes con localidad y afectacion verificables; no significa servicio normal.'
    except Exception as exc:
        result['message']='No se pudo consultar SAMEEP: '+type(exc).__name__
    return result



# Concordia's municipal sanitation authority (EDOS) publishes dated official
# water interruption stories. Only the municipal site is accepted. Headlines
# about completed works are never treated as new interruptions.
_EDOS_HOST='www.concordia.gob.ar'
_EDOS_IMPACT = re.compile(
    r'(?:corte\s+(?:programado\s+)?(?:de\s+)?agua|'
    r'interrupci[oó]n\s+(?:temporal\s+)?del\s+(?:servicio|suministro)|'
    r'se\s+interrumpir[aá]\s+el\s+(?:servicio|suministro)|'
    r'parada\s+programada\s+de\s+la\s+planta\s+potabilizadora|'
    r'(?:baja|menor|reducci[oó]n\s+de)\s+presi[oó]n|'
    r'falta\s+de\s+agua|'
    r'se\s+reducir[aá]\s+el\s+(?:servicio|suministro))', re.I)
_EDOS_FINISHED = re.compile(
    r'(?:finalizaron|finaliz[oó]|terminaron|concluyeron|se\s+normaliz[oó]|'
    r'(?:servicio|suministro)\s+(?:ya\s+)?restablecido|'
    r'restaurado\s+el\s+servicio)', re.I)


def _edos_date(text):
    """Read an unambiguous complete Spanish publication date, not a relative day."""
    m=re.search(r'\b(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(20\d{2})\b',folded(text))
    if not m or m.group(2) not in MONTH:
        return None
    try:
        return date(int(m.group(3)),MONTH[m.group(2)],int(m.group(1)))
    except ValueError:
        return None


def _edos_article(html,url,now):
    dom,visible=page(html)
    # Dates shown under other/related articles cannot date the main story.
    intro=visible.split('Noticias relacionadas')[0].split('Te puede interesar')[0]
    published=_edos_date(intro[:1200])
    if not published or published>now.date():
        return None,published
    if published<now.date()-timedelta(days=4):
        return None,published
    title=next((h for h in dom.headings if len(h)>14 and folded(h) not in
                ('noticias','obras sanitarias','municipalidad de concordia')), '')
    if not title or _EDOS_FINISHED.search(folded(title)):
        return None,published
    paragraphs=[]
    for para in dom.paragraphs:
        f=folded(para)
        if 'noticias relacionadas' in f or 'te puede interesar' in f:
            break
        if len(para)>45:
            paragraphs.append(para)
    content=' '.join(paragraphs)
    if not content or not _EDOS_IMPACT.search(folded(title+' '+content)):
        return None,published
    # Explicit negation cannot become a positive outage bulletin.
    if re.search(r'(?:sin\s+afectar\s+el\s+servicio|sin\s+cortes|'
                 r'no\s+(?:se\s+)?interrumpir[aá]\s+el\s+(?:servicio|suministro))',folded(content)):
        return None,published
    notice=mk_notice('EDOS Concordia','Entre Ríos','Concordia',url,
                     'water_service_bulletin','publication_only_not_live',
                     content,published_on=published.isoformat(),
                     area_precision='zonas_segun_comunicado_no_toda_la_ciudad',
                     scheduled_start=None,scheduled_end=None)
    return notice,published


def _collect_edos(checked_at,now,fetch):
    result=_result('edos_concordia',checked_at)
    result['parser_revision']='EDOS-MUNICIPIO-v5.43'
    result['coverage_kind']='dated_municipal_water_bulletins_only'
    result['article_links_seen']=0
    result['articles_checked']=0
    result['source_attempts']=[]
    last=None
    try:
        dom,_=page(fetch(result['source_url']))
        links=[]
        for href,label in dom.anchors:
            link=urljoin(result['source_url'],href)
            parsed=urlsplit(link)
            if parsed.scheme!='https' or parsed.hostname!=_EDOS_HOST:
                continue
            if not re.fullmatch(r'/noticias/[a-zA-Z0-9_%-]+/?',parsed.path):
                continue
            if len(label)<12 or link in links:
                continue
            links.append(link)
        result['article_links_seen']=len(links)
        for link in links[:8]:
            try:
                notice,published=_edos_article(fetch(link),link,now)
                result['articles_checked']+=1
                if published is not None and (last is None or published>last):
                    last=published
                if notice is not None:
                    result['notices'].append(notice)
                    result['source_attempts'].append({'url':link,'result':'parsed'})
                else:
                    result['source_attempts'].append({'url':link,'result':'no_recent_service_notice'})
            except Exception as exc:
                result['source_attempts'].append({'url':link,'result':'fetch_or_parse_error',
                                                  'error_type':type(exc).__name__})
        if last:
            result['latest_published_date']=last.isoformat()
        if result['notices']:
            result['status']='ok'
            result['message']='Comunicados municipales fechados; no confirman un corte actual ni un domicilio afectado.'
        elif last and last<now.date()-timedelta(days=4):
            result['status']='stale'
            result['message']='Solo publicaciones antiguas; no permite determinar el estado actual del agua.'
        else:
            result['message']='No hay comunicados recientes suficientemente precisos. No acredita suministro normal.'
        if any(x['result']=='fetch_or_parse_error' for x in result['source_attempts']):
            result['message']+=' Algunos articulos no pudieron consultarse.'
    except Exception as exc:
        result['message']='No se pudo consultar el portal municipal EDOS: '+type(exc).__name__
    return result

# OSSE (Mar del Plata / Batán): official WordPress news index and optional RSS.
# The list of articles is NOT a live interruption feed. Only specific, recent,
# geographically supported impact statements may become read-only bulletins.
_OSSE_HOSTS = ('www.osmgp.gov.ar', 'osmgp.gov.ar')
_OSSE_RSS = 'https://www.osmgp.gov.ar/osse/feed/'
_OSSE_ENGLISH_MONTH = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                       'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
_OSSE_RELEVANT_HEADLINE = re.compile(
    r'(corte|interrupcion|baja presion|menor presion|falta de agua|'
    r'afectacion del servicio|servicio de agua|estacion elevadora de agua|'
    r'planta potabilizadora|parada programada)', re.I)
_OSSE_IMPACT = re.compile(
    r'(baja\s+(?:temporaria\s+)?(?:(?:en\s+)?(?:la\s+|de\s+)?)presion|'
    r'falta\s+de\s+agua|corte\s+(?:de\s+)?agua|'
    r'(?:interrumpir|interrupcion)\s+(?:del\s+)?(?:servicio|suministro)|'
    r'(?:podria|podran|puede|podra|se vera|se veran|verse)\s+'
    r'(?:afectad[oa]s?|afectar|alterad[oa]s?|alterar)\s+'
    r'(?:el\s+)?(?:normal\s+)?(?:suministro|servicio|abastecimiento)|'
    r'(?:servicio|suministro|abastecimiento)\s+(?:de\s+agua\s+)?'
    r'(?:afectad[oa]s?|interrumpid[oa]s?|reducid[oa]s?))', re.I)
_OSSE_NEGATIVE = re.compile(
    r'(sin\s+afectar\s+el\s+(?:suministro|servicio)|'
    r'no\s+afectara\s+el\s+(?:suministro|servicio)|'
    r'no\s+se\s+interrumpira\s+el\s+(?:suministro|servicio)|'
    r'sin\s+interrupciones|no\s+se\s+veran\s+afectad[oa]s?)', re.I)
_OSSE_FINISHED = re.compile(
    r'(finaliz[oó]|finalizaron|se\s+normaliz[oó]|normalizado|'
    r'se\s+restableci[oó]|restablecido|trabajos\s+concluidos)', re.I)


def _osse_article_date(text):
    """Only dates near the main article or beside a listing title."""
    m = re.search(r'\b([A-Za-z]{3})\s+(\d{1,2}),\s*(20\d{2})\b', text[:1100])
    if m and m.group(1).lower() in _OSSE_ENGLISH_MONTH:
        try:
            return date(int(m.group(3)), _OSSE_ENGLISH_MONTH[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    m = re.search(r'\b(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+de\s+(20\d{2})\b', text[:1100], re.I)
    if m:
        month = MONTH.get(folded(m.group(2)))
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    return None


def _osse_valid_article_url(url):
    """Allow only individual HTTPS news articles under the official site."""
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname in _OSSE_HOSTS
            and not parsed.username and not parsed.password and not parsed.port
            and not parsed.query and not parsed.fragment
            and bool(re.fullmatch(r'/osse/[a-z0-9-]{15,}/?', parsed.path, re.I)))


def _osse_rss_index(xml_text):
    """Read RSS item metadata only; never use its summary as outage evidence."""
    if not isinstance(xml_text, str) or len(xml_text.encode('utf-8')) > MAX_PAGE_BYTES:
        raise ValueError('RSS ausente o demasiado grande')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', xml_text, re.I):
        raise ValueError('RSS con DTD/entidades no admitidas')
    root = ET.fromstring(xml_text)
    if root.tag != 'rss':
        raise ValueError('La respuesta no es un feed RSS')
    entries = []
    seen = set()
    for item in root.findall('./channel/item'):
        title = clean(item.findtext('title'), 240)
        link = clean(item.findtext('link'), 1000)
        if len(title) < 18 or not _osse_valid_article_url(link) or link in seen:
            continue
        published = None
        raw_date = item.findtext('pubDate')
        if raw_date:
            try:
                parsed = parsedate_to_datetime(raw_date)
                if parsed.tzinfo is not None:
                    published = parsed.astimezone(ART).date()
            except (ValueError, TypeError, OverflowError):
                pass
        entries.append((link, title, published))
        seen.add(link)
    return entries


def _osse_html_index(html):
    """Count real article links, not only headings matching outage keywords."""
    dom, visible = page(html)
    headings = {folded(h) for h in dom.headings if len(h) >= 18}
    entries = []
    seen = set()
    for href, label in dom.anchors:
        link = urljoin(SOURCES['osse_mar_del_plata'][2], href)
        if (not _osse_valid_article_url(link) or link in seen or
                len(label) < 18 or folded(label) not in headings):
            continue
        # Article-list date follows its heading on OSSE's public news page.
        nearby = None
        positions = [m.end() for m in re.finditer(re.escape(label), visible, re.I)]
        for pos in positions:
            nearby = _osse_article_date(visible[pos:pos + 125])
            if nearby:
                break
        entries.append((link, label, nearby))
        seen.add(link)
    return entries


def _osse_article(html, url, now, index_published=None):
    dom, visible = page(html)
    headline = next((h for h in dom.headings if len(h) > 22 and folded(h) not in
                     ('ultimas noticias', 'obras sanitarias', 'noticias')), '')
    if not headline:
        return None, None
    before, after = (visible.split(headline, 1) + [''])[:2]
    near_headline = _osse_article_date((before[-180:] + ' ' + after[:350]))
    meta_date = _published_date_from_meta(html)
    # Prefer the visible article's own date over theme/SEO metadata.
    published = near_headline or meta_date or index_published
    if index_published and published and index_published != published:
        return None, published  # contradictory publication dates: do not guess
    if not published or published > now.date():
        return None, published
    if published < now.date() - timedelta(days=4):
        return None, published
    if _OSSE_FINISHED.search(folded(headline)):
        return None, published
    if not _OSSE_RELEVANT_HEADLINE.search(folded(headline)):
        return None, published
    paras = []
    for paragraph in dom.paragraphs:
        norm = folded(paragraph)
        if 'te puede interesar' in norm or 'noticias relacionadas' in norm:
            break
        if len(paragraph) >= 45:
            paras.append(paragraph)
    content = ' '.join(paras)
    if not content or len(content) > 12000:
        return None, published
    lines = re.split(r'(?<=[.!?])\s+', content)
    impact = [sentence for sentence in lines if _OSSE_IMPACT.search(folded(sentence))
              and not _OSSE_NEGATIVE.search(folded(sentence))]
    if not impact:
        return None, published
    # Geographic proof must occur in the title or the impact statement,
    # not in a generic corporate footer saying 'OSSE Mar del Plata'.
    affected = folded(headline + ' ' + ' '.join(impact))
    if 'batan' in affected and 'mar del plata' not in affected:
        locality = 'Batán'
    elif any(term in affected for term in ('mar del plata', 'punta mogotes',
                                          'plaza mitre', 'constitucion', 'camet')):
        locality = 'Mar del Plata'
    else:
        return None, published
    return mk_notice('OSSE Mar del Plata', 'Buenos Aires', locality, url,
                     'water_service_bulletin', 'publication_only_not_live', content,
                     published_on=published.isoformat(),
                     area_precision='subzonas_del_partido_segun_comunicado_no_toda_la_ciudad',
                     scheduled_start=None, scheduled_end=None), published


def _collect_osse(checked_at, now, fetch):
    result = _result('osse_mar_del_plata', checked_at)
    result.update(parser_revision='OSSE-RSS-HTML-v5.45',
                  coverage_kind='dated_official_municipal_water_bulletins_only',
                  index_mode='unavailable', index_attempts=[],
                  html_news_headings_seen=0, index_warning=None,
                  article_links_seen=0, candidate_links_selected=0,
                  articles_skipped_old=0, articles_checked=0, source_attempts=[])
    entries = []
    for mode, url, reader in (('rss', _OSSE_RSS, _osse_rss_index),
                              ('html', result['source_url'], _osse_html_index)):
        try:
            payload = fetch(url)
            parsed = reader(payload)
            if mode == 'html':
                dom, _visible = page(payload)
                result['html_news_headings_seen'] = sum(
                    len(h) >= 18 and folded(h) not in
                    ('ultimas noticias', 'obras sanitarias', 'noticias')
                    for h in dom.headings)
                if result['html_news_headings_seen'] > 0 and not parsed:
                    result['index_warning'] = (
                        'Se reconocen títulos en la página de noticias, pero no '
                        'sus enlaces individuales. Revisar estructura HTML de OSSE.')
            result['index_attempts'].append({'url':url, 'result':
                                             'article_links_found' if parsed else 'no_article_links'})
            if parsed:
                entries = parsed
                result['index_mode'] = mode
                break
        except Exception as exc:
            result['index_attempts'].append({'url':url, 'result':'fetch_or_parse_error',
                                             'error_type':type(exc).__name__})
    if result['index_mode'] == 'unavailable':
        result['message'] = ('OSSE: no se pudieron identificar artículos en el índice oficial. '
                             'La cobertura es desconocida; no confirma normalidad del servicio.')
        return result
    result['article_links_seen'] = len(entries)
    candidates = []
    newest = None
    for link, label, published in entries:
        if published is not None:
            newest = max(newest, published) if newest else published
            if published < now.date() - timedelta(days=4):
                result['articles_skipped_old'] += 1
                continue
            if published > now.date():
                continue
        candidates.append((link, published))
    result['candidate_links_selected'] = min(len(candidates), 8)
    if newest:
        result['latest_published_date'] = newest.isoformat()
    for link, published_index in candidates[:8]:
        try:
            notice, article_date = _osse_article(fetch(link), link, now, published_index)
            result['articles_checked'] += 1
            if article_date:
                newest = max(newest, article_date) if newest else article_date
            if notice:
                result['notices'].append(notice)
            result['source_attempts'].append({'url':link, 'result':
                                              'parsed' if notice else 'no_precise_recent_impact'})
        except Exception as exc:
            attempt = {'url':link, 'result':'fetch_or_parse_error',
                       'error_type':type(exc).__name__}
            if isinstance(exc, HTTPError):
                attempt['http_status'] = exc.code
            result['source_attempts'].append(attempt)
            if isinstance(exc, HTTPError) and exc.code == 429:
                break  # Never retry a rate-limited provider immediately.
    if newest:
        result['latest_published_date'] = newest.isoformat()
    result['notices'] = list({item['id']:item for item in result['notices']}.values())
    failures = sum(x['result'] == 'fetch_or_parse_error' for x in result['source_attempts'])
    if result['notices']:
        result['status'] = 'ok'
        result['message'] = ('Comunicados fechados con afectación localizada; '
                             'no confirman cortes activos ni afectación de toda la ciudad.')
    elif newest and newest < now.date() - timedelta(days=4):
        result['status'] = 'stale'
        result['message'] = ('OSSE publica noticias, pero las recuperadas son antiguas. '
                             'No significa suministro normal.')
    else:
        result['message'] = ('OSSE: índice consultado, sin afectaciones recientes '
                             'y suficientemente localizadas; estado del servicio desconocido.')
    if failures:
        result['message'] += f' Consulta parcial: {failures} noticia(s) no pudieron leerse.'
    return result



# v5.46: Public company news from SAMSA and official Jujuy government press.
# These are article archives, NOT live outage-status services. Recent, specific
# articles may be displayed only as read-only historical/publication bulletins.
_SAMSA_HOSTS = ('samsa.com.ar', 'www.samsa.com.ar')
_JUJUY_HOST = 'prensa.jujuy.gob.ar'
_WATER_IMPACT = re.compile(
    r'(?:interrupcion\s+(?:del\s+)?(?:servicio|suministro)|'
    r'(?:interrumpir|interrumpira|interrumpido)\s+(?:el\s+)?(?:servicio|suministro|bombeo)|'
    r'(?:detener|detuvo|suspender|suspendio)\s+(?:el\s+)?bombeo|'
    r'corte\s+(?:de\s+)?agua|falta\s+de\s+agua|baja\s+presion|'
    r'(?:afecta|afectara|afectado|afectada|afectacion)\s+(?:el\s+)?(?:suministro|servicio|abastecimiento)|'
    r'(?:suministro|servicio|abastecimiento)\s+(?:de\s+agua\s+)?(?:afectad[oa]|interrumpid[oa])|'
    r'no\s+habra\s+(?:suministro|agua))', re.I)
_WATER_NEGATED = re.compile(
    r'(?:sin\s+afectar|no\s+afectara|no\s+se\s+interrumpira|no\s+se\s+suspendera|'
    r'no\s+habra\s+cortes|sin\s+cortes|sin\s+interrupciones)', re.I)
_WATER_FINISHED = re.compile(
    r'(?:concluy[oó]|concluyeron|finaliz[oó]|finalizaron|'
    r'restableci[oó]|restablecido|normaliz[oó]|normalizado|'
    r'servicio\s+restaurado|trabajos\s+terminados)', re.I)


def _day_spanish(text):
    """Only an explicit absolute Spanish date (year required)."""
    m = re.search(r'\b(\d{1,2})\s+(?:de\s+)?([a-z]+),?\s+(?:de\s+)?(20\d{2})\b', folded(text))
    if not m or m.group(2) not in MONTH:
        return None
    try:
        return date(int(m.group(3)), MONTH[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


def _article_listing_html(html, base_url, which):
    """Use linked headings only. Do not follow search tags or unrelated pages."""
    dom, visible = page(html)
    headings = {folded(h) for h in dom.headings if len(h) >= 18}
    collected = []
    seen = set()
    for href, label in dom.anchors:
        absolute = urljoin(base_url, href)
        parsed = urlsplit(absolute)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            continue
        if which == 'samsa':
            if parsed.hostname not in _SAMSA_HOSTS or not re.fullmatch(r'/[a-z0-9-]{22,}/?', parsed.path, re.I):
                continue
        else:
            if parsed.hostname != _JUJUY_HOST or not re.fullmatch(r'/[a-z0-9-]+/[a-z0-9-]+-n\d+/?', parsed.path, re.I):
                continue
        if len(label) < 18 or absolute in seen:
            continue
        if which == 'samsa':
            # SAMSA's live WordPress listing may put titles in h4/h5 or
            # article-card links, which VisiblePage does not list as headings.
            # A title-to-slug check is safer than requiring a particular tag.
            title_slug = re.sub(r'[^a-z0-9]+', '-', folded(label)).strip('-')
            path_slug = parsed.path.strip('/').lower()
            title_in_heading = folded(label) in headings
            slug_corresponds = (path_slug == title_slug or
                                path_slug.startswith(title_slug + '-') or
                                title_slug.startswith(path_slug + '-'))
            if (folded(label).startswith(('leer mas', 'read more')) or
                    len(title_slug) < 22 or
                    not (title_in_heading or slug_corresponds)):
                continue
        elif folded(label) not in headings:
            # Keep Jujuy's independent government-site filter unchanged.
            continue
        date_index = None
        if which == 'samsa':
            # Listing template: article title immediately followed by "6 noviembre, 2026".
            # If a date cannot be tied to the title, fetch and validate the article itself.
            for match in re.finditer(re.escape(label), visible, re.I):
                date_index = _day_spanish(visible[match.end():match.end()+75])
                if date_index:
                    break
        collected.append((absolute, label, date_index))
        seen.add(absolute)
    return collected


def _samsa_article(html, url, now, index_published=None):
    dom, visible = page(html)
    title = next((h for h in dom.headings if len(h) >= 18 and folded(h) not in ('noticias', 'sobre nosotros')), '')
    if not title:
        return None, None
    before, after = (visible.split(title, 1) + [''])[:2]
    published = _day_spanish(before[-130:] + ' ' + after[:160]) or _published_date_from_meta(html) or index_published
    if index_published and published and index_published != published:
        return None, published
    if not published or published > now.date() or published < now.date() - timedelta(days=4):
        return None, published
    if _WATER_FINISHED.search(folded(title)):
        return None, published
    # Headline serves as a relevance filter, but actual service impact MUST
    # be explicitly in the article's own body, not the sidebar or footer.
    if not re.search(r'agua|acueducto|bombeo|servicio|suministro|corte|interrupcion|presion', folded(title)):
        return None, published
    paragraphs = []
    for para in dom.paragraphs:
        f = folded(para)
        if 'informacion de contacto' in f or 'politica de privacidad' in f:
            break
        if len(para) >= 36:
            paragraphs.append(para)
    # Prevent unrelated long corporate-footer text from being treated as body.
    body = ' '.join(paragraphs[:14])[:7000]
    if not body:
        return None, published
    impact_sentences = [sentence for sentence in re.split(r'(?<=[.!?])\s+', body)
                        if _WATER_IMPACT.search(folded(sentence))
                        and not _WATER_NEGATED.search(folded(sentence))]
    if not impact_sentences:
        return None, published
    # SAMSA operates in Posadas/Garupa. Require explicit localities in article
    # title OR affected-service sentences, not inferred from provider address.
    locations = folded(title + ' ' + ' '.join(impact_sentences))
    if 'garupa' in locations and 'posadas' not in locations:
        locality = 'Garupá'
    elif 'posadas' in locations and 'garupa' not in locations:
        locality = 'Posadas'
    elif 'garupa' in locations and 'posadas' in locations:
        # A multi-town report must not imply that both cities are wholly affected.
        locality = 'Posadas / Garupá'
    else:
        return None, published
    return mk_notice('SAMSA', 'Misiones', locality, url, 'water_service_bulletin',
                     'publication_only_not_live', body, published_on=published.isoformat(),
                     area_precision='zonas_segun_comunicado_no_toda_la_localidad',
                     scheduled_start=None, scheduled_end=None), published


def _collect_samsa(checked_at, now, fetch):
    result = _result('samsa_misiones', checked_at)
    result.update(parser_revision='SAMSA-INDEX-v5.47', coverage_kind='dated_company_bulletins_only',
                  article_links_seen=0, articles_checked=0, articles_skipped_old=0,
                  source_attempts=[])
    newest = None
    try:
        entries = _article_listing_html(fetch(result['source_url']), result['source_url'], 'samsa')
        result['article_links_seen'] = len(entries)
        # Never fetch articles whose dated listing is already older than 4 days.
        for link, label, index_date in entries[:10]:
            if index_date:
                newest = max(newest, index_date) if newest else index_date
                if index_date < now.date() - timedelta(days=4) or index_date > now.date():
                    result['articles_skipped_old'] += 1
                    continue
            if result['articles_checked'] >= 6:
                break
            try:
                notice, published = _samsa_article(fetch(link), link, now, index_date)
                result['articles_checked'] += 1
                if published:
                    newest = max(newest, published) if newest else published
                if notice:
                    result['notices'].append(notice)
                result['source_attempts'].append({'url':link, 'result':'parsed' if notice else 'no_precise_recent_impact'})
            except Exception as exc:
                result['source_attempts'].append({'url':link, 'result':'fetch_or_parse_error',
                                                  'error_type':type(exc).__name__})
                if isinstance(exc, HTTPError) and exc.code == 429:
                    break
    except Exception as exc:
        result['message'] = 'No se pudo consultar noticias oficiales de SAMSA: ' + type(exc).__name__
        return result
    if newest:
        result['latest_published_date'] = newest.isoformat()
    if result['notices']:
        result.update(status='ok', message='Comunicados de SAMSA fechados, no estado de servicio en tiempo real.')
    elif newest and newest < now.date() - timedelta(days=4):
        result.update(status='stale', message='Noticias institucionales antiguas; estado actual del servicio desconocido.')
    elif result['article_links_seen'] == 0:
        result['message'] = ('Índice accesible sin enlaces de artículos que coincidan con títulos oficiales; '
                             'estructura no verificada. No significa servicio normal.')
    else:
        result['message'] = 'Sin afectaciones recientes, explícitas y localizadas en las noticias consultadas. No implica servicio normal.'
    if any(x['result']=='fetch_or_parse_error' for x in result['source_attempts']):
        result['message'] += ' Algunos artículos no pudieron consultarse.'
    return result


_JUJUY_PLACES = (
    'Alto Comedero', 'Los Alisos', 'Palpalá', 'Perico', 'San Pedro',
    'San Salvador de Jujuy', 'La Quiaca', 'Yala', 'Palma Sola',
    'El Carmen', 'Abra Pampa', 'Humahuaca', 'Libertador General San Martin',
    'Fraile Pintado', 'Ciudad de Nieva', 'Huaico', 'Monterrico', 'Tilcara',
    'Susques', 'El Ceibal', 'San Antonio', 'Lozano', 'La Mendieta',
)


# v5.82: The government press uses headlines such as "corte de emergencia"
# and "corte total del suministro", which the older generic impact matcher
# could reject despite an explicit water-service impact in the article body.
# Never turn a generic infrastructure project or a road/electricity cut into a
# water bulletin solely from the title.
_JUJUY_DIRECT_CUT = re.compile(
    r'(?:\bcorte\s+(?:total|de\s+emergencia|programad[oa])\b|'
    r'\bcorte\s+(?:del?\s+)?(?:suministro|servicio|abastecimiento)\b|'
    r'\binterrupcion\s+(?:total|programada|del?\s+(?:servicio|suministro))\b|'
    r'\bse\s+interrumpira\s+(?:el\s+)?(?:servicio|suministro)\b)', re.I)
_JUJUY_NONWATER_CUT = re.compile(
    r'\bcorte\s+(?:de\s+)?(?:calle|transito|ruta|energia|electricidad)\b', re.I)
_JUJUY_WATER_CONTEXT = re.compile(
    r'\b(?:agua\s+potable|suministro\s+de\s+agua|servicio\s+de\s+agua|'
    r'abastecimiento\s+de\s+agua|acueducto|red\s+de\s+agua)\b', re.I)


def _jujuy_article(html, url, now, index_title=None):
    dom, visible = page(html)
    headings = [h for h in dom.headings if len(h) >= 20]
    # Follow the government listing's actual headline rather than the first
    # 20-character navigation heading. Allow a matching site heading if the
    # listing has punctuation differences, but do not use a random sidebar.
    title = next((h for h in headings if index_title and folded(h) == folded(index_title)), '')
    if not title:
        title = next((h for h in headings if
                      re.search(r'agua potable|interrupcion|corte de agua', folded(h)) and
                      not re.search(r'las mas leidas|noticias relacionadas|te puede interesar',folded(h))), '')
    if not title:
        return None, None, 'article_title_not_verified'
    # A headline may occur in page navigation as well as the article itself.
    # Associate its publication date with the body, not a later news item.
    # The official page may repeat its headline in a navigation/card and in
    # the real article. A single first-match search can stop at the site's
    # navigation (e.g. "Ministerios"), hiding the actual water announcement.
    # Divide equal-headline occurrences into bounded sections and prefer the
    # section containing substantive ARTICLE PARAGRAPHS, not a menu headline.
    # Neither another story's paragraphs nor dates in the narrated work are
    # accepted as corroboration for this story.
    occurrences = list(re.finditer(re.escape(title), visible, re.I))
    meta_published = _published_date_from_meta(html)
    sections = []
    for pos, match in enumerate(occurrences):
        stop = occurrences[pos+1].start() if pos+1 < len(occurrences) else len(visible)
        following = visible[match.end():stop]
        footer = re.search(r'\blas m[a\u00e1]s le[i\u00ed]das\b|\bte puede interesar\b|\bministerios\b',
                           following, re.I)
        if footer:
            following = following[:footer.start()]
        first_body_para = next((para for para in dom.paragraphs
                                if len(para) >= 35 and para in following), None)
        header = (following.split(first_body_para, 1)[0] if first_body_para
                  else following[:180])
        local_date = _day_spanish(header[:450])
        candidate_text = following[:7500]
        candidate_body = re.sub(r'^.*?\b20\d\d\s*-\s*\d\d:\d\d\b',
                                '', candidate_text, count=1)
        # A title, an image caption or a sidebar alone cannot establish a
        # dated impact. Paragraphs must be present INSIDE this title section.
        substantive_paragraphs = [para for para in dom.paragraphs
                                  if len(para) >= 50 and para in candidate_body]
        norm_paragraphs = folded(' '.join(substantive_paragraphs))
        has_water = bool(_JUJUY_WATER_CONTEXT.search(norm_paragraphs))
        has_impact = bool(_WATER_IMPACT.search(norm_paragraphs) or
                          _JUJUY_DIRECT_CUT.search(norm_paragraphs))
        sections.append((pos, following, local_date, bool(substantive_paragraphs),
                         has_water, has_impact, substantive_paragraphs))
    # Stronger source evidence wins; only if equally strong do we prefer the
    # later article heading over an earlier duplicated navigation headline.
    if len(sections) > 1:
        _idx, main, published, _has_p, _water, _impact, body_paragraphs = max(
            sections, key=lambda sec:(sec[3] and sec[4] and sec[5],
                                     sec[3] and sec[4],sec[3],sec[0]))
    elif sections:
        _idx, main, published, _has_p, _water, _impact, body_paragraphs = sections[0]
    else:
        main, published, body_paragraphs = visible.split(title, 1)[-1], None, []
    if published and meta_published and published != meta_published:
        return None, None, 'publication_date_conflict'
    published = published or meta_published
    footer = re.search(r'\blas m[aá]s le[ií]das\b|\bte puede interesar\b|\bministerios\b',
                       main, re.I)
    if footer:
        main = main[:footer.start()]
    if not published:
        return None, None, 'publication_date_not_verified'
    if published > now.date() or published < now.date()-timedelta(days=4):
        return None, published, 'outside_publication_window'
    if _WATER_FINISHED.search(folded(title)):
        return None, published, 'completed_article_title'
    # Do not put the whole visible heading-to-footer region into a bulletin.
    # The official newspaper template inserts navigation cards, "Seguí leyendo"
    # and related headlines between real article paragraphs.  We require
    # substantial paragraph text, already verified to occur within the chosen
    # dated article section; headings/links/cards never become zone_detail.
    article_text = main[:7500]
    related_titles = []
    for href, label in dom.anchors:
        link = urlsplit(urljoin(url, href))
        if (link.scheme == 'https' and link.hostname == _JUJUY_HOST and
                re.fullmatch(r'/[a-z0-9-]+/[a-z0-9-]+-n\d+/?', link.path, re.I)
                and len(label) >= 18 and folded(label) != folded(title)):
            related_titles.append(label)
    # Reapply the already-trimmed footer boundary to paragraph candidates;
    # otherwise an unrelated sidebar p could re-enter after the selection.
    body_paragraphs = [p for p in body_paragraphs if p in main]
    accepted_paragraphs = []
    for paragraph in body_paragraphs[:20]:
        # Remove inline linked suggestions, while retaining the true text on
        # either side of a linked card when the publisher mixes them in a p.
        para = paragraph
        for label in related_titles:
            para = re.sub(r'\bseg[uú]?[ií]\s+leyendo\s*' + re.escape(label),
                          ' ', para, flags=re.I)
        # A lone editorial call-to-action is not part of the announcement.
        para = re.sub(r'\bsegu[ií]\s+leyendo\b', ' ', para, flags=re.I)
        para = re.sub(r'\s+', ' ', para).strip()
        if len(para) >= 35:
            accepted_paragraphs.append(para)
    body = ' '.join(accepted_paragraphs)[:7500]
    folded_body = folded(body)
    if len(body.strip()) < 35 or not _JUJUY_WATER_CONTEXT.search(folded_body):
        return None, published, 'no_verifiable_water_article_body'
    # Attribution to the official water provider is required even though the
    # source website is governmental. Article metadata alone is insufficient.
    attribution = folded(title + ' ' + article_text[:850])
    if not re.search(r'agua potable(?:\s+de\s+jujuy|\s+y\s+saneamiento|'
                     r'\s+s\.?e\.?|\s+informa|\s+confirmo)', attribution):
        return None, published, 'water_provider_not_attributed'
    sentences = re.split(r'(?<=[.!?])\s+', body)
    impacts = []
    for sentence in sentences:
        norm = folded(sentence)
        if _WATER_NEGATED.search(norm):
            continue
        # A water-company article about its ELECTRICITY supply is not by
        # itself an interruption of drinking water for the neighborhoods.
        if (re.search(r'\b(?:suministro|servicio)\s+(?:electrico|de\s+energia|de\s+electricidad)\b', norm)
                and not re.search(r'\b(?:suministro|servicio|abastecimiento)\s+de\s+agua\b', norm)):
            continue
        direct = bool(_WATER_IMPACT.search(norm))
        emergency = bool(_JUJUY_DIRECT_CUT.search(norm)) and bool(_JUJUY_WATER_CONTEXT.search(norm))
        # "Corte de calle por reparación de cañería" is a traffic notice.
        if _JUJUY_NONWATER_CUT.search(norm) and not direct:
            continue
        if direct or emergency:
            impacts.append(sentence)
    if not impacts:
        return None, published, 'no_explicit_water_service_impact'
    # A location must be in the official article's headline or impact
    # statements. Never take a city from site footer/contact information.
    localized_text = folded(title + ' ' + ' '.join(impacts))
    places = [place for place in _JUJUY_PLACES if re.search(
        r'(?<![a-z])' + re.escape(folded(place)) + r'(?![a-z])', localized_text)]
    if not places:
        return None, published, 'impacted_locality_not_verified'
    locality = ' / '.join(places[:3])
    # A dated public report is NOT proof of a current cut. Without independently
    # verified source-side schedules, do not infer start/end times from news.
    return mk_notice('Agua Potable de Jujuy', 'Jujuy', locality, url,
                     'water_service_bulletin', 'publication_only_not_live',
                     body, published_on=published.isoformat(),
                     area_precision='sectores_segun_comunicado_no_toda_la_localidad',
                     scheduled_start=None, scheduled_end=None), published, 'parsed'


def _collect_jujuy(checked_at, now, fetch):
    result = _result('agua_potable_jujuy_prensa', checked_at)
    result.update(parser_revision='JUJUY-PARAGRAPHS-NO-RELATED-NEWS-v5.85', coverage_kind='dated_official_government_water_bulletins_only',
                  article_links_seen=0, articles_checked=0, source_attempts=[])
    newest = None
    try:
        entries = _article_listing_html(fetch(result['source_url']), result['source_url'], 'jujuy')
        result['article_links_seen'] = len(entries)
        # Read only a bounded number of articles in the government water topic.
        for link, title, _idx in entries[:8]:
            if result['articles_checked'] >= 6:
                break
            try:
                article_html = fetch(link)
                notice, published, verdict = _jujuy_article(article_html, link, now, title)
                result['articles_checked'] += 1
                if published:
                    newest = max(newest, published) if newest else published
                if notice:
                    result['notices'].append(notice)
                attempt = {'url':link, 'result':verdict}
                if verdict == 'no_verifiable_water_article_body':
                    # Shape-only diagnostic, no second request or article text.
                    # Helps distinguish missing paragraphs from a page-section
                    # detection failure without relaxing editorial validation.
                    dom_check, visible_check = page(article_html)
                    attempt['article_html_bytes'] = len(article_html.encode('utf-8'))
                    attempt['article_visible_characters'] = len(visible_check)
                    attempt['article_paragraphs_seen'] = len(dom_check.paragraphs)
                    attempt['matching_headings_seen'] = sum(
                        folded(h) == folded(title) for h in dom_check.headings)
                    attempt['repeated_title_occurrences_in_visible'] = len(list(
                        re.finditer(re.escape(title), visible_check, re.I)))
                    attempt['water_context_paragraphs_seen'] = sum(
                        bool(_JUJUY_WATER_CONTEXT.search(folded(paragraph)))
                        for paragraph in dom_check.paragraphs)
                    attempt['impact_like_paragraphs_seen'] = sum(
                        bool(_WATER_IMPACT.search(folded(paragraph)) or
                             _JUJUY_DIRECT_CUT.search(folded(paragraph)))
                        for paragraph in dom_check.paragraphs)
                result['source_attempts'].append(attempt)
            except Exception as exc:
                result['source_attempts'].append({'url':link, 'result':'fetch_or_parse_error',
                                                  'error_type':type(exc).__name__})
                if isinstance(exc, HTTPError) and exc.code == 429:
                    break
    except Exception as exc:
        result['message'] = 'No se pudo consultar prensa oficial de Jujuy: ' + type(exc).__name__
        return result
    if newest:
        result['latest_published_date'] = newest.isoformat()
    if result['notices']:
        result.update(status='ok', message='Comunicados oficiales fechados; no confirman el corte actual ni un domicilio afectado.')
    elif newest and newest < now.date() - timedelta(days=4):
        result.update(status='stale', message='Solo publicaciones antiguas; estado actual del suministro desconocido.')
    elif result['article_links_seen'] == 0:
        result['message'] = 'Página oficial accesible sin enlaces de noticias reconocibles; revisar estructura.'
    else:
        result['message'] = 'Sin comunicado reciente con afectación explícita y localidad identificada. No implica suministro normal.'
    if any(x['result']=='fetch_or_parse_error' for x in result['source_attempts']):
        result['message'] += ' Algunos artículos no pudieron consultarse.'
    return result



# The SCPL (Comodoro Rivadavia) publishes individual, dated water-service
# announcements and cancellations. The old season-wide recurring schedule is
# NEVER projected into future outages: more recent notices can suspend it.
_SCPL_HOSTS = ('scpl.coop', 'www.scpl.coop')
_SCPL_WATER_TITLE = re.compile(r'(?:corte|interrupcion|falta de agua|baja presion|suministro|servicio)', re.I)
_SCPL_IMPACT = re.compile(
    r'(?:se interrump(?:e|ira) el (?:suministro|servicio)|'
    r'(?:interrupcion|corte) (?:del |de )?(?:servicio|suministro|agua)|'
    r'(?:falta de agua|baja presion|sin suministro|se vera afectad[oa])|'
    r'(?:se registraran|podran registrarse) (?:baja presion|faltas de suministro))', re.I)
_SCPL_CANCEL = re.compile(
    r'(?:se suspende|suspendido|se cancela|se reprograma|no habra corte|'
    r'no hay corte|no se interrumpira|sin cortes|se normaliza|'
    r'normalizacion|se restablecio|se restablece|finalizaron)', re.I)


def _scpl_index_date(index_text, label):
    # Date is immediately after the title on the official index.
    if not label:
        return None
    for m in re.finditer(re.escape(label), index_text, re.I):
        chunk = index_text[m.end():m.end()+100]
        found = re.search(r'\b(\d{2}-\d{2}-20\d{2})\b', chunk)
        if found:
            try:
                return _ddmmyyyy(found.group(1))
            except ValueError:
                continue
    return None


def _scpl_index(html, root):
    dom, visible = page(html)
    result = []
    seen = set()
    for href, label in dom.anchors:
        url = urljoin(root, href)
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in _SCPL_HOSTS:
            continue
        if parts.path != '/index.php/site/ver-nota':
            continue
        if not re.search(r'(?:^|&)id=\d{1,7}(?:&|$)', parts.query):
            continue
        if url in seen or len(label) < 22:
            continue
        title = folded(label)
        if not _SCPL_WATER_TITLE.search(title) or not re.search(r'agua|suministro', title):
            continue
        if re.search(r'corte de calzada|corte de energia|saneamiento|red cloacal', title):
            continue
        seen.add(url)
        # SCPL archives can contain hundreds of historic links. Never scan
        # the entire page repeatedly to date items beyond our first window.
        published = _scpl_index_date(visible, label) if len(result) < 24 else None
        result.append((url, label, published))
    return result



def _scpl_explicit_schedule(paragraphs, published, now):
    """Keep an explicitly stated future SCPL water interruption and both clocks.

    A date and two times must occur in the SAME service-interruption paragraph.
    A weekday/month/day must agree with the calendar; avoid office hours,
    unrelated electricity schedules, or estimated restoration claims.
    """
    day_phrase = re.compile(
        r'\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)'
        r'\s+\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|'
        r'julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b')
    time_pair = re.compile(
        r'\bdesde\s+las\s+(\d{1,2}):(\d{2})\s*(?:hs\.?|horas?)?'
        r'\s*(?:,?\s*y\s+)?hasta\s+las\s+(\d{1,2}):(\d{2})'
        r'\s*(?:hs\.?|horas?)?', re.I)
    options=[]
    for paragraph in paragraphs:
        text = folded(paragraph)
        days = list(day_phrase.finditer(text))
        clocks = list(time_pair.finditer(text))
        if len(days) != 1 or len(clocks) != 1:
            continue
        day = _weekday_date(days[0].group(), published)
        if not day or not now.date() <= day <= now.date() + timedelta(days=HORIZON_DAYS):
            continue
        match = clocks[0]
        # The notice's water interruption must be stated right after the
        # published interval; do not reuse unrelated hours in a long article.
        consequence = text[match.end():match.end()+100]
        if not re.match(r'^[\s,.;:-]*se\s+interrump(?:e|ira)\s+el\s+(?:suministro|servicio)'
                        r'\s+de\s+agua\b', consequence):
            continue
        h1,m1,h2,m2 = (int(v) for v in match.groups())
        if max(h1,h2) > 23 or max(m1,m2) > 59:
            continue
        start = datetime(day.year,day.month,day.day,h1,m1,tzinfo=ART)
        end = datetime(day.year,day.month,day.day,h2,m2,tzinfo=ART)
        if not start < end <= start + timedelta(hours=20):
            continue
        # The stated end of an interruption is not proof of restoration.
        options.append((day, start, end))
    if len(options) != 1:
        return None
    day,start,end=options[0]
    return {'scheduled_date':day.isoformat(),
            'scheduled_start':start.isoformat(),
            'scheduled_end':end.isoformat(),
            'time_precision':'start_and_end_published'}

def _scpl_article(html, url, now, index_published=None):
    dom, visible = page(html)
    headline = next((h for h in dom.headings
                     if len(h) >= 22 and _SCPL_WATER_TITLE.search(folded(h))), '')
    if not headline:
        return None, None, 'no_water_headline'
    # A date next to the headline belongs to the article; navigation dates do not.
    pos = visible.find(headline)
    block = visible[pos+len(headline):pos+len(headline)+220] if pos >= 0 else ''
    m = re.search(r'\b(\d{2}-\d{2}-20\d{2})\b', block)
    published = None
    if m:
        try:
            published = _ddmmyyyy(m.group(1))
        except ValueError:
            pass
    if index_published and published and index_published != published:
        return None, None, 'index_article_date_mismatch'
    published = published or index_published
    if not published or published > now.date() + timedelta(days=1):
        return None, published, 'missing_or_future_publication_date'
    if published < now.date() - timedelta(days=3):
        return None, published, 'old_publication'
    if _SCPL_CANCEL.search(folded(headline)):
        return None, published, 'cancelled_or_restored_announcement'
    # Read the article body only, never the footer or other site announcements.
    paragraph_list = []
    for para in dom.paragraphs:
        if len(para) > 30 and not re.search(r'consejos utiles|atencion al publico', folded(para)):
            paragraph_list.append(para)
    body = ' '.join(paragraph_list)
    if not body and pos >= 0:
        following = visible[pos+len(headline):]
        following = re.split(r'CONSEJOS UTILES|GALERIA DE IMAGENES|DATOS IMPORTANTES', following, 1, flags=re.I)[0]
        body = clean(following, 3000)
    if not body or len(body) > 12000:
        return None, published, 'article_body_unavailable'
    normalized = folded(body)
    if _SCPL_CANCEL.search(normalized):
        return None, published, 'cancelled_or_restored_announcement'
    if not _SCPL_IMPACT.search(normalized) or not re.search(r'\bagua\b|\bpotable\b', normalized):
        return None, published, 'no_explicit_water_impact'
    # A past explicitly dated incident must not be republished as a new event.
    action_day = None
    for para in paragraph_list or [body]:
        candidate = _weekday_date(para, published)
        if candidate:
            action_day = candidate
            break
    if action_day and action_day < now.date():
        return None, published, 'event_date_already_passed'
    if 'rada tilly' in folded(headline) and 'comodoro' in folded(headline):
        return None, published, 'multiple_localities_ambiguous'
    locality = 'Rada Tilly' if 'rada tilly' in folded(headline) else 'Comodoro Rivadavia'
    schedule = _scpl_explicit_schedule(paragraph_list or [body], published, now)
    # The day can be today but the official interval may already have ended.
    # Preserve the historical times; do not display the expired plan as an
    # upcoming schedule or equate its end with restored pressure.
    elapsed = bool(schedule and datetime.fromisoformat(schedule['scheduled_end']) < now)
    notice = mk_notice('SCPL Comodoro Rivadavia', 'Chubut', locality, url,
                       'planned_water_service_impact' if schedule else 'water_service_bulletin',
                       ('publication_only_not_live' if elapsed else 'scheduled_not_confirmed')
                       if schedule else 'publication_only_not_live', body,
                       published_on=published.isoformat(),
                       area_precision='barrios_o_zonas_segun_comunicado_no_toda_la_ciudad',
                       **(schedule if schedule else {'scheduled_start':None,'scheduled_end':None}))
    if elapsed:
        notice['published_schedule_window_elapsed'] = True
        notice['message'] = ('El intervalo publicado ya transcurrio. No confirma la '
                             'finalizacion de trabajos ni la normalizacion del suministro.')
    return notice, published, 'parsed'


def _collect_scpl(checked_at, now, fetch):
    r = _result('scpl_comodoro_chubut', checked_at)
    r.update(parser_revision='SCPL-DATED-SCHEDULES-v5.81',
             coverage_kind='dated_public_scpl_bulletins_only_not_recurring_schedule',
             article_links_seen=0, articles_checked=0, articles_skipped_old=0,
             articles_skipped_cancelled=0, index_window_considered=0,
             article_links_outside_window=0,
             source_attempts=[], index_attempts=[], notices=[])
    newest = None
    try:
        entries = []
        for index_url in (r['source_url'], 'https://scpl.coop/'):
            try:
                entries = _scpl_index(fetch(index_url), index_url)
                r['index_attempts'].append({'url': index_url,
                                            'result': 'article_links_found' if entries else 'no_matching_links'})
                if entries:
                    r['index_mode'] = 'official_communications' if index_url == r['source_url'] else 'official_home_fallback'
                    break
            except Exception as index_exc:
                r['index_attempts'].append({'url': index_url, 'result': 'fetch_or_parse_error',
                                            'error_type': type(index_exc).__name__})
        r['article_links_seen'] = len(entries)
        # Only the first window is monitored, NOT the whole 963+ article archive.
        # Explicitly record that limitation in the feed.
        window = entries[:12]
        r['index_window_considered'] = len(window)
        r['article_links_outside_window'] = max(0, len(entries)-len(window))
        for link, label, day in window:
            if day:
                newest = max(newest, day) if newest else day
            if day and day < now.date() - timedelta(days=3):
                r['articles_skipped_old'] += 1
                continue
            # Cancelled and normalized water interruptions can be recognized
            # from the official headline without re-requesting the article.
            if _SCPL_CANCEL.search(folded(label)):
                r['articles_skipped_cancelled'] += 1
                r['source_attempts'].append({'url':link,
                    'result':'cancelled_or_restored_announcement',
                    'not_fetched':True})
                continue
            if r['articles_checked'] >= 5:
                break
            try:
                note, published, reason = _scpl_article(fetch(link), link, now, day)
                r['articles_checked'] += 1
                if published:
                    newest = max(newest, published) if newest else published
                if note:
                    r['notices'].append(note)
                r['source_attempts'].append({'url': link, 'result': reason})
            except Exception as exc:
                r['source_attempts'].append({'url': link, 'result': 'fetch_or_parse_error',
                                             'error_type': type(exc).__name__})
                if isinstance(exc, HTTPError) and exc.code == 429:
                    r['rate_limited'] = True
                    break
    except Exception as exc:
        r['message'] = 'Portal SCPL no verificable: ' + type(exc).__name__
        return r
    if newest:
        r['latest_published_date'] = newest.isoformat()
    if r['notices']:
        r['status'] = 'ok'
        r['message'] = 'Comunicados recientes y fechados. No confirman que el corte siga activo.'
    elif newest and newest < now.date() - timedelta(days=3):
        r['status'] = 'stale'
        r['message'] = 'Solo comunicados antiguos. No se proyectan cortes estacionales sin confirmacion reciente.'
    elif not entries:
        r['message'] = 'Indice accesible pero no se identificaron articulos de agua.'
    else:
        r['message'] = 'Sin afectaciones recientes vigentes verificables; los anuncios de suspension no se convierten en cortes.'
    if any(x['result'] == 'fetch_or_parse_error' for x in r['source_attempts']):
        r['message'] += ' Consulta parcial por errores de lectura.'
    if r['article_links_outside_window']:
        r['message'] += ' Se revisó solo la ventana reciente del índice; no el archivo histórico completo.'
    return r


_EPAS_HOSTS = ('epas.gov.ar', 'www.epas.gov.ar')
_EPAS_LOCATIONS = (
    'Neuqu\u00e9n Capital', 'Chos Malal', 'Centenario', 'Cutral C\u00f3',
    'Plaza Huincul', 'Andacollo', 'Jun\u00edn de los Andes',
    'Villa La Angostura', 'Senillosa', 'Loncopu\u00e9',
    'Villa El Choc\u00f3n', 'Taquimil\u00e1n', 'Caviahue',
)
_EPAS_IMPACT = re.compile(
    r'(?:se vera interrumpid[oa] (?:el )?(?:suministro|servicio)|'
    r'se interrumpira (?:el )?(?:suministro|servicio)|'
    r'interrupcion (?:del |de )?(?:servicio|suministro|agua)|'
    r'corte de agua|falta de agua|baja presion|'
    r'sin suministro de agua|afectara el suministro)', re.I)


def _epas_index(html, root):
    dom, visible = page(html)
    entries, seen = [], set()
    for href, label in dom.anchors:
        url = urljoin(root, href)
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in _EPAS_HOSTS:
            continue
        if not re.fullmatch(r'/20\d{2}/\d{2}/\d{2}/[a-z0-9-]+/?', parsed.path):
            continue
        if url in seen or len(label) < 23:
            continue
        # Find an index date immediately following its title.
        d = None
        for m in re.finditer(re.escape(label), visible, re.I):
            match = re.search(r'\b\d{1,2}\s+(?:de\s+)?[a-z]+,?\s*(?:de\s+)?20\d{2}\b',
                              folded(visible[m.end():m.end()+160]))
            if match:
                d = _parse_official_day(match.group(0))
                if d:
                    break
        seen.add(url)
        entries.append((url, label, d))
    return entries


def _epas_article(html, url, now, index_published=None):
    dom, visible = page(html)
    title = next((h for h in dom.headings if len(h) > 24 and
                  folded(h) not in ('noticias', 'novedades')), '')
    if not title:
        return None, None, 'article_title_missing'
    published = _published_date_from_meta(html)
    if not published:
        pos = visible.find(title)
        if pos >= 0:
            published = _parse_official_day(visible[pos+len(title):pos+len(title)+220])
    if published and index_published and published != index_published:
        return None, None, 'index_article_date_mismatch'
    published = published or index_published
    if not published or published > now.date()+timedelta(days=1):
        return None, published, 'missing_or_future_publication_date'
    if published < now.date()-timedelta(days=3):
        return None, published, 'old_publication'
    if re.search(r'finaliz|normaliz|restablecid|sin cortes|sin afectar', folded(title)):
        return None, published, 'finished_or_negative_headline'
    body = ' '.join(p for p in dom.paragraphs if len(p) > 40)
    if not body or len(body) > 12000:
        return None, published, 'no_article_body'
    normalized = folded(body)
    if re.search(r'no se interrumpira|sin afectar el servicio|no habra corte', normalized):
        return None, published, 'negative_impact'
    if not _EPAS_IMPACT.search(normalized):
        return None, published, 'no_explicit_water_impact'
    named = [loc for loc in _EPAS_LOCATIONS if re.search(
        r'(?<![a-z])' + re.escape(folded(loc)) + r'(?![a-z])', folded(title))]
    if not named:
        # A precise article sentence is required; province-wide mention is not enough.
        for loc in _EPAS_LOCATIONS:
            patt = r'(?:en|de)\s+(?:la localidad de\s+|la ciudad de\s+)?' + re.escape(folded(loc)) + r'\b'
            if re.search(patt, normalized):
                named.append(loc)
    if len(named) != 1:
        return None, published, 'locality_not_precise'
    notice = mk_notice('EPAS Neuquen', 'Neuquen', named[0], url,
                       'water_service_bulletin', 'publication_only_not_live', body,
                       published_on=published.isoformat(),
                       area_precision='zonas_segun_comunicado_no_toda_la_localidad',
                       scheduled_start=None, scheduled_end=None)
    return notice, published, 'parsed'


def _collect_epas(checked_at, now, fetch):
    r = _result('epas_neuquen_noticias', checked_at)
    r.update(parser_revision='EPAS-INDEX-FALLBACK-v5.53',
             coverage_kind='dated_official_epas_public_news_only',
             article_links_seen=0, articles_checked=0,
             articles_skipped_old=0, notices=[], source_attempts=[])
    newest = None
    r['index_attempts']=[]
    r['index_mode']='news_page'
    r['index_warning']=None
    try:
        index_html=fetch(r['source_url'])
        dom,visible=page(index_html)
        entries=_epas_index(index_html,r['source_url'])
        r['index_attempts'].append({
            'url':r['source_url'],'result':'article_links_found' if entries else 'no_recognizable_links',
            'html_anchors_seen':len(dom.anchors),'visible_text_characters':len(visible),
            'html_bytes':len(index_html.encode('utf-8'))})
        if not entries:
            fallback='https://www.epas.gov.ar/category/noticias/'
            try:
                alternate_html=fetch(fallback)
                alternate_dom,alternate_visible=page(alternate_html)
                entries=_epas_index(alternate_html,fallback)
                r['index_attempts'].append({
                    'url':fallback,'result':'article_links_found' if entries else 'no_recognizable_links',
                    'html_anchors_seen':len(alternate_dom.anchors),
                    'visible_text_characters':len(alternate_visible),
                    'html_bytes':len(alternate_html.encode('utf-8'))})
                r['index_mode']='official_category_fallback'
            except Exception as exc:
                r['index_attempts'].append({
                    'url':fallback,'result':'fetch_or_parse_error',
                    'error_type':type(exc).__name__})
        if not entries:
            r['index_warning']='No se detectaron enlaces en los dos indices oficiales. No confirma ausencia de avisos.'
        r['article_links_seen'] = len(entries)
        for url, title, indexed in entries[:10]:
            if indexed:
                newest = max(newest, indexed) if newest else indexed
            if indexed and indexed < now.date() - timedelta(days=3):
                r['articles_skipped_old'] += 1
                continue
            if r['articles_checked'] >= 5:
                break
            try:
                note, published, reason = _epas_article(fetch(url), url, now, indexed)
                r['articles_checked'] += 1
                if published:
                    newest = max(newest, published) if newest else published
                if note:
                    r['notices'].append(note)
                r['source_attempts'].append({'url': url, 'result': reason})
            except Exception as exc:
                r['source_attempts'].append({'url': url, 'result': 'fetch_or_parse_error',
                                             'error_type': type(exc).__name__})
                if isinstance(exc, HTTPError) and exc.code == 429:
                    break
    except Exception as exc:
        r['message'] = 'No se pudo consultar noticias EPAS: ' + type(exc).__name__
        return r
    if newest:
        r['latest_published_date'] = newest.isoformat()
    if r['notices']:
        r['status'] = 'ok'
        r['message'] = 'Comunicados oficiales de impacto localizado; no prueban estado actual.'
    elif newest and newest < now.date() - timedelta(days=3):
        r['status'] = 'stale'
        r['message'] = 'Las publicaciones del listado son antiguas; no equivale a suministro normal.'
    elif not entries:
        r['message'] = 'Portal accesible sin articulos EPAS reconocibles.'
    else:
        r['message'] = 'Sin publicaciones recientes que acrediten afectaciones precisas al suministro.'
    if r.get('index_warning'):
        r['message'] += ' '+r['index_warning']
    if any(x['result'] == 'fetch_or_parse_error' for x in r['source_attempts']):
        r['message'] += ' Consulta parcial por errores de lectura.'
    return r



# v5.51: new provider news sections. These are official public bulletins,
# not real-time supply checks. No user account, cookies or personal data.
_REGIONAL_HOSTS = {
    'sat_tucuman_noticias': ('aguasdeltucuman.com.ar', 'www.aguasdeltucuman.com.ar'),
    'aguas_santiago_novedades': ('aguasdesantiago.com.ar', 'www.aguasdesantiago.com.ar'),
}
_REGIONAL_LOCATIONS = {
    'sat_tucuman_noticias': (
        'San Miguel de Tucumán', 'Tafí Viejo', 'Yerba Buena',
        'Banda del Río Salí', 'Las Talitas', 'Alderetes', 'Lules',
        'Bella Vista', 'Concepción', 'Monteros', 'Aguilares', 'Famaillá',
        'Ranchillos', 'Trancas',
    ),
    'aguas_santiago_novedades': (
        'Santiago del Estero', 'La Banda', 'Termas de Río Hondo',
        'Añatuya', 'Clodomira', 'El Simbolar', 'La Cañada',
        'Los Quiroga', 'Quimilí', 'Suncho Corral', 'Tintina',
    ),
}
_REGIONAL_IMPACT = re.compile(
    r'(?:corte(?:s)? (?:programad[oa]s? )?(?:de agua|del (?:servicio|suministro))|'
    r'interrupcion(?:es)? (?:del |de )?(?:servicio|suministro|agua potable)|'
    r'(?:se )?interrumpira (?:el )?(?:servicio|suministro)|'
    r'(?:falta de agua|baja presion|disminucion (?:de la )?presion)|'
    r'(?:sin suministro de agua|suministro (?:se vera|esta) afectado)|'
    r'(?:afectara|afectado|afectacion) (?:el |del )?(?:servicio|suministro))')
_REGIONAL_NEGATIVE = re.compile(
    r'(?:sin (?:afectar|interrumpir) (?:el )?(?:servicio|suministro)|'
    r'no (?:se )?(?:interrumpira|vera afectado) (?:el )?(?:servicio|suministro)|'
    r'no (?:habra|se registraran) (?:cortes|interrupciones)|'
    r'ya (?:se )?(?:normalizo|restablecio)|'
    r'no implica(?:n)? (?:cortes|interrupciones))')
_REGIONAL_FINISHED = re.compile(
    r'\b(?:finaliz[oa]|finalizaron|concluyeron|normaliz[oa]|'
    r'restablecid[oa]|se restablecio|sin cortes|sin interrupciones)\b')
_REGIONAL_SANTIAGO_MONTHS = {'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,
                              'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}


def _regional_index_date(fragment):
    """Recognize complete Spanish month abbreviations, never guess years."""
    f=folded(fragment)
    match=re.search(r'\b(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\.?\s+(20\d{2})\b',f)
    if match:
        try:
            return date(int(match.group(3)), _REGIONAL_SANTIAGO_MONTHS[match.group(2)],
                        int(match.group(1)))
        except ValueError:
            return None
    match=re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b',f)
    if match:
        try:
            return date(int(match.group(3)),int(match.group(2)),int(match.group(1)))
        except ValueError:
            return None
    return _parse_official_day(fragment)


# v5.52: some SAT pages expose navigation as routerLink/onclick or
# serialized route strings instead of ordinary <a href> links. Only exact
# HTTPS official-domain article paths are accepted. No script is executed.
_SAT_LITERAL_ROUTE = re.compile(
    r"""["']((?:https://(?:www\.)?aguasdeltucuman\.com\.ar)?/noticias/[A-Za-z0-9%_.=+\-]{8,}/?)["']""", 
    re.I)


def _sat_embedded_article_routes(html, base):
    """Read literal SAT article routes from HTML attributes or markup.

    A string containing an external hostname is never re-based onto SAT.
    No guesses about unpublished dates or affected localities are made.
    """
    from html import unescape
    raw=unescape(html).replace('\\/', '/')
    # Requiring quote boundaries prevents matching /noticias/... inside an
    # untrusted full URL such as https://evil.example/noticias/anything.
    found=[]
    for match in _SAT_LITERAL_ROUTE.finditer(raw):
        candidate=urljoin(base,match.group(1))
        parsed=urlsplit(candidate)
        if (parsed.scheme=='https' and parsed.hostname in _REGIONAL_HOSTS['sat_tucuman_noticias']
                and not parsed.username and not parsed.password and parsed.port is None
                and not parsed.query and not parsed.fragment
                and re.fullmatch(r'/noticias/[^/]{8,}/?',parsed.path)
                and candidate not in found):
            found.append(candidate)
    return found


def _regional_index(html, base, key):
    """Accept only article links at two official hosts, no external shorteners."""
    dom,visible=page(html)
    entries=[]
    seen=set()
    for href,label in dom.anchors:
        link=urljoin(base, href)
        parsed=urlsplit(link)
        if parsed.scheme!='https' or parsed.hostname not in _REGIONAL_HOSTS[key]:
            continue
        if key=='sat_tucuman_noticias':
            # SAT uses both Unicode titles and encoded text as news slugs.
            valid=(parsed.path.startswith('/noticias/') and len(parsed.path)>len('/noticias/')+5)
        else:
            valid=bool(re.fullmatch(r'/nota/\d+/[a-zA-Z0-9_-]+/?',parsed.path))
        if not valid or link in seen:
            continue
        seen.add(link)
        # Publication date must be linked to the listing title, not to another
        # story. SAT may not expose index dates: keep those as unknown.
        index_day=None
        if key=='aguas_santiago_novedades' and len(label)>14:
            positions=[m.start() for m in re.finditer(re.escape(label),visible,re.I)]
            for pos in positions:
                before=visible[max(0,pos-55):pos]
                after=visible[pos+len(label):pos+len(label)+75]
                index_day=_regional_index_date(before) or _regional_index_date(after)
                if index_day: break
        entries.append((link,label,index_day))
    if key=='sat_tucuman_noticias':
        # Article URLs can be stored in HTML attributes/embedded route strings
        # even when DOM anchors contain no usable href. The article body still
        # needs its own verified publication date, impact and locality.
        for candidate in _sat_embedded_article_routes(html,base):
            if candidate not in seen:
                seen.add(candidate)
                entries.append((candidate,'',None))
    return entries


def _regional_article(html,url,now,key,index_published=None):
    dom,visible=page(html)
    title=next((h for h in dom.headings if len(h)>18 and folded(h) not in
                ('noticias','noticias y novedades','novedades')), '')
    if not title:
        return None,None,'article_title_missing'
    published=_published_date_from_meta(html)
    if not published:
        # Only use a date immediately adjacent to the main heading.
        at=visible.find(title)
        if at>=0:
            published=(_regional_index_date(visible[max(0,at-65):at]) or
                       _regional_index_date(visible[at+len(title):at+len(title)+95]))
    if published and index_published and published!=index_published:
        return None,None,'index_article_date_mismatch'
    published=published or index_published
    if not published:
        return None,None,'publication_date_not_verified'
    if published>now.date()+timedelta(days=1):
        return None,published,'publication_date_in_future'
    if published<now.date()-timedelta(days=3):
        return None,published,'old_publication'
    if _REGIONAL_FINISHED.search(folded(title)):
        return None,published,'finished_or_negative_headline'
    paragraphs=[]
    for p in dom.paragraphs:
        f=folded(p)
        if re.search(r'noticias relacionadas|te puede interesar|noticias destacadas|atencion comercial',f):
            break
        if len(p)>45:
            paragraphs.append(p)
    if not paragraphs:
        return None,published,'no_article_paragraphs'
    content=' '.join(paragraphs)
    if len(content)>12000:
        return None,published,'article_body_too_large'
    # An impact has to be mentioned in an actual article sentence, not just
    # inferred from the company name, historical works or site navigation.
    impact_sentences=[]
    for paragraph in paragraphs:
        for sentence in re.split(r'(?<=[.!?])\s+',paragraph):
            f=folded(sentence)
            if _REGIONAL_NEGATIVE.search(f):
                continue
            if _REGIONAL_IMPACT.search(f):
                impact_sentences.append(sentence)
    if not impact_sentences:
        return None,published,'no_explicit_water_impact'
    # Location must be attached to the affected service, or to the headline.
    scope=folded(title+' '+' '.join(impact_sentences))
    found=[]
    for locality in _REGIONAL_LOCATIONS[key]:
        if re.search(r'(?<![a-z])'+re.escape(folded(locality))+r'(?![a-z])',scope):
            found.append(locality)
    if len(found)!=1:
        return None,published,'location_missing_or_ambiguous'
    company,province,_=SOURCES[key]
    notice=mk_notice(company,province,found[0],url,
                     'water_service_bulletin','publication_only_not_live',
                     content,published_on=published.isoformat(),
                     area_precision='zonas_segun_comunicado_no_toda_la_localidad',
                     scheduled_start=None,scheduled_end=None)
    return notice,published,'parsed'


def _collect_regional_news(key,checked_at,now,fetch):
    r=_result(key,checked_at)
    r.update(parser_revision='REGIONAL-NEWS-v5.51',
             coverage_kind='dated_official_company_news_only_not_live_state',
             article_links_seen=0,articles_checked=0,articles_skipped_old=0,
             source_attempts=[],notices=[])
    newest=None
    r['index_attempts']=[]
    try:
        index_html=fetch(r['source_url'])
        entries=_regional_index(index_html,r['source_url'],key)
        dom,index_visible=page(index_html)
        r['index_attempts'].append({
            'url':r['source_url'],
            'result':'article_links_found' if entries else 'no_recognizable_links',
            'html_anchors_seen':len(dom.anchors),
            'visible_text_characters':len(index_visible),
            'html_bytes':len(index_html.encode('utf-8'))})
        if key=='sat_tucuman_noticias':
            r['parser_revision']='SAT-ROUTE-DIAGNOSTIC-v5.52'
            r['index_mode']='news_index'
            if not entries:
                # Homepage is a second official public route, never a search
                # engine or unofficial service. Limit fallback to one request.
                homepage='https://aguasdeltucuman.com.ar/'
                try:
                    homepage_html=fetch(homepage)
                    entries=_regional_index(homepage_html,homepage,key)
                    home_dom,home_visible=page(homepage_html)
                    r['index_attempts'].append({
                        'url':homepage,
                        'result':'article_links_found' if entries else 'no_recognizable_links',
                        'html_anchors_seen':len(home_dom.anchors),
                        'visible_text_characters':len(home_visible),
                        'html_bytes':len(homepage_html.encode('utf-8'))})
                    r['index_mode']='homepage_fallback'
                except Exception as exc:
                    r['index_attempts'].append({
                        'url':homepage,'result':'fetch_or_parse_error',
                        'error_type':type(exc).__name__})
            if not entries:
                tiny_shells=[a for a in r['index_attempts'] if
                             a.get('result')=='no_recognizable_links' and
                             a.get('html_anchors_seen')==0 and
                             a.get('visible_text_characters',99999)<=100 and
                             a.get('html_bytes',99999)<=3500]
                if len(tiny_shells)==2:
                    r['access_mode']='client_rendered_shell_suspected'
                    r['index_warning']=('SAT no expone rutas de noticias reconocibles. Las dos rutas oficiales entregaron HTML minimo sin noticias ni enlaces. '
                                        'El contenido probablemente se carga con JavaScript; sin datos publicos verificables no se generan avisos.')
                else:
                    r['index_warning']='SAT no expone rutas de noticias reconocibles en las paginas consultadas; no confirma ausencia de comunicados.'

        r['article_links_seen']=len(entries)
        for link,label,index_day in entries[:12]:
            if index_day:
                newest=max(newest,index_day) if newest else index_day
            if index_day and index_day<now.date()-timedelta(days=3):
                r['articles_skipped_old']+=1
                continue
            if r['articles_checked']>=4:break
            try:
                notes,published,reason=_regional_article(fetch(link),link,now,key,index_day)
                r['articles_checked']+=1
                if published:
                    newest=max(newest,published) if newest else published
                if notes:r['notices'].append(notes)
                r['source_attempts'].append({'url':link,'result':reason})
            except Exception as exc:
                error={'url':link,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
                if isinstance(exc,HTTPError):error['http_status']=exc.code
                r['source_attempts'].append(error)
                if isinstance(exc,HTTPError) and exc.code==429:
                    r['rate_limited']=True
                    break
    except Exception as exc:
        r['message']='No se pudo verificar el índice oficial: '+type(exc).__name__
        return r
    if newest:r['latest_published_date']=newest.isoformat()
    if r['notices']:
        r['status']='ok'
        r['message']='Noticias oficiales fechadas sobre posibles afectaciones; no acreditan servicio actual.'
    elif newest and newest<now.date()-timedelta(days=3):
        r['status']='stale'
        r['message']='Las publicaciones verificadas son antiguas; no implica servicio normal.'
    elif not entries:
        r['message']='Índice accesible, sin enlaces de noticias reconocibles; requiere revisar su estructura.'
    else:
        r['message']='No se identificaron avisos recientes con fecha, afectación y localidad verificables.'
    if r.get('rate_limited'):
        r['message']+=' Consulta parcial por límite HTTP 429.'
    elif any(a['result']=='fetch_or_parse_error' for a in r['source_attempts']):
        r['message']+=' Consulta parcial por errores de lectura.'
    return r

# v5.57: San Luis and Santa Rosa municipality RSS public bulletins. The feeds
# supply dates and canonical URLs, NOT evidence that a current outage exists.
# Articles are re-checked on their official domains; no credentials or APIs.
_MUNICIPAL_RSS_HOSTS = {
    'san_luis_serba_municipal': {'sanluislaciudad.gob.ar','www.sanluislaciudad.gob.ar'},
    'santa_rosa_municipal_lp': {'santarosa.gob.ar','www.santarosa.gob.ar'},
}
_MUNICIPAL_TITLE_TOPIC = re.compile(
    r'agua|acueduct|serba|potabiliz|suministro|desabastec|cisterna|saneamiento|'
    r'perforacion|red hidrica|red de distribucion')
_MUNICIPAL_WATER = re.compile(
    r'agua potable|acueducto|red de agua|suministro de agua|servicio de agua|'
    r'planta potabilizadora|serba|provision de agua|sistema de abastecimiento')
_MUNICIPAL_IMPACT = re.compile(
    r'corte(?:s)? (?:de agua|del (?:servicio|suministro))|'
    r'(?:(?:falta|faltante) de agua)|baja presion|'
    r'interrupcion (?:del suministro|del servicio|de agua)|'
    r'(?:servicio|suministro) (?:se vera|se encuentra|esta|resultara) afectad[oa]|'
    r'(?:se vera|se encuentra|esta) (?:interrumpido|afectado) (?:el )?(?:suministro|servicio)|'
    r'(?:restricciones|reduccion) (?:en el )?(?:suministro|servicio de agua)|'
    r'(?:afectara|afectado|afectacion) (?:el |del )?(?:servicio|suministro)')


def _municipal_rss_index(xml_text,key):
    if not isinstance(xml_text,str) or len(xml_text.encode('utf-8'))>MAX_PAGE_BYTES:
        raise ValueError('RSS vacio o demasiado grande')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b',xml_text,re.I):
        raise ValueError('RSS con entidades no admitidas')
    root=ET.fromstring(xml_text)
    if root.tag!='rss':
        raise ValueError('No es un RSS municipal')
    entries=[]
    seen=set()
    items=root.findall('./channel/item')
    for item in items:
        title=clean(item.findtext('title'),240)
        url=clean(item.findtext('link'),1000)
        parsed=urlsplit(url)
        valid=(parsed.scheme=='https' and
               parsed.hostname in _MUNICIPAL_RSS_HOSTS[key] and
               parsed.username is None and parsed.password is None and parsed.port is None and
               not parsed.query and not parsed.fragment and
               len(parsed.path.strip('/'))>18 and
               re.fullmatch(r'/[a-zA-Z0-9%_./-]+/?',parsed.path))
        if not valid or len(title)<17 or url in seen:
            continue
        seen.add(url)
        pub=None
        if item.findtext('pubDate'):
            try:
                dt=parsedate_to_datetime(item.findtext('pubDate'))
                if dt.tzinfo is not None:
                    pub=dt.astimezone(ART).date()
            except (ValueError,TypeError,OverflowError):
                pass
        entries.append((url,title,pub))
    return entries,len(items)


def _municipal_article(html,url,now,key,index_day,rss_title=None):
    dom,visible=page(html)
    title=next((h for h in dom.headings if len(h)>22 and
                not re.match(r'^(?:novedades|noticias|inicio)$',folded(h))), '')
    if not title:
        return None,'article_title_missing'
    if rss_title and not (folded(title) in folded(rss_title) or folded(rss_title) in folded(title)):
        return None,'rss_article_title_mismatch'
    pub=_published_date_from_meta(html)
    if not pub:
        at=visible.find(title)
        if at>=0:
            pub=(_regional_index_date(visible[max(0,at-80):at]) or
                 _regional_index_date(visible[at+len(title):at+len(title)+90]))
    if not index_day:
        return None,'rss_publication_date_missing'
    # Publisher might show UTC publication timestamp a day apart from ART.
    # Larger differences indicate conflicting metadata; never infer an outage.
    if pub and abs((pub-index_day).days)>1:
        return None,'publication_date_mismatch'
    if index_day>now.date() or index_day<now.date()-timedelta(days=3):
        return None,'outside_publication_window'
    if _REGIONAL_FINISHED.search(folded(title)):
        return None,'restoration_or_finished_announcement'
    paragraphs=[]
    for para in dom.paragraphs:
        f=folded(para)
        if re.search(r'novedades relacionadas|noticias relacionadas|te puede interesar',f):
            break
        if len(para)>40:
            paragraphs.append(para)
    content=' '.join(paragraphs)
    if not content or len(content)>12000:
        return None,'article_body_absent_or_too_long'
    title_content=folded(title+' '+content)
    if not _MUNICIPAL_WATER.search(title_content):
        return None,'water_topic_not_verified'
    impact=[]
    for para in paragraphs:
        for sentence in re.split(r'(?<=[.!?])\s+',para):
            f=folded(sentence)
            if _REGIONAL_NEGATIVE.search(f) or _REGIONAL_FINISHED.search(f):
                continue
            if _MUNICIPAL_IMPACT.search(f):
                impact.append(sentence)
    if not impact:
        return None,'no_current_or_planned_service_impact'
    scope=folded(title+' '+' '.join(impact))
    if key=='san_luis_serba_municipal':
        # SerBa is the municipal water provider in San Luis city.
        if not re.search(r'\bsan luis\b|\bserba\b',scope):
            return None,'municipal_service_scope_not_verified'
        locality='San Luis'
    else:
        if not re.search(r'\bsanta rosa\b|\banguil\b',scope):
            return None,'municipal_service_scope_not_verified'
        locality='Santa Rosa'
    company,province,_=SOURCES[key]
    notice=mk_notice(company,province,locality,url,'water_service_bulletin',
        'publication_only_not_live',content,published_on=index_day.isoformat(),
        area_precision='solo_zonas_mencionadas_en_publicacion',
        scheduled_start=None,scheduled_end=None)
    return notice,'parsed'


# v5.79: official Santa Rosa HTML fallback when its RSS endpoint answers 403.
# /noticias/ can be a JavaScript shell; the homepage offers public story
# links. HTML discovery is only a candidate list, NEVER an outage or date.
_SANTA_ROSA_NEWS_INDEX = 'https://www.santarosa.gob.ar/noticias/'
_SANTA_ROSA_HOME = 'https://www.santarosa.gob.ar/'
_SANTA_ROSA_STORY = re.compile(r'^/noticias/[a-z0-9][a-z0-9-]{11,200}/?$',re.I)
_SANTA_ROSA_SERVICE_TOPIC = re.compile(
    r'agua|acueduct|potabiliz|suministro|presion|abastec|caneria|red-hidrica', re.I)


def _santa_rosa_public_links(html,base):
    dom,_=page(html)
    found=[]; seen=set()
    for href,label in dom.anchors:
        if not href or len(href)>800:
            continue
        link=urljoin(base,href.strip())
        u=urlsplit(link)
        try:
            safe=(u.scheme=='https' and
                  u.hostname in _MUNICIPAL_RSS_HOSTS['santa_rosa_municipal_lp'] and
                  u.username is None and u.password is None and u.port is None and
                  not u.query and not u.fragment and
                  bool(_SANTA_ROSA_STORY.fullmatch(u.path)) and link not in seen)
        except ValueError:  # Invalid URL ports never abort the entire index.
            safe=False
        if not safe:
            continue
        seen.add(link)
        # An anchor may wrap the entire card, or may say only 'Leer mas'.
        # The official slug is suitable for candidate selection, never date.
        slug=u.path.rstrip('/').split('/')[-1].replace('-',' ')
        label=clean(label,240)
        title=label if len(label)>18 and not re.fullmatch(r'leer (?:mas|noticia completa)',folded(label)) else slug
        found.append((link,title))
    return found,len(dom.anchors)


def _santa_rosa_publication_day(html):
    dom,visible=page(html)
    title=next((h for h in dom.headings if len(h)>22 and 'santa rosa' in folded(h)),None)
    if not title:
        return None
    # The title may occur inside <title> before the visible H1. Scan every
    # occurrence, as in the Cordoba v5.78 fix, and accept only an explicit
    # 'Noticias DD de mes de YYYY' immediately preceding the heading.
    header=None
    for match_title in re.finditer(re.escape(title),visible):
        before=visible[max(0,match_title.start()-110):match_title.start()]
        date_match=re.search(r'\bnoticias\s+(\d{1,2}\s+de\s+\w+\s+de\s+20\d{2})\s*$',folded(before))
        if date_match:
            header=_parse_official_day(date_match.group(1))
            if header:break
    meta=_published_date_from_meta(html)
    if header and meta and abs((header-meta).days)>1:
        return None
    return header or meta


def _santa_rosa_html_fallback(r,now,fetch):
    r['fallback_index_attempts']=[]
    links=None
    for url in (_SANTA_ROSA_NEWS_INDEX,_SANTA_ROSA_HOME):
        try:
            html=fetch(url)
            stories,anchors=_santa_rosa_public_links(html,url)
            r['fallback_index_attempts'].append({
                'url':url,'result':'official_html_read','html_anchors_seen':anchors,
                'valid_article_links_seen':len(stories)})
            if stories:
                links=stories
                r['index_mode']='official_html_news_fallback' if url==_SANTA_ROSA_NEWS_INDEX else 'official_homepage_sample_fallback'
                break
        except Exception as exc:
            attempt={'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):attempt['http_status']=exc.code
            r['fallback_index_attempts'].append(attempt)
            if isinstance(exc,HTTPError) and exc.code==429:
                break
    if links is None:
        all_attempts=r.get('index_attempts',[])+r['fallback_index_attempts']
        all_denied=bool(all_attempts) and all(a.get('http_status')==403 for a in all_attempts)
        if all_denied:
            # A proven HTTP 403 is an access refusal, not an empty index or a
            # JavaScript application. Avoid giving a misleading diagnosis.
            r['access_mode']='official_site_rejected_automated_request'
            r['http_status']=403
            r['message']='Los cuatro endpoints oficiales rechazaron la consulta (HTTP 403); suministro desconocido.'
            r['index_warning']='RSS y HTML rechazados por el servidor (HTTP 403). No implica servicio normal.'
        else:
            r['message']='RSS oficial inaccesible y HTML municipal sin titulares aprovechables; suministro desconocido.'
            r['index_warning']='El indice de noticias puede requerir JavaScript; no equivale a servicio normal.'
        if any(a['result']=='official_html_read' for a in r['fallback_index_attempts']):
            r['index_status']='html_no_article_links'
            r['index_mode']='official_html_no_recognizable_stories'
        return r
    r['source_url']=url  # The real official index read, not the blocked RSS.
    r['index_status']='official_html_article_links_found'
    r['article_links_seen']=len(links)
    r['html_links_seen']=len(links)
    r['source_attempts']=[]
    candidates=[(url,title) for url,title in links if _SANTA_ROSA_SERVICE_TOPIC.search(
        folded(title).replace(' ','-'))]
    r['relevant_titles_seen']=len(candidates)
    r['article_candidates_before_budget']=len(candidates)
    r['articles_deferred_by_budget']=max(0,len(candidates)-3)
    r['index_warning']='La lectura HTML es parcial: se examinan solo titulares del indice visible, no todos los cortes.'
    published_days=[]
    for url,title in candidates[:3]:
        try:
            html=fetch(url)
            r['articles_checked']+=1
            published=_santa_rosa_publication_day(html)
            if not published:
                reason='publication_date_not_verified'
                notice=None
            elif published>now.date() or published<now.date()-timedelta(days=3):
                reason='outside_publication_window'
                notice=None
                r['articles_skipped_old']+=1
            else:
                notice,reason=_municipal_article(html,url,now,'santa_rosa_municipal_lp',published)
            if published:published_days.append(published)
            r['source_attempts'].append({'url':url,'result':reason})
            if notice:r['notices'].append(notice)
        except Exception as exc:
            attempt={'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):attempt['http_status']=exc.code
            r['source_attempts'].append(attempt)
            if isinstance(exc,HTTPError) and exc.code==429:
                r['rate_limited']=True
                break
    if published_days:
        r['latest_published_date']=max(published_days).isoformat()
    if r['notices']:
        r['status']='ok'
        r['message']='Comunicados municipales fechados de fuente HTML oficial; no confirman cortes en tiempo real.'
    elif published_days and max(published_days)<now.date()-timedelta(days=3):
        r['status']='stale'
        r['message']='La portada municipal incluye noticias antiguas; no confirma normalidad del suministro.'
    else:
        r['message']='Indice HTML municipal consultado sin corte reciente de agua verificado; servicio desconocido.'
    return r


def _collect_municipal_rss(key,checked_at,now,fetch):
    r=_result(key,checked_at)
    r.update(parser_revision='MUNICIPAL-RSS-DIAGNOSTIC-v5.58',
        coverage_kind='municipal_official_dated_water_bulletins_not_live',
        notices=[],rss_items_seen=0,article_links_seen=0,
        relevant_titles_seen=0,articles_checked=0,articles_skipped_old=0,
        articles_undated=0,source_attempts=[])
    # Santa Rosa's official RSS may reject a particular host in CI. Retry
    # once on the same municipality's apex host, never on a third-party feed.
    urls=[r['source_url']]
    if key=='santa_rosa_municipal_lp':
        urls.append('https://santarosa.gob.ar/rss.xml')
    r['index_attempts']=[]
    entries=None
    count=0
    for attempt_no,feed_url in enumerate(urls):
        try:
            entries,count=_municipal_rss_index(fetch(feed_url),key)
            r['index_attempts'].append({'url':feed_url,'result':'rss_parsed',
                                         'rss_items_seen':count})
            r['index_mode']=('primary_rss' if attempt_no==0 else 'official_apex_rss_fallback')
            break
        except Exception as exc:
            attempt={'url':feed_url,'result':'fetch_or_parse_error',
                     'error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):
                attempt['http_status']=exc.code
            r['index_attempts'].append(attempt)
            # Only access failures justify a second HTTP request. Never retry
            # during rate limiting or after a structurally invalid document.
            if not isinstance(exc,(HTTPError,URLError)) or (
                isinstance(exc,HTTPError) and exc.code==429):
                break
    if entries is None:
        error=r['index_attempts'][-1]
        r['message']='RSS oficial no verificable: '+error['error_type']
        if 'http_status' in error:
            r['message']+=' (HTTP '+str(error['http_status'])+')'
        r['index_status']='fetch_or_parse_error'
        if (key=='santa_rosa_municipal_lp' and r['index_attempts']
                and all(a.get('http_status')==403 for a in r['index_attempts'])):
            return _santa_rosa_html_fallback(r,now,fetch)
        return r
    r['rss_items_seen']=count
    r['article_links_seen']=len(entries)
    if not entries:
        r['message']='RSS sin articulos oficiales con URL y fecha comprobables; no implica normalidad.'
        r['index_status']='no_official_article_links'
        return r
    dates=[d for _,_,d in entries if d]
    if dates:r['latest_published_date']=max(dates).isoformat()
    for link,title,published in entries:
        if published is None:
            r['articles_undated']+=1
            continue
        if published>now.date():
            continue
        if published<now.date()-timedelta(days=3):
            r['articles_skipped_old']+=1
            continue
        if not _MUNICIPAL_TITLE_TOPIC.search(folded(title)):
            continue
        if _REGIONAL_FINISHED.search(folded(title)):
            r['source_attempts'].append({'url':link,'result':'restoration_or_finished_title','not_fetched':True})
            continue
        r['relevant_titles_seen']+=1
        if r['articles_checked']>=3:
            break
        try:
            notice,reason=_municipal_article(fetch(link),link,now,key,published,title)
            r['articles_checked']+=1
            r['source_attempts'].append({'url':link,'result':reason})
            if notice:r['notices'].append(notice)
        except Exception as exc:
            a={'url':link,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):a['http_status']=exc.code
            r['source_attempts'].append(a)
            if isinstance(exc,HTTPError) and exc.code==429:
                r['rate_limited']=True
                break
    if r['notices']:
        r['status']='ok'
        r['message']='Comunicados municipales fechados; ninguna noticia verifica un corte en tiempo real.'
    elif dates and max(dates)<now.date()-timedelta(days=3):
        r['status']='stale'
        r['message']='El RSS contiene publicaciones antiguas; no equivale a suministro normal.'
    else:
        r['message']='RSS consultado sin impacto reciente, localizado y verificable; no confirma servicio normal.'
    if r.get('rate_limited') or any(x['result']=='fetch_or_parse_error' for x in r['source_attempts']):
        r['message']+=' Consulta parcial por problema de acceso.'
    return r



# v5.59: Public DPOSS repair records (Ushuaia / Tolhuin). The official page
# includes completed historical repairs; a label 'Tipo de corte' is NOT live
# state verification. Only date/time-localized windows with explicit possible
# drinking-water impact may become publication-only pilot bulletins. No push.
_DPOSS_ENTRY = re.compile(r'\bPublicada\s+el\s*:\s*', re.I)
_DPOSS_HEADER = re.compile(r'^\s*(\d{2}/\d{2}/\d{4})\s+(\d{1,2}):(\d{2})\b')
_DPOSS_TYPE = re.compile(r'\bTipo\s+de\s+corte\s*:\s*(Programado|Imprevisto)\b', re.I)
_DPOSS_LOCALITY = re.compile(r'\bLocalidad\s*:\s*(Ushuaia|Tolhuin)\b', re.I)
_DPOSS_ADDRESS = re.compile(r'\bDirecci[oó]n\s+aproximada\s*:\s*(.*?)\s+(?=Fecha\s*:\s*El\s+)', re.I|re.S)
_DPOSS_WINDOW = re.compile(
    r'\bFecha\s*:\s*El\s+(\d{2}/\d{2}/\d{4})\s+de\s+'
    r'(\d{1,2}):(\d{2})\s+a\s+(\d{1,2}):(\d{2})\b', re.I)
_DPOSS_IMPACT = re.compile(
    r'\bbaja presion\b|\bfalta de (?:agua|suministro)\b|'
    r'\bcorte(?:s)? de agua\b|\binterrupcion del (?:servicio|suministro)\b|'
    r'\bpodra (?:registrarse|experimentar) (?:baja presion|falta de suministro)\b')


def _dposs_structured_records(html, now):
    """Return grounded records, total visible records and discard diagnostics.

    HTML is parsed as visible text, not arbitrary script/JSON. Each record must
    contain its own labels; adjacent records must never donate dates or places.
    The website may report *completed* repairs; ended windows are not alerts.
    """
    _,visible=page(html)
    chunks=_DPOSS_ENTRY.split(visible)
    records=[]
    diagnostics={'records_seen':max(0,len(chunks)-1),'records_skipped_old':0,
                 'records_skipped_invalid':0,'records_skipped_without_water_impact':0,
                 'records_completed_today':0}
    for chunk in chunks[1:26]:
        block=chunk[:6500]
        pub=_DPOSS_HEADER.match(block)
        work_type=_DPOSS_TYPE.search(block)
        loc=_DPOSS_LOCALITY.search(block)
        window=_DPOSS_WINDOW.search(block)
        address=_DPOSS_ADDRESS.search(block)
        if not (pub and work_type and loc and window and address):
            diagnostics['records_skipped_invalid']+=1
            continue
        try:
            pub_day=_ddmmyyyy(pub.group(1))
            day=_ddmmyyyy(window.group(1))
            hour1,min1,hour2,min2=map(int,window.groups()[1:])
            if max(hour1,hour2)>23 or max(min1,min2)>59:
                raise ValueError('invalid clock')
            start=datetime(day.year,day.month,day.day,hour1,min1,tzinfo=ART)
            end=datetime(day.year,day.month,day.day,hour2,min2,tzinfo=ART)
            if end<=start or end-start>timedelta(hours=18):
                raise ValueError('invalid work window')
        except (ValueError,TypeError):
            diagnostics['records_skipped_invalid']+=1
            continue
        if (pub_day>now.date() or pub_day<day-timedelta(days=14) or
            day<now.date()-timedelta(days=1) or
            day>now.date()+timedelta(days=HORIZON_DAYS)):
            diagnostics['records_skipped_old']+=1
            continue
        # Public repairs list may describe works already concluded today.
        if end <= now:
            diagnostics['records_completed_today']+=1
            continue
        narrative=block[window.end():].strip()
        normalized=folded(narrative)
        if not re.search(r'\bagua\b|\bsuministro\b|\bred de distribucion\b|\bpotable\b',normalized):
            diagnostics['records_skipped_without_water_impact']+=1
            continue
        sentences=re.split(r'(?<=[.!?])\s+',narrative)
        possible_impact=False
        for sentence in sentences:
            f=folded(sentence)
            if _DPOSS_IMPACT.search(f) and not re.search(
                r'\bno (?:habra|habran|se registrara|se registraran|afectara|afectaran)\b|'
                r'\bsin (?:afectacion|interrupcion|corte)\b',f):
                possible_impact=True
                break
        if not possible_impact:
            diagnostics['records_skipped_without_water_impact']+=1
            continue
        if work_type.group(1).lower()=='imprevisto' and day>now.date():
            diagnostics['records_skipped_invalid']+=1
            continue
        locality=loc.group(1)
        approximate=clean(address.group(1),180)
        if len(approximate)<5:
            diagnostics['records_skipped_invalid']+=1
            continue
        company,province,url=SOURCES['dposs_tierra_del_fuego_reparaciones']
        upcoming=(start>now and work_type.group(1).lower()=='programado')
        note=mk_notice(company,province,locality,url,
            'planned_water_service_impact' if upcoming else 'water_service_bulletin',
            'scheduled_not_confirmed' if upcoming else 'publication_only_not_live',
            narrative,published_on=pub_day.isoformat(),
            scheduled_date=day.isoformat(),
            scheduled_start=start.isoformat(timespec='minutes'),
            scheduled_end=end.isoformat(timespec='minutes'),
            time_precision='official_work_window_not_live',
            repair_category=work_type.group(1).lower(),
            reported_work_location=approximate)
        # Multiple DPOSS repair notices can share the exact page, city and day.
        # Each gets its own stable ID from the separately documented location.
        distinct='|'.join([url,locality,day.isoformat(),
                           start.isoformat(timespec='minutes'),approximate])
        note['id']='agua-'+sha256(distinct.encode('utf-8')).hexdigest()[:18]
        records.append(note)
    return records,diagnostics


def _collect_dposs(checked_at,now,fetch):
    key='dposs_tierra_del_fuego_reparaciones'
    r=_result(key,checked_at)
    r.update(parser_revision='DPOSS-REPAIRS-v5.59',
             coverage_kind='official_dated_public_repair_records_not_live',
             records_seen=0,records_checked=0,notices=[],source_attempts=[])
    url=r['source_url']
    try:
        records,details=_dposs_structured_records(fetch(url),now)
        r.update(details)
        r['records_checked']=len(records)
        r['notices']=records[:12]
        r['source_attempts'].append({'url':url,'result':'structured_records_read',
                                     'records_seen':r['records_seen']})
        if r['notices']:
            r['status']='ok'
            r['message']='Registros DPOSS con fecha y horarios: no verifican estado del suministro en tiempo real.'
        elif r['records_seen']:
            if r['records_skipped_old'] or r['records_completed_today']:
                r['status']='stale'
                r['message']='La página contiene reparaciones finalizadas o históricas. No implica suministro normal.'
            else:
                r['message']='No hay registros completos con impacto de agua verificable; estado actual desconocido.'
        else:
            r['message']='La página DPOSS no expuso reparaciones estructuradas reconocibles; estado desconocido.'
    except Exception as exc:
        r['message']='No se pudo verificar la página de reparaciones DPOSS: '+type(exc).__name__
        attempt={'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
        if isinstance(exc,HTTPError):attempt['http_status']=exc.code
        r['source_attempts'].append(attempt)
    return r

# v5.62: Corrientes regulator news and Parana municipal-radio news.
# Both are OFFICIAL PUBLIC NEWS, not live service status and not a utility API.
# The articles are only sampled if their dates, official URLs and concrete
# effect on potable-water service are separately verifiable. No notifications.
_PUBLIC_NEWS_HOSTS = {
    'aosc_corrientes_regulador': 'aosc.gob.ar',
    'parana_radio_municipal_agua': 'costa.parana.gob.ar',
}
_PUBLIC_WATER_TITLE = re.compile(
    r'agua potable|servicio de agua|suministro de agua|corte de agua|'
    r'falta de agua|baja presion|caneria|acueducto|red de agua|'
    r'planta potabilizadora|obras sanitarias')
_PUBLIC_REGULATOR_LOCALITIES = (
    'Curuzu Cuatia', 'Goya', 'Mercedes', 'Paso de los Libres',
    'Monte Caseros', 'Santo Tome', 'Ituzaingo', 'Bella Vista',
    'Empedrado', 'Esquina', 'Saladas', 'San Roque', 'Alvear',
    'San Luis del Palmar', 'San Cosme', 'Santa Lucia', 'Virasoro',
    'Yapeyu', 'Mburucuya', 'San Miguel',
)


def _public_news_valid_url(url,key):
    parsed=urlsplit(url)
    if (parsed.scheme!='https' or parsed.hostname!=_PUBLIC_NEWS_HOSTS[key]
        or parsed.username is not None or parsed.password is not None
        or parsed.port is not None or parsed.query or parsed.fragment):
        return False
    path=parsed.path
    if key=='aosc_corrientes_regulador':
        return bool(re.fullmatch(r'/noticias/[A-Za-z0-9_-]{6,}/?',path))
    return bool(re.fullmatch(r'/[a-zA-Z0-9%_-]{14,}/?',path))


# v5.63: The municipality radio's /category/locales/ archive showed October
# stories on 21 November despite having 40 HTML anchors. Its official /noticias/
# index, independently checked, is current. The labels contain a dated/category
# prefix ("20/11/2026 | Locales | (1) Headline") which must be removed before
# comparing with the article's H1. An index date is only a *fetch filter*;
# the article itself must still independently verify its publication date.
_PUBLIC_PARANA_OLD_INDEX='https://costa.parana.gob.ar/category/locales/'


def _public_news_index_label(label,key):
    label=clean(label,450)
    if key!='parana_radio_municipal_agua':
        return label,None
    observed=None
    m=re.match(r'^\s*(\d{1,2})/(\d{1,2})/(20\d{2})\b',label)
    if m:
        try:observed=date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
        except ValueError:pass
        label=label[m.end():].lstrip(' |:-')
    # The category and thumbnail counter are not part of the H1 title.
    label=re.sub(r'^(?:[^|]{2,55}\|\s*)?\(\d{1,3}\)\s*','',label).strip()
    return label,observed


def _public_news_index(html,base,key,now=None,stats=None):
    dom,visible=page(html)
    items=[];seen=set()
    stats=stats if stats is not None else {}
    stats.update(valid_article_links_seen=0,relevant_titles_seen=0,
                 older_headlines_skipped=0,future_headlines_skipped=0,
                 index_dated_headlines_seen=0)
    for href,label in dom.anchors:
        url=urljoin(base,href)
        if not _public_news_valid_url(url,key) or url in seen:
            continue
        seen.add(url)
        stats['valid_article_links_seen']+=1
        title,listing_day=_public_news_index_label(label,key)
        if key=='parana_radio_municipal_agua':
            if not _PUBLIC_WATER_TITLE.search(folded(title)):
                continue
            stats['relevant_titles_seen']+=1
            if listing_day:
                stats['index_dated_headlines_seen']+=1
                if now and listing_day<now.date()-timedelta(days=3):
                    stats['older_headlines_skipped']+=1
                    continue
                if now and listing_day>now.date():
                    stats['future_headlines_skipped']+=1
                    continue
        items.append((url,title))
    return items[:12],len(dom.anchors),visible


def _public_news_date(dom,visible,html,title,key):
    d=_published_date_from_meta(html)
    if d:
        return d
    # Only an article's own visible publication date, adjacent to its title.
    # Never read dates from unrelated page navigation or other articles.
    at=folded(visible).find(folded(title))
    if at<0:
        return None
    nearby=visible[max(0,at-85):at+len(title)+150]
    d=_parse_official_day(nearby)
    if d:
        return d
    # Corrientes AOSC displays e.g. 02-02-2023 on article pages.
    if key=='aosc_corrientes_regulador':
        m=re.search(r'\b(\d{2})-(\d{2})-(20\d{2})\b',nearby)
        if m:
            try:
                return date(int(m[3]),int(m[2]),int(m[1]))
            except ValueError:
                pass
    return None


def _public_news_locality(title,key):
    if key=='parana_radio_municipal_agua':
        return 'Parana'
    f=folded(title)
    possible=[loc for loc in _PUBLIC_REGULATOR_LOCALITIES
              if re.search(r'(?<!\w)'+re.escape(folded(loc))+r'(?!\w)',f)]
    return possible[0] if len(possible)==1 else None


def _public_news_article(html,url,now,key,index_title=''):
    dom,visible=page(html)
    title=next((h for h in dom.headings if len(h)>=19 and
                folded(h) not in ('noticias','inicio','aosc','locales')),'')
    if not title:
        return None,None,'article_title_missing'
    if index_title and folded(index_title) not in ('leer mas','leer mas...'):
        if not (folded(index_title) in folded(title) or folded(title) in folded(index_title)):
            return None,None,'article_title_mismatch'
    published=_public_news_date(dom,visible,html,title,key)
    if not published:
        return None,None,'publication_date_not_verified'
    if published>now.date() or published<now.date()-timedelta(days=3):
        return None,published,'outside_publication_window'
    locality=_public_news_locality(title,key)
    if not locality:
        return None,published,'locality_not_grounded_in_title'
    if _REGIONAL_FINISHED.search(folded(title)):
        return None,published,'completed_or_restored_title'
    paragraphs=[p for p in dom.paragraphs if len(p)>25][:24]
    if not paragraphs:
        return None,published,'no_article_body'
    relevant=[]
    for p in paragraphs:
        # Keep negation local to its paragraph; a statement that works do
        # NOT affect supply must never be turned into a water outage.
        f=folded(p)
        if _REGIONAL_NEGATIVE.search(f) or _REGIONAL_FINISHED.search(f):
            continue
        sentences=re.split(r'(?<=[.!?])\s+',p)
        for i,sentence in enumerate(sentences):
            sf=folded(sentence)
            if not _MUNICIPAL_IMPACT.search(sf) or _REGIONAL_NEGATIVE.search(sf):
                continue
            local_context=sf+' '+(folded(sentences[i-1]) if i else '')
            if not _MUNICIPAL_WATER.search(local_context):
                continue
            relevant.append(sentence)
    if not relevant:
        return None,published,'no_explicit_potable_water_service_impact'
    company,province,_=SOURCES[key]
    return mk_notice(company,province,locality,url,'water_service_bulletin',
        'publication_only_not_live',' '.join(paragraphs),published_on=published.isoformat(),
        scheduled_start=None,scheduled_end=None,
        coverage_kind='dated_official_public_news_not_live'),published,'parsed'


def _collect_public_news(key,checked_at,now,fetch):
    r=_result(key,checked_at)
    r.update(parser_revision='PUBLIC-OFFICIAL-NEWS-v5.63',
             coverage_kind='dated_official_public_news_not_live',
             article_links_seen=0,articles_checked=0,
             source_attempts=[],notices=[],articles_deferred_by_budget=0,
             index_attempts=[])
    original=r['source_url']
    indices=[original]
    if key=='parana_radio_municipal_agua':
        indices.append(_PUBLIC_PARANA_OLD_INDEX)
    items=[]
    for index_no,index_url in enumerate(indices):
        try:
            html=fetch(index_url)
            stats={}
            candidates,anchors,visible=_public_news_index(html,index_url,key,now,stats)
            r['html_anchors_seen']=anchors
            for field,value in stats.items():r[field]=value
            r['index_attempts'].append({'url':index_url,
                 'result':'recent_water_links_found' if candidates else 'no_recent_water_headlines',
                 'html_anchors_seen':anchors,
                 'valid_article_links_seen':stats['valid_article_links_seen'],
                 'relevant_titles_seen':stats['relevant_titles_seen'],
                 'older_headlines_skipped':stats['older_headlines_skipped']})
            items=candidates
            r['index_mode']='current_news_index' if index_no==0 else 'official_category_fallback'
            # A successfully read, article-bearing index with no recent water
            # titles is not an access error; don't retry an outdated archive.
            if items or stats['valid_article_links_seen']:
                break
        except Exception as exc:
            attempt={'url':index_url,'result':'fetch_or_parse_error',
                     'error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):attempt['http_status']=exc.code
            r['index_attempts'].append(attempt)
            r['index_status']='fetch_or_parse_error'
            if isinstance(exc,HTTPError):r['http_status']=exc.code
            # Explicit 403 is a refusal from the site, not a zero-results list;
            # do not probe alternate routes after an explicit access denial.
            if isinstance(exc,HTTPError) and exc.code in (403,429):
                r['access_mode']='official_site_rejected_automated_request'
                r['message']='El sitio oficial rechazó la consulta (HTTP %s). No se pudieron verificar avisos.'%exc.code
                return r
            if index_no==len(indices)-1:
                r['message']='No se pudo verificar el portal oficial: '+type(exc).__name__
                return r
            continue
    r['index_status']='recent_water_links_found' if items else 'no_recent_water_headlines'
    r['article_links_seen']=len(items)
    limit=3 if key=='aosc_corrientes_regulador' else 2
    chosen=items[:limit]
    r['articles_deferred_by_budget']=max(0,len(items)-len(chosen))
    dates=[]
    for url,label in chosen:
        try:
            notice,d,reason=_public_news_article(fetch(url),url,now,key,label)
            r['articles_checked']+=1
            r['source_attempts'].append({'url':url,'result':reason})
            if d:dates.append(d)
            if notice:r['notices'].append(notice)
        except Exception as exc:
            a={'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):a['http_status']=exc.code
            r['source_attempts'].append(a)
            if isinstance(exc,HTTPError) and exc.code==429:
                r['rate_limited']=True
                break
    if dates:r['latest_published_date']=max(dates).isoformat()
    if r['notices']:
        r['status']='ok'
        r['message']='Noticias oficiales fechadas; no acreditan el estado del suministro en tiempo real.'
    elif dates and all(d<now.date()-timedelta(days=3) for d in dates):
        r['status']='stale'
        r['message']='Noticias consultadas antiguas; no implica suministro normal.'
    elif key=='parana_radio_municipal_agua' and not items and r.get('valid_article_links_seen'):
        r['message']='Índice oficial consultado sin titulares recientes sobre afectaciones del agua potable; no confirma servicio normal.'
    else:
        r['message']='No se verificaron avisos recientes con localidad e impacto concreto. Estado desconocido.'
    if r['articles_deferred_by_budget'] or r.get('rate_limited') or any(
            a['result']=='fetch_or_parse_error' for a in r['source_attempts']):
        r['message']+=' Lectura parcial; no se revisaron todas las publicaciones.'
    return r



# v5.64: official concessionaire news (separate from AOSC, which responds 403).
# The public /estado-del-servicio page can be an empty/dynamic shell; a reachable
# page is not proof of normal water service. Only dated, localised, affirmative
# potable-water impacts in the concessionaire's own articles can be notices.
_ADC_KEY='aguas_corrientes_prestador'
_ADC_HOST='www.aguasdecorrientes.com'
_ADC_HOSTS=frozenset((_ADC_HOST,'aguasdecorrientes.com'))
_ADC_IMPACT_HEADLINE=re.compile(
    r'\b(?:corte|cortes|interrupcion|interrupciones|suspension|'
    r'baja presion|falta de agua|sin agua|sin suministro|'
    r'suministro interrumpido|afectara el suministro)\b')
# Concessionaire-specific negations not fully covered by shared news filters.
# A news title mentioning a cut is not enough when its BODY denies impact.
_ADC_NO_IMPACT=re.compile(
    r'\b(?:no se afectara (?:el )?(?:servicio|suministro)|'
    r'no (?:se )?(?:registrara|producira) (?:baja presion|falta de agua|faltante de agua)|'
    r'no habra (?:baja presion|falta de agua|cortes|interrupciones)|'
    r'no se vera afectad[oa] (?:el )?(?:servicio|suministro))\b')
_ADC_CITIES=(
    'Corrientes', 'Goya', 'Curuzu Cuatia', 'Paso de los Libres',
    'Mercedes', 'Monte Caseros', 'Santo Tome', 'Ituzaingo',
    'Bella Vista', 'Empedrado', 'Esquina', 'Saladas',
    'San Luis del Palmar', 'Santa Lucia', 'Yapeyu', 'Virasoro',
    'Alvear', 'San Roque', 'San Cosme', 'Mburucuya',
)


def _adc_safe_public_url(url):
    """Only same-site public HTTPS. No query strings, fragments or credentials."""
    try:
        p=urlsplit(url)
        return (p.scheme=='https' and p.hostname in _ADC_HOSTS and
                not p.username and not p.password and p.port is None and
                not p.query and not p.fragment)
    except ValueError:
        return False


def _adc_article_url(url):
    if not _adc_safe_public_url(url):
        return False
    path=urlsplit(url).path
    # Route shapes are candidate PUBLIC ARTICLES only, not proof of an impact.
    # v5.65 confirmed 69 same-site /NNNN public news links on the real
    # /noticias index. Recognize root-level numeric story IDs, but ONLY when
    # discovered via that index and independently verified as dated impacts.
    return bool(
        re.fullmatch(r'/[0-9]{1,8}/?',path) or
        re.fullmatch(r'/[0-9]{1,8}/[a-z0-9-]{12,160}/?',path) or
        re.fullmatch(r'/(?:noticias|noticia|novedades|novedad)/[a-z0-9-]{12,160}/?',path) or
        re.fullmatch(r'/(?:noticias|noticia|novedades|novedad)/[0-9]{1,8}(?:/[a-z0-9-]{12,160})?/?',path)
    )


def _adc_index(html,base):
    dom,visible=page(html)
    unique={};valid=0;same_site=0;rejected=0;path_samples=[];title_hits=0
    for href,label in dom.anchors:
        url=urljoin(base,href)
        label=clean(label,260)
        # Treat links with queries, fragments and credential-looking URLs as
        # opaque and never log their parameters or fetch them.
        if not _adc_safe_public_url(url):
            continue
        same_site+=1
        if _ADC_IMPACT_HEADLINE.search(folded(label)):
            title_hits+=1
        if not _adc_article_url(url):
            rejected+=1
            path=urlsplit(url).path
            # Only public-looking non-navigation headings; no full query URLs.
            if (len(label)>=24 and len(path)>2 and len(path)<=160 and
                path not in ('/noticias','/noticias/','/') and
                not re.search(r'/(?:login|cuenta|usuario|factura|registro|perfil|carrito|search|buscar)(?:/|$)',path,re.I) and
                len(path_samples)<8):
                path_samples.append({'path':path,'title':clean(label,100)})
            continue
        if url in unique:
            continue
        unique[url]=label
        valid+=1
    # A headline alone is not an outage. The article must independently
    # establish the locality, publication date and an affirmative impact.
    likely=[(u,t) for u,t in unique.items()
            if _ADC_IMPACT_HEADLINE.search(folded(t))]
    return likely[:3],{'html_anchors_seen':len(dom.anchors),
                       'html_visible_characters':len(visible),
                       'same_site_anchors_seen':same_site,
                       'same_site_unmatched_paths_seen':rejected,
                       'same_site_unmatched_path_samples':path_samples,
                       'same_site_impact_headlines_seen':title_hits,
                       'valid_article_links_seen':valid,
                       'impact_title_candidates_seen':len(likely),
                       'articles_deferred_by_budget':max(0,len(likely)-3)}


def _adc_locality(headline):
    f=folded(headline)
    matches=[city for city in _ADC_CITIES
             if re.search(r'(?<!\w)'+re.escape(folded(city))+r'(?!\w)',f)]
    return matches[0] if len(matches)==1 else None


# v5.67: A numeric date is a publication date only if it is explicitly
# labelled as such in the ARTICLE heading area. The /NNNN story identifier,
# dates mentioned in the story body, and the crawl time are NEVER dates.
_ADC_PUBLISHED_NUMERIC = re.compile(
    r'\b(?:publicad[oa](?:\s+el)?|fecha\s+de\s+publicacion)'
    r'\s*[:\-]?\s*(\d{1,2})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*(20\d{2})\b')
_ADC_PUBLISHED_TEXTUAL = re.compile(
    r'\b(?:publicad[oa](?:\s+el)?|fecha\s+de\s+publicacion)'
    r'\s*[:\-]?\s*(\d{1,2})\s+(?:de\s+)?'
    r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)'
    r'\s*,?\s*(?:de\s+)?(20\d{2})\b')


def _adc_publication_day(html,visible,title):
    # The ordinary article:published_time / datePublished / time[datetime]
    # source already covers many official publication-date formats.
    metadata=_published_date_from_meta(html)
    if metadata:
        return metadata
    visible_folded=folded(visible)
    title_folded=folded(title)
    if not title_folded:
        return None
    # A repeated story title may occur in navigation. Inspect each occurrence
    # without scanning unrelated page content. Require a publication marker
    # for numeric dates; otherwise a future scheduled work date might be read
    # as the publication date.
    positions=[m.start() for m in re.finditer(re.escape(title_folded),visible_folded)]
    for at in reversed(positions):
        before=visible[max(0,at-95):at]
        after=visible[at+len(title):at+len(title)+145]
        for nearby in (after,before):
            compact=folded(nearby)
            match=_ADC_PUBLISHED_NUMERIC.search(compact)
            if match:
                try:
                    return date(int(match.group(3)),int(match.group(2)),int(match.group(1)))
                except ValueError:
                    continue
        # An unlabelled textual date may describe a PLANNED work day, not
        # publication. Accept the full-month form only with the same explicit
        # publication marker; no guessing from the article body.
        for nearby in (after,before):
            match=_ADC_PUBLISHED_TEXTUAL.search(folded(nearby))
            if match:
                try:
                    return date(int(match.group(3)),MONTH[match.group(2)],int(match.group(1)))
                except ValueError:
                    continue
    return None


def _adc_article(html,url,now,listing_title):
    dom,visible=page(html)
    candidate_headings=[h for h in dom.headings if len(h)>15 and
                        folded(h) not in ('ultimas noticias','noticias','empresa')]
    # Official pages can have unrelated 'Agua y Saneamiento' headings above
    # the actual story. Match the verified listing title, not the first H tag.
    if listing_title:
        match=folded(listing_title)
        title=next((h for h in candidate_headings if
                    match in folded(h) or folded(h) in match),None)
    else:
        title=next(iter(candidate_headings),None)
    if not title:
        return None,None,('article_title_mismatch' if candidate_headings
                          else 'article_title_missing')
    if _REGIONAL_FINISHED.search(folded(title)):
        return None,None,'completed_or_restored_title'
    city=_adc_locality(title)
    if not city:
        return None,None,'locality_not_explicit_in_title'
    # Publication date must be explicit; never infer from /NNNN article ID.
    # Keep report-only status if no official publication date can be checked.
    published=_adc_publication_day(html,visible,title)
    if not published:
        return None,None,'publication_date_not_verified'
    if published>now.date() or published<now.date()-timedelta(days=3):
        return None,published,'outside_publication_window'
    paragraphs=[p for p in dom.paragraphs if len(p)>28][:20]
    if not paragraphs:
        return None,published,'no_article_body'
    found=False
    for p in paragraphs:
        # Negated announcements and restored service never produce alerts.
        f=folded(p)
        if (_REGIONAL_NEGATIVE.search(f) or _REGIONAL_FINISHED.search(f) or
            _ADC_NO_IMPACT.search(f)):
            continue
        for line in re.split(r'(?<=[.!?])\s+',p):
            linef=folded(line)
            if (_MUNICIPAL_IMPACT.search(linef) and
                not _ADC_NO_IMPACT.search(linef) and
                ('agua potable' in linef or 'suministro de agua' in linef or
                 'servicio de agua' in linef) and
                not _REGIONAL_NEGATIVE.search(linef)):
                found=True
                break
        if found:break
    if not found:
        return None,published,'no_explicit_potable_water_impact'
    company,province,_=SOURCES[_ADC_KEY]
    n=mk_notice(company,province,city,url,'water_service_bulletin',
                'publication_only_not_live',' '.join(paragraphs),
                published_on=published.isoformat(),scheduled_start=None,
                scheduled_end=None)
    return n,published,'parsed'


def _collect_adc(checked_at,now,fetch):
    r=_result(_ADC_KEY,checked_at)
    r.update(parser_revision='ADC-HEADING-PUBLISHED-DATE-v5.67',
             coverage_kind='dated_official_company_news_not_live',
             notices=[],article_links_seen=0,articles_checked=0,
             source_attempts=[],index_attempts=[],
             articles_deferred_by_budget=0)
    url=r['source_url']
    try:
        html=fetch(url)
        chosen,stats=_adc_index(html,url)
        r.update(stats)
        r['article_links_seen']=stats['valid_article_links_seen']
        r['index_attempts'].append({'url':url,'result':'official_news_index_read',
                                    'valid_article_links_seen':stats['valid_article_links_seen']})
    except Exception as exc:
        attempt={'url':url,'result':'fetch_or_parse_error',
                 'error_type':type(exc).__name__}
        if isinstance(exc,HTTPError):attempt['http_status']=exc.code
        r['index_attempts'].append(attempt)
        r['message']='No se pudo verificar el portal oficial de Aguas de Corrientes: '+type(exc).__name__
        if isinstance(exc,HTTPError):r['http_status']=exc.code
        return r
    dates=[]
    for article_url,label in chosen:
        try:
            n,d,reason=_adc_article(fetch(article_url),article_url,now,label)
            attempt={'url':article_url,'result':reason}
            if reason=='publication_date_not_verified':
                attempt['publication_date_check']='no_explicit_date_in_article_metadata_or_heading'
            if d:
                attempt['published_on']=d.isoformat();dates.append(d)
            r['source_attempts'].append(attempt)
            r['articles_checked']+=1
            if n:r['notices'].append(n)
        except HTTPError as exc:
            r['source_attempts'].append({'url':article_url,'result':'fetch_or_parse_error',
                                         'error_type':'HTTPError','http_status':exc.code})
            if exc.code==429:
                r['rate_limited']=True
                break
        except Exception as exc:
            r['source_attempts'].append({'url':article_url,'result':'fetch_or_parse_error',
                                         'error_type':type(exc).__name__})
    if r['notices']:
        r['status']='ok'
        r['message']='Comunicados fechados de la prestadora; no certifican cortes en tiempo real.'
    elif dates and all(d<now.date()-timedelta(days=3) for d in dates):
        r['status']='stale'
        r['message']='Publicaciones antiguas de la prestadora; estado actual desconocido.'
    elif not r['article_links_seen'] and r['html_anchors_seen']:
        r['message']=('El índice de la prestadora responde, pero no ofrece enlaces de artículos '
                      'en los formatos reconocidos; se requiere validar su estructura. '
                      'No se pudo verificar el estado del servicio.')
    elif r['article_links_seen'] and not r['impact_title_candidates_seen']:
        r['message']='Noticias oficiales revisadas sin titulares sobre cortes de agua; estado del servicio desconocido.'
    else:
        r['message']='No se verificó afectación reciente, fechada y localizada en el portal de la prestadora; estado desconocido.'
    if r.get('rate_limited') or any(x['result']=='fetch_or_parse_error' for x in r['source_attempts']):
        r['message']+=' Consulta parcial.'
    return r




# v5.68: Official OSSE San Juan news is a PUBLIC pilot, not an interruption
# monitor. The new site has a news carousel; the legacy /v4/prensa index
# previously displayed old items. Do not substitute that stale archive for a
# fresh index and never infer any disruption from restrictions on water use.
_OSSE_SJ_KEY='osse_san_juan_prensa'
_OSSE_SJ_HOSTS=frozenset(('www.ossesanjuan.com.ar','ossesanjuan.com.ar'))
_OSSE_SJ_LOCALITIES=(
    'Rawson','Pocito','Rivadavia','Chimbas','Caucete','Albardon',
    'Santa Lucia','San Martin','Sarmiento','Jachal','Iglesia','Calingasta',
    'Valle Fertil','25 de Mayo','9 de Julio','Ullum','Zonda','Angaco',
    'Barreal','Rodeo',
)


def _osse_sj_news_url(url):
    try:
        u=urlsplit(url)
        if (u.scheme!='https' or u.hostname not in _OSSE_SJ_HOSTS or
            u.username or u.password or u.port is not None or u.fragment):
            return False
        path=u.path.lower()
        if re.search(r'/(?:usuario|cuenta|perfil|login|registro|factura|pago|reclamo)(?:/|$)',path):
            return False
        if re.fullmatch(r'/v4/prensa/noticia/?',path):
            return bool(re.fullmatch(r'noticia=[A-Za-z0-9_-]{12,200}',u.query))
        return (not u.query and bool(re.fullmatch(
            r'/(?:noticias|novedades|noticia|prensa)/(?:[a-z0-9_-]{6,}/?){1,3}',path)))
    except ValueError:
        return False


class _OSSESJIndexPage(VisiblePage):
    """Capture the H2/H3 preceding a generic 'Ver más' news-card link."""
    def __init__(self):
        super().__init__()
        self.news_anchors=[]
        self._last_heading=''
        self._since_heading=9999
        self._anchor_heading=''
    def handle_starttag(self,tag,attrs):
        if tag=='a' and not self.ignored:
            self._anchor_heading=(self._last_heading if self._since_heading<550 else '')
        super().handle_starttag(tag,attrs)
    def handle_data(self,t):
        super().handle_data(t)
        if not self.ignored:
            self._since_heading+=len(t)
    def handle_endtag(self,tag):
        prev=len(self.anchors)
        super().handle_endtag(tag)
        if tag in ('h2','h3') and self.headings:
            self._last_heading=self.headings[-1]
            self._since_heading=0
        if tag=='a' and len(self.anchors)>prev:
            href,label=self.anchors[-1]
            self.news_anchors.append((href,label,self._anchor_heading))
            self._anchor_heading=''


def _osse_sj_index(html,base):
    if not isinstance(html,str) or not html.strip() or len(html.encode('utf-8'))>MAX_PAGE_BYTES:
        raise ValueError('Índice OSSE vacío o muy grande')
    parser=_OSSESJIndexPage()
    parser.feed(html)
    seen=set();candidate=[];valid=0;hits=0;unmatched=[]
    for href,label,nearby_h in parser.news_anchors:
        url=urljoin(base,href)
        if url in seen:continue
        seen.add(url)
        if not _osse_sj_news_url(url):
            if (urlsplit(url).hostname in _OSSE_SJ_HOSTS and
                urlsplit(url).scheme=='https' and len(unmatched)<6 and
                re.search('noticia|noticias|prensa|novedad',urlsplit(url).path,re.I)):
                unmatched.append(urlsplit(url).path[:120])
            continue
        valid+=1
        title=label
        if folded(label).strip(' .:') in ('ver mas','leer mas','mas informacion',''):
            title=nearby_h
        title=clean(title,240)
        if not title or len(title)<18:continue
        if _ADC_IMPACT_HEADLINE.search(folded(title)):
            hits+=1;candidate.append((url,title))
    return candidate[:3],{
        'html_anchors_seen':len(parser.anchors),
        'valid_article_links_seen':valid,
        'impact_title_candidates_seen':hits,
        'unmatched_news_route_samples':unmatched,
    }


def _osse_sj_locality(title):
    f=folded(title)
    found=[loc for loc in _OSSE_SJ_LOCALITIES
           if re.search(r'(?<!\w)'+re.escape(folded(loc))+r'(?!\w)',f)]
    if re.search(r'(?<!\w)capital(?!\w)',f):found.append('Capital')
    # 'San Juan' alone is a province, and is NOT enough to identify city.
    return found[0] if len(found)==1 else None


def _osse_sj_article(html,url,now,listed_title):
    dom,visible=page(html)
    name=folded(listed_title).rstrip('. ').strip()
    # A carousel H2 may be clipped by an ellipsis. Still require the article
    # heading to have the same substantive first words.
    probe=name[:min(len(name),27)]
    title=next((h for h in dom.headings if len(h)>15 and probe in folded(h)),None)
    if not title:
        return None,None,'article_title_not_verified'
    locality=_osse_sj_locality(title)
    if not locality:return None,None,'locality_not_explicit_in_title'
    if _REGIONAL_FINISHED.search(folded(title)):
        return None,None,'completed_or_restored_title'
    pub=_adc_publication_day(html,visible,title)
    if not pub:return None,None,'publication_date_not_verified'
    if pub>now.date() or pub<now.date()-timedelta(days=3):
        return None,pub,'outside_publication_window'
    paragraphs=[p for p in dom.paragraphs if len(p)>28][:18]
    if not paragraphs:return None,pub,'no_article_body'
    affirmative=False
    for p in paragraphs:
        f=folded(p)
        if (_REGIONAL_NEGATIVE.search(f) or _REGIONAL_FINISHED.search(f) or
            _ADC_NO_IMPACT.search(f)):
            continue
        for sentence in re.split(r'(?<=[.!?])\s+',p):
            sf=folded(sentence)
            if (_MUNICIPAL_IMPACT.search(sf) and
                not _REGIONAL_NEGATIVE.search(sf) and
                not _ADC_NO_IMPACT.search(sf) and
                _MUNICIPAL_WATER.search(sf)):
                affirmative=True;break
        if affirmative:break
    if not affirmative:return None,pub,'no_explicit_water_impact'
    company,province,_=SOURCES[_OSSE_SJ_KEY]
    notice=mk_notice(company,province,locality,url,
        'water_service_bulletin','publication_only_not_live',' '.join(paragraphs),
        published_on=pub.isoformat(),scheduled_start=None,scheduled_end=None)
    return notice,pub,'parsed'


def _collect_osse_sj(checked_at,now,fetch):
    r=_result(_OSSE_SJ_KEY,checked_at)
    r.update(parser_revision='OSSE-SANJUAN-PUBLIC-NEWS-v5.68',
             coverage_kind='official_public_company_news_not_live',
             notices=[],article_links_seen=0,articles_checked=0,
             source_attempts=[],index_attempts=[],articles_deferred_by_budget=0)
    url=r['source_url']
    try:
        index_html=fetch(url)
        chosen,stats=_osse_sj_index(index_html,url)
        _dom,index_visible=page(index_html)
        stats['html_visible_characters']=len(index_visible)
        stats['index_mode']=('client_rendered_shell_suspected' if not stats['html_anchors_seen'] and re.search(r'<script\b',index_html,re.I) else 'public_html_index')
        r.update(stats)
        r['article_links_seen']=stats['valid_article_links_seen']
        r['index_attempts'].append({'url':url,'result':'index_read',
                                    'valid_article_links_seen':stats['valid_article_links_seen']})
    except Exception as exc:
        a={'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
        if isinstance(exc,HTTPError):a['http_status']=exc.code
        r['index_attempts'].append(a)
        r['message']='No se pudo verificar el índice oficial OSSE: '+type(exc).__name__
        return r
    dates=[]
    for u,label in chosen:
        try:
            n,d,why=_osse_sj_article(fetch(u),u,now,label)
            r['articles_checked']+=1
            r['source_attempts'].append({'url':u,'result':why})
            if d:dates.append(d)
            if n:r['notices'].append(n)
        except Exception as exc:
            a={'url':u,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):a['http_status']=exc.code
            r['source_attempts'].append(a)
            if isinstance(exc,HTTPError) and exc.code==429:
                r['rate_limited']=True
                break
    if r['notices']:
        r['status']='ok'
        r['message']='Comunicados oficiales fechados; no son cortes confirmados en tiempo real.'
    elif dates and all(d<now.date()-timedelta(days=3) for d in dates):
        r['status']='stale'
        r['message']='Las noticias recuperadas son antiguas; estado del servicio desconocido.'
    elif not r['article_links_seen']:
        r['message']=('La portada oficial no expuso enlaces de noticias utilizables en el HTML recibido. '
                      'Si el contenido se carga mediante JavaScript, el estado del servicio sigue sin verificar.')
    else:
        r['message']='Portada oficial consultada, sin afectaciones recientes verificables; no implica servicio normal.'
    return r



# v5.69: Province of Santa Cruz government press, official SPSE section.
# The public news index explicitly shows publication dates and story links.
# This is NOT the SPSE outage-monitor API; only verified dated announcements.
_SPSE_KEY='spse_santa_cruz_prensa'
_SPSE_PRESS_PREFIX='/organismos/entes-publicos/servicios-publicos/'
_SPSE_HEADLINE=re.compile(
    r'\b(?:corte(?:s)?|interrupcion(?:es)?|suspension(?:es)?|'
    r'falta de agua|sin agua|baja presion|presion reducida|'
    r'suministro (?:de agua )?(?:afectado|interrumpido))\b')
_SPSE_WATER_TOPIC=re.compile(
    r'\b(?:agua potable|red de agua|servicio de agua|suministro de agua|'
    r'falta de agua|agua corriente|acueducto|planta potabilizadora)\b')
_SPSE_NEGATIVE=re.compile(
    r'\b(?:no hubo (?:corte|interrupcion|falta de agua)|'
    r'no se registraron (?:cortes|interrupciones)|'
    r'no se afectara|sin afectar|sin interrumpir|'
    r'no se interrumpira|no se vera afectad[oa])\b')
_SPSE_PLACES=(
    'Rio Gallegos','Caleta Olivia','Pico Truncado','Puerto Deseado',
    'Las Heras','Perito Moreno','El Calafate','Rio Turbio',
    '28 de Noviembre','Puerto San Julian','San Julian','Gobernador Gregores',
    'Comandante Luis Piedra Buena','Piedra Buena','Los Antiguos',
    'Puerto Santa Cruz','Canadon Seco','Lago Posadas','El Chalten',
    'Puerto Santa Cruz','Tres Lagos','Jaramillo','Fitz Roy','Tellier',
)
_SPSE_DATE=re.compile(
    r'\b(\d{1,2})\s+(?:de\s+)?'
    r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)'
    r'\s+(?:de\s+)?(20\d{2})\b')


def _spse_date(text):
    m=_SPSE_DATE.search(folded(text))
    if not m:return None,m
    try:return date(int(m.group(3)),MONTH[m.group(2)],int(m.group(1))),m
    except ValueError:return None,m


def _spse_story_url(url):
    try:
        u=urlsplit(url)
        slug=u.path[len(_SPSE_PRESS_PREFIX):] if u.path.startswith(_SPSE_PRESS_PREFIX) else ''
        if slug in ('contacto','reclamos','usuarios','login','noticias','facturas','servicios'):
            return False
        return (u.scheme=='https' and u.hostname=='noticias.santacruz.gob.ar' and
                not u.username and not u.password and u.port is None and
                not u.query and not u.fragment and
                bool(re.fullmatch(re.escape(_SPSE_PRESS_PREFIX)+r'[a-z0-9-]{8,180}',u.path)))
    except ValueError:
        return False


def _spse_index(html,base,now):
    dom,visible=page(html)
    seen=set(); candidates=[]; valid=0; dated=0; skipped_old=0; topical=0
    for href,label in dom.anchors:
        url=urljoin(base,href)
        if not _spse_story_url(url) or url in seen:continue
        seen.add(url);valid+=1
        pub,match=_spse_date(label)
        if not pub or not match:continue
        dated+=1
        title=clean(label[match.end():],240).strip(' -|:')
        if len(title)<17:continue
        if pub>now.date() or pub<now.date()-timedelta(days=3):
            skipped_old+=1;continue
        if _REGIONAL_FINISHED.search(folded(title)):
            continue
        if not _SPSE_HEADLINE.search(folded(title)):
            continue
        topical+=1
        candidates.append((url,title,pub))
    return candidates[:3],{
        'html_anchors_seen':len(dom.anchors),
        'valid_article_links_seen':valid,
        'dated_headlines_seen':dated,
        'headlines_skipped_outside_window':skipped_old,
        'impact_title_candidates_seen':topical,
        'articles_deferred_by_budget':max(0,len(candidates)-3),
    }


def _spse_location(title,paragraphs):
    # Locality must occur explicitly in the title, or in a short opening
    # fragment as 'en [city]'/'de [city]'. The provincial seat isn't assumed.
    ft=folded(title)
    names=[]
    for city in _SPSE_PLACES:
        if re.search(r'(?<!\w)'+re.escape(folded(city))+r'(?!\w)',ft):
            names.append(city)
    if not names and paragraphs:
        intro=folded(' '.join(paragraphs[:2])[:390])
        for city in _SPSE_PLACES:
            if re.search(r'\b(?:en|de|localidad de|ciudad de)\s+'+re.escape(folded(city))+r'(?!\w)',intro):
                names.append(city)
    # Avoid a shorter overlapping city if a full official place is named.
    if 'Comandante Luis Piedra Buena' in names and 'Piedra Buena' in names:
        names.remove('Piedra Buena')
    if 'Puerto San Julian' in names and 'San Julian' in names:
        names.remove('San Julian')
    return names[0] if len(set(names))==1 else None


def _spse_article(html,url,now,listed_title,listed_date):
    dom,visible=page(html)
    title=next((h for h in dom.headings if
                (folded(listed_title) in folded(h) or folded(h) in folded(listed_title))
                and len(h)>16),None)
    if not title:return None,'article_title_not_verified'
    if _REGIONAL_FINISHED.search(folded(title)):
        return None,'completed_or_restored_title'
    # The provincial press places the explicit article publication day near
    # the H1, after its deck paragraph. Do not use dates elsewhere in body.
    flat=folded(visible);at=flat.find(folded(title))
    if at<0:return None,'article_title_not_in_visible_text'
    # The article date must occupy its own HTML text element, rather than
    # appearing inside a sentence that announces the DATE OF THE WORK.
    heading_end=re.search(r'</h[123]\s*>',html,re.I)
    if not heading_end:
        return None,'article_publication_date_not_confirmed'
    near_html=html[heading_end.end():heading_end.end()+5000]
    standalone_dates=re.findall(
        r'>\s*(\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?20\d{2})\s*<',
        near_html,re.I)
    article_days=[_spse_date(fragment)[0] for fragment in standalone_dates]
    if listed_date not in article_days:
        return None,'article_publication_date_not_confirmed'
    article_day=listed_date
    if article_day>now.date() or article_day<now.date()-timedelta(days=3):
        return None,'outside_publication_window'
    paragraphs=[p for p in dom.paragraphs if len(p)>35][:16]
    if not paragraphs:return None,'article_body_not_verified'
    locality=_spse_location(title,paragraphs)
    if not locality:return None,'locality_not_explicit_or_ambiguous'
    impact=False
    for para in paragraphs:
        for sentence in re.split(r'(?<=[.!?])\s+',para):
            text=folded(sentence)
            if (_REGIONAL_NEGATIVE.search(text) or _REGIONAL_FINISHED.search(text)
                or _ADC_NO_IMPACT.search(text) or _SPSE_NEGATIVE.search(text)):
                continue
            if _SPSE_WATER_TOPIC.search(text) and _REGIONAL_IMPACT.search(text):
                impact=True;break
        if impact:break
    if not impact:return None,'explicit_potable_water_impact_missing'
    company,province,_=SOURCES[_SPSE_KEY]
    notice=mk_notice(company,province,locality,url,'water_service_bulletin',
                     'publication_only_not_live',' '.join(paragraphs),
                     published_on=article_day.isoformat(),
                     scheduled_start=None,scheduled_end=None)
    return notice,'parsed'


def _collect_spse(checked_at,now,fetch):
    r=_result(_SPSE_KEY,checked_at)
    r.update(parser_revision='SPSE-PROVINCIAL-PRESS-v5.69',
             coverage_kind='official_dated_provincial_spse_bulletins_not_live',
             notices=[],article_links_seen=0,articles_checked=0,
             source_attempts=[],index_attempts=[],articles_deferred_by_budget=0)
    url=r['source_url']
    try:
        selected,stats=_spse_index(fetch(url),url,now)
        r.update(stats);r['article_links_seen']=stats['valid_article_links_seen']
        r['index_attempts'].append({'url':url,'result':'official_index_read',
                                    'valid_article_links_seen':stats['valid_article_links_seen']})
    except Exception as exc:
        e={'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
        if isinstance(exc,HTTPError):e['http_status']=exc.code
        r['index_attempts'].append(e)
        r['message']='No se pudo verificar el índice provincial de SPSE: '+type(exc).__name__
        return r
    for article_url,title,day in selected:
        try:
            n,reason=_spse_article(fetch(article_url),article_url,now,title,day)
            r['articles_checked']+=1
            r['source_attempts'].append({'url':article_url,'result':reason,
                                         'index_published_on':day.isoformat()})
            if n:r['notices'].append(n)
        except Exception as exc:
            e={'url':article_url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):e['http_status']=exc.code
            r['source_attempts'].append(e)
            if isinstance(exc,HTTPError) and exc.code==429:
                r['rate_limited']=True;break
    if r['notices']:
        r['status']='ok'
        r['message']='Comunicados públicos fechados de SPSE, no verificación de cortes en tiempo real.'
    elif r['valid_article_links_seen']==0:
        r['message']='Índice provincial sin enlaces de artículos verificables; cobertura desconocida.'
    elif r['impact_title_candidates_seen']==0:
        r['message']='Índice oficial leído sin titulares recientes de afectación de agua; no implica servicio normal.'
    else:
        r['message']='Sin aviso reciente con fecha, localidad y afectación de agua confirmadas en la publicación.'
    if any(x['result']=='fetch_or_parse_error' for x in r['source_attempts']):
        r['message']+=' Lectura parcial por error de acceso.'
    return r



# v5.71: La Rioja Ministry of Water and Energy public news home.
# Only public articles, never customer-account checks, status APIs, social networks,
# or assumptions about ongoing disruption. An index headline alone is insufficient.
_RIOJA_KEY='la_rioja_ministerio_agua'
_RIOJA_HOST='aguayenergia.larioja.gob.ar'
_RIOJA_LOCATIONS=(
    'Chilecito','Aimogasta','Chamical','Chepes','Olta','Famatina',
    'Villa Union','Villa Castelli','Vinchina',
    'Villa Mazan','Vichigasta','Nonogasta','Patquia','Tama','Ulapes',
    'Milagro','Malanzan','Anillaco','Aminga',
    'La Rioja','Los Molinos','San Pedro','Balde de la Viuda',
    'Punta de los Llanos','Miranda','Guanchin','Chañar','Ambil',
    'Santo Domingo','Bañado de los Pantanos',
    'Guandacol','Los Tres Pozos',
)
_RIOJA_HEADLINE_TOPIC=re.compile(
    r'\b(?:agua|acueducto|suministro|abastecimiento|potabiliz|'
    r'corte|interrupcion|presion|caneria|red hidrica|perforacion|servicio hidrico)')
_RIOJA_WATER_TOPIC=re.compile(
    r'\b(?:agua potable|servicio de agua|suministro de agua|red de agua|'
    r'acueducto|red de distribucion de agua|sistema de agua)')
_RIOJA_IMPACT=re.compile(
    r'\b(?:cortes? (?:programad[oa]s? )?(?:de agua|del (?:servicio|suministro))|'
    r'interrupcion(?:es)? (?:del |de )?(?:servicio|suministro|agua potable)|'
    r'falta de agua|faltante de agua|baja presion|sin suministro|'
    r'sin agua|interrumpira (?:el )?(?:servicio|suministro)|'
    r'(?:servicio|suministro) (?:se vera|esta|se encuentra) afectado|'
    r'se vera afectad[oa] (?:el )?(?:servicio|suministro))\b')
_RIOJA_PREVENTIVE=re.compile(
    r'\b(?:evitar|prevenir|reducir el riesgo de|reducir riesgo de|'
    r'para que no haya|sin generar|sin ocasionar|sin provocar)\b.{0,50}'
    r'(?:cortes?|interrupciones?|falta de agua|baja presion)')
_RIOJA_PUB=re.compile(r'\bfecha de publicacion\s*:?[\s-]*'
                     r'(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b')


def _rioja_story_url(url):
    parts=urlsplit(url)
    return (parts.scheme=='https' and parts.hostname==_RIOJA_HOST
            and parts.username is None and parts.password is None
            and parts.port is None and not parts.query and not parts.fragment
            and re.fullmatch(r'/noticia/[a-z0-9-]{12,160}/?',parts.path) is not None
            and '..' not in parts.path)


def _rioja_index(html,base):
    dom,visible=page(html)
    seen=set();candidates=[];valid=0;topic=0
    for href,title in dom.anchors:
        absolute=urljoin(base,href)
        if not _rioja_story_url(absolute) or absolute in seen:continue
        seen.add(absolute);valid+=1
        label=clean(title,240)
        if len(label)<16 or not _RIOJA_HEADLINE_TOPIC.search(folded(label)):
            continue
        if _REGIONAL_FINISHED.search(folded(label)):continue
        topic+=1;candidates.append((absolute,label))
    return candidates[:3],{
        'html_anchors_seen':len(dom.anchors),
        'html_visible_characters':len(visible),
        'valid_article_links_seen':valid,
        'impact_title_candidates_seen':topic,
        'articles_deferred_by_budget':max(0,len(candidates)-3),
    }


def _rioja_locality(title,paragraphs):
    # The phrase 'Gobierno de La Rioja' names a province, NOT the city.
    title_f=folded(title)
    possibilities=set()
    for loc in _RIOJA_LOCATIONS:
        place=folded(loc)
        if loc=='La Rioja':
            if re.search(r'\b(?:ciudad|capital) de la rioja\b',title_f):
                possibilities.add('La Rioja')
            continue
        if re.search(r'(?<!\w)'+re.escape(place)+r'(?!\w)',title_f):
            possibilities.add(loc)
    if not possibilities:
        first=folded(' '.join(paragraphs[:2])[:440])
        for loc in _RIOJA_LOCATIONS:
            place=folded(loc)
            if loc=='La Rioja':
                if re.search(r'\b(?:ciudad|capital) de la rioja\b',first):
                    possibilities.add('La Rioja')
            elif re.search(r'\b(?:en|de|localidad de|ciudad de)\s+'+re.escape(place)+r'(?!\w)',first):
                possibilities.add(loc)
    return next(iter(possibilities)) if len(possibilities)==1 else None


def _rioja_article(html,url,now,listed_title):
    dom,visible=page(html)
    title=next((h for h in dom.headings if len(h)>16 and
                (folded(listed_title) in folded(h) or folded(h) in folded(listed_title))),None)
    if not title:return None,None,'article_title_not_verified'
    if _REGIONAL_FINISHED.search(folded(title)):
        return None,None,'completed_or_restored_title'
    start=folded(visible).find(folded(title))
    if start<0:return None,None,'article_heading_not_in_visible_text'
    # Restrict publication-day recognition to the article header, explicitly
    # labelled 'Fecha de Publicacion', not an event date in the body.
    head=folded(visible[start+len(title):start+len(title)+800])
    m=_RIOJA_PUB.search(head)
    if not m:return None,None,'publication_date_not_verified'
    try:
        published=date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
    except ValueError:
        return None,None,'publication_date_invalid'
    if published>now.date() or published<now.date()-timedelta(days=3):
        return None,published,'outside_publication_window'
    paragraphs=[p for p in dom.paragraphs if len(p)>35][:16]
    locality=_rioja_locality(title,paragraphs)
    if not locality:return None,published,'locality_not_explicit_or_ambiguous'
    if not paragraphs:return None,published,'no_article_body'
    affirmative=False
    for para in paragraphs:
        for sentence in re.split(r'(?<=[.!?])\s+',para):
            sf=folded(sentence)
            if (_REGIONAL_NEGATIVE.search(sf) or _ADC_NO_IMPACT.search(sf)
                or _RIOJA_PREVENTIVE.search(sf) or _REGIONAL_FINISHED.search(sf)):
                continue
            if _RIOJA_WATER_TOPIC.search(sf) and _RIOJA_IMPACT.search(sf):
                affirmative=True;break
        if affirmative:break
    if not affirmative:return None,published,'no_explicit_water_service_impact'
    company,province,_=SOURCES[_RIOJA_KEY]
    n=mk_notice(company,province,locality,url,
        'water_service_bulletin','publication_only_not_live',' '.join(paragraphs),
        published_on=published.isoformat(),scheduled_start=None,scheduled_end=None)
    return n,published,'parsed'


def _collect_rioja(checked_at,now,fetch):
    r=_result(_RIOJA_KEY,checked_at)
    r.update(parser_revision='LA-RIOJA-OFFICIAL-PUBLIC-NEWS-v5.71',
             coverage_kind='official_dated_ministry_public_news_not_live',
             notices=[],article_links_seen=0,articles_checked=0,
             index_attempts=[],source_attempts=[],articles_deferred_by_budget=0)
    url=r['source_url']
    try:
        selected,stats=_rioja_index(fetch(url),url)
        r.update(stats);r['article_links_seen']=stats['valid_article_links_seen']
        r['index_attempts'].append({'url':url,'result':'official_index_read',
                                    'valid_article_links_seen':stats['valid_article_links_seen']})
    except Exception as exc:
        a={'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
        if isinstance(exc,HTTPError):a['http_status']=exc.code
        r['index_attempts'].append(a)
        r['message']='No se pudo leer la portada oficial de La Rioja: '+type(exc).__name__
        return r
    dates=[]
    for article_url,heading in selected:
        try:
            n,d,reason=_rioja_article(fetch(article_url),article_url,now,heading)
            r['articles_checked']+=1
            a={'url':article_url,'result':reason}
            if d:a['article_published_on']=d.isoformat();dates.append(d)
            r['source_attempts'].append(a)
            if n:r['notices'].append(n)
        except Exception as exc:
            a={'url':article_url,'result':'fetch_or_parse_error','error_type':type(exc).__name__}
            if isinstance(exc,HTTPError):a['http_status']=exc.code
            r['source_attempts'].append(a)
            if isinstance(exc,HTTPError) and exc.code==429:
                r['rate_limited']=True;break
    if r['notices']:
        r['status']='ok'
        r['message']='Publicaciones oficiales fechadas, no verificacion de cortes activos.'
    elif dates and all(d<now.date()-timedelta(days=3) for d in dates):
        r['status']='stale'
        r['message']='Solo publicaciones antiguas en los articulos consultados; estado desconocido.'
    elif not r['valid_article_links_seen']:
        r['message']='La portada no mostro articulos reconocibles; cobertura sin verificar.'
    else:
        r['message']='Portada consultada, sin afectaciones recientes confirmadas por articulos; no implica servicio normal.'
    if any(a['result']=='fetch_or_parse_error' for a in r['source_attempts']):
        r['message']+=' Acceso parcial a noticias.'
    return r

# v5.73: the official Chaco homepage is an observed news index, while /noticias
# reported URLError in GitHub. Read a safe canonical index with one fallback.
# These remain NEWS, not outage-state APIs.
# Most importantly, the CORPICO homepage advertises ELECTRIC interruptions;
# no mixed-service generic heading can create a water notice.
_WATER3_KEYS=frozenset(('sameep_chaco_prensa_gobierno',
                        'gualeguaychu_obras_sanitarias',
                        'corpico_general_pico_agua'))
_WATER3_CHACO_LOCATIONS=(
    'Resistencia','Barranqueras','Fontana','Puerto Vilelas','Colonia Benitez',
    'Puerto Tirol','Presidencia Roque Saenz Pena','Saenz Pena','Villa Angela',
    'Charata','Las Brenas','Quitilipi','Machagai','General San Martin',
    'La Leonesa','Las Palmas','Puerto Bermejo','Presidencia Roca','Pampa del Indio',
    'General Pinedo','Coronel Du Graty','Santa Sylvina','La Tigra','La Clotilde',
    'San Bernardo','Basail','Colonias Unidas','Castelli','Tres Isletas',
    'Juan Jose Castelli','Corzuela','Avia Terai','Napénay','Nap enay',
    'Villa Berthet','Hermoso Campo','Campo Largo','Makalle','Pampa Almiron',
    'Isla del Cerrito','Margarita Belen','Los Frentones','La Escondida',
)
_WATER3_TOPIC=re.compile(
    r'\b(?:agua potable|servicio de agua|suministro de agua|red de agua|'
    r'distribucion de agua|acueducto|planta potabilizadora|bombeo de agua|'
    r'captacion de agua|presion del agua|sistema de abastecimiento de agua)\b')
_WATER3_HEAD=re.compile(
    r'\b(?:falta de agua|baja presion|sin agua|sin suministro|corte|'
    r'interrupcion|suspension|rotura|reparacion|averia|normalizar|'
    r'restablecer|restablecimiento|bombeo|afectacion|cañeria|caneria)\b')
_WATER3_IMPACT=re.compile(
    r'\b(?:faltante de agua|falta de agua|baja presion|presion baja|'
    r'sin agua|sin suministro|corte(?:s)? (?:de agua|del servicio|del suministro)|'
    r'interrupcion(?:es)? (?:del |de )?(?:suministro|servicio|agua potable)|'
    r'suspension (?:del |de )?(?:servicio|suministro)|'
    r'(?:servicio|suministro) (?:se vera|esta|se encuentra|fue) afectado|'
    r'afecta (?:el |al )?(?:servicio|suministro)|'
    r'se interrumpira (?:el )?(?:servicio|suministro)|'
    r'podria(?:n)? (?:registrarse|producirse) (?:baja presion|faltante de agua|falta de agua)|'
    r'(?:reduccion|disminucion) de (?:la )?presion)\b')
_WATER3_NEGATIVE=re.compile(
    r'\b(?:sin afectar|sin interrumpir|no se interrumpira|no se vera afectado|'
    r'no afectara|no se afectara|no registraran|no se registraron|'
    r'no hay cortes|no habra cortes|no habrá cortes|'
    r'no se produjeron cortes|para evitar cortes|'
    r'se normalizo el servicio|servicio restablecido)\b')


def _water3_story_url(key,url):
    try:
        u=urlsplit(url)
        if (u.scheme!='https' or u.username or u.password or u.port is not None
            or u.query or u.fragment or '..' in u.path):return False
        if key=='sameep_chaco_prensa_gobierno':
            return (u.hostname in ('chaco.gob.ar','www.chaco.gob.ar') and
                    re.fullmatch(r'/noticia-[a-z0-9-]{12,210}',u.path) is not None)
        if key=='gualeguaychu_obras_sanitarias':
            return (u.hostname in ('gualeguaychu.gov.ar','www.gualeguaychu.gov.ar',
                                   'ws.gualeguaychu.gov.ar') and
                    (re.fullmatch(r'/redaccion/[a-z0-9-]{14,200}/?',u.path) is not None or
                     re.fullmatch(r'/noticia/[0-9]{3,7}-[a-z0-9-]{12,180}/?',u.path) is not None))
        if key=='corpico_general_pico_agua':
            return (u.hostname in ('corpico.com.ar','www.corpico.com.ar') and
                    re.fullmatch(r'/novedades/[0-9]{2,8}/?',u.path) is not None)
    except ValueError:
        pass
    return False


def _water3_url_day(key,url):
    if key!='sameep_chaco_prensa_gobierno':return None
    m=re.search(r'-(20\d{2})-(\d{2})-(\d{2})-\d{2}-\d{2}/?$',urlsplit(url).path)
    if not m:return None
    try:return date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
    except ValueError:return None


def _water3_explicit_day(fragment):
    d=_regional_index_date(fragment)
    if d:return d
    # The official pages also use month names without 'de', and with a trailing dot.
    text=folded(fragment)
    m=re.search(r'\b(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\.?\s+(20\d{2})\b',text)
    if m:
        try:return date(int(m.group(3)),_REGIONAL_SANTIAGO_MONTHS[m.group(2)],int(m.group(1)))
        except ValueError:return None
    return None


def _water3_index(key,html,url,now):
    dom,visible=page(html)
    seen=set(); items=[];valid=0;impact=0;skipped_old=0
    for href,label in dom.anchors:
        absolute=urljoin(url,href)
        if absolute in seen or not _water3_story_url(key,absolute):continue
        seen.add(absolute);valid+=1
        name=clean(label,240)
        f=folded(name)
        if len(name)<14 or not _WATER3_HEAD.search(f):continue
        # A story headline MUST actually name water service. A generic outage,
        # 'cortes programados' or electric-works reference is not enough.
        if not _WATER3_TOPIC.search(f):continue
        if _WATER3_NEGATIVE.search(f) or _REGIONAL_FINISHED.search(f):continue
        if key=='sameep_chaco_prensa_gobierno' and not re.search(r'\bsameep\b',f):continue
        impact+=1
        url_day=_water3_url_day(key,absolute)
        if url_day and (url_day<now.date()-timedelta(days=3) or url_day>now.date()):
            skipped_old+=1;continue
        items.append((absolute,name,url_day))
    stats={'html_anchors_seen':len(dom.anchors),'html_visible_characters':len(visible),
           'valid_article_links_seen':valid,'impact_title_candidates_seen':impact,
           'headlines_skipped_outside_window':skipped_old,
           'articles_deferred_by_budget':max(0,len(items)-3)}
    return items[:3],stats


def _water3_article_date(key,html,visible,title,listed_day):
    f=folded(visible)
    pos=f.find(folded(title))
    if pos<0:return None
    # Only a date placed as a HEADER immediately before or after the verified
    # title may be a publication date. A work date inside an article paragraph
    # is not a publication date and MUST NOT be promoted to one.
    tail=folded(visible[pos+len(title):pos+len(title)+140])
    day_pattern=(r'(?:\d{1,2}[/-]\d{1,2}[/-]20\d{2}|'
                 r'\d{1,2}\s+(?:de\s+)?[a-z]+\.?\s+(?:de\s+)?20\d{2})')
    label=r'(?:fecha de publicacion|publicado el|publicado|fecha)'
    d=None
    if re.match(r'^\s*(?:'+label+r'\s*:?\s*)?'+day_pattern+r'\b',tail):
        d=_water3_explicit_day(tail[:95])
    if not d:
        before=folded(visible[max(0,pos-100):pos])
        match=re.search(r'('+day_pattern+r')\s*$',before)
        if match:d=_water3_explicit_day(match.group(1))
    if not d:return None
    if listed_day and d!=listed_day:return None
    return d


def _water3_locality(key,title,paragraphs):
    if key=='gualeguaychu_obras_sanitarias':return 'Gualeguaychú'
    if key=='corpico_general_pico_agua':
        z=folded(' '.join([title]+paragraphs[:3]))
        return 'General Pico' if re.search(r'\bgeneral pico\b',z) else None
    f=folded(' '.join([title]+paragraphs[:2])[:650])
    locations=set()
    for loc in _WATER3_CHACO_LOCATIONS:
        if re.search(r'(?<!\w)'+re.escape(folded(loc))+r'(?!\w)',f):locations.add(loc)
    return next(iter(locations)) if len(locations)==1 else None


def _water3_article(key,html,url,now,label,listed_day):
    dom,visible=page(html)
    f_label=folded(label)
    title=next((h for h in dom.headings if len(h)>12 and
                 (folded(h) in f_label or f_label in folded(h)) and
                 len(folded(h))>14),None)
    if not title:return None,None,'article_title_not_confirmed'
    d=_water3_article_date(key,html,visible,title,listed_day)
    if not d:return None,None,'publication_date_not_verified'
    if d>now.date() or d<now.date()-timedelta(days=3):
        return None,d,'outside_publication_window'
    if _REGIONAL_FINISHED.search(folded(title)) or _WATER3_NEGATIVE.search(folded(title)):
        return None,d,'completed_or_negated_headline'
    body=[p for p in dom.paragraphs if len(p)>30][:20]
    if not body:return None,d,'article_body_not_verified'
    locality=_water3_locality(key,title,body)
    if not locality:return None,d,'locality_missing_or_ambiguous'
    impact=False
    for paragraph in body:
        for sentence in re.split(r'(?<=[.!?])\s+',paragraph):
            f=folded(sentence)
            if (_WATER3_NEGATIVE.search(f) or _REGIONAL_NEGATIVE.search(f)
                or _ADC_NO_IMPACT.search(f) or _REGIONAL_FINISHED.search(f)):
                continue
            if _WATER3_TOPIC.search(f) and _WATER3_IMPACT.search(f):
                impact=True;break
        if impact:break
    if not impact:return None,d,'water_service_impact_not_explicit'
    name,province,_=SOURCES[key]
    n=mk_notice(name,province,locality,url,'water_service_bulletin',
                'publication_only_not_live',' '.join(body),
                published_on=d.isoformat(),scheduled_start=None,scheduled_end=None)
    return n,d,'parsed'


def _water3_collect(key,checked_at,now,fetch):
    result=_result(key,checked_at)
    result.update(parser_revision='THREE-REGIONAL-PUBLIC-NEWS-CHACO-INDEX-v5.73',
        coverage_kind='official_dated_public_news_only_not_live',
        notices=[],source_attempts=[],index_attempts=[],article_links_seen=0,
        articles_checked=0,articles_deferred_by_budget=0)
    indices=[result['source_url']]
    if key=='sameep_chaco_prensa_gobierno':
        # The previously configured /noticias route was not readable in Actions.
        # The government homepage is a public dated news index. Alternate host
        # is attempted only if the canonical site fails or has no story links.
        indices.append('https://www.chaco.gob.ar/')
    if key=='gualeguaychu_obras_sanitarias':
        indices.append('https://gualeguaychu.gov.ar/noticias')
    newest=None;selected=[]
    for index_url in indices:
        try:
            items,stats=_water3_index(key,fetch(index_url),index_url,now)
            result.update(stats)
            result['article_links_seen']=stats['valid_article_links_seen']
            result['index_attempts'].append({
                'url':index_url,'result':'official_index_read',
                'valid_article_links_seen':stats['valid_article_links_seen']})
            selected=items
            if items or stats['valid_article_links_seen'] or key not in ('gualeguaychu_obras_sanitarias','sameep_chaco_prensa_gobierno'):
                break
        except Exception as e:
            err={'url':index_url,'result':'fetch_or_parse_error','error_type':type(e).__name__}
            if isinstance(e,HTTPError):err['http_status']=e.code
            result['index_attempts'].append(err)
    if not any(a['result']=='official_index_read' for a in result['index_attempts']):
        result['message']='No se pudo leer índice oficial; suministro desconocido.'
        return result
    for article_url,label,index_day in selected:
        try:
            notice,pub,reason=_water3_article(key,fetch(article_url),article_url,now,label,index_day)
            result['articles_checked']+=1
            result['source_attempts'].append({'url':article_url,'result':reason})
            if pub and (newest is None or pub>newest):newest=pub
            if notice:result['notices'].append(notice)
        except Exception as e:
            result['source_attempts'].append({'url':article_url,'result':'fetch_or_parse_error',
                                              'error_type':type(e).__name__})
    if newest:result['latest_published_date']=newest.isoformat()
    if result['notices']:
        result['status']='ok'
        result['message']='Comunicados públicos fechados; no confirman cortes activos.'
    elif key=='corpico_general_pico_agua':
        result['status']='unverified'
        result['message']=('Noticias oficiales sin afectación reciente verificable de agua. '
                           'Los cortes eléctricos publicados por CORPICO se excluyen; servicio de agua desconocido.')
    else:
        result['status']='unverified'
        result['message']='Sin comunicados recientes de agua suficientemente verificados; servicio desconocido.'
    return result



# v5.75: Public institutional articles are a fallback to a broken legacy
# hostname, NOT live/address-specific interruptions. Article text, locality,
# explicit water impact, and date are required; no user data is queried.
_CBA_KEY='aguas_cordobesas'
_CBA_INDEX_FALLBACK='https://www.aguascordobesas.com.ar/CanalNoticias/HomeNoticias'
_CBA_HOSTS=frozenset(('www.aguascordobesas.com.ar','www.aws.aguascordobesas.com.ar'))
_CBA_TITLE_TOPIC=re.compile(r'\b(?:agua potable|suministro|baja presion|falta de agua|'
    r'interrupcion|corte(?:s)?|reparacion|mantenimiento|cañeria|caneria|'
    r'estacion elevadora|restablecimiento|trabajos|servicio)\b')
_CBA_TITLE_BAD=re.compile(r'\b(?:finalizaron|finalizo|terminaron|culminaron|'
    r'normalizo|normalizacion completa|servicio restablecido|obra inaugurada|'
    r'convenio|tarifa|factura|sustentabilidad|visita|hidratacion)\b')
_CBA_DIRECT_IMPACT=re.compile(r'\b(?:baja presion|falta de agua|sin agua|'
    r'sin suministro|corte(?:s)? de agua|'
    r'(?:interrupcion|suspension) (?:del? )?(?:servicio|suministro)(?: de agua)?|'
    r'(?:servicio|suministro)(?: de agua(?: potable)?)? (?:se encuentra |esta |se vera |fue )?afectado|'
    r'presion del agua (?:se vera |esta )?afectada|'
    r'(?:falta|faltante) (?:de )?(?:suministro|agua))\b')
_CBA_NEGATED=re.compile(r'\b(?:no deberian experimentar inconvenientes|'
    r'no se registraran cortes|no se registrara falta de agua|no hay interrupcion|'
    r'no se interrumpira|sin cortes|sin interrupcion|sin afectar|no afectara|'
    r'no se vera afectado|no se vera interrumpido|no hay corte|'
    r'se normalizo|ya fue restablecido|se encuentra normalizado|'
    r'para evitar cortes)\b')


def _cba_article_url(url):
    """Accept first-party dated article routes only, never generic links."""
    try:
        u=urlsplit(url)
        if (u.scheme!='https' or u.hostname not in _CBA_HOSTS or
                u.username or u.password or u.port is not None or
                u.query or u.fragment or '..' in u.path):return False
        # Official site uses two independent publication sections:
        # /CanalNoticias/DetalleNoticia/<id>/<slug> and
        # /CanalSaladePrensa/DetalleComunicado/<id>/<slug>.
        # Never follow arbitrary routes, queries, or offsite URLs.
        return re.fullmatch(
            r'/(?:CanalNoticias/DetalleNoticia|CanalSaladePrensa/DetalleComunicado)/'
            r'\d{1,6}/[a-z0-9-]{5,210}/?',u.path,re.I) is not None
    except ValueError:
        return False


def _cba_resolve_article_href(href,base):
    """Canonicalize only first-party news/press routes from official indices.

    The public site emits links like 'CanalSaladePrensa/DetalleComunicado/ID/slug'
    *without* an initial slash, despite a nested HomeSalaPrensa/ page URL.
    urljoin(base, href) would incorrectly put the HomeSalaPrensa directory in
    front of the real article route. Reject traversal, foreign hosts, userinfo,
    non-HTTPS, queries, fragments and arbitrary paths even after resolution.
    """
    raw=str(href or '').strip()
    if not raw or '..' in raw or '\\' in raw:return None
    try:
        source=urlsplit(base)
        if (source.scheme!='https' or source.hostname not in _CBA_HOSTS or
                source.username or source.password or source.port is not None):
            return None
        if re.match(r'^(?:CanalSaladePrensa/DetalleComunicado|CanalNoticias/DetalleNoticia)/',raw,re.I):
            resolved=urljoin('https://'+source.netloc+'/',raw)
        else:
            resolved=urljoin(base,raw)
        return resolved if _cba_article_url(resolved) else None
    except ValueError:
        return None


def _cba_index(html,base,now):
    dom,visible=page(html)
    discovered=[];seen=set();candidates=[];old=0;filtered=0;relative_fixed=0
    for href,label in dom.anchors:
        url=_cba_resolve_article_href(href,base)
        if not url or url in seen:continue
        if re.match(r'^(?:CanalSaladePrensa/DetalleComunicado|CanalNoticias/DetalleNoticia)/',str(href).strip(),re.I):
            relative_fixed+=1
        seen.add(url);discovered.append(url)
        slug=folded(urlsplit(url).path.split('/')[-1].replace('-',' '))
        title=folded(label) if len(label)>=15 else slug
        if _CBA_TITLE_BAD.search(title) or _CBA_TITLE_BAD.search(slug):
            filtered+=1;continue
        if not _CBA_TITLE_TOPIC.search(title+' '+slug):continue
        # A date embedded in the URL is a *recency screening hint only*,
        # NEVER proof of publication date or of service interruption.
        md=re.search(r'(\d{1,2})-(\d{1,2})-(20\d{2})',urlsplit(url).path)
        if md:
            try:
                maybe=date(int(md.group(3)),int(md.group(2)),int(md.group(1)))
            except ValueError:
                maybe=None
            if maybe and (maybe<now.date()-timedelta(days=3) or maybe>now.date()):
                old+=1;continue
        candidates.append(url)
    press_links=sum('/CanalSaladePrensa/DetalleComunicado/' in url for url in discovered)
    news_links=sum('/CanalNoticias/DetalleNoticia/' in url for url in discovered)
    return candidates[:3],{'html_anchors_seen':len(dom.anchors),
        'press_article_links_seen':press_links,'news_article_links_seen':news_links,
        'relative_article_links_fixed':relative_fixed,
        'html_visible_characters':len(visible),'valid_article_links_seen':len(discovered),
        'article_candidates_before_budget':len(candidates),'articles_deferred_by_budget':max(0,len(candidates)-3),
        'articles_skipped_dated_slug':old,'articles_skipped_completed_title':filtered}


def _cba_publication_date(html,dom,visible,title):
    """Publication marker must be in article header, not event text/body."""
    meta=_published_date_from_meta(html)
    if meta:return meta
    txt=folded(visible);head=folded(title)
    # The public page repeats its article title in the HTML <title> (which
    # VisiblePage sees) and in the actual article heading. Looking only at
    # txt.find(head) can select the document-title copy BEFORE the official
    # date and discard an otherwise explicitly dated article. Inspect every
    # occurrence, nearest to the article heading first. Dates in the title,
    # URL slug, unrelated cards, or article body are NEVER evidence by themselves.
    positions=[m.start() for m in re.finditer(re.escape(head),txt)] if head else []
    expr=r'(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](20\d{2})(?!\d)'
    for pos in reversed(positions):
        before=txt[max(0,pos-160):pos]
        # Official template: "Comunicado de prensa 20/11/2026" or
        # "Servicio 20/11/2026" directly precedes the article H1.
        # Allow a standalone DD/MM/YYYY preceding H1 (older official layout),
        # but do not scan any date far into the preceding article body.
        m=re.search(expr+r'\s*$',before)
        if not m:
            continue
        prefix=before[:m.start()]
        # A date directly before H1 is credible only with a header label,
        # or as a separate date element very close to the H1, never a date
        # from a paragraph about works/events.
        labeled=bool(re.search(r'(?:comunicado de prensa|servicio|publicado el|fecha(?: de publicacion)?\s*:)\s*$',prefix))
        nearby=bool(re.search(r'\b(?:comunicado de prensa|servicio)\b',prefix[-85:]))
        last_context=prefix[max(0,len(prefix)-60):]
        event=bool(re.search(r'\b(?:trabajos?|reparacion|corte|inicio|estimad|previst|normalizacion|desde|hasta)\b',last_context))
        if labeled or (nearby and not event):
            try:return date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
            except ValueError:continue
    # An older official template uses a bare date in its own <div> (or
    # <time>) immediately before the article H1. This is distinct from a
    # paragraph describing WHEN an event happened: never mine <p> dates.
    header_html=re.compile(
        r'<(?:div|time)\b[^>]*>\s*'
        r'(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\s*'
        r'</(?:div|time)>\s*<h1\b[^>]*>\s*([^<]{10,250})\s*</h1>',re.I)
    for m in header_html.finditer(html):
        if folded(clean(m.group(4)))!=head:
            continue
        try:return date(int(m.group(3)),int(m.group(2)),int(m.group(1)))
        except ValueError:continue
    return None


def _cba_article(html,url,now):
    dom,visible=page(html)
    slug=folded(urlsplit(url).path.split('/')[-1].replace('-',' '))
    heads=[h for h in dom.headings if len(h)>=18 and
           len(set(re.findall(r'[a-z]{4,}',folded(h))) & set(re.findall(r'[a-z]{4,}',slug)))>=2]
    if not heads:return None,None,'article_heading_not_confirmed'
    title=heads[0]
    if _CBA_TITLE_BAD.search(folded(title)) or _REGIONAL_FINISHED.search(folded(title)):
        return None,None,'completed_or_institutional_title'
    published=_cba_publication_date(html,dom,visible,title)
    if not published:return None,None,'publication_date_not_verified'
    if published<now.date()-timedelta(days=3) or published>now.date():
        return None,published,'outside_publication_window'
    paras=[p for p in dom.paragraphs if len(p)>32][:20]
    if not paras:return None,published,'body_missing'
    # Service-provider scope is Córdoba CITY, not province-wide.
    # Headline must mention a bounded service area (barrio, named street)
    # or explicit 'Ciudad de Córdoba'. Never infer a province-wide event.
    evidence=folded(' '.join([title]+paras[:3])[:900])
    area=re.search(r'\b(?:barrio|b°|av\.|avenida|calle|bv\.|boulevard|'
                   r'ciudad de cordoba)\s+[a-z0-9]+',evidence)
    if not area:return None,published,'service_area_not_precise'
    impacted=False
    for para in paras:
        sent=re.split(r'(?<=[.!?])\s+',para)
        for i,sentence in enumerate(sent):
            f=folded(sentence)
            if (_CBA_NEGATED.search(f) or _ADC_NO_IMPACT.search(f) or
                    _REGIONAL_NEGATIVE.search(f) or _REGIONAL_FINISHED.search(f)):
                continue
            if not _CBA_DIRECT_IMPACT.search(f):continue
            context=f+' '+(folded(sent[i-1]) if i else '')
            if re.search(r'\b(?:agua|suministro|servicio|red|presion)\b',context):
                impacted=True;break
        if impacted:break
    if not impacted:return None,published,'no_explicit_water_service_interruption'
    name,province,_=SOURCES[_CBA_KEY]
    item=mk_notice(name,province,'Córdoba',url,'water_service_bulletin',
        'publication_only_not_live',' '.join(paras),
        published_on=published.isoformat(),scheduled_start=None,scheduled_end=None,
        coverage_kind='official_dated_public_water_bulletin_not_live')
    return item,published,'parsed'


def _collect_cba(checked_at,now,fetch):
    r=_result(_CBA_KEY,checked_at)
    r.update(parser_revision='CBA-ARTICLE-HEADER-PUBLISHED-DATE-v5.78',
        coverage_kind='official_dated_public_water_bulletins_not_live',
        notices=[],article_links_seen=0,articles_checked=0,
        source_attempts=[],index_attempts=[],articles_deferred_by_budget=0,
        account_lookup_required_for_address=True)
    candidates=[];index_read=False;index_stats=[]
    for url in (r['source_url'],_CBA_INDEX_FALLBACK):
        try:
            selected,stats=_cba_index(fetch(url),url,now)
            index_read=True;candidates=selected;index_stats.append(stats);r.update(stats)
            r['article_links_seen']=stats['valid_article_links_seen']
            r['index_attempts'].append({'url':url,'result':'official_index_read',
                'valid_article_links_seen':stats['valid_article_links_seen']})
            # A valid archive link is not evidence of a current service notice.
            # On a page with no candidates, consult the other official index.
            if selected:break
        except Exception as e:
            d={'url':url,'result':'fetch_or_parse_error','error_type':type(e).__name__}
            if isinstance(e,HTTPError):d['http_status']=e.code
            r['index_attempts'].append(d)
            if isinstance(e,HTTPError) and e.code in (403,429):
                r['message']='Portal oficial rechazó la consulta (HTTP %s); suministro desconocido.'%e.code
                return r
    if not index_read:
        r['message']='No se pudo leer la prensa oficial de Aguas Cordobesas; suministro desconocido.'
        return r
    # The fallback index must not erase a successfully read first index:
    # report the total public links examined, including both official pages.
    for key in ('html_anchors_seen','html_visible_characters',
                'valid_article_links_seen','press_article_links_seen',
                'news_article_links_seen','relative_article_links_fixed',
                'article_candidates_before_budget',
                'articles_deferred_by_budget','articles_skipped_dated_slug',
                'articles_skipped_completed_title'):
        r[key]=sum(stats.get(key,0) for stats in index_stats)
    r['article_links_seen']=r['valid_article_links_seen']
    pubs=[]
    for url in candidates:
        try:
            notice,day,reason=_cba_article(fetch(url),url,now)
            r['articles_checked']+=1
            r['source_attempts'].append({'url':url,'result':reason})
            if day:pubs.append(day)
            if notice:r['notices'].append(notice)
        except Exception as e:
            d={'url':url,'result':'fetch_or_parse_error','error_type':type(e).__name__}
            if isinstance(e,HTTPError):d['http_status']=e.code
            r['source_attempts'].append(d)
            if isinstance(e,HTTPError) and e.code==429:break
    if pubs:r['latest_published_date']=max(pubs).isoformat()
    if r['notices']:
        r['status']='ok';r['message']='Comunicados oficiales fechados; no acreditan cortes activos.'
    elif r['article_links_seen']==0:
        r['message']='Índice consultado sin enlaces de noticias reconocibles; suministro desconocido.'
    else:
        r['message']='Índice oficial consultado sin afectación reciente y verificada del agua; no implica suministro normal.'
    return r

def collect_one(key,checked_at,fetcher=None):
    if key not in SOURCES:
        raise KeyError(key)
    now=checked_instant(checked_at)
    fetch=fetcher or fetch_html
    if key==_CBA_KEY:return _collect_cba(checked_at,now,fetch)
    if key==_ADC_KEY:return _collect_adc(checked_at,now,fetch)
    if key==_OSSE_SJ_KEY:return _collect_osse_sj(checked_at,now,fetch)
    if key==_SPSE_KEY:return _collect_spse(checked_at,now,fetch)
    if key==_RIOJA_KEY:return _collect_rioja(checked_at,now,fetch)
    if key in _WATER3_KEYS:return _water3_collect(key,checked_at,now,fetch)
    if key in _PUBLIC_NEWS_HOSTS:return _collect_public_news(key,checked_at,now,fetch)
    if key=='dposs_tierra_del_fuego_reparaciones':return _collect_dposs(checked_at,now,fetch)
    if key=='absa_buenos_aires':return _collect_absa(checked_at,now,fetch)
    if key=='aysam_mendoza':return _collect_aysam(checked_at,now,fetch)
    if key=='aguas_del_norte_salta':return _collect_salta(checked_at,now,fetch)
    if key=='aguas_rionegrinas_arsa':return _collect_arsa(checked_at,now,fetch)
    if key=='aguas_catamarca':return _collect_catamarca(checked_at,now,fetch)
    if key=='aysa_amba':return _collect_aysa(checked_at,now,fetch)
    if key=='aysa_public_bulletins_amba':return _collect_aysa_public(checked_at,now,fetch)
    if key=='sameep_chaco':return _collect_sameep(checked_at,now,fetch)
    if key=='edos_concordia':return _collect_edos(checked_at,now,fetch)
    if key=='osse_mar_del_plata':return _collect_osse(checked_at,now,fetch)
    if key=='samsa_misiones':return _collect_samsa(checked_at,now,fetch)
    if key=='agua_potable_jujuy_prensa':return _collect_jujuy(checked_at,now,fetch)
    if key=='scpl_comodoro_chubut':return _collect_scpl(checked_at,now,fetch)
    if key=='epas_neuquen_noticias':return _collect_epas(checked_at,now,fetch)
    if key in _MUNICIPAL_RSS_HOSTS:
        return _collect_municipal_rss(key,checked_at,now,fetch)
    if key in ('sat_tucuman_noticias','aguas_santiago_novedades'):
        return _collect_regional_news(key,checked_at,now,fetch)
    return _collect_diagnostic(key,checked_at,now,fetch)



# v5.80: Technical reachability is NOT public-service coverage. These
# diagnostics make it possible to tell apart a site rejecting every request,
# a readable site with no qualifying bulletin, and an accepted public notice.
# The schema is additive and does not change notifications or individual notices.
_INDEX_READ_RESULTS=frozenset((
    'official_index_read','rss_parsed','article_links_found',
    'official_news_index_read','structured_records_read','index_read',
    'no_recent_water_headlines','page_read','official_html_read',
))


def source_health_summary(results):
    """Summarize observed retrieval evidence, never infer live water supply."""
    if not isinstance(results,dict):
        raise TypeError('sources debe ser un diccionario')
    counts={'ok':0,'stale':0,'unverified':0}
    with_notices=[]
    readable_no_notices=[]
    rejected_http_403=[]
    all_url_errors=[]
    account_only=[]
    unresolved=[]
    budget_exhausted=[]
    for key,r in results.items():
        status=r.get('status','unverified')
        counts[status]=counts.get(status,0)+1
        news=r.get('notices') or []
        if news:with_notices.append(key)
        attempts=[]
        for name in ('index_attempts','fallback_index_attempts','source_attempts'):
            for entry in r.get(name,[]) or []:
                if isinstance(entry,dict):attempts.append(entry)
        index_attempts=[entry for name in ('index_attempts','fallback_index_attempts')
            for entry in (r.get(name,[]) or []) if isinstance(entry,dict)]
        failed_403=(bool(index_attempts) and all(
            a.get('result')=='fetch_or_parse_error' and a.get('http_status')==403
            for a in index_attempts))
        if failed_403:rejected_http_403.append(key)
        failed_url=(bool(index_attempts) and all(
            a.get('result')=='fetch_or_parse_error' and a.get('error_type')=='URLError'
            for a in index_attempts))
        if failed_url:all_url_errors.append(key)
        private_lookup=(r.get('access_mode')=='account_required' or
            r.get('coverage_kind')=='address_account_lookup_only')
        if private_lookup:account_only.append(key)
        if ('SourceFetchBudgetExceeded' in str(r.get('message','')) or
            any(a.get('error_type') == 'SourceFetchBudgetExceeded' for a in attempts)):
            budget_exhausted.append(key)
        readable=(not private_lookup and (status in ('ok','stale') or
            r.get('page_read') is True or
            (isinstance(r.get('article_links_seen'),int) and r['article_links_seen']>0) or
            (isinstance(r.get('articles_checked'),int) and r['articles_checked']>0) or
            any(a.get('result') in _INDEX_READ_RESULTS for a in index_attempts) or
            any(a.get('result')=='page_read' for a in attempts)))
        if readable and not news:readable_no_notices.append(key)
        if status=='unverified' and not readable and not private_lookup and not news:
            unresolved.append(key)
    accepted=sum(len(r.get('notices') or []) for r in results.values())
    return {
        'configured_sources':len(results),
        'status_counts':counts,
        'sources_with_accepted_bulletins':with_notices,
        'accepted_public_bulletins':accepted,
        'readable_sources_without_accepted_bulletins':readable_no_notices,
        'all_index_requests_rejected_http_403':rejected_http_403,
        'all_index_requests_failed_url_error':all_url_errors,
        'account_only_sources_without_public_status':account_only,
        'source_query_budget_exhausted':budget_exhausted,
        'unverified_without_readable_index':unresolved,
        'interpretation':'Public official bulletins only. Reachability, status OK, or absence of notices does not confirm live water service or comprehensive geographic coverage.'
    }

def collect_water(checked_at,fetcher=None):
    checked_instant(checked_at)

    def safe_one(key, source_fetcher):
        try:
            return collect_one(key, checked_at, fetcher=source_fetcher)
        except Exception as exc:
            result = _result(key, checked_at)
            result['message'] = 'Fallo aislado: ' + type(exc).__name__
            return result

    if fetcher is not None:
        # Deterministic offline tests and injected fetchers retain the previous
        # sequential behavior. Never start threads for a caller's mock.
        out = {key: safe_one(key, fetcher) for key in SOURCES}
    else:
        # Independent sources can run concurrently; within each source the
        # requests remain serialized, preserving rate-limit protection.
        def production_one(key):
            limited = _budgeted_fetcher(fetch_html)
            # ARSA keeps its inter-request pause despite the budget wrapper.
            limited._production_network_fetch = True
            return safe_one(key, limited)

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SOURCES,
                                thread_name_prefix='water-source') as executor:
            pending = {key: executor.submit(production_one, key) for key in SOURCES}
            # Preserve stable, predictable source and notice ordering even if
            # some providers respond slower than others.
            out = {key: pending[key].result() for key in SOURCES}
    notices=[]
    for key in SOURCES:
        notices.extend(out[key]['notices'])
    notices.sort(key=lambda x:(x.get('scheduled_date') or x.get('published_on') or '',x['id']))
    return {'schema_version':1,'generated_at':checked_at,
            'status':'pilot_read_only_in_android',
            'category':'agua','country':'Argentina',
            'coverage_kind':'public_official_notices_not_live_state',
            'notifications_enabled':False,'android_display_enabled':False,
            'android_read_only_pilot_available':True,
            'message':'Comunicados públicos disponibles en Android v5.39+ como lectura piloto. Notificaciones automáticas de agua desactivadas.',
            'sources':out,'notices':notices,
            'source_health':source_health_summary(out)}
