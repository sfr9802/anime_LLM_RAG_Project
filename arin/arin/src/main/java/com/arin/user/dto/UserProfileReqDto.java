package com.arin.user.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.*;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UserProfileReqDto {

    @NotBlank(message = "nickname is required")
    @Size(max = 30, message = "nickname must be <= 30 chars")
    private String nickname;
}
