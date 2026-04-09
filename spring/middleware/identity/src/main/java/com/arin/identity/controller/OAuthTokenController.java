package com.arin.identity.controller;

import com.arin.identity.dto.TokenResponseDto;
import com.arin.identity.jwt.JwtProvider;
import com.arin.identity.service.TokenService;
import io.jsonwebtoken.Claims;
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
    private final JwtProvider jwtProvider;

    @GetMapping(value = "/exchange", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<?> exchange(@RequestParam("code") String code) {
        var dtoOpt = tokenService.consumeOneTimeCode(code);
        HttpHeaders noCache = new HttpHeaders();
        noCache.setCacheControl(CacheControl.noStore());
        noCache.add("Pragma", "no-cache");
        if (dtoOpt.isEmpty()) {
            return ResponseEntity.status(HttpStatus.BAD_REQUEST).headers(noCache).body(Map.of("error", "invalid_code"));
        }
        var dto = dtoOpt.get();
        Claims ref = jwtProvider.getClaims(dto.refreshToken());
        long rtTtlMs = Math.max(0L, ref.getExpiration().getTime() - System.currentTimeMillis());
        var cookie = tokenService.buildRefreshCookie(dto.refreshToken(), rtTtlMs);
        Claims at = jwtProvider.getClaims(dto.accessToken());
        long accessExpiresInSec = Math.max(0L, (at.getExpiration().getTime() - System.currentTimeMillis()) / 1000);
        return ResponseEntity.ok().headers(noCache).header(HttpHeaders.SET_COOKIE, cookie.toString())
                .body(new TokenResponseDto(dto.accessToken(), accessExpiresInSec));
    }
}
