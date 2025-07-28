package com.arin.dto;

import com.arin.entity.User;
import lombok.*;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UserResDto {
    private Long id;
    private String username;
    private String role;

    // Entity → DTO 변환용 생성자
    public UserResDto(User user) {
        this.id = user.getId();
        this.username = user.getUsername();
        this.role = user.getRole().name();
    }
}
