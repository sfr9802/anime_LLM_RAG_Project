package com.arin.user.entity;

import com.arin.auth.entity.AppUser;
import jakarta.persistence.*;
import lombok.*;

@Entity
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class UserProfile {

    @Id @GeneratedValue
    private Long id;

    private String nickname;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "app_user_id", nullable = false, unique = true)
    private AppUser appUser;

    public UserProfile(String nickname, AppUser appUser) {
        this.nickname = nickname;
        this.appUser = appUser;
    }
}




