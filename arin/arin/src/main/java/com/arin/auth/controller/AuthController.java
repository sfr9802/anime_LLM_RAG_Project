package com.arin.auth.controller;

import com.arin.auth.jwt.JwtProvider;
import com.arin.auth.entity.AppUser;
import com.arin.auth.repository.AppUserRepository;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import com.arin.auth.dto.LoginReq;
import com.arin.auth.dto.JwtRes;

@Tag(name = "User", description = "유저 관련 API")
@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class AuthController {

    private final AppUserRepository appUserRepository;
    private final JwtProvider jwtProvider;

    @PostMapping("/login")
    public ResponseEntity<?> login(@RequestBody LoginReq loginRequest) {
        String email = loginRequest.getEmail();
        String password = loginRequest.getPassword(); // 실제론 비밀번호 비교도 해야 함

        AppUser user = appUserRepository.findByEmail(email)
                .orElse(null);

        if (user == null) {
            return ResponseEntity.badRequest().body("존재하지 않는 사용자입니다.");
        }

        // TODO: 평문 비밀번호 비교 로직 필요 (지금은 생략)
        // 실제 운영용이면 BCryptPasswordEncoder 등 사용 필수

        String token = jwtProvider.generateToken(user.getId(), user.getRole().name());
        return ResponseEntity.ok().body(new JwtRes(token));
    }


}
