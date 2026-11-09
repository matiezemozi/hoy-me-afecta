package ar.com.hoymeafecta;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.Manifest;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.Normalizer;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

public class MainActivity extends Activity {
    // Pilot feed: later replaced by the central, country-independent service.
    private static final int NOTIFY_PERMISSION_REQUEST = 115;
    private static final String FEED_URL =
            "https://raw.githubusercontent.com/matiezemozi/hoy-me-afecta/main/docs/feed.json";
    private static final long MAX_FEED_AGE_MS = 3L * 60 * 60 * 1000;
    private static final int INK = Color.rgb(29, 43, 62);
    private static final int BLUE = Color.rgb(27, 92, 160);
    private static final int LIGHT = Color.rgb(245, 247, 251);
    private static final int GREY = Color.rgb(93, 107, 125);
    private static final String[] COUNTRIES = {
            "Argentina", "Bolivia", "Chile", "Colombia", "Costa Rica", "Cuba",
            "Ecuador", "El Salvador", "Guatemala", "Honduras", "México",
            "Nicaragua", "Panamá", "Paraguay", "Perú", "Puerto Rico",
            "República Dominicana", "Uruguay", "Venezuela"
    };
    // A hidden section affects presentation only, never notification subscriptions.
    // Every section is visible by default when upgrading from v5.5.
    private static final String[] SECTION_KEYS = {
            "historial", "informe", "electricidad", "colectivos", "subtes", "trenes",
            "bancos", "operativos", "agua", "transito", "fuentes"
    };
    private static final String[] SECTION_LABELS = {
            "Mis avisos", "Tu informe personal", "Electricidad", "Colectivos", "Subtes",
            "Trenes", "Bancos", "Operativos públicos", "Agua",
            "Tránsito y vías públicas", "Información y fuentes"
    };
    private LinearLayout root;
    private EditText placeField, lineField, branchField, trainField;
    private Spinner countrySpinner;
    private SharedPreferences prefs;
    private JSONObject feed;
    private String connection = "Sin datos descargados todavía";
    private boolean refreshing = false;
    private boolean historyScreen = false;
    private long historyDetailId = -1L;
    private boolean detailChecking = false;
    private String detailNetworkMessage = "";
    private JSONObject detailNetworkFeed = null;
    private long detailNetworkFeedRecordId = -1L;
    private int historyDisplayed = 25;
    private int historyScrollPosition = 0;
    private ScrollView mainScroll;
    private final Map<String, View> sectionAnchors = new HashMap<>();

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("hoy_me_afecta", MODE_PRIVATE);
        // Honor an overdue archive-clear preference even if Android deferred jobs.
        try { HistoryCleanup.runIfDue(this); }
        catch (RuntimeException ignored) { /* Preserve app startup if storage is unavailable. */ }
        HistoryCleanup.scheduleIfNeeded(this);
        AlertCheckJobService.scheduleIfNeeded(this);
        // Show the last downloaded report immediately, even without a network.
        // Its age and each source's age are still checked before showing incidents.
        try {
            String cached = prefs.getString("cached_feed", "");
            if (!cached.isEmpty() && cached.length() < 2_000_000) {
                JSONObject previous = new JSONObject(cached);
                if (previous.optInt("schema_version") == 1) feed = previous;
            }
        } catch (Exception ignored) { feed = null; }
        if (feed != null) connection = "Último informe guardado; comprobando actualización…";
        draw();
        refresh();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private GradientDrawable background(int color, int radius) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radius));
        return shape;
    }

    private TextView text(String label, int size, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextSize(size);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        t.setPadding(0, dp(3), 0, dp(3));
        return t;
    }

    private LinearLayout card() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(16), dp(13), dp(16), dp(13));
        c.setBackground(background(Color.WHITE, 14));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, 0, 0, dp(12));
        root.addView(c, lp);
        return c;
    }

    private Button button(String label, Runnable action) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setBackground(background(BLUE, 10));
        b.setPadding(dp(12), dp(6), dp(12), dp(6));
        b.setOnClickListener(v -> action.run());
        return b;
    }

    private EditText edit(String label, String value) {
        EditText e = new EditText(this);
        e.setSingleLine(true);
        e.setTextSize(15);
        e.setTextColor(INK);
        e.setHint(label);
        e.setText(value);
        return e;
    }

    private void title(String label) {
        title(label, null);
    }

    /** Register the real heading so personal-report rows can scroll to it. */
    private void title(String label, String sectionKey) {
        TextView heading = text(label, 19, INK, true);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(15), 0, dp(9));
        root.addView(heading, lp);
        if (sectionKey != null) sectionAnchors.put(sectionKey, heading);
    }

    /** Keep navigation inside the existing page: no new screen or feed fetch. */
    private void jumpToSection(String key) {
        final ScrollView scroll = mainScroll;
        final View heading = sectionAnchors.get(key);
        if (scroll == null || heading == null) return;
        scroll.post(() -> {
            if (mainScroll == scroll && sectionAnchors.get(key) == heading) {
                scroll.smoothScrollTo(0, Math.max(0, heading.getTop() - dp(12)));
            }
        });
    }

    /** Each summary entry is itself a large, accessible touch target. */
    private void reportLink(LinearLayout parent, String key,
                            String heading, String detail) {
        LinearLayout tile = new LinearLayout(this);
        tile.setOrientation(LinearLayout.VERTICAL);
        tile.setPadding(dp(12), dp(10), dp(12), dp(10));
        tile.setBackground(background(Color.rgb(235, 243, 252), 10));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(6), 0, dp(4));
        parent.addView(tile, lp);
        tile.addView(text(heading + "  ›", 15, BLUE, true));
        tile.addView(text(detail, 13, INK, false));
        tile.setOnClickListener(v -> jumpToSection(key));
        tile.setClickable(true);
        tile.setFocusable(true);
        tile.setContentDescription(heading + ". " + detail + ". Abrir sección.");
    }

    private String selectedCountry() {
        return prefs.getString("country", "Argentina");
    }

    private boolean sectionVisible(String key) {
        return prefs.getBoolean("section_visible_" + key, true);
    }

    private void chooseVisibleSections() {
        final boolean[] choices = new boolean[SECTION_KEYS.length];
        for (int i = 0; i < SECTION_KEYS.length; i++) {
            choices[i] = sectionVisible(SECTION_KEYS[i]);
        }
        new AlertDialog.Builder(this)
                .setTitle("Personalizar secciones")
                .setMultiChoiceItems(SECTION_LABELS, choices,
                        (dialog, index, checked) -> choices[index] = checked)
                .setPositiveButton("Guardar", (dialog, which) -> {
                    SharedPreferences.Editor edit = prefs.edit();
                    for (int i = 0; i < SECTION_KEYS.length; i++) {
                        edit.putBoolean("section_visible_" + SECTION_KEYS[i], choices[i]);
                    }
                    edit.apply();
                    draw();
                })
                .setNeutralButton("Mostrar todas", (dialog, which) -> {
                    SharedPreferences.Editor edit = prefs.edit();
                    for (String key : SECTION_KEYS) {
                        edit.putBoolean("section_visible_" + key, true);
                    }
                    edit.apply();
                    draw();
                })
                .setNegativeButton("Cancelar", (dialog, which) -> { })
                .show();
    }

    private int visibleSectionCount() {
        int visible = 0;
        for (String key : SECTION_KEYS) {
            if (sectionVisible(key)) visible++;
        }
        return visible;
    }

    private void draw() {
        if (historyScreen) {
            if (historyDetailId > 0) drawHistoryDetail();
            else drawHistory();
            return;
        }
        ScrollView scroll = new ScrollView(this);
        // Save the main scroll and rebuild anchors after each feed refresh.
        final int previousScroll = mainScroll == null ? 0 : mainScroll.getScrollY();
        mainScroll = scroll;
        sectionAnchors.clear();
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(LIGHT);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(20), dp(20), dp(28));
        scroll.addView(root);
        setContentView(scroll);

        root.addView(text("HOY ME AFECTA", 26, INK, true));
        root.addView(text("Lo que te conviene saber antes de salir", 14, GREY, false));
        root.addView(text("Piloto v5.23 · Nuevas fuentes provinciales y resumen navegable", 12, GREY, false));
        LinearLayout status = card();
        status.addView(text(connection, 14, BLUE, false));
        if (feed != null) {
            status.addView(text("Última recopilación: " + formatUtc(feed.optString("generated_at", "")),
                    12, GREY, false));
        }
        if (refreshing) status.addView(text("Descargando el informe...", 13, GREY, false));
        status.addView(button("Actualizar ahora", this::refresh));

        // Put relevant information before configuration and unconnected categories.
        if (sectionVisible("informe")) {
            title("Tu informe personal", "informe");
            personalReport();
        }

        title("Personalizar pantalla");
        LinearLayout displaySettings = card();
        displaySettings.addView(text("Secciones visibles: " + visibleSectionCount() +
                " de " + SECTION_KEYS.length + ". Elegí qué servicios querés ver.",
                13, GREY, false));
        displaySettings.addView(button("Configurar secciones", this::chooseVisibleSections));
        displaySettings.addView(text("Ocultar una sección no desactiva las notificaciones ni " +
                "modifica las fuentes. Los controles de avisos permanecen accesibles.",
                12, GREY, false));

        title("Tus preferencias");
        LinearLayout setup = card();
        setup.addView(text("País", 13, GREY, true));
        countrySpinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, COUNTRIES);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        countrySpinner.setAdapter(adapter);
        String savedCountry = selectedCountry();
        for (int i = 0; i < COUNTRIES.length; i++) {
            if (COUNTRIES[i].equals(savedCountry)) { countrySpinner.setSelection(i); break; }
        }
        setup.addView(countrySpinner);
        setup.addView(text("Zonas de interés (separadas por punto y coma)", 13, GREY, true));
        placeField = edit("Ejemplo: Pilar; Recoleta", prefs.getString("place", ""));
        setup.addView(placeField);
        setup.addView(text("Línea de colectivo favorita (piloto argentino)", 13, GREY, true));
        lineField = edit("Ejemplo: 57", prefs.getString("line", "57"));
        setup.addView(lineField);
        setup.addView(text("Ramal (opcional)", 13, GREY, true));
        branchField = edit("Ejemplo: Q", prefs.getString("branch", ""));
        setup.addView(branchField);
        setup.addView(text("Tren habitual (opcional)", 13, GREY, true));
        trainField = edit("Ejemplo: Sarmiento, Mitre, San Martín", prefs.getString("train", ""));
        setup.addView(trainField);
        setup.addView(text("No se necesita GPS. La cobertura se ampliará progresivamente.",
                12, GREY, false));
        setup.addView(button("Guardar y actualizar", () -> {
            String country = String.valueOf(countrySpinner.getSelectedItem());
            prefs.edit().putString("country", country)
                    .putString("place", placeField.getText().toString().trim())
                    .putString("line", lineField.getText().toString().trim())
                    .putString("branch", branchField.getText().toString().trim())
                    .putString("train", trainField.getText().toString().trim())
                    .apply();
            if (prefs.getBoolean("notifications_enabled", false)) {
                if (!"Argentina".equals(country) ||
                        prefs.getString("place", "").trim().isEmpty()) {
                    prefs.edit().putBoolean("notifications_enabled", false).apply();
                    AlertCheckJobService.cancel(this);
                } else {
                    // New areas need a quiet baseline, not old publications.
                    prefs.edit().putBoolean("notification_primed", false)
                            .remove("notification_seen_ids").apply();
                    AlertCheckJobService.scheduleIfNeeded(this);
                }
            }
            draw();
            refresh();
        }));

        title("Notificaciones (prueba)");
        notificationSettings();
        if (sectionVisible("historial")) {
            title("Mis avisos", "historial");
            historySummary();
        }
        if (sectionVisible("electricidad")) {
            title("Electricidad · fuentes oficiales", "electricidad");
            electricity();
        }
        if (sectionVisible("colectivos")) {
            title("Transporte · colectivos", "colectivos");
            buses();
        }
        if (sectionVisible("subtes")) {
            title("Subtes · Ciudad de Buenos Aires", "subtes");
            subtes();
        }
        if (sectionVisible("trenes")) {
            title("Trenes", "trenes");
            trainNotices();
        }
        if (sectionVisible("bancos")) {
            title("Bancos · atención presencial", "bancos");
            banks();
        }
        if (sectionVisible("operativos")) {
            title("Operativos públicos · impacto en la circulación", "operativos");
            publicCategory("operativo_publico", "Avisos de accesos y circulación", "Solo se muestran efectos anunciados oficialmente sobre la circulación o eventos públicos. No se muestran ubicaciones de controles ni despliegues policiales.",
                    "Consultar seguridad y tránsito CABA", "https://buenosaires.gob.ar/");
        }
        if (sectionVisible("agua")) {
            title("Agua", "agua");
            publicCategory("agua", "Interrupciones del suministro", "Todavía no existe un conector automático verificado para el servicio de agua.",
                    "Consultar AySA", "https://www.aysa.com.ar/");
        }
        if (sectionVisible("transito")) {
            title("Tránsito y vías públicas", "transito");
            publicCategory("transito", "Cortes, obras y desvíos", "Aún no hay un conector automático verificado para cortes de tránsito.",
                    "Consultar BA Cómo Llego", "https://mapa.buenosaires.gob.ar/");
        }
        if (sectionVisible("fuentes")) {
            title("Información y fuentes", "fuentes");
            LinearLayout notes = card();
            notes.addView(text("Fuentes: ENRE para Edenor y Edesur. Estado de subtes en prueba mediante " +
                    "una página pública de CABA, solo cuando tiene fecha verificable y reciente. " +
                    "Los comunicados ferroviarios fechados no equivalen a estado en vivo. " +
                    "No hay conexión automática verificada para la línea 57.", 13, GREY, false));
            notes.addView(text("Un aviso publicado se refiere a un área; no confirma el estado de " +
                    "cada domicilio. Ausencia de avisos no equivale a servicio normal.", 13, GREY, false));
            notes.addView(text("El informe y cada fuente eléctrica deben tener menos de " +
                    "3 horas para mostrar avisos como recientes. La aplicación no sustituye las alertas oficiales.",
                    13, GREY, false));
            notes.addView(text("Bancos: calendario nacional del BCRA consultado automáticamente; " +
                    "no indica si las sucursales están abiertas. " +
                    "Trenes: novedades oficiales fechadas sin estado en vivo. " +
                    "Agua, tránsito y operativos: sin conexión automática verificada.",
                    12, GREY, false));
            notes.addView(text("Las zonas se comparan por nombre exacto con partido o localidad. " +
                    "No se comprueba si un corte alcanza una dirección específica.", 12, GREY, false));
            provincialSourcesSummary(notes);
        }
        if (previousScroll > 0) {
            scroll.post(() -> {
                if (mainScroll == scroll) scroll.scrollTo(0, previousScroll);
            });
        }
    }

    private void historySummary() {
        LinearLayout c = card();
        long total = -1;
        try (NotificationHistory history = new NotificationHistory(this)) {
            total = history.count();
            c.addView(text(total == 0 ? "Todavía no hay avisos guardados." :
                    "Avisos guardados en este teléfono: " + total, 14, INK, true));
            c.addView(text("Borrado automático: " +
                    HistoryCleanup.label(HistoryCleanup.frequency(this)), 13, BLUE, true));
            c.addView(text(HistoryCleanup.description(this), 12, GREY, false));
        } catch (RuntimeException ex) {
            c.addView(text("No se pudo abrir el historial local.", 13, GREY, false));
        }
        c.addView(button("Elegir limpieza: Mensual / Semanal / Nunca", this::chooseHistoryCleanup));
        if (total > 0) c.addView(button("Borrar historial ahora", this::confirmClearHistory));
        c.addView(button("Ver historial de avisos", () -> {
            historyDetailId = -1L;
            historyScreen = true;
            historyDisplayed = 25;
            historyScrollPosition = 0;
            draw();
        }));
        c.addView(text("Solo se borran las notificaciones guardadas: tus localidades, " +
                "preferencias y avisos futuros se conservan.", 12, GREY, false));
    }

    /** Explicit confirmation; never deletes subscriptions or duplicate protection. */
    private void confirmClearHistory() {
        new AlertDialog.Builder(this)
                .setTitle("¿Borrar el historial?")
                .setMessage("Se borrarán todas las notificaciones guardadas en este " +
                        "teléfono. No se pueden recuperar. Tus localidades, preferencias, " +
                        "notificaciones activadas y control de duplicados no se modificarán.")
                .setNegativeButton("Cancelar", (dialog, which) -> { })
                .setPositiveButton("Borrar historial", (dialog, which) -> {
                    try (NotificationHistory history = new NotificationHistory(this)) {
                        history.clearAll();
                        HistoryCleanup.afterManualClear(this);
                        historyDisplayed = 25;
                        historyScrollPosition = 0;
                        draw();
                    } catch (RuntimeException ex) {
                        android.widget.Toast.makeText(this,
                                "No se pudo borrar el historial.",
                                android.widget.Toast.LENGTH_LONG).show();
                    }
                }).show();
    }

    private void chooseHistoryCleanup() {
        final int[] chosen = {HistoryCleanup.selectionIndex(HistoryCleanup.frequency(this))};
        new AlertDialog.Builder(this)
                .setTitle("Vaciado automático del historial")
                .setSingleChoiceItems(HistoryCleanup.LABELS, chosen[0],
                        (dialog, index) -> chosen[0] = index)
                .setNegativeButton("Cancelar", (dialog, which) -> { })
                .setPositiveButton("Guardar", (dialog, which) -> {
                    try {
                        HistoryCleanup.setFrequency(this,
                                HistoryCleanup.frequencyForIndex(chosen[0]));
                        draw();
                    } catch (RuntimeException error) {
                        android.widget.Toast.makeText(this,
                                "No se pudo guardar la frecuencia.",
                                android.widget.Toast.LENGTH_LONG).show();
                    }
                })
                .show();
    }

    private void drawHistory() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(LIGHT);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(20), dp(20), dp(28));
        scroll.addView(root);
        setContentView(scroll);
        root.addView(text("Mis avisos", 26, INK, true));
        root.addView(text("Historial privado de notificaciones recibidas en este teléfono.",
                13, GREY, false));
        root.addView(button("Volver a HOY ME AFECTA", () -> {
            historyScreen = false;
            historyDetailId = -1L;
            draw();
        }));

        long total;
        try (NotificationHistory history = new NotificationHistory(this)) {
            total = history.count();
            LinearLayout controls = card();
            controls.addView(text("Total guardado: " + total, 13, INK, true));
            String frequency = HistoryCleanup.frequency(this);
            controls.addView(text("Vaciado automático: " + HistoryCleanup.label(frequency),
                    14, INK, true));
            controls.addView(text(HistoryCleanup.description(this), 12, GREY, false));
            String lastClear = HistoryCleanup.lastAutomaticClear(this);
            if (!lastClear.isEmpty()) controls.addView(text(lastClear, 12, GREY, false));
            controls.addView(button("Configurar vaciado automático", this::chooseHistoryCleanup));
            controls.addView(text("Opciones: Mensualmente (predeterminada; un mes calendario), " +
                    "Semanalmente (cada 7 días) o Nunca. Se borra el historial local completo, " +
                    "sin límite de cantidad de avisos.", 12, GREY, false));
            controls.addView(text("Los registros del ENRE describen publicaciones, no " +
                    "confirman la duración del corte. Las pruebas están identificadas.",
                    12, GREY, false));
            if (total > 0) {
                controls.addView(button("Borrar historial ahora", this::confirmClearHistory));
            }
            if (total == 0) {
                LinearLayout empty = card();
                empty.addView(text("Todavía no hay avisos guardados.",
                        14, GREY, false));
            } else {
                int shown = 0;
                int offset = 0;
                while (shown < historyDisplayed) {
                    int next = Math.min(25, historyDisplayed - shown);
                    java.util.List<NotificationHistory.Record> page = history.newest(offset, next);
                    if (page.isEmpty()) break;
                    for (NotificationHistory.Record item : page) {
                        LinearLayout entry = card();
                        entry.addView(text(item.type, 12,
                                "AVISO DEL ENRE".equals(item.type) ? BLUE : GREY, true));
                        entry.addView(text(item.title, 15, INK, true));
                        entry.addView(text("Recibido: " + new SimpleDateFormat(
                                "dd/MM/yyyy HH:mm", Locale.getDefault())
                                .format(new Date(item.receivedAt)), 12, GREY, false));
                        if (!item.company.isEmpty())
                            entry.addView(text("Origen: " + item.company, 12, GREY, false));
                        String area = item.locality;
                        if (!item.partido.isEmpty() && !item.partido.equalsIgnoreCase(area))
                            area += (area.isEmpty() ? "" : " · ") + item.partido;
                        if (!area.isEmpty()) entry.addView(text("Zona: " + area, 12, GREY, false));
                        if (!item.firstSeenAt.isEmpty())
                            entry.addView(text("Primera aparición registrada: " +
                                    formatUtc(item.firstSeenAt), 12, GREY, false));
                        if (!item.description.isEmpty())
                            entry.addView(text(item.description, 12, GREY, false));
                        entry.addView(button("Ver detalles del aviso", () -> {
                            historyDetailId = item.id;
                            detailChecking = false;
                            detailNetworkFeed = null;
                            detailNetworkFeedRecordId = -1L;
                            detailNetworkMessage = "";
                            draw();
                        }));
                        if (item.sourceUrl.startsWith("https://www.enre.gov.ar/") ||
                                item.sourceUrl.startsWith("https://enre.gov.ar/")) {
                            entry.addView(button("Consultar publicación del ENRE",
                                    () -> open(item.sourceUrl)));
                        }
                    }
                    shown += page.size();
                    offset += page.size();
                    if (page.size() < next) break;
                }
                if (total > shown) {
                    LinearLayout more = card();
                    more.addView(text("Mostrando " + shown + " de " + total +
                            ". Los anteriores siguen guardados.", 12, GREY, false));
                    more.addView(button("Mostrar avisos anteriores", () -> {
                        historyScrollPosition = scroll.getScrollY();
                        historyDisplayed += 25;
                        drawHistory();
                    }));
                }
            }
        } catch (RuntimeException ex) {
            LinearLayout error = card();
            error.addView(text("No se pudo consultar el historial local.",
                    13, GREY, false));
        }
        if (historyScrollPosition > 0) {
            int restore = historyScrollPosition;
            scroll.post(() -> scroll.scrollTo(0, restore));
            historyScrollPosition = 0;
        }
    }

    @Override public void onBackPressed() {
        if (historyScreen && historyDetailId > 0) {
            historyDetailId = -1L;
            draw();
        } else if (historyScreen) {
            historyScreen = false;
            draw();
        } else {
            super.onBackPressed();
        }
    }

    /** Read-only detail; no automatic deletions, changes to settings, or assumed restorations. */
    private void drawHistoryDetail() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(LIGHT);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(20), dp(20), dp(28));
        scroll.addView(root);
        setContentView(scroll);
        root.addView(text("Detalle del aviso", 26, INK, true));
        root.addView(button("Volver a Mis avisos", () -> {
            historyDetailId = -1L;
            draw();
        }));
        try (NotificationHistory history = new NotificationHistory(this)) {
            NotificationHistory.Record record = history.byId(historyDetailId);
            if (record == null) {
                LinearLayout missing = card();
                missing.addView(text("El aviso ya no está disponible en este teléfono.",
                        14, GREY, false));
                return;
            }
            LinearLayout detail = card();
            detail.addView(text(record.type, 13, BLUE, true));
            detail.addView(text(record.title, 19, INK, true));
            detail.addView(text("Recibido: " + new SimpleDateFormat(
                    "dd/MM/yyyy HH:mm", Locale.getDefault())
                    .format(new Date(record.receivedAt)), 13, GREY, false));
            if (!record.company.isEmpty())
                detail.addView(text("Organismo / empresa: " + record.company, 13, GREY, false));
            if (!record.partido.isEmpty())
                detail.addView(text("Partido: " + record.partido, 13, GREY, false));
            if (!record.locality.isEmpty())
                detail.addView(text("Localidad: " + record.locality, 13, GREY, false));
            if (!record.firstSeenAt.isEmpty())
                detail.addView(text("Primera aparición en el informe: " +
                        formatUtc(record.firstSeenAt), 13, GREY, false));
            if (!record.description.isEmpty())
                detail.addView(text(record.description, 13, GREY, false));

            if (!"AVISO DEL ENRE".equals(record.type)) {
                LinearLayout test = card();
                test.addView(text("Prueba o simulación local: no representa un incidente real. " +
                        "No corresponde verificar su vigencia en el ENRE.", 13, GREY, true));
                return;
            }
            LinearLayout check = card();
            check.addView(text("¿Todavía figura en la publicación?", 16, INK, true));
            check.addView(text("Se consulta el informe publicado por el proyecto, que recopila " +
                    "datos del ENRE. Se busca un aviso equivalente por empresa, tipo y zona. " +
                    "No se puede identificar con certeza el mismo incidente " +
                    "ni confirmar el suministro de un domicilio.", 12, GREY, false));
            JSONObject candidate = detailNetworkFeedRecordId == record.id &&
                    detailNetworkFeed != null ? detailNetworkFeed : feed;
            PublicationStatus.Result status = PublicationStatus.assess(candidate,
                    record.company, record.partido, record.locality, record.title,
                    System.currentTimeMillis());
            check.addView(text(status.explanation, 14,
                    PublicationStatus.MATCH_FOUND.equals(status.status) ? BLUE : GREY, true));
            if (!status.generatedAt.isEmpty())
                check.addView(text("Informe: " + formatUtc(status.generatedAt), 12, GREY, false));
            if (!status.sourceCheckedAt.isEmpty())
                check.addView(text("Fuente consultada: " + formatUtc(status.sourceCheckedAt),
                        12, GREY, false));
            if (!detailNetworkMessage.isEmpty())
                check.addView(text(detailNetworkMessage, 12, GREY, false));
            if (detailNetworkFeedRecordId != record.id || detailNetworkFeed == null)
                check.addView(text("Evaluación inicial del informe almacenado. Para consultar " +
                        "la publicación más reciente, presioná el botón siguiente.",
                        12, GREY, false));
            if (detailChecking) {
                check.addView(text("Consultando la publicación...", 13, GREY, false));
            } else {
                check.addView(button("Comprobar publicación ahora", () ->
                        checkHistoryPublication(record.id)));
            }
            if (record.sourceUrl.startsWith("https://www.enre.gov.ar/") ||
                    record.sourceUrl.startsWith("https://enre.gov.ar/")) {
                check.addView(button("Abrir la fuente oficial", () -> open(record.sourceUrl)));
            }
        } catch (RuntimeException ex) {
            LinearLayout problem = card();
            problem.addView(text("No se pudo consultar este aviso guardado.",
                    13, GREY, false));
        }
    }

    /** Refresh detail from GitHub in a worker thread; never infer resolution on failure. */
    private void checkHistoryPublication(final long id) {
        if (detailChecking) return;
        detailChecking = true;
        detailNetworkMessage = "";
        draw();
        new Thread(() -> {
            HttpURLConnection handle = null;
            try {
                handle = (HttpURLConnection) new URL(FEED_URL + "?detail=" +
                        System.currentTimeMillis()).openConnection();
                handle.setConnectTimeout(12000);
                handle.setReadTimeout(12000);
                handle.setRequestProperty("Accept", "application/json");
                if (handle.getResponseCode() != 200)
                    throw new Exception("Respuesta HTTP " + handle.getResponseCode());
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                try (InputStream stream = handle.getInputStream()) {
                    byte[] buffer = new byte[4096];
                    int count;
                    while ((count = stream.read(buffer)) != -1) {
                        if (bytes.size() + count > 2_000_000)
                            throw new Exception("Informe demasiado grande");
                        bytes.write(buffer, 0, count);
                    }
                }
                JSONObject latest = new JSONObject(bytes.toString("UTF-8"));
                if (latest.optInt("schema_version") != 1)
                    throw new Exception("Formato de informe desconocido");
                runOnUiThread(() -> {
                    if (!historyScreen || historyDetailId != id) return;
                    detailChecking = false;
                    detailNetworkFeed = latest;
                    detailNetworkFeedRecordId = id;
                    detailNetworkMessage = "Consulta al informe de GitHub completada. " +
                            "Revisá su fecha y la de la fuente: los datos podrían no ser recientes.";
                    draw();
                });
            } catch (Exception ex) {
                runOnUiThread(() -> {
                    if (!historyScreen || historyDetailId != id) return;
                    detailChecking = false;
                    detailNetworkFeed = null;
                    detailNetworkFeedRecordId = -1L;
                    detailNetworkMessage = "No se pudo consultar el servidor. " +
                            "El estado actual no está verificado.";
                    draw();
                });
            } finally {
                if (handle != null) handle.disconnect();
            }
        }).start();
    }

    private void notificationSettings() {
        LinearLayout c = card();
        boolean enabled = prefs.getBoolean("notifications_enabled", false);
        c.addView(text(enabled ? "Avisos eléctricos activados" : "Avisos eléctricos desactivados",
                15, enabled ? BLUE : GREY, true));
        c.addView(text("Avisos optativos cuando aparece un registro nuevo del ENRE para tus zonas. " +
                "No indica cuándo comenzó el corte. Se comprueba aproximadamente cada 30 minutos, " +
                "pero Android puede retrasarlo, y GitHub actualiza el informe normalmente cada hora.",
                12, GREY, false));
        c.addView(text("Por ahora solo electricidad (Edenor y Edesur). No se envían avisos de " +
                "normalización sin confirmación. No sustituye los canales oficiales.",
                12, GREY, false));
        if (enabled) {
            c.addView(text("Trabajo en segundo plano: " +
                    (AlertCheckJobService.isScheduled(this) ? "programado" : "NO programado"),
                    12, GREY, false));
            c.addView(text(AlertCheckJobService.lastBackgroundCheck(this),
                    12, GREY, false));
            c.addView(button("Enviar notificación de prueba", () -> {
                boolean sent = AlertNotifier.sendTestNotification(this);
                android.widget.Toast.makeText(this,
                        sent ? "Prueba enviada a Android. Revisala en tus notificaciones." :
                                "Android bloqueo la prueba. Revisa los permisos y el canal de avisos.",
                        android.widget.Toast.LENGTH_LONG).show();
            }));
            c.addView(text("La prueba anterior es local: no representa un corte real y " +
                    "no comprueba todavia la ejecucion automatica.", 12, GREY, false));
            TextView diagnostic = text("", 12, GREY, false);
            c.addView(button("Comprobar conexión de avisos ahora", () -> {
                diagnostic.setText("Consultando el informe desde el telefono...");
                new Thread(() -> {
                    String result = AlertNotifier.fetchAndProcess(getApplicationContext());
                    runOnUiThread(() -> diagnostic.setText(result));
                }, "HMA-manual-check").start();
            }));
            c.addView(diagnostic);
            c.addView(text(AlertNotifier.backgroundSimulationStatus(this), 12, GREY, false));
            c.addView(button("Programar simulacion en segundo plano", () -> {
                String outcome = AlertNotifier.queueBackgroundSimulation(this);
                android.widget.Toast.makeText(this, outcome,
                        android.widget.Toast.LENGTH_LONG).show();
                draw();
            }));
            c.addView(text("La simulacion usa una localidad elegida y espera una consulta " +
                    "automatica real. Siempre indicara PRUEBA y NO se publica en GitHub. " +
                    "Puede tardar por las restricciones de Android.", 12, GREY, false));
            c.addView(button("Actualizar estado de segundo plano", () -> {
                android.widget.Toast.makeText(this,
                        (AlertCheckJobService.isScheduled(this) ?
                                "Comprobacion periodica programada. " :
                                "Sin comprobacion periodica programada. ") +
                                AlertCheckJobService.lastBackgroundCheck(this),
                        android.widget.Toast.LENGTH_LONG).show();
                draw();
            }));
        }
        c.addView(button(enabled ? "Desactivar notificaciones" : "Activar notificaciones", () -> {
            if (enabled) {
                prefs.edit().putBoolean("notifications_enabled", false)
                        .remove("background_simulation_pending_ms").apply();
                AlertCheckJobService.cancel(this);
                draw();
            } else if (prefs.getString("place", "").trim().isEmpty() ||
                    !"Argentina".equals(selectedCountry())) {
                android.widget.Toast.makeText(this,
                        "Elegí primero una o varias localidades de Argentina.",
                        android.widget.Toast.LENGTH_LONG).show();
            } else if (!AlertNotifier.permitted(this) && Build.VERSION.SDK_INT >= 33) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},
                        NOTIFY_PERMISSION_REQUEST);
            } else {
                enableNotices();
            }
        }));
    }

    private void enableNotices() {
        prefs.edit().putBoolean("notifications_enabled", true)
                .remove("background_simulation_pending_ms")
                .putBoolean("notification_primed", false)
                .remove("notification_seen_ids").apply();
        // Seed a quiet baseline from a fresh cached feed, if available.
        AlertNotifier.processFeed(this, feed);
        AlertCheckJobService.scheduleIfNeeded(this);
        draw();
    }

    @Override public void onRequestPermissionsResult(int requestCode,
            String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == NOTIFY_PERMISSION_REQUEST && grantResults.length > 0 &&
                grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            enableNotices();
        } else if (requestCode == NOTIFY_PERMISSION_REQUEST) {
            android.widget.Toast.makeText(this, "No se activaron las notificaciones.",
                    android.widget.Toast.LENGTH_LONG).show();
        }
    }

    private static String norm(String raw) {
        return Normalizer.normalize(raw == null ? "" : raw, Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "").trim().toLowerCase(Locale.ROOT);
    }

    private static Date parseUtc(String iso) {
        try {
            SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
            fmt.setTimeZone(TimeZone.getTimeZone("UTC"));
            fmt.setLenient(false);
            return fmt.parse(iso);
        } catch (Exception ignored) { return null; }
    }

    private static String formatUtc(String iso) {
        Date date = parseUtc(iso);
        if (date == null) return "fecha no disponible";
        SimpleDateFormat local = new SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault());
        return local.format(date) + " (hora local)";
    }

    private boolean isFresh() {
        if (feed == null) return false;
        Date date = parseUtc(feed.optString("generated_at", ""));
        if (date == null) return false;
        long age = System.currentTimeMillis() - date.getTime();
        return age >= -60000L && age < MAX_FEED_AGE_MS;
    }

    private String favoriteLine() {
        String line = prefs.getString("line", "57").trim();
        return line.isEmpty() ? "57" : line;
    }

    // Exact normalized match prevents accidentally including similarly named towns.
    private boolean selectedAreaMatches(String partido, String localidad) {
        String raw = prefs.getString("place", "");
        for (String segment : raw.split("[;,]")) {
            String wanted = norm(segment);
            if (!wanted.isEmpty() && (wanted.equals(norm(partido)) ||
                    wanted.equals(norm(localidad)))) return true;
        }
        return false;
    }

    private boolean sourceFresh(JSONObject source) {
        if (source == null || !"ok".equals(usable(source, "status"))) return false;
        Date checked = parseUtc(usable(source, "checked_at"));
        if (checked == null) return false;
        long age = System.currentTimeMillis() - checked.getTime();
        return age >= -60000L && age < MAX_FEED_AGE_MS;
    }

    private int matchingElectricityCount() {
        if (!"Argentina".equals(selectedCountry()) || !isFresh() || feed == null) return 0;
        JSONArray entries = feed.optJSONArray("alerts");
        JSONObject sources = feed.optJSONObject("sources");
        if (entries == null || sources == null) return 0;
        int count = 0;
        for (int i = 0; i < entries.length(); i++) {
            JSONObject a = entries.optJSONObject(i);
            if (a == null || !"electricidad".equals(usable(a, "category"))) continue;
            if (!selectedAreaMatches(usable(a, "partido"), usable(a, "localidad"))) continue;
            if (sourceFresh(sources.optJSONObject(usable(a,"company").toLowerCase(Locale.ROOT)))) count++;
        }
        return count;
    }

    private void personalReport() {
        LinearLayout box = card();
        box.addView(text("Seleccioná un servicio para ir a sus avisos y fuentes.",
                13, BLUE, true));
        if (!"Argentina".equals(selectedCountry())) {
            box.addView(text("Cobertura en preparación para " + selectedCountry() +
                    ". Todavía no contamos con conectores locales verificados.",
                    13, GREY, false));
            return;
        }
        final boolean fresh = isFresh();
        final boolean hasZones = !prefs.getString("place", "").trim().isEmpty();
        box.addView(text("Localidades: " + (hasZones ? prefs.getString("place", "") :
                "sin configurar"), 12, GREY, false));
        if (!fresh) {
            box.addView(text("Informe no actualizado: no podemos verificar la situación " +
                    "actual. Podés abrir igualmente cada sección para consultar sus fuentes.",
                    13, GREY, true));
        } else if (!hasZones) {
            box.addView(text("Elegí una o varias localidades en Tus preferencias " +
                    "para recibir un resumen local.", 13, GREY, false));
        }

        int categories = 0;
        if (sectionVisible("electricidad")) {
            categories++;
            String detail;
            if (!fresh) {
                detail = "No hay informe reciente para validar avisos.";
            } else if (!hasZones) {
                detail = "Faltan localidades para filtrar avisos eléctricos.";
            } else {
                JSONObject sources = feed.optJSONObject("sources");
                boolean connected = sources != null &&
                        (sourceFresh(sources.optJSONObject("edenor")) ||
                         sourceFresh(sources.optJSONObject("edesur")));
                int enre = matchingElectricityCount();
                int works = countBuenosAiresScheduledMatches() +
                        countSantiagoScheduledMatches() + countNeuquenScheduledMatches() +
                        countAdditionalProvincialScheduledMatches();
                detail = (connected ? enre + (enre == 1 ?
                        " aviso del ENRE coincidente" : " avisos del ENRE coincidentes") :
                        "ENRE sin consulta reciente verificable") +
                        "; " + works + (works == 1 ? " trabajo programado" :
                        " trabajos programados") +
                        " coincidentes en las fuentes provinciales verificadas. " +
                        "Otras provincias: consultar el detalle. No confirma cortes actuales.";
            }
            reportLink(box, "electricidad", "Electricidad", detail);
        }
        if (sectionVisible("colectivos")) {
            categories++;
            reportLink(box, "colectivos", "Colectivos · línea " + favoriteLine(),
                    "Sin datos automáticos verificados de demoras. " +
                    "Consultá los avisos documentados y los enlaces oficiales.");
        }
        if (sectionVisible("subtes")) {
            categories++;
            reportLink(box, "subtes", "Subtes de CABA",
                    fresh ? "Estado publicado para la red; comprobá su fecha y vigencia." :
                            "Estado actual no verificado. Consultá las fuentes.");
        }
        if (sectionVisible("trenes")) {
            categories++;
            String detail;
            if (!fresh) {
                detail = "No hay consulta reciente verificable de comunicados.";
            } else {
                JSONObject rail = feed.optJSONObject("rail_official");
                if (!"ok".equals(usable(rail, "status"))) {
                    detail = "Fuente ferroviaria no verificada en esta consulta.";
                } else {
                    int railCount = countDatedRailPublications();
                    int localCount = hasZones ? countPublicMatches("tren") : 0;
                    detail = railCount + (railCount == 1 ?
                            " comunicado oficial reciente" : " comunicados oficiales recientes") +
                            (localCount > 0 ? "; " + localCount +
                                    " aviso(s) documentado(s) para tus zonas" : "") +
                            ". No informa circulación en vivo.";
                }
            }
            reportLink(box, "trenes", "Trenes", detail);
        }
        if (sectionVisible("bancos")) {
            categories++;
            JSONObject banking = fresh ? feed.optJSONObject("banking") : null;
            boolean calendar = "published_reference_2026".equals(usable(banking, "status"));
            int alerts = fresh && hasZones ? countPublicMatches("banco") : 0;
            reportLink(box, "bancos", "Bancos",
                    (calendar ? "Calendario nacional de feriados disponible" :
                            "Calendario actual no comprobado") +
                    (alerts > 0 ? "; " + alerts + " aviso(s) local(es)" : "") +
                    ". No confirma el estado de cada sucursal.");
        }
        if (sectionVisible("operativos")) {
            categories++;
            int alerts = fresh && hasZones ? countPublicMatches("operativo_publico") : 0;
            reportLink(box, "operativos", "Operativos públicos",
                    fresh && hasZones ? alerts + " aviso(s) documentado(s) para tus zonas. " +
                            "Cobertura parcial de circulación." :
                            "Sin información local actual verificable.");
        }
        if (sectionVisible("agua")) {
            categories++;
            int alerts = fresh && hasZones ? countPublicMatches("agua") : 0;
            reportLink(box, "agua", "Agua",
                    fresh && hasZones ? alerts + " aviso(s) documentado(s) para tus zonas. " +
                            "Sin conector automático completo." :
                            "Sin información local actual verificable.");
        }
        if (sectionVisible("transito")) {
            categories++;
            int alerts = fresh && hasZones ? countPublicMatches("transito") : 0;
            reportLink(box, "transito", "Tránsito y obras",
                    fresh && hasZones ? alerts + " aviso(s) documentado(s) para tus zonas. " +
                            "Cobertura incompleta." :
                            "Sin información local actual verificable.");
        }
        if (categories == 0) {
            box.addView(text("No hay categorías de servicios visibles. Podés activarlas " +
                    "en Personalizar pantalla.", 13, GREY, false));
        }
        box.addView(text("Un cero significa que no se encontraron publicaciones " +
                "coincidentes en las fuentes disponibles; no garantiza que todo funcione.",
                12, GREY, false));
    }

    /** Recent journal entries are publication changes, never proof of a live outage. */
    private void showRecentPublicationHighlights(LinearLayout box) {
        if (feed == null || !isFresh()) return;
        JSONObject journal = feed.optJSONObject("notification_events");
        JSONObject sources = feed.optJSONObject("sources");
        if (journal == null || sources == null ||
                !"ready".equals(usable(journal, "status"))) return;
        JSONArray events = journal.optJSONArray("events");
        if (events == null) return;
        int found = 0;
        for (int i = events.length() - 1; i >= 0; i--) {
            JSONObject event = events.optJSONObject(i);
            if (event == null || !"electricity_publication_added".equals(
                    usable(event, "kind"))) continue;
            if (!selectedAreaMatches(usable(event, "partido"),
                    usable(event, "localidad"))) continue;
            String company = usable(event, "company").toLowerCase(Locale.ROOT);
            if (!sourceFresh(sources.optJSONObject(company))) continue;
            Date first = parseUtc(usable(event, "first_seen_at"));
            if (first == null) continue;
            long age = System.currentTimeMillis() - first.getTime();
            if (age < -60_000L || age >= MAX_FEED_AGE_MS) continue;
            if (found == 0) box.addView(text("Novedades recientes en publicaciones:",
                    14, INK, true));
            if (found < 3) {
                box.addView(text("• " + usable(event, "company") + " · " +
                        usable(event, "title") + " · " +
                        usable(event, "localidad") + " (" +
                        formatUtc(usable(event, "first_seen_at")) + ")",
                        13, GREY, false));
            }
            found++;
        }
        if (found > 0) {
            if (found > 3) box.addView(text("Y " + (found - 3) +
                    " novedades adicionales.", 12, GREY, false));
            box.addView(text("Son cambios detectados en las publicaciones del ENRE; " +
                    "no prueban que los cortes continúen ni cuándo comenzaron.",
                    12, GREY, false));
        }
    }

    private static String usable(JSONObject obj, String key) {
        if (obj == null || obj.isNull(key)) return "";
        return obj.optString(key, "").trim();
    }

    private void electricity() {
        LinearLayout c = card();
        if (!"Argentina".equals(selectedCountry())) {
            c.addView(text("Todavía no hay fuentes eléctricas conectadas para " +
                    selectedCountry() + ". La cobertura está en preparación.", 14, GREY, false));
            return;
        }
        c.addView(text("Cobertura parcial: ENRE (Edenor/Edesur, AMBA). " +
                "Trabajos programados: EDESA (Salta), EDERSA (Río Negro), " +
                "EDESE (Santiago del Estero, ENRESE), EPEN (Neuquén), " +
                "EJESA (Jujuy) y otras fuentes provinciales, además de " +
                "EDEN, EDEA, EDES y EDELAP (Buenos Aires). " +
                "Los trabajos no prueban cortes en curso ni hay cobertura nacional completa.",
                12, GREY, false));
        if (feed == null) {
            c.addView(text("Sin información descargada. No se puede determinar el estado del servicio.",
                    14, GREY, false));
            return;
        }
        JSONObject sources = feed.optJSONObject("sources");
        if (sources == null) {
            c.addView(text("El informe no incluye el estado de las fuentes.", 14, GREY, false));
            return;
        }
        for (String company : new String[]{"edenor", "edesur"}) {
            JSONObject src = sources.optJSONObject(company);
            String state = usable(src, "status");
            String checked = formatUtc(usable(src, "checked_at"));
            if (sourceFresh(src) && isFresh()) {
                c.addView(text(company.toUpperCase(Locale.ROOT) + ": fuente consultada · " + checked,
                        12, BLUE, false));
            } else {
                c.addView(text(company.toUpperCase(Locale.ROOT) +
                        ": fuente sin datos recientes verificados", 12, GREY, true));
            }
        }
        if (!isFresh()) {
            c.addView(text("Informe desactualizado: no se muestran cortes como actuales. " +
                    "Intentá actualizar.", 14, GREY, true));
            return;
        }
        String area = prefs.getString("place", "").trim();
        if (area.isEmpty()) {
            c.addView(text("Elegí una localidad o partido para filtrar avisos.", 14, GREY, false));
            return;
        }
        JSONArray alerts = feed.optJSONArray("alerts");
        int shown = 0;
        if (alerts != null) for (int i = 0; i < alerts.length(); i++) {
            JSONObject a = alerts.optJSONObject(i);
            if (a == null || !"electricidad".equals(usable(a, "category"))) continue;
            String partido = usable(a, "partido");
            String localidad = usable(a, "localidad");
            if (!selectedAreaMatches(partido, localidad)) continue;
            JSONObject src = sources.optJSONObject(usable(a, "company").toLowerCase(Locale.ROOT));
            if (!sourceFresh(src)) continue;
            String place = partido + (localidad.isEmpty() ? "" : " · " + localidad);
            c.addView(text("• " + a.optString("title", "Interrupción informada"),
                    15, INK, true));
            c.addView(text(usable(a, "company") + " · " + place, 13, GREY, false));
            String users = usable(a, "users_affected");
            if (!users.isEmpty()) c.addView(text("Usuarios afectados reportados: " + users,
                    13, GREY, false));
            String restoration = usable(a, "expected_restoration");
            if (!restoration.isEmpty()) c.addView(text("Reposición estimada: " + restoration,
                    13, GREY, false));
            c.addView(text("Observado: " + formatUtc(usable(a, "observed_at")),
                    12, GREY, false));
            String link = usable(a, "source_url");
            if (link.startsWith("https://")) {
                c.addView(button("Ver aviso en la fuente oficial", () -> open(link)));
            }
            shown++;
            if (shown >= 15) break;
        }
        if (shown == 0) {
            c.addView(text("No hay avisos del ENRE coincidentes para «" + area + "». " +
                    "Esto NO garantiza suministro normal ni cobertura de esa zona.",
                    13, GREY, false));
        }
        showRecentPublicationHighlights(c);
        showSaltaScheduledWorks(c);
        showRioNegroScheduledWorks(c);
        showSantiagoScheduledWorks(c);
        showNeuquenScheduledWorks(c);
        showAdditionalProvincialScheduledWorks(c);
        showBuenosAiresScheduledWorks(c);
    }

    /** Read-only source health; unverified provinces are not shown as connected. */
    private void provincialSourcesSummary(LinearLayout notes) {
        if (feed == null || !isFresh() ||
                !"Argentina".equals(selectedCountry())) return;
        JSONObject group = feed.optJSONObject("provincial_electricity");
        if (group == null) return;
        String[] keys = {"epec_cordoba", "epe_santa_fe", "edersa_rio_negro",
                "edese_santiago_del_estero", "epen_neuquen"};
        String[] labels = {"EPEC (Córdoba)", "EPE (Santa Fe)", "EDERSA (Río Negro)",
                "EDESE (Santiago del Estero · ENRESE)", "EPEN (Neuquén)"};
        notes.addView(text("Fuentes eléctricas provinciales (solo trabajos programados):",
                13, INK, true));
        for (int i = 0; i < keys.length; i++) {
            JSONObject item = group.optJSONObject(keys[i]);
            String state = sourceFresh(item) ? "publicaciones verificadas" :
                    ("stale".equals(usable(item, "status")) ? "publicaciones antiguas" :
                     "sin verificación actual");
            notes.addView(text("• " + labels[i] + ": " + state +
                    ". No indica cortes en curso.", 12, GREY, false));
        }
        // Future backend-only provincial additions appear without another APK.
        JSONArray extraKeys = group.names();
        if (extraKeys != null) for (int i = 0; i < extraKeys.length(); i++) {
            String key = extraKeys.optString(i, "");
            if (isSpecificProvincialKey(key)) continue;
            JSONObject item = group.optJSONObject(key);
            if (item == null || !"Argentina".equals(usable(item, "country"))) continue;
            String company = usable(item, "company");
            String province = usable(item, "province");
            if (company.isEmpty() || province.isEmpty()) continue;
            String state = sourceFresh(item) ? "publicaciones verificadas" :
                    ("stale".equals(usable(item, "status")) ?
                    "publicaciones antiguas" : "sin verificación actual");
            notes.addView(text("• " + company + " (" + province + "): " + state +
                    ". Solo trabajos programados, no cortes actuales.", 12, GREY, false));
        }
        JSONObject ba = feed.optJSONObject("buenos_aires_work");
        if (ba != null) {
            String[] baKeys = {"eden_buenos_aires", "edea_buenos_aires",
                    "edes_buenos_aires", "edelap_buenos_aires"};
            String[] baLabels = {"EDEN", "EDEA", "EDES", "EDELAP"};
            notes.addView(text("Obras anunciadas · Buenos Aires:", 13, INK, true));
            for (int i = 0; i < baKeys.length; i++) {
                JSONObject item = ba.optJSONObject(baKeys[i]);
                String status = usable(item, "status");
                String state = sourceFresh(item) ? "avisos futuros verificados" :
                        ("stale".equals(status) ? "sin horarios futuros vigentes en la consulta" :
                         "fuente no verificada");
                notes.addView(text("• " + baLabels[i] + ": " + state +
                        ". No indica cortes en curso.", 12, GREY, false));
            }
        }
    }

    /** EDESA is a list of PLANNED works, NOT live outages or push alerts. */
    private void showSaltaScheduledWorks(LinearLayout c) {
        if (feed == null || !isFresh()) return;
        JSONObject edesa = feed.optJSONObject("edesa_salta");
        if (edesa == null) return; // Old feeds still work.
        c.addView(text("EDESA · Provincia de Salta · trabajos programados",
                15, INK, true));
        if (!sourceFresh(edesa)) {
            c.addView(text("Fuente de Salta sin verificación reciente. " +
                    "No se puede confirmar que no haya trabajos.", 12, GREY, false));
            return;
        }
        JSONArray notices = edesa.optJSONArray("notices");
        if (notices == null || notices.length() == 0) {
            c.addView(text("No se reconocieron trabajos futuros en la página oficial. " +
                    "Esto NO equivale a suministro normal.", 12, GREY, false));
            return;
        }
        int matches = 0;
        for (int i = 0; i < notices.length() && matches < 6; i++) {
            JSONObject n = notices.optJSONObject(i);
            if (n == null || !saltaAreaMentioned(usable(n, "zone_detail"),
                    usable(n, "locality_hint"))) continue;
            String start = usable(n, "scheduled_start");
            start = start.replace('T', ' ');
            if (start.length() > 16) start = start.substring(0, 16);
            c.addView(text("• Trabajo futuro publicado: " + start +
                    " (hora argentina)", 14, INK, true));
            c.addView(text("Zona informada: " + usable(n, "zone_detail"),
                    12, GREY, false));
            matches++;
        }
        if (matches == 0) {
            c.addView(text("EDESA informa " + notices.length() +
                    " trabajo(s) futuro(s) en Salta, pero ninguna descripción menciona " +
                    "tus zonas guardadas. El cotejo por nombres es aproximado y " +
                    "no determina cobertura de domicilio.", 12, GREY, false));
        } else {
            c.addView(text("Coincidencias de nombres en las descripciones, " +
                    "NO confirmación de afectación de tu domicilio ni de corte en curso.",
                    12, GREY, false));
        }
        c.addView(button("Ver trabajos EDESA en su página oficial", () ->
                open("https://www.edesa.com.ar/widgets/cortes.php")));
    }

    private boolean saltaAreaMentioned(String zone, String hint) {
        String checked = " " + norm(zone).replaceAll("[^a-z0-9]+", " ").trim() + " ";
        String explicit = norm(hint);
        String raw = prefs.getString("place", "");
        for (String segment : raw.split("[;,]")) {
            String wanted = norm(segment).replaceAll("[^a-z0-9]+", " ").trim();
            if (wanted.length() < 4) continue;
            if (wanted.equals(explicit) || checked.contains(" " + wanted + " ")) return true;
        }
        return false;
    }

    /** EDERSA publishes future planned works, NOT confirmed active interruptions.
     *  Only exact locality names are considered: no province-wide push alerts.
     *  It is possible for names to repeat in other provinces, so the user must
     *  confirm the province before treating a matching name as relevant.
     */
    private void showRioNegroScheduledWorks(LinearLayout c) {
        if (feed == null || !isFresh()) return;
        JSONObject group = feed.optJSONObject("provincial_electricity");
        if (group == null) return; // Previous server versions remain supported.
        JSONObject edersa = group.optJSONObject("edersa_rio_negro");
        if (!sourceFresh(edersa)) return; // Never display unverified or stale data.
        JSONArray notices = edersa.optJSONArray("notices");
        if (notices == null || notices.length() == 0) return;

        int matches = 0;
        for (int i = 0; i < notices.length() && matches < 6; i++) {
            JSONObject item = notices.optJSONObject(i);
            if (item == null) continue;
            String recordStatus = usable(item, "status");
            if (!"scheduled_not_confirmed".equals(recordStatus) &&
                    !"scheduled_zone_unverified".equals(recordStatus)) continue;
            String locality = usable(item, "locality_hint");
            // Explicit exact match; never search arbitrary fragments of street names.
            if (locality.isEmpty() || !selectedAreaMatches("", locality)) continue;
            String start = usable(item, "scheduled_start");
            String end = usable(item, "scheduled_end");
            if (!ScheduledWorkWindow.isPublishedWindowRelevant(
                    start, end, System.currentTimeMillis())) continue;
            if (matches == 0) {
                c.addView(text("EDERSA · Provincia de Río Negro · trabajos programados",
                        15, INK, true));
            }
            c.addView(text("• Trabajo previsto en " + locality + ": " +
                    simpleArgentinaDateTime(start) + " a " +
                    simpleArgentinaDateTime(end) + " (hora argentina)",
                    14, INK, true));
            boolean doubtfulZone = "scheduled_zone_unverified".equals(recordStatus) ||
                    item.optBoolean("source_zone_conflict", false);
            if (doubtfulZone) {
                c.addView(text("Zona NO verificada: la fuente publicó la misma " +
                        "descripción para localidades diferentes. Revisá el enlace oficial.",
                        12, GREY, true));
            } else {
                String zone = usable(item, "zone_detail");
                if (!zone.isEmpty()) c.addView(text("Zona publicada: " + zone,
                        12, GREY, false));
            }
            String task = usable(item, "task");
            if (!task.isEmpty()) c.addView(text("Tarea: " + task, 12, GREY, false));
            matches++;
        }
        if (matches == 0) return; // Hide irrelevant provincial notices.
        c.addView(text("Coincidencia por nombre de localidad en Río Negro. " +
                "Confirmá la provincia y la zona en la fuente: no demuestra corte " +
                "activo ni afectación de tu domicilio.", 12, GREY, false));
        c.addView(button("Consultar cortes programados de EDERSA", () ->
                open("https://www.edersa.com.ar/cortes-programados/")));
    }

    /** ENRESE publishes EDESE work schedules, not verified live interruptions.
     *  The underlying bulletin may list sensitive customer data in "Notas";
     *  the collector does not carry that field into the feed.
     */
    private int countSantiagoScheduledMatches() {
        if (feed == null || !isFresh() || !"Argentina".equals(selectedCountry())) return 0;
        JSONObject group = feed.optJSONObject("provincial_electricity");
        JSONObject provider = group == null ? null : group.optJSONObject("edese_santiago_del_estero");
        if (!sourceFresh(provider)) return 0;
        JSONArray notices = provider.optJSONArray("notices");
        if (notices == null) return 0;
        int count = 0;
        for (int i = 0; i < notices.length(); i++) {
            JSONObject n = notices.optJSONObject(i);
            if (!validSantiagoNotice(n)) continue;
            count++;
        }
        return count;
    }

    private boolean validSantiagoNotice(JSONObject n) {
        if (n == null || !"EDESE".equals(usable(n, "company")) ||
                !"Santiago del Estero".equals(usable(n, "province")) ||
                !"scheduled_not_confirmed".equals(usable(n, "status")) ||
                !"https://www.enrese.com.ar/CortesProgramados.html".equals(
                        usable(n, "source_url"))) return false;
        String locality = usable(n, "locality_hint");
        return !locality.isEmpty() && selectedAreaMatches("", locality) &&
                ScheduledWorkWindow.isPublishedWindowRelevant(
                        usable(n, "scheduled_start"), usable(n, "scheduled_end"),
                        System.currentTimeMillis());
    }

    private void showSantiagoScheduledWorks(LinearLayout c) {
        if (feed == null || !isFresh() || !"Argentina".equals(selectedCountry())) return;
        JSONObject group = feed.optJSONObject("provincial_electricity");
        JSONObject provider = group == null ? null : group.optJSONObject("edese_santiago_del_estero");
        if (!sourceFresh(provider)) return;
        JSONArray notices = provider.optJSONArray("notices");
        if (notices == null) return;
        int displayed = 0;
        for (int i = 0; i < notices.length() && displayed < 6; i++) {
            JSONObject n = notices.optJSONObject(i);
            if (!validSantiagoNotice(n)) continue;
            if (displayed == 0) {
                c.addView(text("EDESE · Santiago del Estero · publicación de ENRESE",
                        15, INK, true));
                c.addView(text("Trabajos previstos, no cortes confirmados. " +
                        "La coincidencia por localidad no acredita afectación de tu domicilio.",
                        12, GREY, false));
            }
            c.addView(text("• " + usable(n, "locality_hint") + " · " +
                    simpleArgentinaDateTime(usable(n, "scheduled_start")) + " a " +
                    simpleArgentinaDateTime(usable(n, "scheduled_end")) +
                    " (hora argentina)", 14, INK, true));
            c.addView(text("Zona publicada: " + usable(n, "zone_detail"),
                    12, GREY, false));
            c.addView(text("Trabajo: " + usable(n, "task"), 12, GREY, false));
            displayed++;
        }
        if (displayed > 0) {
            c.addView(text("Confirmá que la localidad corresponde a Santiago del Estero. " +
                    "Los horarios pueden modificarse o suspenderse.", 12, GREY, false));
            c.addView(button("Consultar programación oficial de ENRESE", () ->
                    open("https://www.enrese.com.ar/CortesProgramados.html")));
        }
    }

    /** Neuquén EPEN: source-backed future works only, never live outage alerts.
     * Each official article and its date/hour are checked in the backend.
     */
    private boolean validNeuquenNotice(JSONObject n) {
        if (n == null || !"EPEN".equals(usable(n, "company")) ||
                !"Neuquén".equals(usable(n, "province")) ||
                !"scheduled_not_confirmed".equals(usable(n, "status"))) return false;
        String locality = usable(n, "locality_hint");
        if (locality.isEmpty() || !selectedAreaMatches("", locality)) return false;
        String url = usable(n, "source_url");
        try {
            Uri link = Uri.parse(url);
            String host = link.getHost();
            if (!"https".equals(link.getScheme()) ||
                    !("www.epen.gov.ar".equals(host) || "epen.gov.ar".equals(host)) ||
                    link.getQuery() != null || link.getFragment() != null ||
                    link.getPath() == null || !link.getPath().matches(
                            "/index\\.php/20\\d{2}/\\d{2}/\\d{2}/[a-z0-9-]+/")) return false;
        } catch (Exception exc) {
            return false;
        }
        return ScheduledWorkWindow.isPublishedWindowRelevant(
                usable(n, "scheduled_start"), usable(n, "scheduled_end"),
                System.currentTimeMillis());
    }

    private int countNeuquenScheduledMatches() {
        if (feed == null || !isFresh() || !"Argentina".equals(selectedCountry())) return 0;
        JSONObject group = feed.optJSONObject("provincial_electricity");
        JSONObject provider = group == null ? null : group.optJSONObject("epen_neuquen");
        if (!sourceFresh(provider)) return 0;
        JSONArray notices = provider.optJSONArray("notices");
        if (notices == null) return 0;
        int count = 0;
        for (int i = 0; i < notices.length(); i++) {
            if (validNeuquenNotice(notices.optJSONObject(i))) count++;
        }
        return count;
    }

    private void showNeuquenScheduledWorks(LinearLayout c) {
        if (feed == null || !isFresh() || !"Argentina".equals(selectedCountry())) return;
        JSONObject group = feed.optJSONObject("provincial_electricity");
        JSONObject provider = group == null ? null : group.optJSONObject("epen_neuquen");
        if (!sourceFresh(provider)) return;
        JSONArray notices = provider.optJSONArray("notices");
        if (notices == null) return;
        int shown = 0;
        for (int i = 0; i < notices.length() && shown < 8; i++) {
            JSONObject n = notices.optJSONObject(i);
            if (!validNeuquenNotice(n)) continue;
            if (shown == 0) {
                c.addView(text("EPEN · Neuquén · trabajos programados", 15, INK, true));
                c.addView(text("El organismo publica cortes previstos. No confirma " +
                        "que el servicio esté interrumpido ahora ni que tu domicilio " +
                        "esté afectado.", 12, GREY, false));
            }
            c.addView(text("• " + usable(n, "locality_hint") + " · " +
                    simpleArgentinaDateTime(usable(n, "scheduled_start")) + " a " +
                    simpleArgentinaDateTime(usable(n, "scheduled_end")) +
                    " (hora argentina)", 14, INK, true));
            c.addView(text("Zona publicada: " + usable(n, "zone_detail"),
                    12, GREY, false));
            String task = usable(n, "task");
            if (!task.isEmpty()) c.addView(text("Trabajo: " + task, 12, GREY, false));
            String officialLink = usable(n, "source_url");
            c.addView(button("Ver publicación original de EPEN", () -> open(officialLink)));
            shown++;
        }
        if (shown > 0) {
            c.addView(text("Para zonas amplias, la coincidencia es por localidad " +
                    "nombrada en el comunicado. Confirmá los sectores y posibles " +
                    "modificaciones en el enlace oficial.", 12, GREY, false));
        }
    }

    /** New provincial feeds use the existing planned-work schema. Known older
     *  providers retain their specific screens; newer verified providers are
     *  shown generically. No automatic notifications are generated here.
     */
    private boolean isSpecificProvincialKey(String key) {
        return "epec_cordoba".equals(key) || "epe_santa_fe".equals(key) ||
                "edersa_rio_negro".equals(key) ||
                "edese_santiago_del_estero".equals(key) ||
                "epen_neuquen".equals(key);
    }

    private boolean validAdditionalProvincialNotice(JSONObject source, JSONObject n) {
        if (source == null || n == null ||
                !"Argentina".equals(usable(source, "country")) ||
                !"Argentina".equals(usable(n, "country")) ||
                !"planned_outages_only".equals(usable(source, "coverage_kind")) ||
                !"scheduled_not_confirmed".equals(usable(n, "status")) ||
                !"planned_electricity_work".equals(usable(n, "kind")) ||
                !usable(source, "province").equals(usable(n, "province")) ||
                !usable(source, "company").equals(usable(n, "company"))) return false;
        String locality = usable(n, "locality_hint");
        if (locality.isEmpty() || !selectedAreaMatches("", locality) ||
                usable(n, "zone_detail").isEmpty()) return false;
        // Open only the same official host as the collector, not arbitrary links.
        try {
            Uri official = Uri.parse(usable(source, "source_url"));
            Uri item = Uri.parse(usable(n, "source_url"));
            if (!"https".equals(official.getScheme()) ||
                    !"https".equals(item.getScheme()) ||
                    official.getHost() == null ||
                    !official.getHost().equalsIgnoreCase(item.getHost()) ||
                    official.getUserInfo() != null || item.getUserInfo() != null ||
                    official.getFragment() != null || item.getFragment() != null) return false;
        } catch (Exception ignored) {
            return false;
        }
        return ScheduledWorkWindow.isPublishedWindowRelevant(
                usable(n, "scheduled_start"), usable(n, "scheduled_end"),
                System.currentTimeMillis());
    }

    private int countAdditionalProvincialScheduledMatches() {
        if (feed == null || !isFresh() || !"Argentina".equals(selectedCountry())) return 0;
        JSONObject group = feed.optJSONObject("provincial_electricity");
        if (group == null) return 0;
        JSONArray keys = group.names();
        if (keys == null) return 0;
        int count = 0;
        for (int p = 0; p < keys.length() && p < 40; p++) {
            String key = keys.optString(p, "");
            if (isSpecificProvincialKey(key)) continue;
            JSONObject source = group.optJSONObject(key);
            if (!sourceFresh(source)) continue;
            JSONArray notices = source.optJSONArray("notices");
            if (notices == null) continue;
            for (int i = 0; i < notices.length() && i < 150; i++) {
                if (validAdditionalProvincialNotice(source, notices.optJSONObject(i))) count++;
            }
        }
        return count;
    }

    private void showAdditionalProvincialScheduledWorks(LinearLayout c) {
        if (feed == null || !isFresh() || !"Argentina".equals(selectedCountry())) return;
        JSONObject group = feed.optJSONObject("provincial_electricity");
        if (group == null) return;
        JSONArray keys = group.names();
        if (keys == null) return;
        int total = 0;
        for (int p = 0; p < keys.length() && p < 40 && total < 20; p++) {
            String key = keys.optString(p, "");
            if (isSpecificProvincialKey(key)) continue;
            JSONObject source = group.optJSONObject(key);
            if (!sourceFresh(source)) continue;
            JSONArray notices = source.optJSONArray("notices");
            if (notices == null) continue;
            int shown = 0;
            for (int i = 0; i < notices.length() && i < 150 && shown < 8 && total < 20; i++) {
                JSONObject n = notices.optJSONObject(i);
                if (!validAdditionalProvincialNotice(source, n)) continue;
                if (shown == 0) {
                    c.addView(text(usable(source, "company") + " · " +
                            usable(source, "province") + " · trabajos programados",
                            15, INK, true));
                    c.addView(text("Avisos futuros publicados; no confirman cortes " +
                            "en curso ni afectación de tu domicilio.", 12, GREY, false));
                }
                c.addView(text("• " + usable(n, "locality_hint") + " · " +
                        simpleArgentinaDateTime(usable(n, "scheduled_start")) + " a " +
                        simpleArgentinaDateTime(usable(n, "scheduled_end")) +
                        " (hora argentina)", 14, INK, true));
                c.addView(text("Zona publicada: " + usable(n, "zone_detail"),
                        12, GREY, false));
                String task = usable(n, "task");
                if (!task.isEmpty()) c.addView(text("Trabajo: " + task, 12, GREY, false));
                final String link = usable(n, "source_url");
                c.addView(button("Consultar publicación oficial", () -> open(link)));
                shown++;
                total++;
            }
            if (shown > 0) c.addView(text("Coincidencia por localidad. Confirmá la " +
                    "provincia, los sectores y posibles cambios con la distribuidora.",
                    12, GREY, false));
        }
    }

    private static String simpleArgentinaDateTime(String value) {
        if (value.length() < 16) return "horario no disponible";
        return value.substring(8,10) + "/" + value.substring(5,7) + "/" +
                value.substring(0,4) + " " + value.substring(11,16);
    }

    /** Visual presentation of dated electricity work notices from Buenos Aires.
     *  Never merge these into ENRE active outages or notification history.
     *  A matching locality may exist in another province: confirm location on the source.
     */
    private int countBuenosAiresScheduledMatches() {
        if (feed == null || !isFresh() || !"Argentina".equals(selectedCountry())) return 0;
        JSONObject group = feed.optJSONObject("buenos_aires_work");
        if (group == null) return 0;
        String[] keys = {"eden_buenos_aires", "edea_buenos_aires",
                "edes_buenos_aires", "edelap_buenos_aires"};
        String[] names = {"EDEN", "EDEA", "EDES", "EDELAP"};
        int count = 0;
        for (int p = 0; p < keys.length; p++) {
            JSONObject provider = group.optJSONObject(keys[p]);
            if (!sourceFresh(provider)) continue;
            JSONArray notices = provider.optJSONArray("notices");
            if (notices == null) continue;
            for (int i = 0; i < notices.length(); i++) {
                JSONObject item = notices.optJSONObject(i);
                if (item == null || !"scheduled_not_confirmed".equals(
                        usable(item, "status"))) continue;
                if (!"Buenos Aires".equals(usable(item, "province")) ||
                        !names[p].equals(usable(item, "company"))) continue;
                String locality = usable(item, "locality_hint");
                if (locality.isEmpty() || !selectedAreaMatches("", locality)) continue;
                if (!ScheduledWorkWindow.isPublishedWindowRelevant(
                        usable(item, "scheduled_start"), usable(item, "scheduled_end"),
                        System.currentTimeMillis())) continue;
                String expectedUrl = p == 0 ? "https://www.edensa.com.ar/obras-en-tu-barrio/" :
                        p == 1 ? "https://www.edeaweb.com.ar/obras-en-tu-barrio/" :
                        p == 2 ? "https://www.infoedes.com/obras-en-tu-barrio/" :
                                 "https://www.edelap.com.ar/obras-en-tu-barrio/";
                if (!expectedUrl.equals(usable(item, "source_url"))) continue;
                count++;
            }
        }
        return count;
    }

    private void showBuenosAiresScheduledWorks(LinearLayout c) {
        if (feed == null || !isFresh()) return;
        JSONObject group = feed.optJSONObject("buenos_aires_work");
        if (group == null) return; // Gracefully support older server reports.
        String[] keys = {"eden_buenos_aires", "edea_buenos_aires",
                "edes_buenos_aires", "edelap_buenos_aires"};
        String[] names = {"EDEN", "EDEA", "EDES", "EDELAP"};
        String[] links = {"https://www.edensa.com.ar/obras-en-tu-barrio/",
                "https://www.edeaweb.com.ar/obras-en-tu-barrio/",
                "https://www.infoedes.com/obras-en-tu-barrio/",
                "https://www.edelap.com.ar/obras-en-tu-barrio/"};
        int displayed = 0;
        for (int p = 0; p < keys.length && displayed < 12; p++) {
            JSONObject provider = group.optJSONObject(keys[p]);
            if (!sourceFresh(provider)) continue; // stale/unverified => not current data.
            JSONArray notices = provider.optJSONArray("notices");
            if (notices == null) continue;
            int companyShown = 0;
            for (int i = 0; i < notices.length() && companyShown < 6 && displayed < 12; i++) {
                JSONObject item = notices.optJSONObject(i);
                if (item == null || !"scheduled_not_confirmed".equals(
                        usable(item, "status"))) continue;
                if (!"Buenos Aires".equals(usable(item, "province")) ||
                        !names[p].equals(usable(item, "company"))) continue;
                String locality = usable(item, "locality_hint");
                // Only exact names, not street fragments or partial city names.
                if (locality.isEmpty() || !selectedAreaMatches("", locality)) continue;
                String start = usable(item, "scheduled_start");
                String end = usable(item, "scheduled_end");
                if (!ScheduledWorkWindow.isPublishedWindowRelevant(
                        start, end, System.currentTimeMillis())) continue;
                if (!links[p].equals(usable(item, "source_url"))) continue;
                if (displayed == 0) {
                    c.addView(text("Buenos Aires · obras eléctricas anunciadas",
                            15, INK, true));
                    c.addView(text("Son franjas horarias previstas por la empresa. " +
                            "No confirman un corte actual ni que tu domicilio resulte afectado.",
                            12, GREY, false));
                }
                c.addView(text("• " + names[p] + " · " + locality,
                        14, INK, true));
                c.addView(text("Franja publicada: " + simpleArgentinaDateTime(start) +
                        " a " + simpleArgentinaDateTime(end) + " (hora argentina)",
                        12, GREY, false));
                String zone = usable(item, "zone_detail");
                if (!zone.isEmpty()) c.addView(text("Zona descrita: " + zone,
                        12, GREY, false));
                final String official = links[p];
                c.addView(button("Ver publicación oficial de " + names[p],
                        () -> open(official)));
                companyShown++;
                displayed++;
            }
        }
        if (displayed > 0) {
            c.addView(text("Solo coincidencias exactas de localidad. Si hay localidades " +
                    "homónimas en otras provincias, confirmá jurisdicción y calles.",
                    12, GREY, false));
        }
    }

    private void buses() {
        LinearLayout c = card();
        if (!"Argentina".equals(selectedCountry())) {
            c.addView(text("Todavía no hay operadores de transporte conectados para " +
                    selectedCountry() + ".", 14, GREY, false));
            return;
        }
        String line = favoriteLine();
        String branch = prefs.getString("branch", "").trim();
        c.addView(text("Línea " + line + (branch.isEmpty() ? "" : " · Ramal " + branch),
                18, INK, true));
        c.addView(text("Posiciones, llegadas y demoras: no hay una conexión automática verificada.",
                13, GREY, false));
        int found = 0;
        if (feed != null && isFresh()) {
            JSONArray alerts = feed.optJSONArray("alerts");
            if (alerts != null) for (int i = 0; i < alerts.length(); i++) {
                JSONObject a = alerts.optJSONObject(i);
                if (a == null || !"colectivo".equals(usable(a, "category")) ||
                        !line.equalsIgnoreCase(usable(a, "line"))) continue;
                String country = usable(a, "country");
                if (!country.isEmpty() && !"Argentina".equalsIgnoreCase(country)) continue;
                String eventBranch = usable(a, "branch");
                if (!branch.isEmpty() && !eventBranch.isEmpty() &&
                        !norm(branch).equals(norm(eventBranch))) continue;
                Date verified = parseUtc(usable(a, "observed_at"));
                Date end = parseUtc(usable(a, "valid_until"));
                long now = System.currentTimeMillis();
                if (verified == null || end == null || verified.getTime() > now + 60000L ||
                        now - verified.getTime() > 24L * 60 * 60 * 1000 || end.getTime() <= now) continue;
                c.addView(text("Aviso documentado: " + usable(a, "title"), 14, INK, true));
                c.addView(text(usable(a, "description"), 13, GREY, false));
                c.addView(text("Ramal: " + (eventBranch.isEmpty() ? "no especificado" : eventBranch) +
                        " · Registrado: " + formatUtc(usable(a, "observed_at")), 12, GREY, false));
                String link = usable(a, "source_url");
                if (link.startsWith("https://"))
                    c.addView(button("Consultar fuente del aviso", () -> open(link)));
                found++;
                if (found >= 12) break;
            }
        }
        if (found == 0) c.addView(text("No tenemos avisos documentados vigentes para esta línea. " +
                "Esto no confirma que el servicio sea normal.", 13, GREY, false));
        c.addView(button("Consultar Cuándo SUBO", () ->
                open("https://www.argentina.gob.ar/sube/cuandosubo")));
        if ("57".equals(line)) {
            c.addView(button("Ver recorridos oficiales de la línea 57", () ->
                    open("https://www.argentina.gob.ar/sites/default/files/recorridos_web_0/057.pdf")));
        }
    }


    // A dated official publication is not proof of a disruption active now.
    private boolean matchesChosenTrain(String newsLine) {
        String chosen = norm(prefs.getString("train", ""));
        if (chosen.isEmpty()) return true;
        return chosen.equals(norm(newsLine));
    }

    private int countDatedRailPublications() {
        if (feed == null || !isFresh() || !"Argentina".equals(selectedCountry())) return 0;
        JSONObject rail = feed.optJSONObject("rail_official");
        if (rail == null || !"ok".equals(usable(rail, "status"))) return 0;
        JSONArray items = rail.optJSONArray("notices");
        if (items == null) return 0;
        int count = 0;
        for (int i = 0; i < items.length(); i++) {
            JSONObject notice = items.optJSONObject(i);
            if (notice != null && matchesChosenTrain(usable(notice, "line"))) count++;
        }
        return count;
    }

    private void trainNotices() {
        LinearLayout c = card();
        if (!"Argentina".equals(selectedCountry())) {
            c.addView(text("Esta primera fuente cubre solo Trenes Argentinos en Argentina.",
                    13, GREY, false));
            return;
        }
        String chosen = prefs.getString("train", "").trim();
        c.addView(text(chosen.isEmpty() ? "Todos los trenes (sin línea seleccionada)" :
                "Tren habitual: " + chosen, 13, INK, true));
        c.addView(text("Comunicados oficiales recientes: NO son el estado en vivo de los trenes. " +
                "Una noticia publicada días atrás no confirma una demora actual.", 13, GREY, false));
        if (feed == null || !isFresh()) {
            c.addView(text("Sin informe reciente. No se puede verificar la consulta de los comunicados.",
                    13, GREY, false));
        } else {
            JSONObject rail = feed.optJSONObject("rail_official");
            String status = usable(rail, "status");
            if ("ok".equals(status)) {
                JSONArray news = rail.optJSONArray("notices");
                int shown = 0;
                if (news != null) for (int i = 0; i < news.length(); i++) {
                    JSONObject item = news.optJSONObject(i);
                    if (item == null || !matchesChosenTrain(usable(item, "line"))) continue;
                    String url = usable(item, "source_url");
                    if (!url.startsWith("https://www.argentina.gob.ar/")) continue;
                    c.addView(text("• " + usable(item, "title"), 14, INK, true));
                    c.addView(text("Línea: " + usable(item, "line") +
                            " · Publicado: " + usable(item, "published_on"),
                            12, GREY, false));
                    c.addView(button("Leer comunicado oficial", () -> open(url)));
                    shown++;
                }
                if (shown == 0) {
                    c.addView(text("No se encontraron comunicados recientes para esta línea. " +
                            "Esto NO significa que el servicio funcione normalmente.",
                            13, GREY, false));
                }
                c.addView(text("Última consulta: " + formatUtc(usable(rail, "checked_at")),
                        12, GREY, false));
            } else {
                c.addView(text("Comunicados oficiales no verificables en esta consulta (" +
                        (status.isEmpty() ? "sin datos" : status) + "). " +
                        "No se supone normalidad del servicio.", 13, GREY, true));
            }
        }
        c.addView(button("Consultar modificaciones del servicio", () ->
                open("https://www.argentina.gob.ar/transporte/trenes-argentinos/modificaciones-en-el-servicio-y-novedades")));
        c.addView(button("Abrir app oficial de Trenes Argentinos", () ->
                open("https://www.argentina.gob.ar/transporte/trenes-argentinos/app")));

        LinearLayout manual = card();
        manual.addView(text("Avisos documentados con vigencia y zona", 14, INK, true));
        showPublicNotices(manual, "tren");
    }

    private boolean validPublicAlert(JSONObject a, String category) {
        if (a == null || !category.equals(usable(a, "category")) || !isFresh()) return false;
        if (!"Argentina".equals(selectedCountry()) ||
                !"Argentina".equals(usable(a, "country"))) return false;
        if (!selectedAreaMatches(usable(a, "partido"), usable(a, "localidad"))) return false;
        Date verified = parseUtc(usable(a, "observed_at"));
        Date end = parseUtc(usable(a, "valid_until"));
        if (verified == null || end == null) return false;
        long now = System.currentTimeMillis();
        if (verified.getTime() > now + 60000L || now - verified.getTime() >= 24L*3600000L ||
                end.getTime() <= now) return false;
        if ("tren".equals(category)) {
            String chosen = norm(prefs.getString("train", ""));
            if (!chosen.isEmpty() && !chosen.equals(norm(usable(a, "line")))) return false;
        }
        return usable(a, "source_url").startsWith("https://");
    }

    private int countPublicMatches(String category) {
        if (feed == null) return 0;
        JSONArray alerts = feed.optJSONArray("alerts");
        if (alerts == null) return 0;
        int count = 0;
        for (int i = 0; i < alerts.length(); i++)
            if (validPublicAlert(alerts.optJSONObject(i), category)) count++;
        return count;
    }

    private void showPublicNotices(LinearLayout card, String category) {
        if (feed == null || !isFresh()) {
            card.addView(text("Sin informe reciente; no se muestran avisos como vigentes.", 13, GREY, false));
            return;
        }
        if (prefs.getString("place", "").trim().isEmpty()) {
            card.addView(text("Elegí tus zonas para consultar avisos locales.", 13, GREY, false));
            return;
        }
        JSONArray alerts = feed.optJSONArray("alerts");
        int found = 0;
        if (alerts != null) for (int i=0; i<alerts.length() && found<12; i++) {
            JSONObject a = alerts.optJSONObject(i);
            if (!validPublicAlert(a, category)) continue;
            card.addView(text("• " + usable(a, "title"), 15, INK, true));
            card.addView(text(usable(a, "description"), 13, GREY, false));
            String zone = usable(a, "partido") + " · " + usable(a, "localidad");
            String train = usable(a, "line");
            card.addView(text("Zona: " + zone + (train.isEmpty() ? "" : " · Línea: " + train), 12, GREY, false));
            card.addView(text("Verificado: " + formatUtc(usable(a, "observed_at")) +
                    " · Válido hasta: " + formatUtc(usable(a, "valid_until")), 12, GREY, false));
            String url = usable(a, "source_url");
            card.addView(button("Ver publicación oficial", () -> open(url)));
            found++;
        }
        if (found == 0) card.addView(text("No hay avisos documentados vigentes para tus zonas en esta categoría. " +
                "No significa que el servicio sea normal.", 13, GREY, false));
    }

    private void publicCategory(String category, String subtitle, String explanation,
                                String buttonTitle, String sourceUrl) {
        LinearLayout c = card();
        if (!"Argentina".equals(selectedCountry())) {
            c.addView(text("Cobertura en preparación para " + selectedCountry() +
                    ". Todavía no tenemos fuentes conectadas en este país.", 13, GREY, false));
            return;
        }
        c.addView(text(subtitle, 15, INK, true));
        if ("tren".equals(category)) {
            String train = prefs.getString("train", "").trim();
            c.addView(text(train.isEmpty() ? "Tren habitual no seleccionado" : "Tren seleccionado: " + train,
                    12, GREY, false));
        }
        c.addView(text(explanation, 13, GREY, false));
        showPublicNotices(c, category);
        c.addView(button(buttonTitle, () -> open(sourceUrl)));
    }

    private void subtes() {
        LinearLayout c = card();
        c.addView(text("Estado publicado para toda la red de CABA; no se filtra por barrio.",
                13, GREY, false));
        if (!"Argentina".equals(selectedCountry())) {
            c.addView(text("Esta fuente solo cubre la Ciudad de Buenos Aires.", 13, GREY, false));
        } else if (feed == null || !isFresh()) {
            c.addView(text("Sin informe reciente. No se presenta el servicio como normal.", 13, GREY, false));
        } else {
            JSONObject source = feed.optJSONObject("subte");
            String state = usable(source, "status");
            Date published = parseUtc(usable(source, "source_updated_at"));
            long age = published == null ? Long.MAX_VALUE : System.currentTimeMillis() - published.getTime();
            boolean valid = "ok".equals(state) && age >= -180000L && age < 90L * 60L * 1000L;
            if (!valid) {
                c.addView(text("Estado de subtes no comprobable como actual. No se muestran " +
                        "interrupciones antiguas ni se presupone normalidad.", 13, GREY, true));
                if ("stale".equals(state)) c.addView(text("La página oficial contiene datos vencidos.", 12, GREY, false));
                else if ("unverified".equals(state)) c.addView(text("No se pudo verificar la fecha o la estructura del aviso.", 12, GREY, false));
                else if ("error".equals(state)) c.addView(text("Falló la consulta a la fuente.", 12, GREY, false));
                else c.addView(text("Fuente todavía no comprobada.", 12, GREY, false));
            } else {
                c.addView(text("La fuente indica actualización: " +
                        formatUtc(usable(source, "source_updated_at")), 12, GREY, false));
                c.addView(text("Consultado: " + formatUtc(usable(source, "checked_at")) +
                        ". Confirmá antes de viajar.", 12, GREY, false));
                JSONArray lines = source.optJSONArray("lines");
                if (lines == null || lines.length() < 5) {
                    c.addView(text("No se pudo verificar la lista de líneas.", 13, GREY, false));
                } else {
                    int affected = 0;
                    for (int i = 0; i < lines.length(); i++) {
                        JSONObject entry = lines.optJSONObject(i);
                        if (entry != null && "affected".equals(usable(entry, "state"))) {
                            c.addView(text("Línea " + usable(entry, "line") + ": " +
                                    usable(entry, "description"), 13, INK, true));
                            affected++;
                        }
                    }
                    if (affected == 0) c.addView(text("La fuente no registra alteraciones en las líneas " +
                            "reconocidas; esto no garantiza cada estación.", 13, GREY, false));
                }
            }
        }
        c.addView(button("Consultar estado oficial del subte", () ->
                open("https://buenosaires.gob.ar/gcaba_historico/subte")));
    }

    private void banks() {
        LinearLayout c = card();
        if (!"Argentina".equals(selectedCountry())) {
            c.addView(text("Calendario bancario aún no conectado para " + selectedCountry(), 13, GREY, false));
            return;
        }
        c.addView(text("Calendario nacional de feriados BCRA (referencia publicada, no estado en vivo).", 13, GREY, false));
        if (feed == null || !isFresh()) {
            c.addView(text("Sin informe reciente. Consultá el BCRA para confirmar fechas.", 13, GREY, false));
        } else {
            JSONObject banking = feed.optJSONObject("banking");
            if (banking != null && "published_reference_2026".equals(usable(banking, "status"))) {
                c.addView(text("Calendario revisado: " + usable(banking, "source_reviewed_at") +
                        ". Podría haber cambios posteriores.", 12, GREY, false));
                JSONArray upcoming = banking.optJSONArray("upcoming");
                if (upcoming != null && upcoming.length() > 0) {
                    for (int i=0; i<Math.min(3, upcoming.length()); i++) {
                        JSONObject event = upcoming.optJSONObject(i);
                        if (event == null) continue;
                        c.addView(text("• " + usable(event, "date") + " · " + usable(event, "reason"),
                                13, INK, i==0));
                    }
                    c.addView(text("Es un calendario general, no una confirmación sobre sucursales, cajeros o plataformas bancarias.",
                            12, GREY, false));
                } else c.addView(text("No hay próximos feriados cargados para 2026.", 13, GREY, false));
            } else c.addView(text("Calendario de este año todavía no disponible en el sistema.",
                    13, GREY, false));
        }
        showPublicNotices(c, "banco");
        c.addView(button("Consultar calendario oficial BCRA", () ->
                open("https://www.bcra.gob.ar/consulta-feriados-bancarios-2026/")));
    }

    private void open(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
        catch (Exception ignored) {
            connection = "No se pudo abrir el enlace.";
            draw();
        }
    }

    private void refresh() {
        if (refreshing) return;
        refreshing = true;
        draw();
        final String url = FEED_URL + "?refresh=" + System.currentTimeMillis();
        new Thread(() -> {
            HttpURLConnection handle = null;
            try {
                handle = (HttpURLConnection) new URL(url).openConnection();
                handle.setConnectTimeout(12000);
                handle.setReadTimeout(12000);
                handle.setRequestProperty("Accept", "application/json");
                if (handle.getResponseCode() != 200)
                    throw new Exception("HTTP " + handle.getResponseCode());
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                try (InputStream stream = handle.getInputStream()) {
                    byte[] buffer = new byte[4096];
                    int n;
                    while ((n = stream.read(buffer)) != -1) {
                        if (bytes.size() + n > 2_000_000)
                            throw new Exception("Respuesta demasiado grande");
                        bytes.write(buffer, 0, n);
                    }
                }
                JSONObject result = new JSONObject(bytes.toString("UTF-8"));
                if (result.optInt("schema_version") != 1)
                    throw new Exception("Formato de datos desconocido");
                runOnUiThread(() -> {
                    feed = result;
                    prefs.edit().putString("cached_feed", result.toString()).apply();
                    AlertNotifier.processFeed(this, result);
                    refreshing = false;
                    connection = isFresh()
                            ? "Informe descargado. Revisá las fuentes y la cobertura."
                            : "Informe antiguo: no se muestran avisos como vigentes.";
                    draw();
                });
            } catch (Exception ex) {
                String detail = ex.getMessage();
                runOnUiThread(() -> {
                    refreshing = false;
                    // Keep the cached feed, but NEVER bypass its expiration check.
                    connection = "Sin actualización de red; informe guardado sujeto a vigencia. Error: " +
                            (detail == null ? "error de conexión" : detail);
                    draw();
                });
            } finally {
                if (handle != null) handle.disconnect();
            }
        }).start();
    }
}
