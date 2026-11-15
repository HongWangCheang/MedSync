package com.medsync.gateway;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.server.ResponseStatusException;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Least privilege: a delegated token reads medications for ~2 minutes and can do nothing else. */
class DelegationTest {
    private final DelegationMapper mapper = mock(DelegationMapper.class);
    private final Delegation delegation = new Delegation(mapper, mock(RateLimiter.class));

    @Test
    void issuedTokenIsStoredOnlyAsAHashWithScopeAndShortTtl() {
        String token = delegation.issue("acct", Delegation.MEDICATIONS_READ);
        assertThat(token).matches("dlg_[A-Za-z0-9_-]{43}");
        verify(mapper).deleteExpired();
        verify(mapper).insert(SyncAuth.digest(token), "acct", Delegation.MEDICATIONS_READ, 120);
    }

    @Test
    void delegatedTokenNeverPassesTheNormalBearerFormat() {
        String token = delegation.issue("acct", Delegation.MEDICATIONS_READ);
        // SyncAuth.requireAccount only accepts "Bearer " + exactly 43 chars; a delegated token is 47.
        assertThat(("Bearer " + token).matches("Bearer [a-zA-Z0-9_-]{43}")).isFalse();
    }

    @Test
    void verificationNeedsTheRightFormatScopeAndAnUnexpiredRow() {
        String token = delegation.issue("acct", Delegation.MEDICATIONS_READ);
        when(mapper.findAccount(SyncAuth.digest(token), Delegation.MEDICATIONS_READ)).thenReturn("acct");

        assertThat(delegation.requireAccount("Bearer " + token, Delegation.MEDICATIONS_READ)).isEqualTo("acct");
        assertThatThrownBy(() -> delegation.requireAccount("Bearer " + token, "actions:write"))
            .isInstanceOf(ResponseStatusException.class).hasMessageContaining("401");
        assertThatThrownBy(() -> delegation.requireAccount("Bearer " + "a".repeat(43), Delegation.MEDICATIONS_READ))
            .hasMessageContaining("401");  // a normal session token is not a delegation
        assertThatThrownBy(() -> delegation.requireAccount(null, Delegation.MEDICATIONS_READ))
            .hasMessageContaining("401");
    }

    @Test
    void onlyPharmacistAndMedicationRecordDispatchesCarryADelegation() throws Exception {
        ObjectMapper json = new ObjectMapper();
        ActionLedger ledger = mock(ActionLedger.class);
        AgentClient agent = mock(AgentClient.class);
        Delegation issuer = mock(Delegation.class);
        when(issuer.issue("acct", Delegation.MEDICATIONS_READ)).thenReturn("dlg_token");
        ActionService service = new ActionService(ledger, agent, issuer, json);
        when(agent.run(any(ObjectNode.class), any())).thenReturn(new AgentClient.Outcome("PENDING", null, null));

        for (String tool : new String[] {"book_appointment", "ask_pharmacist", "record_medication", "notify_family"}) {
            ActionMapper.Row row = new ActionMapper.Row(tool, "p", 0, tool, "f", "{\"tool\":\"" + tool + "\"}",
                "DISPATCHED", null, null);
            when(ledger.find("acct", tool)).thenReturn(row);
            service.status("acct", tool);
        }
        ArgumentCaptor<ObjectNode> plain = ArgumentCaptor.forClass(ObjectNode.class);
        verify(agent, times(2)).run(plain.capture(), isNull());
        assertThat(plain.getAllValues()).extracting(b -> b.get("tool").asText())
            .containsExactly("book_appointment", "notify_family");
        ArgumentCaptor<ObjectNode> delegated = ArgumentCaptor.forClass(ObjectNode.class);
        verify(agent, times(2)).run(delegated.capture(), eq("dlg_token"));
        assertThat(delegated.getAllValues()).extracting(b -> b.get("tool").asText())
            .containsExactly("ask_pharmacist", "record_medication");
        verify(issuer, times(2)).issue("acct", Delegation.MEDICATIONS_READ);
        assertThat(delegated.getAllValues()).noneMatch(b -> b.has("delegation"));  // never in the body → never persisted
        verify(issuer, never()).issue(eq("acct"), eq("actions:write"));
        verify(mapper, never()).insert(anyString(), anyString(), anyString(), any(Long.class));
    }

    @Test
    void aDecisionWhoseAnswerIsLostLeavesTheStepMovingNotWaitingForTheUserAgain() {
        // Found by eval/run_matrix.py: the agent was killed while sending the message the user had just approved.
        ObjectMapper json = new ObjectMapper();
        ActionLedger ledger = mock(ActionLedger.class);
        AgentClient agent = mock(AgentClient.class);
        ActionService service = new ActionService(ledger, agent, mock(Delegation.class), json);
        ActionMapper.Row waiting = new ActionMapper.Row("k", "p", 1, "notify_family", "f", "{}", "NEEDS_USER", null,
            "conflict_with_later_finding");
        ActionMapper.Row moving = new ActionMapper.Row("k", "p", 1, "notify_family", "f", "{}", "DISPATCHED", null, null);
        when(ledger.find("acct", "k")).thenReturn(waiting);
        when(ledger.settle("acct", "k", "DISPATCHED", null, null)).thenReturn(moving);
        when(agent.resume(eq("k"), any())).thenThrow(new AgentClient.Unavailable(new RuntimeException("reset")));

        ActionService.View view = service.resume("acct", "k", json.createObjectNode().put("decision", "send_with_note"));

        assertThat(view.status()).isEqualTo("ACCEPTED");  // not NEEDS_USER: the app must not ask again
        verify(ledger).settle("acct", "k", "DISPATCHED", null, null);
    }
}
