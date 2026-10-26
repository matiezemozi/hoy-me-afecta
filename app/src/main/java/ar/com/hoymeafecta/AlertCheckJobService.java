package ar.com.hoymeafecta;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Best-effort periodic check. Android can defer jobs because of battery limits. */
public class AlertCheckJobService extends JobService {
    public static final int JOB_ID = 30553;
    private volatile boolean stopped;

    public static void scheduleIfNeeded(Context context) {
        SharedPreferences p = context.getSharedPreferences("hoy_me_afecta", Context.MODE_PRIVATE);
        if (!p.getBoolean("notifications_enabled", false)) return;
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler == null) return;
        for (JobInfo existing : scheduler.getAllPendingJobs()) {
            if (existing.getId() == JOB_ID) return;
        }
        JobInfo job = new JobInfo.Builder(JOB_ID,
                new ComponentName(context, AlertCheckJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(30L * 60L * 1000L)
                .setPersisted(true).build();
        scheduler.schedule(job);
    }

    public static boolean isScheduled(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler == null) return false;
        try {
            for (JobInfo job : scheduler.getAllPendingJobs()) {
                if (job.getId() == JOB_ID) return true;
            }
        } catch (RuntimeException ignored) { return false; }
        return false;
    }

    public static String lastBackgroundCheck(Context context) {
        SharedPreferences p = context.getSharedPreferences("hoy_me_afecta", Context.MODE_PRIVATE);
        long when = p.getLong("last_background_check_ms", 0L);
        if (when <= 0) return "Todavia no se registro una comprobacion en segundo plano.";
        String timestamp = new SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault())
                .format(new Date(when));
        return "Ultima comprobacion automatica: " + timestamp + " - " +
                p.getString("last_background_result", "sin resultado");
    }

    public static void cancel(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler != null) scheduler.cancel(JOB_ID);
    }

    @Override public boolean onStartJob(JobParameters params) {
        stopped = false;
        new Thread(() -> {
            try {
                if (!stopped) {
                    String result = AlertNotifier.fetchAndProcess(getApplicationContext());
                    if (!stopped) {
                        getSharedPreferences("hoy_me_afecta", Context.MODE_PRIVATE).edit()
                                .putLong("last_background_check_ms", System.currentTimeMillis())
                                .putString("last_background_result", result).apply();
                    }
                }
            } finally {
                if (!stopped) jobFinished(params, false);
            }
        }, "HMA-alert-check").start();
        return true;
    }

    @Override public boolean onStopJob(JobParameters params) {
        stopped = true;
        return true;
    }
}
