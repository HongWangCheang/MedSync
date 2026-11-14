package com.medsync.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.Filter;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.util.ContentCachingResponseWrapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {
        "spring.datasource.url=${MEDTRACK_SYNC_TEST_DB_URL}",
        "spring.datasource.username=${MEDTRACK_SYNC_TEST_DB_USER}",
        "spring.datasource.password=${MEDTRACK_SYNC_TEST_DB_PASSWORD}"
    })
class SyncMySqlTest {
    private static final Duration NORMAL_TIMEOUT = Duration.ofSeconds(10);
    private static final String PASSWORD = "fictional-sync-pass";
    private final HttpClient client = HttpClient.newHttpClient();
    @LocalServerPort int port;
    @Autowired JdbcTemplate db;
    @Autowired ObjectMapper json;
    @Autowired ResponseGate gate;

    @Test
    void committedWriteSurvivesClientTimeoutAndRetryWithoutDuplicate() throws Exception {
        JsonNode session = account();
        String account = session.path("accountId").asText();
        String token = session.path("token").asText();
        String requestId = UUID.randomUUID().toString();
        String recordId = UUID.randomUUID().toString();
        String path = "/v1/sync/writes/" + requestId;
        String payload = medication(recordId, "Demo plan");

        var first = client.sendAsync(request(path, "PUT", token, payload, Duration.ofSeconds(2), true),
            HttpResponse.BodyHandlers.ofString());
        try {
            assertThat(gate.committed.await(5, TimeUnit.SECONDS)).isTrue();
            assertThat(count("sync_record", account)).isEqualTo(1);
            assertThat(count("sync_request", account)).isEqualTo(1);
            CompletionException timeout = assertThrows(CompletionException.class, first::join);
            assertThat(timeout.getCause()).isInstanceOf(HttpTimeoutException.class);

            HttpResponse<String> retry = send(path, "PUT", token, payload);
            assertThat(retry.statusCode()).isEqualTo(200);
            assertThat(json.readTree(retry.body()).path("revision").asLong()).isEqualTo(1);
            assertThat(count("sync_record", account)).isEqualTo(1);
            assertThat(count("sync_request", account)).isEqualTo(1);
            assertThat(send(path, "PUT", token, medication(recordId, "Changed body")).statusCode()).isEqualTo(409);
            JsonNode firstPage = json.readTree(send("/v1/sync/changes?after=0", "GET", token, null).body());
            assertThat(firstPage.path("changes").size()).isEqualTo(1);
            assertThat(firstPage.path("changes").get(0).path("recordId").asText()).isEqualTo(recordId);
            assertThat(firstPage.path("nextCursor").asLong()).isEqualTo(1);
        } finally {
            gate.release.countDown();
        }
    }

    @Test
    void simultaneousRetriesUseSameRevisionAndPaginationIsAccountScoped() throws Exception {
        JsonNode session = account();
        String token = session.path("token").asText();
        String account = session.path("accountId").asText();
        String recordId = UUID.randomUUID().toString();
        String path = "/v1/sync/writes/" + UUID.randomUUID();
        String payload = medication(recordId, "Synthetic plan A");
        var first = client.sendAsync(request(path, "PUT", token, payload, NORMAL_TIMEOUT, false),
            HttpResponse.BodyHandlers.ofString());
        var second = client.sendAsync(request(path, "PUT", token, payload, NORMAL_TIMEOUT, false),
            HttpResponse.BodyHandlers.ofString());
        for (var response : List.of(first.join(), second.join())) {
            assertThat(response.statusCode()).isEqualTo(200);
            assertThat(json.readTree(response.body()).path("revision").asLong()).isEqualTo(1);
        }
        assertThat(count("sync_record", account)).isEqualTo(1);
        assertThat(send("/v1/sync/writes/" + UUID.randomUUID(), "PUT", token, payload).statusCode()).isEqualTo(409);
        assertThat(send("/v1/sync/writes/" + UUID.randomUUID(), "PUT", token,
            medication(UUID.randomUUID().toString(), "Synthetic plan B")).statusCode()).isEqualTo(200);

        var page1 = json.readTree(send("/v1/sync/changes?after=0&limit=1", "GET", token, null).body());
        var page2 = json.readTree(send("/v1/sync/changes?after=1&limit=1", "GET", token, null).body());
        assertThat(page1.path("nextCursor").asLong()).isEqualTo(1);
        assertThat(page1.path("hasMore").asBoolean()).isTrue();
        assertThat(page2.path("nextCursor").asLong()).isEqualTo(2);
        assertThat(page2.path("hasMore").asBoolean()).isFalse();
        assertThat(send("/v1/sync/changes", "GET", null, null).statusCode()).isEqualTo(401);

        var other = account().path("token").asText();
        var isolated = json.readTree(send("/v1/sync/changes", "GET", other, null).body());
        assertThat(isolated.path("changes").size()).isZero();
    }

    private int count(String table, String account) {
        return db.queryForObject("SELECT COUNT(*) FROM " + table + " WHERE account_id = ?", Integer.class, account);
    }

    private JsonNode account() throws Exception {
        String payload = json.writeValueAsString(Map.of("username", "demo" + UUID.randomUUID(),
            "password", PASSWORD));
        var response = send("/v1/auth/register", "POST", null, payload);
        assertThat(response.statusCode()).isEqualTo(201);
        var login = send("/v1/auth/login", "POST", null, payload);
        assertThat(login.statusCode()).isEqualTo(200);
        assertThat(json.readTree(login.body()).path("accountId")).isEqualTo(json.readTree(response.body()).path("accountId"));
        return json.readTree(login.body());
    }

    private String medication(String id, String name) throws Exception {
        return json.writeValueAsString(Map.of("recordId", id, "kind", "medication", "body",
            Map.of("name", name, "dosage", "fixture", "frequency", "fixture", "time", "09:00", "type", "fixture", "notes", "")));
    }

    private HttpResponse<String> send(String path, String method, String token, String body) throws Exception {
        return client.send(request(path, method, token, body, NORMAL_TIMEOUT, false),
            HttpResponse.BodyHandlers.ofString());
    }

    private HttpRequest request(String path, String method, String token, String body, Duration timeout, boolean loseResponse) {
        var builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path)).timeout(timeout);
        if (token != null) builder.header("Authorization", "Bearer " + token);
        if (loseResponse) builder.header("X-Test-Hold-Response", "1");
        if (body != null) builder.header("Content-Type", "application/json");
        return builder.method(method, body == null ? HttpRequest.BodyPublishers.noBody()
            : HttpRequest.BodyPublishers.ofString(body)).build();
    }

    @TestConfiguration
    static class TestFilters {
        @Bean ResponseGate responseGate() { return new ResponseGate(); }

        @Bean Filter holdCommittedResponse(ResponseGate gate) {
            return (request, response, chain) -> {
                if (!"1".equals(((HttpServletRequest) request).getHeader("X-Test-Hold-Response"))) {
                    chain.doFilter(request, response);
                    return;
                }
                var wrapped = new ContentCachingResponseWrapper((HttpServletResponse) response);
                chain.doFilter(request, wrapped);
                gate.committed.countDown();
                try {
                    gate.release.await(12, TimeUnit.SECONDS);
                    wrapped.copyBodyToResponse();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            };
        }
    }

    static class ResponseGate {
        final CountDownLatch committed = new CountDownLatch(1);
        final CountDownLatch release = new CountDownLatch(1);
    }
}
