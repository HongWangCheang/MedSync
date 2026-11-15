package com.medsync.client

import androidx.room.Room
import com.medsync.client.app.Availability
import com.medsync.client.app.MedSyncController
import com.medsync.client.data.MedSyncDatabase
import com.medsync.client.data.buildDatabase
import com.medsync.client.outbox.ActionState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue

/**
 * The offline labels on screen must say what the app really does. Each capability is exercised offline on a real
 * controller and database (no network: the gateway address is never reached) and the outcome is checked against
 * its label: OFFLINE → done or saved now, QUEUED → waiting in the outbox, ONLINE_ONLY → refused.
 */
class CapabilitiesTest {
    private fun controller(): MedSyncController {
        val file = File.createTempFile("capabilities", ".db").apply { delete(); deleteOnExit() }
        val db = buildDatabase(Room.databaseBuilder<MedSyncDatabase>(name = file.absolutePath))
        return MedSyncController(db, "http://127.0.0.1:9", CoroutineScope(SupervisorJob() + Dispatchers.Default))
    }

    /** One sentence per capability, in the order of [com.medsync.client.app.Capabilities.of]. */
    private val sentences = mapOf(
        "理解你的话" to "我吃了布洛芬，帮我约明天的心内科",
        "危险信号" to "突然胸痛",
        "记录服药和症状" to "我吃了布洛芬",
        "预约复诊" to "帮我约明天的心内科",
        "通知家属" to "告诉女儿我吃过药了",
        "相互作用检查" to "我吃了华法林",
        "用药问答" to "布洛芬能和阿司匹林一起吃吗",
    )

    @Test
    fun labelsMatchWhatTheAppDoesOffline() = runBlocking {
        val probe = controller()
        assertEquals("every capability is exercised", sentences.keys, probe.capabilities.map { it.name }.toSet())
        for (capability in probe.capabilities) {
            val app = controller()
            app.setOffline(true)
            app.submit(sentences.getValue(capability.name)).join()
            val actions = app.actions.first()
            val what = "${capability.name} (${capability.availability.label}): notice=${app.notice.value}, " +
                "actions=${actions.map { it.tool + ":" + it.state }}"
            when (capability.availability) {
                Availability.OFFLINE -> assertTrue(what, app.redFlag.value != null || actions.isNotEmpty())
                Availability.QUEUED -> {
                    // Waiting on the device; nothing here can have been carried out.
                    assertTrue(what, actions.isNotEmpty())
                    assertTrue(what, actions.none { it.state == ActionState.DONE.name })
                }
                Availability.ONLINE_ONLY -> {
                    assertTrue(what, actions.isEmpty())
                    assertTrue(what, app.notice.value.orEmpty().contains("联网"))
                }
            }
        }
        // The understanding itself is offline: a compound sentence becomes two steps with no network.
        val app = controller().apply { setOffline(true) }
        app.submit(sentences.getValue("理解你的话")).join()
        assertEquals(listOf("record_medication", "book_appointment"), app.actions.first().sortedBy { it.stepIndex }.map { it.tool })
    }
}
