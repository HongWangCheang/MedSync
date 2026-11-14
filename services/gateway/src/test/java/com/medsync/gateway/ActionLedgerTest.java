package com.medsync.gateway;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Hop ① rules: replay on same content, 409 on reused key, and re-dispatch of steps the agent never confirmed. */
class ActionLedgerTest {
    private static final String KEY = "a".repeat(64);
    private final ObjectMapper json = new ObjectMapper();
    private final AccountMapper accounts = mock(AccountMapper.class);
    private final ActionMapper actions = mock(ActionMapper.class);
    private final ActionLedger ledger = new ActionLedger(accounts, actions, json);

    private ActionLedger.Submit submit(String payload) throws Exception {
        return new ActionLedger.Submit(KEY, "plan-1", 0, "book_appointment", "IRREVERSIBLE",
            json.readTree("{\"department\":\"cardiology\"}"), json.readTree(payload), json.readTree("{}"), 1L, null);
    }

    private ActionMapper.Row row(String fingerprint, String status) {
        return new ActionMapper.Row(KEY, "plan-1", 0, "book_appointment", fingerprint,
            "{\"stepKey\":\"" + KEY + "\"}", status, null, null);
    }

    @Test
    void fingerprintIgnoresFieldOrder() throws Exception {
        assertThat(ledger.fingerprint(submit("{\"date\":\"2026-11-18\",\"department\":\"cardiology\"}")))
            .isEqualTo(ledger.fingerprint(submit("{\"department\":\"cardiology\",\"date\":\"2026-11-18\"}")));
    }

    @Test
    void newStepIsInsertedOnce() throws Exception {
        var input = submit("{\"date\":\"2026-11-18\"}");
        when(actions.find("acct", KEY)).thenReturn(null, row(ledger.fingerprint(input), "RECEIVED"));

        assertThat(ledger.record("acct", input).created()).isTrue();
        verify(accounts).lockRevision("acct");
        verify(actions).insert(eq("acct"), eq(KEY), eq("plan-1"), eq(0), eq("book_appointment"),
            eq(ledger.fingerprint(input)), anyString(), eq("RECEIVED"));
    }

    @Test
    void sameContentIsAReplayNotANewRow() throws Exception {
        var input = submit("{\"date\":\"2026-11-18\"}");
        when(actions.find("acct", KEY)).thenReturn(row(ledger.fingerprint(input), "DONE"));

        assertThat(ledger.record("acct", input).created()).isFalse();
        verify(actions, never()).insert(any(), any(), any(), anyInt(), any(), any(), any(), any());
    }

    @Test
    void reusedKeyWithDifferentContentIsAConflict() throws Exception {
        when(actions.find("acct", KEY)).thenReturn(row("f".repeat(64), "DONE"));

        assertThatThrownBy(() -> ledger.record("acct", submit("{\"date\":\"2026-11-19\"}")))
            .isInstanceOf(ResponseStatusException.class).hasMessageContaining("409");
    }

    @Test
    void rejectsMalformedStepKey() throws Exception {
        var bad = new ActionLedger.Submit("not-a-key", "plan-1", 0, "book_appointment", "IRREVERSIBLE",
            json.readTree("{}"), json.readTree("{}"), json.readTree("{}"), 1L, null);
        assertThatThrownBy(() -> ledger.record("acct", bad)).hasMessageContaining("400");
    }

    @Test
    void agentTimeoutLeavesStepAcceptedAndPollReDispatches() throws Exception {
        ActionLedger fakeLedger = mock(ActionLedger.class);
        AgentClient agent = mock(AgentClient.class);
        ActionService service = new ActionService(fakeLedger, agent, json);
        ActionMapper.Row dispatched = row("x".repeat(64), "DISPATCHED");
        when(fakeLedger.find("acct", KEY)).thenReturn(dispatched);
        when(agent.run(any(ObjectNode.class)))
            .thenThrow(new AgentClient.Unavailable(new RuntimeException("timeout")))
            .thenReturn(new AgentClient.Outcome("DONE", json.readTree("{\"bookingId\":\"b1\"}"), null));
        when(fakeLedger.settle(eq("acct"), eq(KEY), eq("DONE"), any(), isNull())).thenReturn(row("x".repeat(64), "DONE"));

        assertThat(service.status("acct", KEY).status()).isEqualTo("ACCEPTED");
        assertThat(service.status("acct", KEY).status()).isEqualTo("DONE");
        verify(agent, times(2)).run(any(ObjectNode.class));
    }

    @Test
    void finishedStepIsNeverSentToTheAgentAgain() throws Exception {
        ActionLedger fakeLedger = mock(ActionLedger.class);
        AgentClient agent = mock(AgentClient.class);
        when(fakeLedger.find("acct", KEY)).thenReturn(row("x".repeat(64), "DONE"));

        assertThat(new ActionService(fakeLedger, agent, json).status("acct", KEY).status()).isEqualTo("DONE");
        verify(agent, never()).run(any());
    }
}
