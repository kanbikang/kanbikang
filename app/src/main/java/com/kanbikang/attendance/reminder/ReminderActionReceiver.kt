package com.kanbikang.attendance.reminder

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.glance.appwidget.updateAll
import com.kanbikang.attendance.data.AttendanceRepository
import com.kanbikang.attendance.widget.AttendanceWidget
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 알림의 "지금 기록" 버튼을 눌렀을 때 실행된다. */
class ReminderActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        val pendingResult = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val repo = AttendanceRepository.get(context)
                val message = when (action) {
                    ACTION_CHECK_IN -> {
                        ReminderNotifier.cancel(context, ReminderNotifier.NOTIFICATION_ID_CHECK_IN)
                        repo.checkIn()
                    }
                    ACTION_CHECK_OUT -> {
                        ReminderNotifier.cancel(context, ReminderNotifier.NOTIFICATION_ID_CHECK_OUT)
                        repo.checkOut()
                    }
                    else -> return@launch
                }
                AttendanceWidget().updateAll(context)
                withContext(Dispatchers.Main) {
                    Toast.makeText(context.applicationContext, message, Toast.LENGTH_SHORT).show()
                }
            } finally {
                pendingResult.finish()
            }
        }
    }

    companion object {
        const val ACTION_CHECK_IN = "com.kanbikang.attendance.RECORD_CHECK_IN"
        const val ACTION_CHECK_OUT = "com.kanbikang.attendance.RECORD_CHECK_OUT"
    }
}
