package com.arin.auth.controller;

import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/oauth")
public class OAuthTokenController {

    @GetMapping("/token")
    public ResponseEntity<Map<String, String>> getTokenFromSession(HttpServletRequest request) {
        Object accessToken = request.getSession().getAttribute("accessToken");
        Object refreshToken = request.getSession().getAttribute("refreshToken");

        if (accessToken == null) {
            log.warn("세션에 accessToken 없음");
            return ResponseEntity.badRequest().body(Map.of("error", "No token in session"));
        }

        Map<String, String> response = new HashMap<>();
        response.put("accessToken", accessToken.toString());
        if (refreshToken != null) {
            response.put("refreshToken", refreshToken.toString());
        }

        // 🔒 이후 세션 제거 (1회성)
        request.getSession().removeAttribute("accessToken");
        request.getSession().removeAttribute("refreshToken");

        log.info("세션에서 accessToken 전달 완료");
        return ResponseEntity.ok(response);
    }
}
