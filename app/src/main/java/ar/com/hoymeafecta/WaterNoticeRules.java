package ar.com.hoymeafecta;

import java.text.Normalizer;
import java.text.ParsePosition;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** Read-only pilot policy for water bulletins. Never handles Android notifications. */
public final class WaterNoticeRules {
    private static final TimeZone ARGENTINA =
            TimeZone.getTimeZone("America/Argentina/Buenos_Aires");
    private static final TimeZone UTC = TimeZone.getTimeZone("UTC");
    private static final long HOUR_MS = 3600000L;
    public static final long MAX_WATER_SOURCE_AGE_MS = 24L * HOUR_MS;
    private static final int BULLETIN_DAYS = 3;
    private static final int SCHEDULE_DAYS = 14;

    private WaterNoticeRules() { }

    private static Date parseExact(String value, String pattern, TimeZone zone) {
        if (value == null || value.isEmpty()) return null;
        SimpleDateFormat fmt = new SimpleDateFormat(pattern, Locale.US);
        fmt.setTimeZone(zone);
        fmt.setLenient(false);
        ParsePosition pos = new ParsePosition(0);
        Date out = fmt.parse(value, pos);
        return out != null && pos.getIndex() == value.length() ? out : null;
    }

    private static String dayOf(long epochMs) {
        SimpleDateFormat day = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
        day.setTimeZone(ARGENTINA);
        return day.format(new Date(epochMs));
    }

    private static String dayShift(long nowMs, int days) {
        Calendar calendar = Calendar.getInstance(ARGENTINA, Locale.US);
        calendar.setTimeInMillis(nowMs);
        calendar.add(Calendar.DAY_OF_MONTH, days);
        return dayOf(calendar.getTimeInMillis());
    }

    public static boolean sourceIsRecent(String timestampUtc, long nowMs) {
        Date checked = parseExact(timestampUtc, "yyyy-MM-dd'T'HH:mm:ss'Z'", UTC);
        if (checked == null) return false;
        long age = nowMs - checked.getTime();
        return age >= -60000L && age < MAX_WATER_SOURCE_AGE_MS;
    }

    public static boolean recentPublication(String date, long nowMs) {
        if (parseExact(date, "yyyy-MM-dd", ARGENTINA) == null) return false;
        return date.compareTo(dayShift(nowMs, -BULLETIN_DAYS)) >= 0 &&
                date.compareTo(dayOf(nowMs)) <= 0;
    }

    public static boolean scheduledDateRelevant(String date, long nowMs) {
        if (parseExact(date, "yyyy-MM-dd", ARGENTINA) == null) return false;
        return date.compareTo(dayOf(nowMs)) >= 0 &&
                date.compareTo(dayShift(nowMs, SCHEDULE_DAYS)) <= 0;
    }

    /** A clearly announced end time in the past should not be presented as upcoming. */
    public static boolean knownEndNotPassed(String endIso, long nowMs) {
        if (endIso == null || endIso.isEmpty()) return true;
        // Android API 23 reliably supports RFC-822 numeric offsets (Z);
        // normalize the colon in ISO offsets rather than depending on XXX.
        Date end = null;
        if (endIso.length() == 22 &&
                (endIso.charAt(16) == '+' || endIso.charAt(16) == '-') &&
                endIso.charAt(19) == ':') {
            String normalized = endIso.substring(0, 19) + endIso.substring(20);
            end = parseExact(normalized, "yyyy-MM-dd'T'HH:mmZ", UTC);
        } else if (endIso.endsWith("Z")) {
            end = parseExact(endIso, "yyyy-MM-dd'T'HH:mm'Z'", UTC);
        }
        return end != null && end.getTime() > nowMs;
    }

    public static boolean displayableNotice(String kind, String status,
                                            String publicationDay, String scheduledDay,
                                            long nowMs) {
        if ("planned_water_service_impact".equals(kind)) {
            return "scheduled_not_confirmed".equals(status) &&
                    scheduledDateRelevant(scheduledDay, nowMs);
        }
        return "water_service_bulletin".equals(kind) &&
                "publication_only_not_live".equals(status) &&
                recentPublication(publicationDay, nowMs);
    }

    private static String norm(String value) {
        return Normalizer.normalize(value == null ? "" : value,
                Normalizer.Form.NFD).replaceAll("\\p{M}", "")
                .replaceAll("\\s+", " ").trim().toLowerCase(Locale.ROOT);
    }

    public static boolean matchesSavedLocality(String saved, String locality) {
        String actual = norm(locality);
        if (actual.isEmpty() || saved == null || saved.trim().isEmpty()) return false;
        for (String part : saved.split("[;,]")) {
            if (actual.equals(norm(part))) return true;
        }
        return false;
    }
}
