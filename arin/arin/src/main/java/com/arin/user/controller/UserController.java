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
            description = "현재 로그인한 사용자의 프로필 정보를 조회합니다. OAuth2/JWT 모두 지원됩니다."
    )
    @ApiResponses(value = {
            @ApiResponse(responseCode = "200", description = "조회 성공"),
            @ApiResponse(responseCode = "401", description = "인증되지 않음"),
            @ApiResponse(responseCode = "500", description = "내부 서버 오류")
    })
    @GetMapping("/me")
    public ResponseEntity<UserProfileResDto> getMyProfile(Authentication authentication) {
        Long appUserId;

        Object principal = authentication.getPrincipal();

        if (principal instanceof CustomOAuth2User customUser) {
            appUserId = customUser.getId();
        } else if (principal instanceof AppUserDetails userDetails) {
            appUserId = userDetails.getUser().getId();
        } else {
            throw new IllegalStateException("지원하지 않는 인증 타입: " + principal.getClass().getName());
        }

        UserProfileResDto dto = userProfileService.getMyProfile(appUserId);
        return ResponseEntity.ok(dto);
    }
}
