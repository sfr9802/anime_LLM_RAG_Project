package com.arin.reverseproxy.controller;

import com.arin.reverseproxy.dto.ProxyRequestDto;
import com.arin.reverseproxy.service.ProxyService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/proxy")
@Tag(name = "Reverse Proxy", description = "외부 API 요청을 프록시로 전달합니다.")
public class ProxyController {

    private final ProxyService proxyService;
    private final RestTemplate restTemplate = new RestTemplate();

    @Operation(summary = "GET 프록시 요청", description = "GET 방식의 외부 API 요청을 프록시를 통해 전달합니다.")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "성공"),
            @ApiResponse(responseCode = "401", description = "인증 필요"),
            @ApiResponse(responseCode = "400", description = "잘못된 요청"),
            @ApiResponse(responseCode = "502", description = "프록시 오류")
    })
    @GetMapping("/**")
    public ResponseEntity<?> handleProxy(HttpServletRequest request, Authentication authentication) {
        try {
            if (authentication == null || authentication.getPrincipal() == null) {
                log.warn("인증 실패: 인증 객체 없음");
                return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("인증이 필요합니다.");
            }

            Object principal = authentication.getPrincipal();
            log.info("[GET 프록시 요청] 사용자: {}", principal);

            String targetUrl = extractTargetUrl(request);
            if (!isValidUrl(targetUrl)) {
                log.warn("유효하지 않은 URL: {}", targetUrl);
                return ResponseEntity.badRequest().body("잘못된 프록시 대상 URL입니다.");
            }

            log.info("Forwarding to: {}", targetUrl);
            ResponseEntity<String> response = restTemplate.getForEntity(targetUrl, String.class);

            return ResponseEntity.status(response.getStatusCode()).body(response.getBody());

        } catch (Exception e) {
            log.error("프록시 처리 중 예외: {}", e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body("프록시 오류: " + e.getMessage());
        }
    }

    @Operation(summary = "POST 프록시 요청", description = "POST 방식의 외부 API 요청을 프록시를 통해 전달합니다.")
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "성공"),
            @ApiResponse(responseCode = "401", description = "인증 필요"),
            @ApiResponse(responseCode = "400", description = "잘못된 요청"),
            @ApiResponse(responseCode = "502", description = "프록시 오류")
    })
    @PostMapping
    public ResponseEntity<?> proxy(@RequestBody ProxyRequestDto dto, Authentication auth) {
        try {
            if (auth == null || auth.getPrincipal() == null) {
                log.warn("POST 프록시 요청 - 인증 정보 없음");
                return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("인증이 필요합니다.");
            }

            if (dto == null || dto.getTargetUrl() == null || dto.getTargetUrl().isBlank()) {
                log.warn("POST 프록시 요청 - 대상 URL 누락");
                return ResponseEntity.badRequest().body("targetUrl이 필요합니다.");
            }

            log.info("[POST 프록시 요청] 사용자: {}, 대상: {}", auth.getPrincipal(), dto.getTargetUrl());
            return proxyService.forward(dto, auth);

        } catch (Exception e) {
            log.error("POST 프록시 처리 실패: {}", e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body("프록시 오류: " + e.getMessage());
        }
    }

    private String extractTargetUrl(HttpServletRequest request) {
        String uri = request.getRequestURI();
        String prefix = "/api/proxy/";
        return uri.substring(uri.indexOf(prefix) + prefix.length());
    }

    private boolean isValidUrl(String url) {
        return url != null && (url.startsWith("http://") || url.startsWith("https://"));
    }
}
