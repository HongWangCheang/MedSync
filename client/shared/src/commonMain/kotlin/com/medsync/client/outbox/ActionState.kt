package com.medsync.client.outbox

/**
 * Lifecycle of one outbox row.
 *
 *     PENDING ─send─▶ SENDING ─┬─ DONE
 *        ▲                     ├─ ACKED (gateway has it, outcome not final) ─poll─▶ DONE / NEEDS_USER / FAILED
 *        │                     ├─ NEEDS_USER (stale / conflict) ─user─▶ PENDING / CANCELLED
 *        └── RETRY_WAIT ◀──────┴─ transient error (network, timeout, 429, 5xx)
 *     BLOCKED (parent not DONE) ─parent done─▶ PENDING ; parent FAILED/CANCELLED ─▶ NEEDS_USER
 */
enum class ActionState {
    PENDING, BLOCKED, SENDING, RETRY_WAIT, ACKED, DONE, NEEDS_USER, FAILED, CANCELLED;

    val terminal: Boolean get() = this == DONE || this == FAILED || this == CANCELLED
}

sealed interface ActionEvent {
    data object Send : ActionEvent
    data object ParentDone : ActionEvent
    data object ParentFailed : ActionEvent
    data object Accepted : ActionEvent
    data object Done : ActionEvent
    data object NeedsUser : ActionEvent
    data object Failed : ActionEvent
    data object Cancelled : ActionEvent
    data object TransientError : ActionEvent
    data object RetryDue : ActionEvent
    data object UserConfirmed : ActionEvent
}

class IllegalTransition(state: ActionState, event: ActionEvent) :
    IllegalStateException("$event is not allowed in $state")

object ActionStateMachine {
    fun next(state: ActionState, event: ActionEvent): ActionState = when (state) {
        ActionState.PENDING -> when (event) {
            ActionEvent.Send -> ActionState.SENDING
            ActionEvent.ParentFailed -> ActionState.NEEDS_USER
            else -> throw IllegalTransition(state, event)
        }
        ActionState.BLOCKED -> when (event) {
            ActionEvent.ParentDone -> ActionState.PENDING
            ActionEvent.ParentFailed -> ActionState.NEEDS_USER
            else -> throw IllegalTransition(state, event)
        }
        ActionState.SENDING, ActionState.ACKED -> when (event) {
            ActionEvent.Accepted -> ActionState.ACKED
            ActionEvent.Done -> ActionState.DONE
            ActionEvent.NeedsUser -> ActionState.NEEDS_USER
            ActionEvent.Failed -> ActionState.FAILED
            ActionEvent.Cancelled -> ActionState.CANCELLED
            ActionEvent.TransientError -> if (state == ActionState.ACKED) ActionState.ACKED else ActionState.RETRY_WAIT
            ActionEvent.Send -> if (state == ActionState.ACKED) ActionState.SENDING else throw IllegalTransition(state, event)
            else -> throw IllegalTransition(state, event)
        }
        ActionState.RETRY_WAIT -> when (event) {
            ActionEvent.RetryDue -> ActionState.PENDING
            ActionEvent.ParentFailed -> ActionState.NEEDS_USER
            else -> throw IllegalTransition(state, event)
        }
        ActionState.NEEDS_USER -> when (event) {
            ActionEvent.UserConfirmed -> ActionState.PENDING
            ActionEvent.Done -> ActionState.DONE
            ActionEvent.Accepted -> ActionState.ACKED
            ActionEvent.Cancelled -> ActionState.CANCELLED
            ActionEvent.Failed -> ActionState.FAILED
            ActionEvent.NeedsUser, ActionEvent.ParentFailed -> ActionState.NEEDS_USER
            else -> throw IllegalTransition(state, event)
        }
        ActionState.DONE, ActionState.FAILED, ActionState.CANCELLED -> throw IllegalTransition(state, event)
    }
}
