# HOY ME AFECTA - piloto tecnico 0.1

**Estado real del proyecto:** prototipo de Android + recolector experimental. NO es una app de emergencias y NO tiene integracion automatica verificada con la linea 57. No se han comprobado peticiones en vivo desde el entorno de desarrollo. Evitar interpretar ausencia de avisos como normalidad.

## Que incluye
- App Android en Java, sin Android Studio, creada para compilar en GitHub Actions.
- Zona personal por municipio/localidad y campo para el ramal de la linea 57.
- Lectura del archivo JSON generado por el propio repositorio desde GitHub.
- Recopilador Python de archivos de cortes de ENRE Edenor/Edesur, cuyos endpoints son **no documentados** y pueden cambiar. Al fallar, deja visible el error.
- Fuente oficial para consultar llegadas de colectivos mediante Cuándo SUBO (abre navegador).
- Plantilla opcional para avisos documentados y cargados manualmente de la linea 57. Sin avisos reales predefinidos.
- Pruebas unitarias con datos simulados. No valida acceso en produccion.

## Publicar en GitHub (interfaz web, sin Android Studio)
1. Crear un **repositorio publico nuevo**, por ejemplo `hoy-me-afecta`, con rama principal `main`.
2. Descomprimir el ZIP en Windows. Abrir la carpeta `hoy_me_afecta_v1` descomprimida y **arrastrar todos sus archivos y carpetas** al formulario `Add file > Upload files` de GitHub. No subir el propio archivo ZIP ni solo los archivos sueltos. Revisar que aparezcan `app`, `backend`, `docs`, `manual` y `.github`. En algunas versiones de Windows, `.github` puede aparecer oculta: hay que asegurarse de subirla.
3. Confirmar la subida con `Commit changes`.
4. En `Actions` ejecutar `Actualizar datos HOY ME AFECTA` con `Run workflow`. Si el repositorio es nuevo, puede requerir habilitar Actions.
5. Revisar `docs/feed.json` en `Code`: `generated_at` debe tener fecha reciente y las fuentes deben indicar `ok` o un error explícito. **No confundir `error` con ausencia de cortes**. El ENRE puede rechazar accesos, cambiar nombres de variables o retirar endpoints. Si todas las fuentes fallan, el piloto no entrega cortes verificados.
6. En `Actions`, ejecutar `Compilar APK HOY ME AFECTA` mediante `Run workflow`. Cuando finalice, descargar el artifact `hoy-me-afecta-piloto-apk`, descomprimirlo e instalar `app-debug.apk` en Android.
7. Al iniciar la app, poner el repositorio publico en formato `USUARIO/hoy-me-afecta` y la localidad que se desea seguir, y pulsar `Guardar y actualizar`.

> El workflow de actualizacion intenta ejecutarse cada hora, pero GitHub puede retrasar o suspender las tareas programadas, especialmente en repositorios poco activos. Por eso la app comprueba la antiguedad del informe y se niega a llamarlo vigente si supera 3 horas.

## Integracion de la linea 57

La linea 57 esta incorporada como favorita y con opcion de seleccionar ramal. La primera version NO usa ubicacion GPS en vivo, demoras estimadas ni tiempos de arribo porque todavia no se verifico una API autorizada para extraerlos. Se ofrece el enlace a Cuándo SUBO y avisos manuales documentados.

Si se verifica una fuente con derechos de reutilizacion, sera posible sumar un conector que cree avisos con `category=colectivo`, `line=57`, `branch`, `observed_at`, `valid_until`, `source_url`.

Para introducir **avisos manuales autenticos**, editar `manual/linea57_alertas.json` como lista de objetos con:
```
{
  "line": "57", "branch": "Q", "title": "...", "description": "...",
  "source_url": "https://...", "verified_at": "2026-10-19T19:00:00Z",
  "ends_at": "2026-10-19T21:00:00Z"
}
```
Estas fechas son SOLO un ejemplo de formato, no un aviso real. No ingresar fechas o cambios inventados. No se muestran avisos vencidos, sin fuente HTTPS, o con verificacion de mas de 24 horas.

## Datos tecnicos
- Kotlin NO requerido: Java 17, Gradle 8.7, Android Gradle Plugin 8.6.1, compileSDK 35, minSDK 23.
- El APK es de depuracion: es util para pruebas, no para publicar en Play Store.
- No se recopila ubicacion precisa y no hay notificaciones automaticas aun.
- No se tiene un servidor propio permanente: el almacenamiento es `docs/feed.json` del mismo repositorio.
- Requiere internet en el celular y un repositorio publico. Los usuarios finales no deberian introducir nombres de repositorios; esta configuracion es temporal para las pruebas.
- El sistema del ENRE reporta el estado publicado por empresas distribuidoras, que no necesariamente refleja cada domicilio o interrupcion aun no reportada.

## Referencias
- ENRE Edenor: https://www.enre.gov.ar/paginacorte/tabla_cortes_edenor.html
- ENRE Edesur: https://www.enre.gov.ar/paginacorte/tabla_cortes_edesur.html
- Cuándo SUBO: https://www.argentina.gob.ar/sube/cuandosubo
- API transporte CABA con limitaciones actuales: https://data.buenosaires.gob.ar/es/dataset/api-transporte-publico
