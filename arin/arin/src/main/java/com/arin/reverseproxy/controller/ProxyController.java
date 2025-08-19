package com.arin.reverseproxy.controller;

import com.arin.reverseproxy.dto.ProxyRequestDto;
import com.arin.reverseproxy.service.ProxyService;
import com.arin.reverseproxy.service.ReverseProxyService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
@RequestMapping("${proxy.prefix:/api/proxy}")
public class ProxyController {

    private final ReverseProxyService reverseProxyService; // 일반 프록시
    private final ProxyService proxyService;               // LLM 전용

    @PostMapping("/llm")
    public ResponseEntity<?> proxyToLlm(@RequestBody ProxyRequestDto dto, Authentication auth) {
        return proxyService.forward(dto, auth);
    }

    @RequestMapping("/**")
    public ResponseEntity<byte[]> proxy(HttpServletRequest req,
                                        Authentication auth,
                                        @RequestBody(required = false) byte[] body) {
        return reverseProxyService.forward(req, auth, body);
    }
}
