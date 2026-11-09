"""Offline fixtures for EPEN's public RSS + official scheduled-work posts.

Fixtures approximate the verified November 2026 articles without copying their
long-form copyrighted text. No outbound request or user information is used.
"""
import unittest
from html import escape
from provincial_outages import (
    PROVIDERS, EPEN_RSS, EPEN_ARCHIVE, _epen_feed_items, _epen_archive_items,
    _parse_epen_article,
    _instant, collect_one, collect_provincial,
)

CHECKED = '2026-11-07T18:00:00Z'  # Saturday 15:00 Argentina
PREFIX = 'https://www.epen.gov.ar/index.php/2026/11/06/'
SINGLE = PREFIX + 'corte-programado-en-sectores-de-villa-la-angostura-el-10-11-26/'
NORTH = PREFIX + 'corte-programado-en-la-zona-norte-el-11-11-26/'
WRONG = PREFIX + 'corte-programado-en-sectores-de-la-zona-norte-el-13-11-26/'

BODY_SINGLE = ('<html><body><h1>Corte programado en sectores de Villa La Angostura el 10/11/26</h1>'
               '<p>El Ente Provincial de Energía del Neuquén (EPEN) informa que se realizará '
               'un corte programado el martes 10 de noviembre, de 9 a 14 horas, para '
               'efectuar trabajos a pedido de terceros.</p><p>Afecta: Puerto Manzano y '
               'Península de Puerto Manzano.</p><p>Se solicita tomar recaudos.</p>'
               '<div>Últimas Noticias: Cortes 7 de septiembre de otro año</div></body></html>')
BODY_NORTH = ('<p>El Ente Provincial de Energía del Neuquén (EPEN) informa '
              'que se realizará un corte programado el miércoles 11 de noviembre '
              'de 13 a 19 horas para realizar mantenimiento en redes.</p>'
              '<p>Afecta: Chos Malal, Andacollo, Huinganco, Los Miches, '
              'Las Ovejas, Varvarco, Manzano Amargo y todos los parajes de la zona.</p>'
              '<p>A partir de la reserva fría, algunas localidades mantendrán '
              'servicios esenciales.</p>')
BODY_WRONG = ('<p>El Ente Provincial de Energía del Neuquén (EPEN) informa '
              'un corte programado el lunes 7 de septiembre de 9 a 13 horas.</p>'
              '<p>Afecta: Desde Picada 04 hasta Picada 01.</p>')


def rss(rows):
    entries = []
    for title, link, content in rows:
        entries.append('<item><title>' + escape(title) + '</title><link>' +
                       escape(link) + '</link><content:encoded><![CDATA[' +
                       content + ']]></content:encoded></item>')
    return ('<?xml version="1.0"?><rss version="2.0" '
            'xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            '<channel><title>EPEN</title>' + ''.join(entries) + '</channel></rss>')


T_SINGLE = 'Corte programado en sectores de Villa La Angostura el 10/11/26'
T_NORTH = 'Corte programado en la zona Norte el 11/11/26'
T_WRONG = 'Corte programado en sectores de la zona Norte el 13/11/26'


class EPENTests(unittest.TestCase):
    def test_accept_single_locality_and_multiple_explicit_north_towns(self):
        data = rss([(T_SINGLE, SINGLE, BODY_SINGLE), (T_NORTH, NORTH, BODY_NORTH),
                    (T_WRONG, WRONG, BODY_WRONG)])
        got = collect_one('epen_neuquen', CHECKED, fetcher=lambda _: data)
        self.assertIn('epen_neuquen', PROVIDERS)
        self.assertEqual(got['status'], 'ok')
        self.assertEqual(got['company'], 'EPEN')
        self.assertEqual(got['province'], 'Neuquén')
        self.assertEqual(got['records_checked'], 2)
        self.assertEqual(got['rejected_article_count'], 1)
        names = {n['locality_hint'] for n in got['notices']}
        self.assertEqual(names, {'Villa La Angostura', 'Chos Malal', 'Andacollo',
                                 'Huinganco', 'Los Miches', 'Las Ovejas',
                                 'Varvarco', 'Manzano Amargo'})
        self.assertEqual(next(n for n in got['notices'] if n['locality_hint'] ==
                              'Villa La Angostura')['scheduled_start'], '2026-11-10T09:00-03:00')
        self.assertEqual(next(n for n in got['notices'] if n['locality_hint'] ==
                              'Andacollo')['scheduled_end'], '2026-11-11T19:00-03:00')
        self.assertTrue(all(n['status'] == 'scheduled_not_confirmed' for n in got['notices']))
        self.assertTrue(all(n['kind'] == 'planned_electricity_work' for n in got['notices']))
        self.assertTrue(all(n['source_url'] in (SINGLE, NORTH) for n in got['notices']))
        self.assertNotIn(WRONG, str(got['notices']))

    def test_explicit_body_date_mismatch_rejected(self):
        bad = _parse_epen_article(T_WRONG, WRONG, BODY_WRONG, _instant(CHECKED))
        self.assertEqual(bad, [])
        got = collect_one('epen_neuquen', CHECKED,
                          fetcher=lambda _: rss([(T_WRONG, WRONG, BODY_WRONG)]))
        self.assertEqual(got['status'], 'unverified')
        self.assertEqual(got['notices'], [])

    def test_no_leak_from_other_posts_or_nonexistent_location(self):
        result = _parse_epen_article(T_SINGLE, SINGLE, BODY_SINGLE, _instant(CHECKED))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['locality_hint'], 'Villa La Angostura')
        self.assertNotIn('septiembre', str(result))
        region_without_towns = BODY_NORTH.replace('Chos Malal, Andacollo, Huinganco, Los Miches, '
                                                  'Las Ovejas, Varvarco, Manzano Amargo',
                                                  'las áreas comprendidas entre rutas provinciales')
        self.assertEqual(_parse_epen_article(T_NORTH, NORTH, region_without_towns,
                                             _instant(CHECKED)), [])

    def test_conflicting_or_invalid_windows_rejected(self):
        odd = BODY_SINGLE.replace('de 9 a 14 horas', 'de 9 a 14 horas y de 15 a 17 horas')
        self.assertEqual(_parse_epen_article(T_SINGLE, SINGLE, odd, _instant(CHECKED)), [])
        self.assertEqual(_parse_epen_article(T_SINGLE, SINGLE,
                          BODY_SINGLE.replace('de 9 a 14 horas', 'de 20 a 8 horas'),
                          _instant(CHECKED)), [])

    def test_article_fetch_fallback_when_rss_description_incomplete(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if url == EPEN_RSS:
                return rss([(T_SINGLE, SINGLE, '<p>Aviso reciente.</p>')])
            if url == SINGLE:
                return BODY_SINGLE
            raise AssertionError('Unexpected URL ' + url)
        got = collect_one('epen_neuquen', CHECKED, fetcher=fetch)
        self.assertEqual(got['status'], 'ok')
        self.assertEqual(len(got['notices']), 1)
        self.assertEqual(calls, [EPEN_RSS, SINGLE])
        self.assertEqual(got['source_attempts'][0]['extra_article_fetches'], 1)


    def test_archive_fallback_when_rss_has_no_relevant_posts(self):
        archive = ('<html><article><h2 class="entry-title"><a href="' + SINGLE +
                   '">' + T_SINGLE + '</a></h2></article>'
                   '<article><h2><a href="' + WRONG + '">' + T_WRONG +
                   '</a></h2></article></html>')
        calls = []
        def fetch(url):
            calls.append(url)
            if url == EPEN_RSS:
                return rss([])
            if url == EPEN_ARCHIVE:
                return archive
            if url == SINGLE:
                return BODY_SINGLE
            if url == WRONG:
                return BODY_WRONG
            raise AssertionError('Unexpected URL ' + url)
        got = collect_one('epen_neuquen', CHECKED, fetcher=fetch)
        self.assertEqual(got['status'], 'ok')
        self.assertEqual(got['records_checked'], 1)
        self.assertEqual(got['rejected_article_count'], 1)
        self.assertEqual(len(got['notices']), 1)
        self.assertNotIn(WRONG, str(got['notices']))
        self.assertEqual(calls, [EPEN_RSS, EPEN_ARCHIVE, SINGLE, WRONG])
        self.assertEqual(got['source_attempts'][1]['posts_verified'], 1)
        self.assertEqual(got['parser_revision'], 'EPEN-RSS-ARCHIVE-v5.22.2')

    def test_archive_accepts_official_link_with_read_more_label(self):
        # Real-world archive pages often put the headline outside <a> and link
        # via a generic 'Leer más' control. v5.22.1 returned zero candidates.
        page = ('<article><h2>' + T_SINGLE + '</h2>'
                '<a href="' + SINGLE + '">Leer más</a></article>')
        entries = _epen_archive_items(page)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1], SINGLE)
        self.assertTrue(entries[0][0].endswith('el 10/11/26'))
        self.assertNotIn('Leer más', entries[0][0])

    def test_archive_can_use_data_url_on_card(self):
        page = ('<article data-url="' + NORTH + '"><h2>' + T_NORTH
                + '</h2></article>')
        self.assertEqual(_epen_archive_items(page)[0][1], NORTH)

    def test_archive_embedded_link_fallback_still_needs_article(self):
        page = '<article><script>var next="' + SINGLE + '";</script></article>'
        self.assertEqual(_epen_archive_items(page)[0][1], SINGLE)
        calls = []
        def fetch(url):
            calls.append(url)
            if url == EPEN_RSS:
                return rss([])
            if url == EPEN_ARCHIVE:
                return page
            if url == SINGLE:
                return BODY_SINGLE
            raise AssertionError('Unexpected URL: ' + url)
        result = collect_one('epen_neuquen', CHECKED, fetcher=fetch)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['notices'][0]['locality_hint'].casefold(),
                         'villa la angostura')
        self.assertEqual(result['source_attempts'][1]['candidate_posts'], 1)

    def test_official_slug_and_label_conflicting_dates_are_rejected(self):
        page = '<a href="' + SINGLE + '">' + T_WRONG + '</a>'
        self.assertEqual(_epen_archive_items(page), [])

    def test_archive_rejects_external_links_and_plaintext(self):
        fake = ('<a href="https://malicious.invalid/index.php/2026/11/06/example/">'
                + T_SINGLE + '</a>'
                '<a href="/index.php/2026/11/06/corte-programado-en-sectores-de-villa-la-angostura-el-10-11-26/">'
                + T_SINGLE + '</a>')
        self.assertEqual(len(_epen_archive_items(fake)), 1)
        self.assertEqual(_epen_archive_items('No hay avisos'), [])

    def test_archive_fallback_rejects_title_body_date_mismatch(self):
        archive = '<a href="' + WRONG + '">' + T_WRONG + '</a>'
        got = collect_one('epen_neuquen', CHECKED, fetcher=lambda url:
                          rss([]) if url == EPEN_RSS else
                          archive if url == EPEN_ARCHIVE else BODY_WRONG)
        self.assertEqual(got['status'], 'unverified')
        self.assertEqual(got['notices'], [])

    def test_reject_external_url_rss_and_missing_data(self):
        spoof = rss([(T_SINGLE, 'https://hostile.example/2026/11/06/example/', BODY_SINGLE)])
        self.assertEqual(_epen_feed_items(spoof), [])
        got = collect_one('epen_neuquen', CHECKED, fetcher=lambda _: spoof)
        self.assertEqual(got['status'], 'unverified')
        self.assertEqual(got['notices'], [])
        error = collect_one('epen_neuquen', CHECKED,
                            fetcher=lambda _: (_ for _ in ()).throw(ConnectionError('offline')))
        self.assertEqual(error['status'], 'unverified')
        self.assertNotIn('offline', str(error))

    def test_epens_failure_cannot_disrupt_other_provinces(self):
        def fetch(url):
            if url == EPEN_RSS:
                return rss([(T_SINGLE, SINGLE, BODY_SINGLE)])
            raise ConnectionError('Unavailable')
        got = collect_provincial(CHECKED, fetcher=fetch)
        self.assertEqual(set(got), set(PROVIDERS))
        self.assertEqual(got['epen_neuquen']['status'], 'ok')
        for key in got:
            if key != 'epen_neuquen':
                self.assertNotEqual(got[key]['status'], 'ok')

    def test_expired_posts_not_exposed_as_current(self):
        expired = collect_one('epen_neuquen', '2026-11-15T18:00:00Z',
                              fetcher=lambda _: rss([(T_SINGLE, SINGLE, BODY_SINGLE)]))
        self.assertEqual(expired['notices'], [])
        self.assertNotEqual(expired['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
