// com.arin.user.repository.UserProfileRepository
package com.arin.user.repository;

import com.arin.auth.entity.AppUser;
import com.arin.user.entity.UserProfile;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface UserProfileRepository extends JpaRepository<UserProfile, Long> {
    boolean existsByAppUser(AppUser appUser);
    Optional<UserProfile> findByAppUser(AppUser appUser);
    Optional<UserProfile> findByAppUserId(Long appUserId); // 편의
}
