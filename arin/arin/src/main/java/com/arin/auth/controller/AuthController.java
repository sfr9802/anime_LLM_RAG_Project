package com.arin.auth.controller;

import com.arin.auth.dto.LoginReq;
import com.arin.auth.dto.TokenResponseDto;
import com.arin.auth.entity.AppUser;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.repository.AppUserRepository;
import com.arin.auth.service.TokenService;
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
    public ResponseEntity<?> login(@RequestBody LoginReq loginRequest,
                                   HttpServletRequest req,
                                   HttpServletResponse res) {
        String email = loginRequest.getEmail();
        String password = loginRequest.getPassword();

        AppUser user = appUserRepository.findByEmail(email).orElse(null);
        if (user == null /* || !passwordEncoder.matches(password, user.getPasswordHash()) */) {
            // TODO: 비번검증 추가. 메시지는 모호하게(유저 enum 방지)
            return ResponseEntity.badRequest().body("이메일 또는 비밀번호가 올바르지 않습니다.");
        }

        // 1) 토큰 발급
        String access  = jwtProvider.generateAccessToken(user.getId(), user.getRole().name());
        String refresh = jwtProvider.generateRefreshToken(user.getId(), user.getRole().name());

        // 2) jti/TTL → 세션형 저장(회전/재사용감지용)
        var refClaims = jwtProvider.getClaims(refresh);
        String jti = refClaims.getId();
        long ttlMillis = Math.max(0, refClaims.getExpiration().getTime() - System.currentTimeMillis());
        tokenService.saveRefreshSession(user.getId(), jti, req, ttlMillis);   // ✅ 이걸로 교체

        // 3) HttpOnly 쿠키로 refresh 심기 (dev/prod 설정에 맞춰 secure/samesite/path 적용)
        var cookie = tokenService.buildRefreshCookie(refresh, ttlMillis);      // ✅ 쿠키 빌더 사용
        res.addHeader(org.springframework.http.HttpHeaders.SET_COOKIE, cookie.toString());

        // 4) 바디엔 access만. refresh는 쿠키로만 운용.
        var claims = jwtProvider.getClaims(access);
        long expiresIn = (claims.getExpiration().getTime() - System.currentTimeMillis()) / 1000;
        return ResponseEntity.ok(new TokenResponseDto(access, expiresIn));

    }

}
