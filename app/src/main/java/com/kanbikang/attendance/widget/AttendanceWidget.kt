package com.kanbikang.attendance.widget

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.action.Action
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxHeight
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextAlign
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import com.kanbikang.attendance.data.AttendanceRepository
import com.kanbikang.attendance.data.WidgetState
import com.kanbikang.attendance.ui.MainActivity

class AttendanceWidget : GlanceAppWidget() {

    override val sizeMode: SizeMode = SizeMode.Single

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val state = AttendanceRepository.get(context).widgetState()
        provideContent { WidgetContent(state) }
    }
}

private val Background = Color(0xFFF7F7F7)
private val TextDark = Color(0xFF212121)
private val TextMuted = Color(0xFF6B6B6B)
private val CheckInColor = Color(0xFF2E7D32)
private val CheckOutColor = Color(0xFF1565C0)

@Composable
private fun WidgetContent(state: WidgetState) {
    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .background(Background)
            .cornerRadius(20.dp)
            .padding(12.dp),
    ) {
        Row(
            modifier = GlanceModifier
                .fillMaxWidth()
                .clickable(actionStartActivity<MainActivity>()),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = state.title,
                style = TextStyle(fontSize = 14.sp, color = ColorProvider(TextMuted)),
            )
            Spacer(modifier = GlanceModifier.defaultWeight())
            Text(
                text = "출근 ${state.checkIn}",
                style = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.Bold, color = ColorProvider(TextDark)),
            )
            Spacer(modifier = GlanceModifier.width(12.dp))
            Text(
                text = "퇴근 ${state.checkOut}",
                style = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.Bold, color = ColorProvider(TextDark)),
            )
        }
        Spacer(modifier = GlanceModifier.height(10.dp))
        Row(modifier = GlanceModifier.fillMaxWidth().defaultWeight()) {
            BigButton(
                label = "출근",
                color = CheckInColor,
                action = actionRunCallback<CheckInAction>(),
                modifier = GlanceModifier.defaultWeight(),
            )
            Spacer(modifier = GlanceModifier.width(10.dp))
            BigButton(
                label = "퇴근",
                color = CheckOutColor,
                action = actionRunCallback<CheckOutAction>(),
                modifier = GlanceModifier.defaultWeight(),
            )
        }
    }
}

@Composable
private fun BigButton(label: String, color: Color, action: Action, modifier: GlanceModifier) {
    Box(
        modifier = modifier
            .fillMaxHeight()
            .background(color)
            .cornerRadius(16.dp)
            .clickable(action),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            style = TextStyle(
                color = ColorProvider(Color.White),
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center,
            ),
        )
    }
}
