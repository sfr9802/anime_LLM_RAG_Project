package com.arin.user.service;

import com.arin.user.dto.UserProfileResDto;
import com.arin.user.entity.UserProfile;
import com.arin.user.repository.UserProfileRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class UserProfileService {

    private final UserProfileRepository userProfileRepository;

    /** /api/users/me 용 단일 진입점 */
    public UserProfileResDto getMe(Long appUserId) {
        UserProfile p = userProfileRepository.findWithUserByAppUserId(appUserId)
                .orElseThrow(() -> new ProfileNotFoundException(appUserId));
        return toDto(p);
    }

    /** 필요 시 다른 사용자 조회 */
    public UserProfileResDto getByUserId(Long userId) {
        UserProfile p = userProfileRepository.findWithUserByAppUserId(userId)
                .orElseThrow(() -> new ProfileNotFoundException(userId));
        return toDto(p);
    }

    private static UserProfileResDto toDto(UserProfile profile) {
        return UserProfileResDto.builder()
                .id(profile.getId())
                .nickname(profile.getNickname())
                .email(profile.getAppUser().getEmail())
                .role(profile.getAppUser().getRole().name())
                .build();
    }
}
