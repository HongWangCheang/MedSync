package com.medsync.client.outbox

/** How dangerous it is to run a tool twice. Drives retry policy and what happens offline. */
enum class ToolClass { READ, WRITE_IDEMPOTENT, IRREVERSIBLE }

/** What a capability does while the device has no network (the degradation matrix). */
enum class OfflineBehaviour {
    /** Completes on the device; synced later. */
    LOCAL,
    /** Queued in the outbox and executed (after revalidation) once online. */
    QUEUED,
    /** Refused offline: without retrieved evidence the answer could be wrong, so don't answer at all. */
    REFUSED,
}

/**
 * @param identityFields the payload fields that decide "is this the same step?". Free text (notes, the message
 *   wording) is excluded on purpose: an LLM re-planning the same step rarely phrases it identically.
 * @param version bumped when the tool's contract changes; the agent refuses steps planned against an old version.
 */
data class ToolSpec(
    val name: String,
    val label: String,
    val toolClass: ToolClass,
    val offline: OfflineBehaviour,
    val identityFields: List<String>,
    val version: String = "v1",
    val ttlMs: Long? = null,
)

object Tools {
    private const val HOUR = 3_600_000L

    val all: Map<String, ToolSpec> = listOf(
        ToolSpec("record_medication", "记录服药", ToolClass.WRITE_IDEMPOTENT, OfflineBehaviour.LOCAL,
            listOf("name", "takenAt")),
        ToolSpec("record_symptom", "记录症状", ToolClass.WRITE_IDEMPOTENT, OfflineBehaviour.LOCAL,
            listOf("category", "recordedAt")),
        ToolSpec("book_appointment", "预约复诊", ToolClass.IRREVERSIBLE, OfflineBehaviour.QUEUED,
            listOf("patient_id", "department", "date")),
        ToolSpec("notify_family", "通知家属", ToolClass.IRREVERSIBLE, OfflineBehaviour.QUEUED,
            listOf("to"), ttlMs = 6 * HOUR),
        ToolSpec("ask_pharmacist", "用药问答", ToolClass.READ, OfflineBehaviour.REFUSED, listOf("question")),
    ).associateBy { it.name }

    operator fun get(name: String): ToolSpec = all[name] ?: error("unknown tool: $name")
}
