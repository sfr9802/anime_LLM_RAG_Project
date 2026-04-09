package com.arin.proxy.controller;

import com.arin.proxy.dto.ProxyRequestDto;
import com.arin.proxy.dto.RagAskDto;
import com.arin.proxy.service.ProxyService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("${proxy.prefix:/api/proxy}")
@RequiredArgsConstructor
public class ProxyController {

    private final ProxyService proxyService;

    @PreAuthorize("isAuthenticated()")
    @PostMapping("/ask")
    public ResponseEntity<?> askV1(@RequestBody ProxyRequestDto dto, Authentication auth) {
        return proxyService.forward(dto, auth);
    }

    @PreAuthorize("isAuthenticated()")
    @PostMapping("/ask-v2")
    public ResponseEntity<?> askV2(@Valid @RequestBody RagAskDto dto, Authentication auth) {
        return proxyService.forwardAskV2(dto, auth);
    }
}
