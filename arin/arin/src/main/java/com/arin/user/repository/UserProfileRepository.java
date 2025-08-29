package com.arin.user.repository;

import com.arin.user.entity.UserProfile;
import com.arin.auth.entity.AppUser;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Optional;

public interface UserProfileRepository extends JpaRepository<UserProfile, Long> {

    Optional<UserProfile> findByAppUser(AppUser appUser);

    @Query("SELECT u FROM UserProfile u WHERE u.appUser.id = :appUserId")
    Optional<UserProfile> findByAppUserId(@Param("appUserId") Long appUserId);

    boolean existsByAppUser(AppUser appUser);

}
