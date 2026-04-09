package com.arin.identity.controller;

import com.arin.identity.dto.LoginReq;
import com.arin.identity.dto.TokenResponseDto;
import com.arin.identity.entity.AppUser;
import com.arin.identity.jwt.JwtProvider;
import com.arin.identity.repository.AppUserRepository;
import com.arin.identity.service.TokenService;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@Tag(name = "User", description = "유저 관련 API")
@RestController
@SecurityRequirement(name = "bearerAuth")
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class AuthController {

    private final AppUserRepository appUserRepository;
    private final JwtProvider jwtProvider;
    private final TokenService tokenService;

    @PostMapping("/login")
    public ResponseEntity<?> login(@RequestBody LoginReq loginRequest, HttpServletRequest req, HttpServletResponse res) {
        String email = loginRequest.getEmail();
        AppUser user = appUserRepository.findByEmail(email).orElse(null);
        if (user == null) {
            return ResponseEntity.badRequest().body("이메일 또는 비밀번호가 올바르지 않습니다.");
        }
        String access  = jwtProvider.generateAccessToken(user.getId(), user.getRole().name());
        String refresh = jwtProvider.generateRefreshToken(user.getId(), user.getRole().name());
        var refClaims = jwtProvider.getClaims(refresh);
        String jti = refClaims.getId();
        long ttlMillis = Math.max(0, refClaims.getExpiration().getTime() - System.currentTimeMillis());
        tokenService.saveRefreshSession(user.getId(), jti, req, ttlMillis);
        var cookie = tokenService.buildRefreshCookie(refresh, ttlMillis);
        res.addHeader(org.springframework.http.HttpHeaders.SET_COOKIE, cookie.toString());
        var claims = jwtProvider.getClaims(access);
        long expiresIn = (claims.getExpiration().getTime() - System.currentTimeMillis()) / 1000;
        return ResponseEntity.ok(new TokenResponseDto(access, expiresIn));
    }
}
