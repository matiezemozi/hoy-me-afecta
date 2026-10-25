# HOY ME AFECTA V4: fuentes y estados (24/10/2026)

| Categoría | Alcance actual | Fuente de referencia |
|--|--|--|
| Electricidad | Obtención automática ENRE (piloto AMBA, no garantiza cobertura de cada domicilio) | https://www.enre.gov.ar/paginacorte/ |
| Colectivos | Sin conexión automática de llegadas. Avisos manuales fechados, si existen | https://www.argentina.gob.ar/sube/cuandosubo |
| Trenes | Sin API automática comprobada; acceso a app oficial, soporte de avisos manuales | https://www.argentina.gob.ar/transporte/trenes-argentinos/app |
| Bancos | Calendario de feriados 2026 como referencia estática al 24/10/2026; no se verifica disponibilidad de sucursales/cajeros | https://www.bcra.gob.ar/consulta-feriados-bancarios-2026/ |
| Agua | Sin conector automático; soporte para avisos públicos manualmente verificados | https://www.aysa.com.ar/ |
| Tránsito | Sin conector automático; soporte para avisos públicos manualmente verificados | https://buenosaires.gob.ar/ |
| Operativos públicos | ÚNICAMENTE impacto civil oficialmente publicado: cortes de calles, desvíos, accesos restringidos, eventos masivos | https://buenosaires.gob.ar/ |

## Importación de avisos públicos

El archivo `manual/avisos_publicos.json` es inicialmente `[]`. Solo un revisor humano
puede agregar un aviso verificado, con estos campos:

- `category`: `tren`, `agua`, `transito`, `banco` o `operativo_publico`
- `country`: `Argentina`
- `partido` o `localidad`: al menos uno, y exactamente como se identificarán las zonas
- `title`, `description`: resumen factual de la comunicación, sin extrapolar
- `source_url`: URL https del organismo oficial; para bancos se aceptan dominios
  oficiales BNA y Banco Provincia, además de los dominios gubernamentales
- `verified_at`, `ends_at`: ISO 8601 con zona horaria, por ejemplo terminación `Z`
- `starts_at`: opcional, ISO 8601 con zona horaria; no más de 7 días en el futuro
- `line`: obligatorio para avisos de tren
- `impact_type`: obligatorio para `operativo_publico`, limitado a
  `corte_de_calle`, `desvio`, `acceso_restringido`, `evento_publico`

El recopilador admite únicamente verificaciones realizadas en las últimas 24 horas,
no incluye avisos vencidos y no presenta los eventos como posiciones ni información
en vivo. NO utilice un título inventado para simular disponibilidad.

Para operativos policiales no se publicarán posiciones de agentes/patrullas,
ubicaciones de controles, controles de alcoholemia móviles, rutas de despliegue ni
horarios tácticos; solo consecuencias públicas oficiales para el desplazamiento.

## Actualización del calendario bancario

La publicación consultada el 24/10/2026 enumera feriados bancarios en 2026;
`backend/bank_calendar.py` la transcribe como referencia con fecha de revisión.
No hay conexión automática que detecte sus correcciones futuras. Cuando cambie el
año o el BCRA publique modificaciones, el equipo debe revisar ese módulo.
