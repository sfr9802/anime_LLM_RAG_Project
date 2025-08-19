package com.arin.user.controller;

import com.arin.auth.entity.AppUserDetails;
import com.arin.auth.oauth.CustomOAuth2User;
import com.arin.user.dto.UserProfileResDto;
import com.arin.user.service.UserProfileService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
@SecurityRequirement(name = "bearerAuth")
@RequiredArgsConstructor
@Tag(name = "User", description = "유저 관련 API")
public class UserController {

    private final UserProfileService userProfileService;

    @Operation(
            summary = "내 프로필 조회",
            description = "현재 로그인한 사용자의 프로필 정보를 조회합니다. (JWT 우선)"
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "조회 성공"),
            @ApiResponse(responseCode = "401", description = "인증되지 않음"),
            @ApiResponse(responseCode = "500", description = "내부 서버 오류")
    })
    @GetMapping("/me")
    public ResponseEntity<UserProfileResDto> getMyProfile(Authentication authentication) {
        Long appUserId = resolveUserId(authentication);
        UserProfileResDto dto = userProfileService.getMyProfile(appUserId);
        return ResponseEntity.ok(dto);
    }

    private Long resolveUserId(Authentication authentication) {
        // ✅ 리소스서버(JWT) 경로: CompositeJwtAuthConverter에서 principal=sub 로 셋됨
        if (authentication instanceof JwtAuthenticationToken jwt) {
            // 기본: principal(name)=sub → 숫자 변환
            String name = jwt.getName(); // 보통 sub
            try {
                return Long.parseLong(name);
            } catch (NumberFormatException ignore) {
                // fallback: 클레임에 userId가 있으면 사용
                Object uid = jwt.getToken().getClaims().get("userId");
                if (uid != null) return Long.valueOf(uid.toString());
                throw new IllegalStateException("JWT에 유효한 userId/sub 없음");
            }
        }

        // ⬇️ 레거시(세션형) 대비: 남겨두되, 새 구조에선 거의 안 타게 됨
        Object principal = authentication.getPrincipal();
        if (principal instanceof CustomOAuth2User customUser) {
            return customUser.getId();
        }
        if (principal instanceof AppUserDetails userDetails) {
            return userDetails.getUser().getId();
        }

        throw new IllegalStateException("지원하지 않는 인증 타입: " + authentication.getClass().getName());
    }
}
