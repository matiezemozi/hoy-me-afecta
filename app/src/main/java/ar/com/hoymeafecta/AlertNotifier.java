package ar.com.hoymeafecta;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.Normalizer;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.TimeZone;

/** Optional local notifications; does not provide guaranteed real-time push. */
public final class AlertNotifier {
    private AlertNotifier() {}
    private static final String FEED_URL =
            "https://raw.githubusercontent.com/matiezemozi/hoy-me-afecta/main/docs/feed.json";
    private static final String CHANNEL = "hoy_me_afecta_avisos_electricos";
    private static final long MAX_AGE = 3L * 60L * 60L * 1000L;
    private static final int MAX_BYTES = 2_000_000;

    public static boolean permitted(Context context) {
        return Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(
                Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    private static String normalized(String input) {
        return Normalizer.normalize(input == null ? "" : input, Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "").trim().toLowerCase(Locale.ROOT);
    }

    private static long epoch(String date) {
        try {
            SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
            f.setTimeZone(TimeZone.getTimeZone("UTC"));
            f.setLenient(false);
            Date d = f.parse(date);
            return d == null ? -1 : d.getTime();
        } catch (Exception ignored) { return -1; }
    }

    private static boolean recent(long date) {
        long age = System.currentTimeMillis() - date;
        return date > 0 && age >= -60_000L && age < MAX_AGE;
    }

    private static boolean stillPublished(JSONObject feed, JSONObject event) {
        JSONArray alerts = feed.optJSONArray("alerts");
        if (alerts == null) return false;
        for (int i = 0; i < alerts.length(); i++) {
            JSONObject alert = alerts.optJSONObject(i);
            if (alert != null && "electricidad".equals(alert.optString("category")) &&
                    normalized(alert.optString("company")).equals(normalized(event.optString("company"))) &&
                    normalized(alert.optString("partido")).equals(normalized(event.optString("partido"))) &&
                    normalized(alert.optString("localidad")).equals(normalized(event.optString("localidad"))) &&
                    normalized(alert.optString("title")).equals(normalized(event.optString("title")))) {
                return true;
            }
        }
        return false;
    }

    private static boolean areaMatches(String selected, String partido, String localidad) {
        for (String part : selected.split("[;,]")) {
            String zone = normalized(part);
            if (!zone.isEmpty() &&
                    (zone.equals(normalized(partido)) || zone.equals(normalized(localidad)))) {
                return true;
            }
        }
        return false;
    }

    // The first valid feed after opting in forms the baseline, without an old alert flood.
    public static synchronized void processFeed(Context context, JSONObject feed) {
        SharedPreferences prefs = context.getSharedPreferences("hoy_me_afecta", Context.MODE_PRIVATE);
        if (!prefs.getBoolean("notifications_enabled", false) || !permitted(context)) return;
        if (feed == null || feed.optInt("schema_version") != 1 ||
                !recent(epoch(feed.optString("generated_at", "")))) return;
        JSONObject journal = feed.optJSONObject("notification_events");
        if (journal == null || !"ready".equals(journal.optString("status", ""))) return;
        JSONArray events = journal.optJSONArray("events");
        if (events == null) return;
        JSONObject sources = feed.optJSONObject("sources");
        if (sources == null) return;
        String country = prefs.getString("country", "Argentina");
        String selected = prefs.getString("place", "");
        if (!"Argentina".equals(country) || selected.trim().isEmpty()) return;

        Set<String> seen = new LinkedHashSet<>();
        for (String id : prefs.getString("notification_seen_ids", "").split(",")) {
            if (id.matches("[a-f0-9]{24}")) seen.add(id);
        }
        boolean primed = prefs.getBoolean("notification_primed", false);
        List<JSONObject> newMatches = new ArrayList<>();
        // Process every journal entry even if outside the selected areas;
        // a changed preference starts a new baseline.
        for (int i = 0; i < events.length(); i++) {
            JSONObject e = events.optJSONObject(i);
            if (e == null || !"electricity_publication_added".equals(e.optString("kind")) ||
                    !"Argentina".equals(e.optString("country"))) continue;
            String id = e.optString("event_id", "");
            if (!id.matches("[a-f0-9]{24}")) continue;
            String provider = normalized(e.optString("company", ""));
            if (!"edenor".equals(provider) && !"edesur".equals(provider)) continue;
            JSONObject source = sources.optJSONObject(provider);
            if (source == null || !"ok".equals(source.optString("status", "")) ||
                    !recent(epoch(source.optString("checked_at", "")))) continue;
            if (!recent(epoch(e.optString("first_seen_at", "")))) continue;
            // Skip duplicate or previously handled entries.
            if (seen.contains(id)) continue;
            seen.add(id);
            if (primed && stillPublished(feed, e) &&
                    areaMatches(selected, e.optString("partido", ""),
                    e.optString("localidad", ""))) newMatches.add(e);
        }
        // Bound stored IDs; 3h server retention makes old IDs unnecessary.
        while (seen.size() > 250) seen.remove(seen.iterator().next());
        StringBuilder saved = new StringBuilder();
        for (String id : seen) {
            if (saved.length() > 0) saved.append(',');
            saved.append(id);
        }
        prefs.edit().putString("notification_seen_ids", saved.toString())
                .putBoolean("notification_primed", true).apply();
        if (!newMatches.isEmpty()) {
            try { notifyNewPublication(context, newMatches); }
            catch (SecurityException ignored) { /* Permission may have been revoked. */ }
        }
    }

    private static void notifyNewPublication(Context context, List<JSONObject> entries) {
        NotificationManager manager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Novedades de electricidad",
                    NotificationManager.IMPORTANCE_DEFAULT);
            channel.setDescription("Avisos nuevos en publicaciones oficiales para tus zonas favoritas");
            manager.createNotificationChannel(channel);
        }
        int number = entries.size();
        JSONObject first = entries.get(0);
        String place = first.optString("localidad", first.optString("partido", "tu zona"));
        String title = number == 1 ? "Nuevo aviso publicado en " + place :
                number + " nuevos avisos en tus zonas";
        String body = number == 1 ? first.optString("company", "ENRE") + ": " +
                first.optString("title", "Interrupción informada") +
                ". El inicio real es desconocido." :
                "Nuevos registros en publicaciones del ENRE. Consultá el informe; " +
                "no indican necesariamente cuándo empezó cada corte.";
        Intent intent = new Intent(context, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pending = PendingIntent.getActivity(context, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26 ?
                new Notification.Builder(context, CHANNEL) : new Notification.Builder(context);
        builder.setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title).setContentText(body).setContentIntent(pending)
                .setAutoCancel(true).setWhen(System.currentTimeMillis());
        if (Build.VERSION.SDK_INT < 26) builder.setPriority(Notification.PRIORITY_DEFAULT);
        manager.notify(553, builder.build());
    }

    // Background job fetches the same published feed as the main screen.
    public static void fetchAndProcess(Context context) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(FEED_URL + "?bg=" + System.currentTimeMillis())
                    .openConnection();
            conn.setConnectTimeout(12_000);
            conn.setReadTimeout(12_000);
            conn.setRequestProperty("Accept", "application/json");
            if (conn.getResponseCode() != 200) return;
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (InputStream input = conn.getInputStream()) {
                byte[] data = new byte[4096];
                int n;
                while ((n = input.read(data)) != -1) {
                    if (bytes.size() + n > MAX_BYTES) return;
                    bytes.write(data, 0, n);
                }
            }
            JSONObject result = new JSONObject(bytes.toString("UTF-8"));
            processFeed(context, result);
        } catch (Exception ignored) {
            // No notification when feed is missing, invalid, stale or unreachable.
        } finally {
            if (conn != null) conn.disconnect();
        }
    }
}
