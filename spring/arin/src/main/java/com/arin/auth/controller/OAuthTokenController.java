package com.arin.auth.controller;

import com.arin.auth.dto.TokenResponseDto;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.service.TokenService;
import io.jsonwebtoken.Claims;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import com.arin.auth.dto.OtcPayload;

import java.util.Map;
import java.util.Optional;

@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/auth")
public class OAuthTokenController {

    private final TokenService tokenService;   // DI
    private final JwtProvider jwtProvider;     // DI

    /**
     * OTC(1회용 코드) 교환:
     * - Redis에서 access/refresh 읽음 (서버 내부 DTO)
     * - refresh는 HttpOnly 쿠키로만 세팅
     * - 바디는 access-only (expiresIn 포함)
     */
    @GetMapping(value = "/exchange", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<?> exchange(@RequestParam("code") String code) {
        var dtoOpt = tokenService.consumeOneTimeCode(code);

        HttpHeaders noCache = new HttpHeaders();
        noCache.setCacheControl(CacheControl.noStore());
        noCache.add("Pragma", "no-cache");

        if (dtoOpt.isEmpty()) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                    .headers(noCache)
                    .body(Map.of("error", "invalid_code"));
        }

        var dto = dtoOpt.get();

        // refresh → 쿠키
        Claims ref = jwtProvider.getClaims(dto.refreshToken());
        long rtTtlMs = Math.max(0L, ref.getExpiration().getTime() - System.currentTimeMillis());
        var cookie = tokenService.buildRefreshCookie(dto.refreshToken(), rtTtlMs);

        // access → 바디
        Claims at = jwtProvider.getClaims(dto.accessToken());
        long accessExpiresInSec = Math.max(0L, (at.getExpiration().getTime() - System.currentTimeMillis()) / 1000);

        return ResponseEntity.ok()
                .headers(noCache)
                .header(HttpHeaders.SET_COOKIE, cookie.toString())
                .body(new TokenResponseDto(dto.accessToken(), accessExpiresInSec)); // refresh 바디에 안 담음
    }


}
