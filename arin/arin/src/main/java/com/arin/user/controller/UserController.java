package com.arin.user.controller;

import com.arin.auth.entity.AppUserDetails;
import com.arin.auth.oauth.CustomOAuth2User;
import com.arin.user.dto.UserProfileResDto;
import com.arin.user.service.UserProfileService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {

    private final UserProfileService userProfileService;

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
