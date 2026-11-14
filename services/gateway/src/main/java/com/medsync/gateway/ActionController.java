package com.medsync.gateway;

import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/v1/actions")
class ActionController {
    private final SyncAuth auth;
    private final ActionService actions;

    ActionController(SyncAuth auth, ActionService actions) {
        this.auth = auth;
        this.actions = actions;
    }

    @PostMapping
    ActionService.View submit(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
                              @RequestBody ActionLedger.Submit body) {
        return actions.submit(auth.requireAccount(token), body);
    }

    @GetMapping("/{stepKey}")
    ActionService.View status(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
                              @PathVariable String stepKey) {
        return actions.status(auth.requireAccount(token), stepKey);
    }

    @PostMapping("/{stepKey}/resume")
    ActionService.View resume(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String token,
                              @PathVariable String stepKey, @RequestBody ObjectNode decision) {
        return actions.resume(auth.requireAccount(token), stepKey, decision);
    }
}
