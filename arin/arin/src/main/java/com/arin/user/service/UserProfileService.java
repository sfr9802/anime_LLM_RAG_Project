package com.arin.user.service;

import com.arin.user.dto.UserProfileResDto;
import com.arin.user.entity.UserProfile;
import com.arin.user.repository.UserProfileRepository;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Service;

import java.util.Optional;

@Service
public class UserProfileService {

    private final UserProfileRepository userProfileRepository;


    public UserProfileService(UserProfileRepository userProfileRepository

    ) {
        this.userProfileRepository = userProfileRepository;
    }

    public UserProfileResDto getProfile(Long userId) {
        UserProfile profile = userProfileRepository.findByAppUserId(userId)
                .orElseThrow(() -> new RuntimeException("프로필 없음"));

        return new UserProfileResDto(profile);  // ✅
    }
    public UserProfileResDto getMyProfile(Long appUserId) {
        UserProfile profile = userProfileRepository.findByAppUserId(appUserId)
                .orElseThrow(() -> new IllegalArgumentException("프로필 없음"));

        return UserProfileResDto.builder()
                .id(profile.getId())
                .nickname(profile.getNickname())
                .email(profile.getAppUser().getEmail())  // 여기는 세션 열려있으므로 괜찮음
                .role(profile.getAppUser().getRole().name())
                .build();
    }
    public UserProfile findByAppUserId(Long appUserId) {
        return userProfileRepository.findByAppUserId(appUserId)
                .orElseThrow(() -> new IllegalArgumentException("해당 AppUser의 프로필이 존재하지 않음"));
    }

}


