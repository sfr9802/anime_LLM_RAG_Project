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
        String role = "USER";

        System.out.println("[OAuth2UserService] 로그인 시도: " + email);

        AppUser appUser = appUserRepository.findByEmail(email)
                .orElseGet(() -> {
                    AppUser newUser = new AppUser(email, AppUser.Role.valueOf(role));
                    System.out.println("[OAuth2UserService] 신규 AppUser 저장: " + email);
                    return appUserRepository.save(newUser);
                });

        if (!userProfileRepository.existsByAppUser(appUser)) {
            String nickname = generateNickname(Objects.requireNonNull(email));
            System.out.println("[OAuth2UserService] UserProfile 없음 → 생성: " + nickname);
            userProfileRepository.save(new UserProfile(nickname, appUser));
        }

        System.out.println("[OAuth2UserService] 로그인 완료: " + email + " (id=" + appUser.getId() + ")");

        return new CustomOAuth2User(appUser, oAuth2User.getAttributes());
    }


    private String generateNickname(String email) {
        return "User_" + email.split("@")[0];
    }
}



