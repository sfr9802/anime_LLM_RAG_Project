package com.arin.auth.controller;

import com.arin.auth.dto.TokenResponseDto;
import com.arin.auth.service.TokenService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/auth")
public class OAuthTokenController {

    private final TokenService tokenService;

    @GetMapping(value = "/exchange", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<?> exchange(@RequestParam("code") String code) {
        var dtoOpt = tokenService.consumeOneTimeCode(code);

        HttpHeaders noCache = new HttpHeaders();
        noCache.setCacheControl(CacheControl.noStore());
        noCache.add("Pragma", "no-cache");

        if (dtoOpt.isEmpty()) {
            // 400 + JSON 에러 바디 (프런트가 안전하게 처리)
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .headers(noCache)
                    .body(Map.of("error", "invalid_code"));
        }

        return ResponseEntity.ok().headers(noCache).body(dtoOpt.get());
    }

//    @Deprecated
//    @GetMapping(value = "/session-token", produces = MediaType.APPLICATION_JSON_VALUE)
//    public ResponseEntity<?> getTokenFromSession(javax.servlet.http.HttpServletRequest request) {
//        var session = request.getSession(false);
//        if (session == null) {
//            return ResponseEntity.badRequest().body(Map.of("error", "No session"));
//        }
//        Object accessToken = session.getAttribute("accessToken");
//        Object refreshToken = session.getAttribute("refreshToken");
//        if (accessToken == null) {
//            return ResponseEntity.badRequest().body(Map.of("error", "No token in session"));
//        }
//        session.removeAttribute("accessToken");
//        session.removeAttribute("refreshToken");
//
//        HttpHeaders noCache = new HttpHeaders();
//        noCache.setCacheControl(CacheControl.noStore());
//        noCache.add("Pragma", "no-cache");
//
//        return ResponseEntity.ok()
//                .headers(noCache)
//                .body(Map.of(
//                        "accessToken", accessToken.toString(),
//                        "refreshToken", refreshToken != null ? refreshToken.toString() : ""
//                ));
//    }
}
