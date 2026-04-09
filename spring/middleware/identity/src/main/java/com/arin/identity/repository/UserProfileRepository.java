package com.arin.identity.repository;

import com.arin.identity.entity.AppUser;
import com.arin.identity.entity.UserProfile;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface UserProfileRepository extends JpaRepository<UserProfile, Long> {
    boolean existsByAppUser(AppUser appUser);
    Optional<UserProfile> findByAppUser(AppUser appUser);
    Optional<UserProfile> findByAppUserId(Long appUserId);
}
