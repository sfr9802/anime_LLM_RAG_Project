// com.arin.user.service.UserProfileService
package com.arin.user.service;

import com.arin.auth.entity.AppUser;
import com.arin.auth.repository.AppUserRepository;
import com.arin.user.dto.UserProfileReqDto;
import com.arin.user.dto.UserProfileResDto;
import com.arin.user.entity.UserProfile;
import com.arin.user.repository.UserProfileRepository;
import jakarta.transaction.Transactional;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class UserProfileService {

    private final AppUserRepository appUserRepository;
    private final UserProfileRepository userProfileRepository;

    @Transactional
    public UserProfileResDto upsertMyProfile(Long userId, UserProfileReqDto req) {
        AppUser user = appUserRepository.findById(userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "user not found"));

        UserProfile profile = userProfileRepository.findByAppUser(user)
                .orElseGet(() -> UserProfile.builder()
                        .appUser(user)
                        .nickname(defaultNick(user.getEmail()))
                        .build());

        if (req.getNickname() != null && !req.getNickname().isBlank()) {
            profile.changeNickname(req.getNickname().trim());
        }

        UserProfile saved = userProfileRepository.save(profile);
        return toResDto(user, saved);
    }

    @Transactional
    public UserProfileResDto getMyProfile(Long userId) {
        AppUser user = appUserRepository.findById(userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "user not found"));

        UserProfile profile = userProfileRepository.findByAppUser(user).orElse(null);
        return toResDto(user, profile);
    }

    private static UserProfileResDto toResDto(AppUser user, UserProfile profile) {
        return UserProfileResDto.builder()
                .id(profile != null ? profile.getId() : null)
                .nickname(profile != null ? profile.getNickname() : defaultNick(user.getEmail()))
                .email(user.getEmail())
                .role(user.getRole().name())
                .build();
    }

    private static String defaultNick(String email) {
        if (email == null || email.isBlank()) return "User";
        int at = email.indexOf('@');
        return "User_" + (at > 0 ? email.substring(0, at) : email);
    }
}
