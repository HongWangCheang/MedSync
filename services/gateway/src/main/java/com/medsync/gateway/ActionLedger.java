package com.medsync.gateway;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/**
 * Hop ① of three (device → gateway). One ledger row per logical step, keyed by the device-generated step_key.
 *
 * <p>Same step_key + same content → replay (returns the stored row, no new work). Same step_key + different content
 * → 409, exactly like MedTrack's request-ID check, but keyed on the logical step instead of the HTTP request so a
 * step that was re-planned or re-sent after an app restart still lands on the same row.
 */
@Service
class ActionLedger {
    static final Set<String> TOOLS = Set.of(
        "record_medication", "record_symptom", "book_appointment", "notify_family", "ask_pharmacist");
    static final Set<String> OPEN = Set.of("RECEIVED", "DISPATCHED");

    record Submit(String stepKey, String planId, int stepIndex, String tool, String toolClass,
                  JsonNode identityArgs, JsonNode payload, JsonNode preconditions, long createdAtMs,
                  Long expiresAtMs, String experimentMode) {}
    /** Comparison-experiment baselines; the agent only honours them when MEDSYNC_EXPERIMENTS=1. */
    static final Set<String> EXPERIMENT_MODES = Set.of("naive", "request_id", "args_hash", "full");
    record Recorded(ActionMapper.Row row, boolean created) {}

    private final AccountMapper accounts;
    private final ActionMapper actions;
    private final ObjectMapper json;

    ActionLedger(AccountMapper accounts, ActionMapper actions, ObjectMapper json) {
        this.accounts = accounts;
        this.actions = actions;
        this.json = json;
    }

    @Transactional
    public Recorded record(String account, Submit input) {
        validate(input);
        String fingerprint = fingerprint(input);
        // Same row lock MedTrack uses for writes: serializes concurrent retries of one account's steps.
        accounts.lockRevision(account);
        ActionMapper.Row existing = actions.find(account, input.stepKey());
        if (existing != null) {
            if (!existing.fingerprint().equals(fingerprint)) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "step_key was already used for different content");
            }
            return new Recorded(existing, false);
        }
        actions.insert(account, input.stepKey(), input.planId(), input.stepIndex(), input.tool(), fingerprint,
            write(input), "RECEIVED");
        return new Recorded(actions.find(account, input.stepKey()), true);
    }

    public ActionMapper.Row find(String account, String stepKey) {
        ActionMapper.Row row = actions.find(account, stepKey);
        if (row == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown step");
        }
        return row;
    }

    public ActionMapper.Row settle(String account, String stepKey, String status, JsonNode result, String reason) {
        actions.updateOutcome(account, stepKey, status, result == null || result.isNull() ? null : write(result),
            reason == null ? null : reason.substring(0, Math.min(reason.length(), 500)));
        return actions.find(account, stepKey);
    }

    /** Content identity of a step: tool, position in its plan, and the canonical payload. */
    String fingerprint(Submit input) {
        return SyncAuth.digest(input.tool() + "\n" + input.planId() + "\n" + input.stepIndex() + "\n" +
            canonical(input.payload()));
    }

    private void validate(Submit input) {
        if (input == null || input.stepKey() == null || !input.stepKey().matches("[0-9a-f]{64}") ||
                input.planId() == null || input.planId().isBlank() || input.planId().length() > 64 ||
                input.stepIndex() < 0 || input.tool() == null || !TOOLS.contains(input.tool()) ||
                input.payload() == null || !input.payload().isObject() ||
                (input.experimentMode() != null && !EXPERIMENT_MODES.contains(input.experimentMode()))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid action");
        }
    }

    /** Key-sorted JSON so the same content always hashes the same, whatever order the client serialized it in. */
    String canonical(JsonNode node) {
        return write(sorted(node));
    }

    private JsonNode sorted(JsonNode node) {
        if (node.isObject()) {
            Map<String, JsonNode> fields = new TreeMap<>();
            for (Iterator<Map.Entry<String, JsonNode>> it = node.fields(); it.hasNext(); ) {
                Map.Entry<String, JsonNode> field = it.next();
                fields.put(field.getKey(), sorted(field.getValue()));
            }
            ObjectNode out = json.createObjectNode();
            fields.forEach(out::set);
            return out;
        }
        if (node.isArray()) {
            ArrayNode out = json.createArrayNode();
            node.forEach(item -> out.add(sorted(item)));
            return out;
        }
        return node;
    }

    private String write(Object value) {
        try {
            return json.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
