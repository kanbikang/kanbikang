package com.kanbikang.attendance.data

import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.YearMonth
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

/** 날짜·시각 계산과 표시 형식을 한곳에 모은 도우미. */
object Times {
    private val timeFmt: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")

    val zone: ZoneId get() = ZoneId.systemDefault()

    fun now(): LocalDateTime = LocalDateTime.now(zone)

    fun toLocalDateTime(ms: Long): LocalDateTime = Instant.ofEpochMilli(ms).atZone(zone).toLocalDateTime()

    fun toMillis(ldt: LocalDateTime): Long = ldt.atZone(zone).toInstant().toEpochMilli()

    fun hhmm(ms: Long): String = toLocalDateTime(ms).format(timeFmt)

    fun hhmm(t: LocalTime): String = t.format(timeFmt)

    /** "08:52", 다음날이면 "익일 01:10", 없으면 "--" */
    fun timeLabel(ms: Long?, recordDate: LocalDate): String {
        if (ms == null) return "--"
        val ldt = toLocalDateTime(ms)
        val text = ldt.format(timeFmt)
        return if (ldt.toLocalDate() != recordDate) "익일 $text" else text
    }

    /** 출근·퇴근이 모두 있고 순서가 맞을 때만 근무 분(minute)을 돌려준다. */
    fun workedMinutes(record: WorkRecord): Long? {
        val start = record.checkIn ?: return null
        val end = record.checkOut ?: return null
        if (end <= start) return null
        return Duration.ofMillis(end - start).toMinutes()
    }

    fun durationLabel(minutes: Long?): String {
        if (minutes == null) return "--"
        return String.format(Locale.KOREA, "%d시간 %02d분", minutes / 60, minutes % 60)
    }

    fun weekdayShort(d: LocalDate): String = d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.KOREAN)

    /** "11/3 (월)" */
    fun dateLabel(d: LocalDate): String = "${d.monthValue}/${d.dayOfMonth} (${weekdayShort(d)})"

    /** "2026년 11월" */
    fun monthLabel(ym: YearMonth): String = "${ym.year}년 ${ym.monthValue}월"
}
