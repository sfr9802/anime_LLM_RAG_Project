package com.arin.user.entity;

import com.arin.auth.entity.AppUser;
import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(
        name = "user_profile",
        uniqueConstraints = @UniqueConstraint(name = "uq_user_profile_app_user", columnNames = "app_user_id"),
        indexes = {
                @Index(name = "idx_user_profile_nickname", columnList = "nickname")
        }
)
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor
@Builder
public class UserProfile {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 30)
    private String nickname;

    @Column(name = "picture_url", length = 500)
    private String pictureUrl;            // nullable

    @Lob
    @Column(name = "bio")
    private String bio;                   // nullable

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "app_user_id", nullable = false, unique = true)
    private AppUser appUser;

    public void changeNickname(String nickname) { this.nickname = nickname; }
    public void changePictureUrl(String pictureUrl) { this.pictureUrl = pictureUrl; }
    public void changeBio(String bio) { this.bio = bio; }
}
