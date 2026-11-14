package com.medsync.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * Hop ② (gateway → agent). The agent keys its LangGraph thread and tool ledger on step_key, so calling it again for
 * the same step is safe: that is what lets the gateway simply re-dispatch on a timeout instead of guessing.
 */
@Component
class AgentClient {
    record Outcome(String status, JsonNode result, String reason) {}

    /** Network failure, timeout or 5xx: the step may or may not have run; the caller re-dispatches later. */
    static class Unavailable extends RuntimeException {
        Unavailable(Throwable cause) {
            super(cause);
        }
    }

    private final RestClient rest;

    AgentClient(@Value("${medsync.agent.url}") String baseUrl,
                @Value("${medsync.agent.connect-timeout}") Duration connectTimeout,
                @Value("${medsync.agent.read-timeout}") Duration readTimeout) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeout);
        factory.setReadTimeout(readTimeout);
        this.rest = RestClient.builder().baseUrl(baseUrl).requestFactory(factory).build();
    }

    /** Header carrying a delegated token for this one dispatch; kept out of the body so nothing persists it. */
    static final String DELEGATION_HEADER = "X-MedSync-Delegation";

    Outcome run(ObjectNode request) {
        return run(request, null);
    }

    Outcome run(ObjectNode request, String delegation) {
        return call("/v1/actions/run", request, delegation);
    }

    Outcome resume(String stepKey, ObjectNode decision) {
        return call("/v1/actions/" + stepKey + "/resume", decision, null);
    }

    private Outcome call(String path, ObjectNode body, String delegation) {
        try {
            var spec = rest.post().uri(path).contentType(MediaType.APPLICATION_JSON).body(body);
            if (delegation != null) {
                spec = spec.header(DELEGATION_HEADER, delegation);
            }
            return spec.retrieve().body(Outcome.class);
        } catch (HttpClientErrorException rejected) {
            throw rejected;  // the agent refused this request; retrying the same body will not help
        } catch (RestClientException exception) {
            // Connection refused, 5xx, and also a timeout while reading the body (headers already arrived, e.g. a
            // pooled connection whose upstream died when the agent restarted). All mean "outcome unknown": the step
            // stays DISPATCHED and the next poll re-dispatches, which the agent deduplicates by step_key.
            throw new Unavailable(exception);
        }
    }
}
