package com.arin.identity.controller;

import com.arin.identity.dto.UserProfileReqDto;
import com.arin.identity.dto.UserProfileResDto;
import com.arin.identity.repository.AppUserRepository;
import com.arin.identity.repository.UserProfileRepository;
import com.arin.identity.service.UserProfileService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.Objects;

@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {

    private final UserProfileService userProfileService;
    private final AppUserRepository appUserRepository;
    private final UserProfileRepository userProfileRepository;

    @GetMapping("/me/profile")
    public ResponseEntity<UserProfileResDto> getMyProfile(Authentication auth) {
        Long userId = resolveUserId(auth);
        return ResponseEntity.ok(userProfileService.getMyProfile(userId));
    }

    @PatchMapping("/me/profile")
    public ResponseEntity<UserProfileResDto> updateMyProfile(Authentication auth, @Valid @RequestBody UserProfileReqDto req) {
        Long userId = resolveUserId(auth);
        return ResponseEntity.ok(userProfileService.upsertMyProfile(userId, req));
    }

    @GetMapping("/me")
    public ResponseEntity<?> me(Authentication auth) {
        if (!(auth instanceof JwtAuthenticationToken jwt)) {
            return ResponseEntity.status(401).body(Map.of("error", "unauthorized"));
        }
        Object v = jwt.getToken().getClaims().getOrDefault("userId", jwt.getToken().getSubject());
        final Long userId;
        try { userId = Long.valueOf(String.valueOf(v)); }
        catch (Exception e) { return ResponseEntity.badRequest().body(Map.of("error", "bad_token")); }
        var user = appUserRepository.findById(userId).orElse(null);
        if (user == null) return ResponseEntity.status(404).body(Map.of("error", "not_found"));
        var p = userProfileRepository.findByAppUserId(userId).orElse(null);
        String username = (p != null && p.getNickname() != null && !p.getNickname().isBlank())
                ? p.getNickname()
                : (user.getEmail() != null ? user.getEmail().split("@")[0] : "user-" + user.getId());
        return ResponseEntity.ok(Map.of("id", user.getId(), "email", Objects.requireNonNull(user.getEmail()), "role", user.getRole().name(), "username", username));
    }

    private Long resolveUserId(Authentication auth) {
        if (!(auth instanceof JwtAuthenticationToken jwt)) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "no jwt");
        Object v = jwt.getToken().getClaims().getOrDefault("userId", jwt.getToken().getSubject());
        try { return Long.valueOf(String.valueOf(v)); }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid userId in token"); }
    }
}
