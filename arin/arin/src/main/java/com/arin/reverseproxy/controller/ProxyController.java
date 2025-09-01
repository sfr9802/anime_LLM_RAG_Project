// src/main/java/com/arin/reverseproxy/api/ProxyController.java
package com.arin.reverseproxy.controller;

import com.arin.reverseproxy.dto.ProxyRequestDto;
import com.arin.reverseproxy.dto.RagAskDto;
import com.arin.reverseproxy.service.ProxyService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("${proxy.prefix:/api/proxy}") // ← 설정값 사용
@RequiredArgsConstructor
public class ProxyController {

    private final ProxyService proxyService;

    // v1 하위호환
    @PreAuthorize("isAuthenticated()")
    @PostMapping("/ask")
    public ResponseEntity<?> askV1(@RequestBody ProxyRequestDto dto, Authentication auth) {
        return proxyService.forward(dto, auth);
    }

    // v2 확장 파라미터
    @PreAuthorize("isAuthenticated()")
    @PostMapping("/ask-v2")
    public ResponseEntity<?> askV2(@Valid @RequestBody RagAskDto dto, Authentication auth) {
        return proxyService.forwardAskV2(dto, auth);
    }
}
