package com.kanbikang.attendance.data

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File
import java.time.LocalDate
import java.time.YearMonth
import java.util.Locale

/** 월별 기록을 엑셀에서 바로 열리는 CSV(UTF-8 BOM)로 만들고 공유 인텐트를 돌려준다. */
object CsvExporter {

    fun buildCsv(records: List<WorkRecord>): String {
        val sb = StringBuilder()
        sb.append('﻿') // 엑셀이 한글을 깨뜨리지 않도록 BOM 추가
        sb.append("날짜,요일,출근,퇴근,근무시간,근무시간(시간 단위)\n")
        var days = 0
        var totalMinutes = 0L
        for (r in records) {
            val date = LocalDate.parse(r.date)
            val minutes = Times.workedMinutes(r)
            if (r.checkIn != null) days++
            if (minutes != null) totalMinutes += minutes
            sb.append(r.date).append(',')
                .append(Times.weekdayShort(date)).append(',')
                .append(cell(Times.timeLabel(r.checkIn, date))).append(',')
                .append(cell(Times.timeLabel(r.checkOut, date))).append(',')
                .append(cell(Times.durationLabel(minutes))).append(',')
                .append(if (minutes == null) "" else String.format(Locale.US, "%.2f", minutes / 60.0))
                .append('\n')
        }
        sb.append('\n')
        sb.append("총 근무일수,").append(days).append("일\n")
        sb.append("총 근무시간,").append(Times.durationLabel(totalMinutes)).append(',')
            .append(String.format(Locale.US, "%.2f", totalMinutes / 60.0)).append('\n')
        return sb.toString()
    }

    private fun cell(v: String): String = if (v == "--") "" else v

    fun shareIntent(context: Context, ym: YearMonth, records: List<WorkRecord>): Intent {
        val dir = File(context.cacheDir, "exports").apply { mkdirs() }
        val file = File(dir, "출퇴근기록_${ym}.csv")
        file.writeText(buildCsv(records), Charsets.UTF_8)

        val uri = FileProvider.getUriForFile(context, context.packageName + ".fileprovider", file)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/csv"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, "출퇴근 기록 ${Times.monthLabel(ym)}")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        return Intent.createChooser(send, "CSV 내보내기").apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }
}
