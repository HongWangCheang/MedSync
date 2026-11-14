package com.medsync.gateway;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * Records a step, then hands it to the agent outside the database transaction. A step left RECEIVED/DISPATCHED
 * (gateway crash, agent timeout) is re-dispatched the next time the device submits or polls it.
 */
@Service
class ActionService {
    /** What the device sees. ACCEPTED means "safe to poll later", never "done". */
    record View(String stepKey, String status, JsonNode result, String reason) {}

    private static final Set<String> AGENT_STATUSES = Set.of("DONE", "NEEDS_USER", "FAILED", "CANCELLED", "PENDING");

    private final ActionLedger ledger;
    private final AgentClient agent;
    private final ObjectMapper json;

    ActionService(ActionLedger ledger, AgentClient agent, ObjectMapper json) {
        this.ledger = ledger;
        this.agent = agent;
        this.json = json;
    }

    View submit(String account, ActionLedger.Submit input) {
        ActionMapper.Row row = ledger.record(account, input).row();
        return ActionLedger.OPEN.contains(row.status()) ? dispatch(account, row) : view(row);
    }

    View status(String account, String stepKey) {
        ActionMapper.Row row = ledger.find(account, stepKey);
        return ActionLedger.OPEN.contains(row.status()) ? dispatch(account, row) : view(row);
    }

    View resume(String account, String stepKey, ObjectNode decision) {
        ActionMapper.Row row = ledger.find(account, stepKey);
        if (!"NEEDS_USER".equals(row.status())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Step is not waiting for the user");
        }
        decision.put("account_id", account);
        try {
            return settle(account, row, agent.resume(stepKey, decision));
        } catch (AgentClient.Unavailable unavailable) {
            return view(row);
        }
    }

    private View dispatch(String account, ActionMapper.Row row) {
        if ("RECEIVED".equals(row.status())) {
            row = ledger.settle(account, row.stepKey(), "DISPATCHED", null, null);
        }
        ObjectNode request = (ObjectNode) parse(row.request());
        request.put("account_id", account);
        try {
            return settle(account, row, agent.run(request));
        } catch (AgentClient.Unavailable unavailable) {
            return view(row);
        }
    }

    private View settle(String account, ActionMapper.Row row, AgentClient.Outcome outcome) {
        if (outcome == null || !AGENT_STATUSES.contains(outcome.status())) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Agent returned an unknown status");
        }
        if ("PENDING".equals(outcome.status())) {
            return view(row);  // the agent could not confirm the side effect yet; stay DISPATCHED and re-ask later
        }
        return view(ledger.settle(account, row.stepKey(), outcome.status(), outcome.result(), outcome.reason()));
    }

    private View view(ActionMapper.Row row) {
        String status = ActionLedger.OPEN.contains(row.status()) ? "ACCEPTED" : row.status();
        return new View(row.stepKey(), status, row.result() == null ? null : parse(row.result()), row.reason());
    }

    private JsonNode parse(String body) {
        try {
            return json.readTree(body);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
