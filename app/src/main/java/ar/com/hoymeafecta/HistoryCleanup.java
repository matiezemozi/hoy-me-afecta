package ar.com.hoymeafecta;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * Opt-in local archive clearing. The default is NEVER, including v5.7 upgrades.
 * A weekly/monthly choice clears the whole archive after one full period from
 * enabling that choice (or from a later manual clear). Android may defer jobs.
 * No internet connection or notification permission is required.
 */
public final class HistoryCleanup {
    private HistoryCleanup() {}

    public static final String NEVER = "never";
    public static final String WEEKLY = "weekly";
    public static final String MONTHLY = "monthly";
    public static final String[] LABELS = {"Nunca", "Semanalmente", "Mensualmente"};

    private static final String PREFS = "hoy_me_afecta";
    private static final String FREQUENCY_KEY = "history_cleanup_frequency";
    private static final String ANCHOR_KEY = "history_cleanup_anchor_ms";
    private static final String LAST_KEY = "history_cleanup_last_ms";
    private static final int JOB_ID = 30554;
    private static final long DAY_MS = 24L * 60L * 60L * 1000L;

    public static String frequency(Context context) {
        String v = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(FREQUENCY_KEY, NEVER);
        return valid(v) ? v : NEVER;
    }

    private static boolean valid(String frequency) {
        return NEVER.equals(frequency) || WEEKLY.equals(frequency) || MONTHLY.equals(frequency);
    }

    public static String label(String frequency) {
        if (WEEKLY.equals(frequency)) return LABELS[1];
        if (MONTHLY.equals(frequency)) return LABELS[2];
        return LABELS[0];
    }

    public static int selectionIndex(String frequency) {
        if (WEEKLY.equals(frequency)) return 1;
        if (MONTHLY.equals(frequency)) return 2;
        return 0;
    }

    public static String frequencyForIndex(int index) {
        if (index == 1) return WEEKLY;
        if (index == 2) return MONTHLY;
        return NEVER;
    }

    /** A calendar week (7 days) or a calendar month in the phone's local timezone. */
    static long nextDue(long anchor, String frequency) {
        if (anchor <= 0 || NEVER.equals(frequency) || !valid(frequency)) return -1L;
        Calendar calendar = Calendar.getInstance();
        calendar.setTimeInMillis(anchor);
        if (WEEKLY.equals(frequency)) calendar.add(Calendar.DAY_OF_MONTH, 7);
        else calendar.add(Calendar.MONTH, 1);
        return calendar.getTimeInMillis();
    }

    /**
     * Switch preference without deleting anything now. The timer restarts only
     * if the chosen frequency actually changes; old records stay until due.
     */
    public static synchronized void setFrequency(Context context, String choice) {
        if (!valid(choice)) throw new IllegalArgumentException("Frecuencia no reconocida");
        Context app = context.getApplicationContext();
        SharedPreferences p = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String old = frequency(app);
        if (!choice.equals(old)) {
            SharedPreferences.Editor edit = p.edit().putString(FREQUENCY_KEY, choice);
            if (NEVER.equals(choice)) edit.remove(ANCHOR_KEY);
            else edit.putLong(ANCHOR_KEY, System.currentTimeMillis());
            if (!edit.commit()) throw new IllegalStateException("No se pudo guardar la preferencia");
        }
        scheduleIfNeeded(app);
    }

    /** Manual clear resets the timing window but never changes the choice. */
    public static synchronized void afterManualClear(Context context) {
        Context app = context.getApplicationContext();
        if (!NEVER.equals(frequency(app))) {
            app.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                    .putLong(ANCHOR_KEY, System.currentTimeMillis()).commit();
        }
    }

    /**
     * Return true only after the scheduled clear really finished. A process
     * crash or database error leaves the anchor intact for a later retry.
     */
    public static synchronized boolean runIfDue(Context context) {
        Context app = context.getApplicationContext();
        SharedPreferences prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String choice = frequency(app);
        if (NEVER.equals(choice)) return false;
        long now = System.currentTimeMillis();
        long anchor = prefs.getLong(ANCHOR_KEY, 0L);
        if (anchor <= 0L || anchor > now) {
            prefs.edit().putLong(ANCHOR_KEY, now).commit();
            return false;
        }
        if (now < nextDue(anchor, choice)) return false;
        try (NotificationHistory history = new NotificationHistory(app)) {
            history.clearAll();
        }
        // A successful clear starts a NEW interval. Do not repeatedly clear if
        // Android was offline/asleep for many weeks.
        prefs.edit().putLong(ANCHOR_KEY, now).putLong(LAST_KEY, now).commit();
        return true;
    }

    public static String description(Context context) {
        String chosen = frequency(context);
        if (NEVER.equals(chosen)) return "Nunca: los avisos solo se borran si elegís Vaciar historial.";
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long due = nextDue(prefs.getLong(ANCHOR_KEY, 0L), chosen);
        if (due <= 0) return "El plazo comienza cuando activás esta opción.";
        String time = new SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault())
                .format(new Date(due));
        return "Próximo vaciado previsto: " + time +
                ". Android puede retrasarlo; al abrir la aplicación también se comprueba.";
    }

    public static String lastAutomaticClear(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        long last = prefs.getLong(LAST_KEY, 0L);
        if (last <= 0) return "";
        return "Último vaciado automático: " +
                new SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault())
                        .format(new Date(last));
    }

    /** Offline, independent daily job: it runs even if electricity alerts are off. */
    public static synchronized void scheduleIfNeeded(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler == null) return;
        if (NEVER.equals(frequency(context))) {
            scheduler.cancel(JOB_ID);
            return;
        }
        try {
            List<JobInfo> pending = scheduler.getAllPendingJobs();
            if (pending != null) {
                for (JobInfo info : pending) if (info.getId() == JOB_ID) return;
            }
            JobInfo job = new JobInfo.Builder(JOB_ID,
                    new ComponentName(context, HistoryCleanupJobService.class))
                    .setPeriodic(DAY_MS)
                    .setPersisted(true)
                    .build();
            scheduler.schedule(job);
        } catch (RuntimeException ignored) {
            // Opening the app and saving an incoming notice still check due dates.
        }
    }
}
