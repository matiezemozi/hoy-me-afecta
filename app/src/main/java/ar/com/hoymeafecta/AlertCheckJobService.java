package ar.com.hoymeafecta;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;

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

    public static void cancel(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler != null) scheduler.cancel(JOB_ID);
    }

    @Override public boolean onStartJob(JobParameters params) {
        stopped = false;
        new Thread(() -> {
            if (!stopped) AlertNotifier.fetchAndProcess(getApplicationContext());
            if (!stopped) jobFinished(params, false);
        }, "HMA-alert-check").start();
        return true;
    }

    @Override public boolean onStopJob(JobParameters params) {
        stopped = true;
        return true;
    }
}
