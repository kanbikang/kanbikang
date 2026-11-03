package com.kanbikang.attendance.reminder

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/** 알람 시각에 호출된다. 기록이 없으면 알림을 띄우고, 다음 알람을 다시 등록한다. */
class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val type = intent.getStringExtra(ReminderScheduler.EXTRA_TYPE) ?: return
        val pendingResult = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                ReminderNotifier.notifyIfMissing(context, type)
            } finally {
                ReminderScheduler.scheduleAll(context)
                pendingResult.finish()
            }
        }
    }
}
