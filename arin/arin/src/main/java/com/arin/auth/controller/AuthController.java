package com.arin.auth.controller;

import com.arin.auth.dto.LoginReq;
import com.arin.auth.dto.TokenResponseDto;
import com.arin.auth.entity.AppUser;
import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.repository.AppUserRepository;
import com.arin.auth.service.TokenService;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
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
    public ResponseEntity<?> login(@RequestBody LoginReq loginRequest) {
        String email = loginRequest.getEmail();
        String password = loginRequest.getPassword(); // TODO: 실제 비밀번호 검증 필요

        AppUser user = appUserRepository.findByEmail(email)
                .orElse(null);

        if (user == null) {
            return ResponseEntity.badRequest().body("존재하지 않는 사용자입니다.");
        }

        // TODO: 비밀번호 비교 로직 추가 (예: BCryptPasswordEncoder)

        String accessToken = jwtProvider.generateAccessToken(user.getId(), user.getRole().name());
        String refreshToken = jwtProvider.generateRefreshToken(user.getId(), user.getRole().name());

        long refreshTtl = jwtProvider.getRemainingValidity(refreshToken);
        tokenService.storeRefreshToken(user.getId(), refreshToken, refreshTtl);

        return ResponseEntity.ok().body(new TokenResponseDto(accessToken, refreshToken));
    }
}
