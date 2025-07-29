package com.arin.user.dto;

import com.arin.user.entity.UserProfile;
import lombok.*;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UserProfileResDto {
    private Long id;          // UserProfile ID
    private String nickname;  // 닉네임
    private String email;     // AppUser.email
    private String role;      // AppUser.role

    public UserProfileResDto(UserProfile userProfile) {
        this.id = userProfile.getId();
        this.nickname = userProfile.getNickname();
        this.email = userProfile.getAppUser().getEmail();
        this.role = userProfile.getAppUser().getRole().name();
    }
}


