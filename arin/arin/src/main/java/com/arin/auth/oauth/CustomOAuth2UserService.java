package com.arin.auth.oauth;

import com.arin.auth.entity.AppUser;
import com.arin.auth.repository.AppUserRepository;
import com.arin.user.entity.UserProfile;
import com.arin.user.repository.UserProfileRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.security.oauth2.client.userinfo.DefaultOAuth2UserService;
import org.springframework.security.oauth2.client.userinfo.OAuth2UserRequest;
import org.springframework.security.oauth2.client.userinfo.OAuth2UserService;
import org.springframework.security.oauth2.core.OAuth2AuthenticationException;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.stereotype.Service;

import java.util.Objects;

@Service
@RequiredArgsConstructor
public class CustomOAuth2UserService extends DefaultOAuth2UserService {

    private final AppUserRepository appUserRepository;
    private final UserProfileRepository userProfileRepository;

    @Override
    public OAuth2User loadUser(OAuth2UserRequest userRequest) throws OAuth2AuthenticationException {
        OAuth2User oAuth2User = super.loadUser(userRequest);

        String email = oAuth2User.getAttribute("email");
        String role = "USER"; // 기본 권한

        // AppUser 저장 또는 조회
        AppUser appUser = appUserRepository.findByEmail(email)
                .orElseGet(() -> {
                    AppUser newUser = new AppUser(email, AppUser.Role.valueOf(role));
                    return appUserRepository.save(newUser);
                });

        // ❗ UserProfile이 없다면 자동 생성
        if (!userProfileRepository.existsByAppUser(appUser)) {
            String nickname = generateNickname(Objects.requireNonNull(email)); // 또는 UUID, 이메일 앞부분 등
            userProfileRepository.save(new UserProfile(nickname, appUser));
        }

        return new CustomOAuth2User(appUser, oAuth2User.getAttributes());

    }

    private String generateNickname(String email) {
        return "User_" + email.split("@")[0];
    }
}



