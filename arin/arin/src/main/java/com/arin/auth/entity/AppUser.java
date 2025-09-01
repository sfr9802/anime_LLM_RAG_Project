package com.arin.auth.entity;

import jakarta.persistence.*;
import lombok.*;

import java.util.Objects;

@Entity
@Table(name = "app_user", indexes = {
        @Index(name = "idx_app_user_email", columnList = "email")
})
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor(access = AccessLevel.PRIVATE)
@Builder
public class AppUser {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // OAuth 공급자에 따라 이메일이 없을 수 있으니 nullable 허용 권장
    @Column(unique = true)
    private String email;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20, columnDefinition = "varchar(20)")
    private Role role;


    public enum Role { USER, ADMIN }

    public static AppUser of(String email, Role role) {
        return AppUser.builder().email(email).role(role != null ? role : Role.USER).build();
    }

    public void changeEmail(String email) { this.email = email; }
    public void changeRole(Role role)     { this.role = role;   }

    @Override public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof AppUser that)) return false;
        return id != null && id.equals(that.id);
    }
    @Override public int hashCode() { return Objects.hashCode(id); }
}
