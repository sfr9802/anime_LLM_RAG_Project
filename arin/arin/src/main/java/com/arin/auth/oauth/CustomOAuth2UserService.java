package com.arin.auth.oauth;

import com.arin.auth.entity.AppUser;
import com.arin.auth.repository.AppUserRepository;
import com.arin.user.entity.UserProfile;
import com.arin.user.repository.UserProfileRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.oauth2.client.userinfo.DefaultOAuth2UserService;
import org.springframework.security.oauth2.client.userinfo.OAuth2UserRequest;
import org.springframework.security.oauth2.core.OAuth2AuthenticationException;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
public class CustomOAuth2UserService extends DefaultOAuth2UserService {

    private final AppUserRepository appUserRepository;
    private final UserProfileRepository userProfileRepository;

    @Override
    @Transactional
    public OAuth2User loadUser(OAuth2UserRequest userRequest) throws OAuth2AuthenticationException {
        OAuth2User oauth = super.loadUser(userRequest);
        String provider = userRequest.getClientRegistration().getRegistrationId();

        String email = attr(oauth, "email");
        if (email == null) {
            String sub   = attr(oauth, "sub");
            String login = attr(oauth, "login");
            String name  = oauth.getName();
            String local = firstNonBlank(login, sub, name, "user");
            email = local + "@" + provider + ".local";
        }

        // ✅ 람다에서 쓸 값은 final 스냅샷으로
        final String emailFinal = email;

        AppUser user = appUserRepository.findByEmail(emailFinal)
                .orElseGet(() -> {
                    AppUser created = AppUser.of(emailFinal, AppUser.Role.USER);
                    created = appUserRepository.save(created);
                    log.info("[OAuth2UserService] 신규 AppUser 저장: id={}, email={}", created.getId(), emailFinal);
                    return created;
                });

        if (!userProfileRepository.existsByAppUser(user)) {
            final String nickname = genNickname(emailFinal); // 이 값도 람다에 쓰면 final로
            userProfileRepository.save(
                    UserProfile.builder()
                            .appUser(user)
                            .nickname(nickname)
                            .build()
            );
            log.info("[OAuth2UserService] 프로필 생성: uid={}, nickname={}", user.getId(), nickname);
        }

        return new CustomOAuth2User(user, oauth.getAttributes());
    }


    private static String attr(OAuth2User u, String key) {
        try {
            Object v = u.getAttribute(key);
            return (v == null) ? null : v.toString();
        } catch (Exception ignored) { return null; }
    }

    private static String genNickname(String email) {
        int at = (email != null) ? email.indexOf('@') : -1;
        String local = (at > 0) ? email.substring(0, at) : "user";
        return "User_" + local;
    }

    private static String firstNonBlank(String... xs) {
        for (String x : xs) if (x != null && !x.isBlank()) return x;
        return null;
    }
}
