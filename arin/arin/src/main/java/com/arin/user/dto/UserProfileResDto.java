package com.arin.user.dto;

import com.arin.user.entity.UserProfile;
import io.swagger.v3.oas.annotations.media.Schema;
import lombok.*;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@Schema(description = "유저 프로필 응답 DTO")
public class UserProfileResDto {

    @Schema(description = "UserProfile ID", example = "1")
    private Long id;

    @Schema(description = "유저 닉네임", example = "arin_dev")
    private String nickname;

    @Schema(description = "이메일", example = "arin@example.com")
    private String email;

    @Schema(description = "유저 역할 (USER/ADMIN)", example = "USER")
    private String role;

    public UserProfileResDto(UserProfile userProfile) {
        this.id = userProfile.getId();
        this.nickname = userProfile.getNickname();
        this.email = userProfile.getAppUser().getEmail();
        this.role = userProfile.getAppUser().getRole().name();
    }
}
