package com.kanbikang.attendance.data

/** 위젯에 보여줄 오늘의 요약. */
data class WidgetState(
    val title: String,
    val checkIn: String,
    val checkOut: String,
)
