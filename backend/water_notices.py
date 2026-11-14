"""Conservative public water-service bulletin collectors for Argentina (v5.36).

No report is a live outage confirmation. No credentials, service identifiers or
unofficial APIs are used. Completely independent of provincial_electricity.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import calendar
import re

ART = timezone(timedelta(hours=-3))
HORIZON_DAYS = 14
MAX_PAGE_BYTES = 1_500_000
SOURCES = {
    'absa_buenos_aires': ('ABSA', 'Buenos Aires', 'https://www.aguasbonaerenses.com.ar/noticias/'),
    'aguas_del_norte_salta': ('Aguas del Norte', 'Salta', 'https://www.aguasdelnortesalta.com.ar/cortes.php'),
    'aysam_mendoza': ('AYSAM', 'Mendoza', 'https://aysam.com.ar/cortes/'),
    'aguas_cordobesas': ('Aguas Cordobesas', 'Córdoba', 'https://www.aws.aguascordobesas.com.ar/CanalNoticias/NoticiasCategoria/2/servicio'),
    'aguas_santafesinas': ('Aguas Santafesinas', 'Santa Fe', 'https://www.aguassantafesinas.com.ar/portal/noticias'),
    'aguas_rionegrinas_arsa': ('Aguas Rionegrinas', 'Río Negro', 'https://aguasrionegrinas.com/category/interrupciones/'),
    'aguas_catamarca': ('Aguas de Catamarca SAPEM', 'Catamarca', 'https://www.adcsapem.com.ar/?page_id=240'),
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
    req = Request(url, headers={'User-Agent':'HoyMeAfecta/5.36 (public notice reader)',
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
    if folded(locality)=='patagones' and 'carmen de patagones' in f:
        locality='Carmen de Patagones'
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
                zone=re.split(re.escape(opening),content,maxsplit=1,flags=re.I)[1].lstrip(' ,;:')
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
        r'planta potabilizadora|sistema de bombeo|cisterna|sistema de abastecimiento',
        folded(text)))


def _arsa_explicit_service_impact(text):
    """Require an actual, localized service impact, not routine maintenance."""
    return bool(re.search(
        r'\b(?:baja presion|falta de (?:suministro|agua)|afectad[oa]|afectar|'
        r'interrumpir|interrupcion|turbiedad|turbidez|corte de agua|'
        r'corte del suministro|afecta (?:a los barrios|a las zonas|el suministro|el servicio))\b',
        folded(text)))


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
        if not _arsa_water_topic(paragraphs):return 'water_topic_not_identified'
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
        # Do not borrow a date from a preceding, different article.
        if re.search(r'\b[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ ]{3,45}:',excerpt):
            continue
        date_parts=re.findall(r'\b\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s*,?\s*(?:de\s+)?20\d{2}\b',folded(excerpt))
        if date_parts:
            return _parse_official_day(date_parts[-1])
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
    if not _arsa_water_topic(content):
        return [],published
    if re.search(r'oficina|atencion al publico|factura|cobranz',folded(title)):
        return [],published
    if re.search(r'finalizaron|normalizad[oa]|restablecido|concluyeron',folded(title)):
        return [],published
    # A generic announcement about works is not evidence of affected supply.
    if not _arsa_explicit_service_impact(content):
        return [],published
    scheduled=None
    for p in paragraphs:
        d=_weekday_date(p,published)
        if d and now.date()<=d<=now.date()+timedelta(days=HORIZON_DAYS):
            scheduled=d
            break
    title_fold=folded(title)
    future_verb=bool(re.search(r'se realizaran|se llevaran adelante|se preve|realizara|tareas programadas|trabajos programados|esta previsto',f+' '+title_fold))
    # Past-tense completed/same-day works are publication-only, not plans.
    if scheduled and future_verb and not re.search(r'inicio trabajos|iniciaron los trabajos|tareas comenzaron',title_fold):
        times=_arsa_times_from_dated_paragraphs(paragraphs,published,scheduled)
        return [mk_notice('Aguas Rionegrinas','Río Negro',locality,url,
                  'planned_water_service_impact','scheduled_not_confirmed',content,
                  published_on=published.isoformat(),scheduled_date=scheduled.isoformat(),
                  **times)],published
    return [mk_notice('Aguas Rionegrinas','Río Negro',locality,url,
                      'water_service_bulletin','publication_only_not_live',content,
                      published_on=published.isoformat(),scheduled_start=None,scheduled_end=None)],published


def _collect_arsa(checked_at,now,fetch):
    result=_result('aguas_rionegrinas_arsa',checked_at)
    result['parser_revision']='ARSA-ARTICLES-v5.36'
    url=result['source_url']
    seen=[];attempts=[];checked=0;newest=None
    try:
        dom,index_visible=page(fetch(url))
        links=[]
        link_dates={}
        for href,label in dom.anchors:
            link=urljoin(url,href)
            parsed=urlsplit(link)
            # Only real articles in the official interruption-category index.
            if parsed.hostname not in ('aguasrionegrinas.com','www.aguasrionegrinas.com'):
                continue
            if not re.fullmatch(r'/[a-z0-9-]{20,}/?',parsed.path):
                continue
            if ':' not in label or len(label)<25 or link in links:
                continue
            links.append(link)
            link_dates[link]=_arsa_index_date(index_visible,label)
        result['article_links_seen']=len(links)
        for link in links[:9]:
            checked+=1
            try:
                transient_retry=False
                try:
                    article_html=fetch(link)
                except HTTPError as http_exc:
                    # Retry ONCE only for transient status codes. A permanent
                    # 403/404 is not retried or silently treated as no incident.
                    if http_exc.code not in (429,500,502,503,504):
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
    except Exception as exc:
        attempts.append({'url':url,'result':'fetch_or_parse_error','error_type':type(exc).__name__})
    result['source_attempts']=attempts
    result['articles_checked']=checked
    result['records_checked']=checked
    result['notices']=list({n['id']:n for n in seen}.values())
    if newest:
        result['latest_published_date']=newest.isoformat()
    if result['notices']:
        result.update(status='ok',message='Comunicados de ARSA fechados; no confirman la situación en tiempo real.')
    elif newest and newest<now.date()-timedelta(days=2):
        result.update(status='stale',message='Solo publicaciones antiguas verificables.')
    else:
        blocked=sum(1 for a in attempts if a.get('result')=='fetch_or_parse_error')
        result['message']='No se recuperaron artículos recientes con localidad y afectación verificables.'
        if blocked:
            result['message']+=f' {blocked} artículo(s) no pudieron consultarse; no implica servicio normal.'
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


def collect_one(key,checked_at,fetcher=None):
    if key not in SOURCES:
        raise KeyError(key)
    now=checked_instant(checked_at)
    fetch=fetcher or fetch_html
    if key=='absa_buenos_aires':return _collect_absa(checked_at,now,fetch)
    if key=='aysam_mendoza':return _collect_aysam(checked_at,now,fetch)
    if key=='aguas_del_norte_salta':return _collect_salta(checked_at,now,fetch)
    if key=='aguas_rionegrinas_arsa':return _collect_arsa(checked_at,now,fetch)
    if key=='aguas_catamarca':return _collect_catamarca(checked_at,now,fetch)
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
