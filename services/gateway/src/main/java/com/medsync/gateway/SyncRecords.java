package com.medsync.gateway;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
class SyncRecords {
    record Write(UUID recordId, String kind, Map<String, String> body) {}
    record Receipt(long revision) {}
    record Change(UUID recordId, String kind, JsonNode body, long revision) {}
    record Page(List<Change> changes, long nextCursor, boolean hasMore) {}
    private static final Map<String, Map<String, Integer>> LIMITS = Map.of(
        "medication", Map.of("name", 160, "dosage", 120, "frequency", 80,
                            "time", 80, "type", 80, "notes", 4000),
        "symptom", Map.of("category", 160, "severity", 80, "dateTime", 100, "notes", 4000)
    );

    private final AccountMapper accounts;
    private final RecordMapper records;
    private final ObjectMapper json;

    SyncRecords(AccountMapper accounts, RecordMapper records, ObjectMapper json) {
        this.accounts = accounts;
        this.records = records;
        this.json = json;
    }

    @Transactional
    public Receipt write(String account, UUID requestId, Write input) {
        String body = validatedBody(input);
        String recordId = input.recordId().toString();
        String fingerprint = SyncAuth.digest(input.kind() + "\n" + recordId + "\n" + body);

        // The account row serializes writes and cursor allocation in commit order.
        Long current = accounts.lockRevision(account);
        RecordMapper.RequestReceipt receipt = records.findRequest(account, requestId.toString());
        if (receipt != null) {
            if (!receipt.fingerprint().equals(fingerprint)) {
                throw conflict("Request ID was already used for different data");
            }
            return new Receipt(receipt.revision());
        }

        if (records.countRecord(account, recordId) > 0) {
            throw conflict("Record ID already exists");
        }
        long revision = current + 1;
        accounts.updateRevision(account, revision);
        records.insertRecord(account, recordId, input.kind(), body, revision);
        records.insertRequest(account, requestId.toString(), fingerprint, revision);
        return new Receipt(revision);
    }

    public Page changes(String account, long after, int limit) {
        if (after < 0 || limit < 1 || limit > 100) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid cursor or page size");
        }
        List<Change> rows = records.changesAfter(account, after, limit + 1).stream()
            .map(row -> new Change(UUID.fromString(row.recordId()), row.kind(), parse(row.body()), row.revision()))
            .toList();
        boolean hasMore = rows.size() > limit;
        List<Change> page = hasMore ? rows.subList(0, limit) : rows;
        return new Page(page, page.isEmpty() ? after : page.getLast().revision(), hasMore);
    }

    private String validatedBody(Write input) {
        Map<String, Integer> limits = input == null || input.kind() == null ? null : LIMITS.get(input.kind());
        if (limits == null || input.recordId() == null || input.body() == null ||
                !input.body().keySet().equals(limits.keySet())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid record format");
        }
        for (var field : limits.entrySet()) {
            String value = input.body().get(field.getKey());
            if (value == null || value.length() > field.getValue()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid record field");
            }
        }
        try {
            return json.writeValueAsString(new TreeMap<>(input.body()));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException(exception);
        }
    }

    private JsonNode parse(String body) {
        try {
            return json.readTree(body);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException(exception);
        }
    }

    private ResponseStatusException conflict(String message) {
        return new ResponseStatusException(HttpStatus.CONFLICT, message);
    }
}
