package ar.com.hoymeafecta;

import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.content.SharedPreferences;
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
import java.util.Locale;
import java.util.TimeZone;

public class MainActivity extends Activity {
    // Pilot feed: later replaced by the central, country-independent service.
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
    private LinearLayout root;
    private EditText placeField, lineField, branchField;
    private Spinner countrySpinner;
    private SharedPreferences prefs;
    private JSONObject feed;
    private String connection = "Sin datos descargados todavía";
    private boolean refreshing = false;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("hoy_me_afecta", MODE_PRIVATE);
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
        TextView heading = text(label, 19, INK, true);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(15), 0, dp(9));
        root.addView(heading, lp);
    }

    private String selectedCountry() {
        return prefs.getString("country", "Argentina");
    }

    private void draw() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(LIGHT);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(20), dp(20), dp(28));
        scroll.addView(root);
        setContentView(scroll);

        root.addView(text("HOY ME AFECTA", 26, INK, true));
        root.addView(text("Lo que te conviene saber antes de salir", 14, GREY, false));
        root.addView(text("Piloto v3 · fuentes verificables, sin inventar estados de servicio", 12, GREY, false));
        LinearLayout status = card();
        status.addView(text(connection, 14, BLUE, false));
        if (feed != null) {
            status.addView(text("Última recopilación: " + formatUtc(feed.optString("generated_at", "")),
                    12, GREY, false));
        }
        if (refreshing) status.addView(text("Descargando el informe...", 13, GREY, false));
        status.addView(button("Actualizar ahora", this::refresh));

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
        setup.addView(text("No se necesita GPS. La cobertura se ampliará progresivamente.",
                12, GREY, false));
        setup.addView(button("Guardar y actualizar", () -> {
            String country = String.valueOf(countrySpinner.getSelectedItem());
            prefs.edit().putString("country", country)
                    .putString("place", placeField.getText().toString().trim())
                    .putString("line", lineField.getText().toString().trim())
                    .putString("branch", branchField.getText().toString().trim())
                    .apply();
            draw();
            refresh();
        }));

        title("Tu informe personal");
        personalReport();
        title("Electricidad · fuentes oficiales");
        electricity();
        title("Transporte · colectivos");
        buses();
        title("Información y fuentes");
        LinearLayout notes = card();
        notes.addView(text("Piloto: la fuente conectada actualmente es el ENRE para Edenor y Edesur. " +
                "No cubre todas las localidades ni distribuidoras de Argentina.", 13, GREY, false));
        notes.addView(text("Un aviso publicado se refiere a un área; no confirma el estado de " +
                "cada domicilio. Ausencia de avisos no equivale a servicio normal.", 13, GREY, false));
        notes.addView(text("El informe y cada fuente eléctrica deben tener menos de " +
                "3 horas para mostrar avisos como recientes. La aplicación no sustituye las alertas oficiales.",
                13, GREY, false));
        notes.addView(text("Las zonas se comparan por nombre exacto con partido o localidad. " +
                "No se comprueba si un corte alcanza una dirección específica.", 12, GREY, false));
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
        if (!"Argentina".equals(selectedCountry())) {
            box.addView(text("Cobertura en preparación para " + selectedCountry() +
                    ". El país se puede seleccionar, pero todavía no tenemos conectores locales.",
                    13, GREY, false));
            return;
        }
        if (!isFresh()) {
            box.addView(text("No hay un informe suficientemente reciente. " +
                    "No es posible conocer el estado actual de tus zonas.", 13, GREY, false));
            return;
        }
        if (prefs.getString("place", "").trim().isEmpty()) {
            box.addView(text("Elegí una o varias zonas para comenzar.", 13, GREY, false));
            return;
        }
        JSONObject sources = feed.optJSONObject("sources");
        if (sources == null || (!sourceFresh(sources.optJSONObject("edenor")) &&
                !sourceFresh(sources.optJSONObject("edesur")))) {
            box.addView(text("Ninguna fuente eléctrica dispone de una consulta reciente validada.",
                    13, GREY, false));
            return;
        }
        int count = matchingElectricityCount();
        box.addView(text(count == 0 ? "Sin avisos eléctricos coincidentes en las fuentes disponibles" :
                        count + (count == 1 ? " aviso eléctrico coincidente" : " avisos eléctricos coincidentes"),
                15, count == 0 ? GREY : INK, true));
        box.addView(text("Zona(s): " + prefs.getString("place", "Sin configurar") +
                " · Cobertura parcial: ENRE para Edenor/Edesur, no todas las distribuidoras.",
                12, GREY, false));
        box.addView(text("Colectivo " + favoriteLine() + ": sin conexión automática verificada de demoras.",
                12, GREY, false));
        if (count == 0) box.addView(text("Ausencia de reportes no significa ausencia de problemas.",
                12, GREY, false));
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
        c.addView(text("Cobertura piloto: Edenor y Edesur (AMBA). " +
                "Otras distribuidoras todavía no están conectadas.", 12, GREY, false));
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
            c.addView(text("No hay avisos coincidentes para «" + area + "» " +
                    "en las fuentes conectadas. Esto NO garantiza suministro normal " +
                    "ni cobertura de esa zona.", 13, GREY, false));
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
