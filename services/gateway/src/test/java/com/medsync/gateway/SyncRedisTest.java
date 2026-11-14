package com.medsync.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.data.redis.core.StringRedisTemplate;
import static org.assertj.core.api.Assertions.assertThat;

/** Real MySQL + real Redis, with small limits so the 429 path is reachable. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {
        "spring.datasource.url=${MEDTRACK_SYNC_TEST_DB_URL}",
        "spring.datasource.username=${MEDTRACK_SYNC_TEST_DB_USER}",
        "spring.datasource.password=${MEDTRACK_SYNC_TEST_DB_PASSWORD}",
        "medtrack.rate-limit.requests-per-minute=3",
        "medtrack.rate-limit.logins-per-minute=2"
    })
class SyncRedisTest {
    private final HttpClient client = HttpClient.newHttpClient();
    @LocalServerPort int port;
    @Autowired ObjectMapper json;
    @Autowired StringRedisTemplate redis;

    @BeforeEach
    void stayInsideOneWindow() throws InterruptedException {
        // Counters use one-minute windows; don't let a test straddle a boundary and see its counter reset.
        long second = Instant.now().getEpochSecond() % 60;
        if (second > 50) Thread.sleep((61 - second) * 1000);
    }

    @Test
    void tokenIsCachedWithTheSessionsRemainingLifetime() throws Exception {
        String token = register("cache");
        assertThat(get(token).statusCode()).isEqualTo(200);
        String key = SessionCache.key(SyncAuth.digest(token));
        assertThat(redis.hasKey(key)).isTrue();
        long ttl = redis.getExpire(key);
        assertThat(ttl).isBetween(7 * 24 * 3600L - 120, 7 * 24 * 3600L);
        assertThat(get(token).statusCode()).isEqualTo(200); // served from the cache
    }

    @Test
    void requestsOverTheLimitGet429WithRetryAfterAndOtherAccountsAreUnaffected() throws Exception {
        String token = register("limit");
        for (int i = 0; i < 3; i++) assertThat(get(token).statusCode()).isEqualTo(200);
        HttpResponse<String> limited = get(token);
        assertThat(limited.statusCode()).isEqualTo(429);
        long retryAfter = Long.parseLong(limited.headers().firstValue("Retry-After").orElseThrow());
        assertThat(retryAfter).isBetween(1L, 60L);
        assertThat(get(register("other")).statusCode()).isEqualTo(200);
    }

    @Test
    void repeatedLoginsForOneUsernameAreLimited() throws Exception {
        String username = "login" + UUID.randomUUID().toString().substring(0, 8);
        send("/v1/auth/register", Map.of("username", username, "password", "correct-password"));
        Map<String, String> wrong = Map.of("username", username, "password", "wrong-password!");
        assertThat(send("/v1/auth/login", wrong).statusCode()).isEqualTo(401);
        assertThat(send("/v1/auth/login", wrong).statusCode()).isEqualTo(401);
        assertThat(send("/v1/auth/login", wrong).statusCode()).isEqualTo(429);
    }

    private String register(String prefix) throws Exception {
        var response = send("/v1/auth/register",
            Map.of("username", prefix + UUID.randomUUID().toString().substring(0, 8), "password", "fictional-pass"));
        assertThat(response.statusCode()).isEqualTo(201);
        JsonNode body = json.readTree(response.body());
        return body.path("token").asText();
    }

    private HttpResponse<String> get(String token) throws Exception {
        return client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/v1/sync/changes"))
            .header("Authorization", "Bearer " + token).GET().build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpResponse<String> send(String path, Map<String, String> body) throws Exception {
        return client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body))).build(),
            HttpResponse.BodyHandlers.ofString());
    }
}
