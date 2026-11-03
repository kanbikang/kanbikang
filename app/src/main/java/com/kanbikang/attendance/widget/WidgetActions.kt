package com.kanbikang.attendance.widget

import android.content.Context
import android.widget.Toast
import androidx.glance.GlanceId
import androidx.glance.action.ActionParameters
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.updateAll
import com.kanbikang.attendance.data.AttendanceRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class CheckInAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val message = AttendanceRepository.get(context).checkIn()
        AttendanceWidget().updateAll(context)
        showToast(context, message)
    }
}

class CheckOutAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val message = AttendanceRepository.get(context).checkOut()
        AttendanceWidget().updateAll(context)
        showToast(context, message)
    }
}

private suspend fun showToast(context: Context, message: String) {
    withContext(Dispatchers.Main) {
        Toast.makeText(context.applicationContext, message, Toast.LENGTH_SHORT).show()
    }
}
