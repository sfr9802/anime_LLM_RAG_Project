package com.arin.user.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.*;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UserProfileResDto {

    @Schema(description = "프로필 ID", example = "10")
    private Long id;

    @Schema(description = "닉네임", example = "arin")
    private String nickname;

    @Schema(description = "이메일", example = "arin@example.com")
    private String email;

    @Schema(description = "역할", example = "USER")
    private String role;
}
