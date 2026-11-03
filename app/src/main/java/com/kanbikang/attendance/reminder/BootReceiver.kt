package com.kanbikang.attendance.reminder

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** 재부팅, 앱 업데이트, 정확한 알람 권한 변경 뒤에 알람을 다시 등록한다. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        ReminderScheduler.scheduleAll(context)
    }
}
