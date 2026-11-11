"""Conservative public water-service bulletin collectors for Argentina (v5.32).

No report is a live outage confirmation. No credentials, service identifiers or
unofficial APIs are used. Completely independent of provincial_electricity.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import calendar
import re

ART = timezone(timedelta(hours=-3))
HORIZON_DAYS = 14
MAX_PAGE_BYTES = 1_500_000
SOURCES = {
    'absa_buenos_aires': ('ABSA', 'Buenos Aires', 'https://www.aguasbonaerenses.com.ar/noticias/'),
    'aguas_del_norte_salta': ('Aguas del Norte', 'Salta', 'https://www.aguasdelnortesalta.com.ar/cortes.php'),
    'aysam_mendoza': ('AYSAM', 'Mendoza', 'https://www.aysam.com.ar/cortes/index.html'),
    'aguas_cordobesas': ('Aguas Cordobesas', 'Córdoba', 'https://www.aws.aguascordobesas.com.ar/CanalNoticias/NoticiasCategoria/2/servicio'),
    'aguas_santafesinas': ('Aguas Santafesinas', 'Santa Fe', 'https://www.aguassantafesinas.com.ar/portal/noticias'),
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
    req = Request(url, headers={'User-Agent':'HoyMeAfecta/5.32 (public notice reader)',
                                'Accept':'text/html,application/xhtml+xml'})
    with urlopen(req, timeout=13) as response:
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


def mk_notice(company, province, locality, url, kind, status, zone, **kwargs):
    key='|'.join([company,locality,url,kind,str(kwargs.get('scheduled_date') or kwargs.get('published_on'))])
    item={'id':'agua-'+sha256(key.encode('utf-8')).hexdigest()[:18],
          'category':'agua','country':'Argentina','province':province,'company':company,
          'kind':kind,'status':status,'locality_hint':clean(locality,100),
          'zone_detail':clean(zone,530),'source_url':url,
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
    if published<now.date()-timedelta(days=2):
        return [],published
    content=clean(' '.join(p for p in dom.paragraphs if len(p)>=45),2800)
    content=content.split('Relacionado')[0]
    f=folded(title+' '+content)
    if not re.search(r'agua|suministro|presion|acueducto|caneria|red',f):
        return [],published
    if re.search(r'\bfinalizaron|\bnormalizad[oa]|\bse restablecio|\bconcluyeron',folded(title)):
        return [],published
    locality=clean(title.split(':')[0],90)
    notices=[]
    # Published schedules without an explicit finish time MUST keep an unknown end.
    future_day=None
    for p in dom.paragraphs:
        d=_weekday_date(p,published)
        if d is not None and now.date()<=d<=now.date()+timedelta(days=HORIZON_DAYS):
            future_day=d
            break
    if (future_day is not None and re.search(r'programad|se realizaran trabajos|se preve[n ]',f)
            and re.search(r'afectara|afectar|interrumpir|faltante|interrupcion|suministro',f)):
        parts=[]
        if 'general daniel cerri' in f and 'bahia blanca' in folded(title):
            parts=[('General Daniel Cerri', 'En General Daniel Cerri', 'En tanto'),
                   ('Bahía Blanca', 'En tanto', 'Por esta razón')]
        else:
            parts=[(locality,None,None)]
        for loc,opening,closing in parts:
            zone=content
            if opening and opening.lower() in content.lower():
                zone=re.split(re.escape(opening),content,maxsplit=1,flags=re.I)[1]
                if closing and re.search(re.escape(closing),zone,re.I):
                    zone=re.split(re.escape(closing),zone,maxsplit=1,flags=re.I)[0]
            if not zone.strip():
                continue
            start=None
            time_precision='date_only'
            # Only a time attached to this locality, not a date in the shared intro.
            time_match=re.search(r'\bdesde\s+las\s+(\d{1,2})(?::(\d{2}))?\b',folded(zone))
            if time_match:
                hour=int(time_match.group(1));minute=int(time_match.group(2) or 0)
                if hour<24 and minute<60:
                    start=datetime(future_day.year,future_day.month,future_day.day,hour,minute,tzinfo=ART).isoformat(timespec='minutes')
                    time_precision='start_known_end_unknown'
            notices.append(mk_notice('ABSA','Buenos Aires',loc,url,'planned_water_service_impact',
                                     'scheduled_not_confirmed',zone,scheduled_date=future_day.isoformat(),
                                     scheduled_start=start,scheduled_end=None,time_precision=time_precision,
                                     published_on=published.isoformat()))
    elif re.search(r'\b(se estan registrando|se registra|afecta el suministro|afectando|falta[s]? de agua|baja presion)\b',f):
        # Recent news is not evidence that the problem remains ongoing.
        notices.append(mk_notice('ABSA','Buenos Aires',locality,url,'water_service_bulletin',
                                  'publication_only_not_live',content,published_on=published.isoformat(),
                                  scheduled_start=None,scheduled_end=None))
    return notices,published


def _collect_absa(checked_at,now,fetch):
    company,province,url=SOURCES['absa_buenos_aires']
    base=_result('absa_buenos_aires',checked_at)
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
            'notifications_enabled':False,'parser_revision':'WATER-v5.32',
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
    url=result['source_url']
    try:
        notices,checked,newest=_parse_aysam(fetch(url),now,url)
        result['records_checked']=checked
        if newest:
            result['latest_published_date']=newest.isoformat()
        if notices:
            result.update(status='ok',notices=notices,
                          message='Interrupciones PROGRAMADAS con zona, fecha y horas verificadas en tabla oficial.')
        elif newest and newest<now.date()-timedelta(days=2):
            result.update(status='stale',message='La tabla contiene solo cortes antiguos; no implica servicio normal.')
        else:
            result['message']='La tabla no presenta interrupciones programadas futuras completas verificables.'
    except Exception as exc:
        result['message']='No se pudo verificar tabla: '+type(exc).__name__
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


def collect_one(key,checked_at,fetcher=None):
    if key not in SOURCES:
        raise KeyError(key)
    now=checked_instant(checked_at)
    fetch=fetcher or fetch_html
    if key=='absa_buenos_aires':return _collect_absa(checked_at,now,fetch)
    if key=='aysam_mendoza':return _collect_aysam(checked_at,now,fetch)
    if key=='aguas_del_norte_salta':return _collect_salta(checked_at,now,fetch)
    return _collect_diagnostic(key,checked_at,now,fetch)


def collect_water(checked_at,fetcher=None):
    checked_instant(checked_at)
    out={}
    for key in SOURCES:
        try:
            out[key]=collect_one(key,checked_at,fetcher=fetcher)
        except Exception as exc:
            out[key]=_result(key,checked_at)
            out[key]['message']='Fallo aislado: '+type(exc).__name__
    notices=[]
    for key in SOURCES:
        notices.extend(out[key]['notices'])
    notices.sort(key=lambda x:(x.get('scheduled_date') or x.get('published_on') or '',x['id']))
    return {'schema_version':1,'generated_at':checked_at,
            'status':'pilot_not_integrated_in_android',
            'category':'agua','country':'Argentina',
            'coverage_kind':'public_official_notices_not_live_state',
            'notifications_enabled':False,'android_display_enabled':False,
            'message':'Fuentes públicas de agua. Sin notificaciones hasta validación y nueva APK.',
            'sources':out,'notices':notices}
