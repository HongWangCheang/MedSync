package com.medsync.gateway;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.HttpClientErrorException;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** Every way the agent can fail to answer must become "outcome unknown", never a 500 to the device. */
class AgentClientTest {
    private final HttpServer server = start();
    private final CountDownLatch release = new CountDownLatch(1);
    private final AgentClient client = new AgentClient("http://127.0.0.1:" + server.getAddress().getPort(),
        Duration.ofMillis(500), Duration.ofMillis(300));

    private static HttpServer start() {
        try {
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.start();
            return server;
        } catch (Exception exception) {
            throw new IllegalStateException(exception);
        }
    }

    @AfterEach
    void stop() {
        release.countDown();
        server.stop(0);
    }

    private void respond(int status, String body, boolean stallBody) {
        server.createContext("/v1/actions/run", exchange -> {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            try (OutputStream out = exchange.getResponseBody()) {
                if (stallBody) {
                    release.await(5, TimeUnit.SECONDS);  // headers sent, body never arrives in time
                }
                out.write(bytes);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        });
    }

    @Test
    void readsANormalOutcome() {
        respond(200, "{\"status\":\"DONE\",\"result\":null,\"reason\":null}", false);
        assertThat(client.run(new ObjectMapper().createObjectNode()).status()).isEqualTo("DONE");
    }

    @Test
    void timeoutWhileReadingTheBodyIsUnavailableNotA500() {
        respond(200, "{\"status\":\"DONE\"}", true);
        assertThatThrownBy(() -> client.run(new ObjectMapper().createObjectNode()))
            .isInstanceOf(AgentClient.Unavailable.class);
    }

    @Test
    void serverErrorIsUnavailable() {
        respond(503, "{}", false);
        assertThatThrownBy(() -> client.run(new ObjectMapper().createObjectNode()))
            .isInstanceOf(AgentClient.Unavailable.class);
    }

    @Test
    void clientErrorIsNotRetried() {
        respond(400, "{\"detail\":\"experiment modes are disabled\"}", false);
        assertThatThrownBy(() -> client.run(new ObjectMapper().createObjectNode()))
            .isInstanceOf(HttpClientErrorException.class);
    }

    @Test
    void refusedConnectionIsUnavailable() {
        AgentClient nobody = new AgentClient("http://127.0.0.1:1", Duration.ofMillis(300), Duration.ofMillis(300));
        assertThatThrownBy(() -> nobody.run(new ObjectMapper().createObjectNode()))
            .isInstanceOf(AgentClient.Unavailable.class);
    }
}
