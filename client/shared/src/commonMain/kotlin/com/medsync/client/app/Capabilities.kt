package com.medsync.client.app

/**
 * What each capability does without a network, shown on screen so the user is never surprised (the degradation
 * matrix in docs/开发计划.md §3.4). The labels describe what [MedSyncController] actually does; CapabilitiesTest
 * checks the two stay in step.
 */
enum class Availability(val label: String) {
    /** Done on the device, now. */
    OFFLINE("离线可用"),
    /** Saved on the device now, carried out by the server once online. */
    QUEUED("联网后执行"),
    /** Refused while offline. */
    ONLINE_ONLY("需要联网"),
}

data class Capability(val name: String, val availability: Availability, val note: String)

object Capabilities {
    /**
     * @param onDeviceModel the on-device model's name when one is loaded (routing and red flags), null for rules only.
     */
    fun of(onDeviceModel: String?): List<Capability> = listOf(
        Capability("理解你的话", Availability.OFFLINE,
            if (onDeviceModel != null) "本机模型 $onDeviceModel，规则兜底" else "本机规则"),
        Capability("危险信号", Availability.OFFLINE,
            if (onDeviceModel != null) "规则先判断，本机模型补充" else "本机规则"),
        Capability("记录服药和症状", Availability.OFFLINE, "先存在本机，联网后同步"),
        Capability("预约复诊", Availability.QUEUED, "联网后先确认号源还在"),
        Capability("通知家属", Availability.QUEUED, "过期的消息会先问你"),
        Capability("相互作用检查", Availability.QUEUED, "服药记录同步后补查"),
        Capability("用药问答", Availability.ONLINE_ONLY, "要检索说明书，离线不回答"),
    )

    /** One line per availability, for the panel under the title. */
    fun grouped(capabilities: List<Capability>): List<Pair<Availability, List<Capability>>> =
        Availability.entries.map { a -> a to capabilities.filter { it.availability == a } }.filter { it.second.isNotEmpty() }
}
