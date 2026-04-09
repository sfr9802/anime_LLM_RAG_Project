CREATE TABLE app_user (
    id         BIGSERIAL PRIMARY KEY,
    email      VARCHAR(255) UNIQUE,
    role       VARCHAR(20) NOT NULL
);
CREATE INDEX idx_app_user_email ON app_user(email);

CREATE TABLE user_profile (
    id          BIGSERIAL PRIMARY KEY,
    nickname    VARCHAR(30) NOT NULL,
    picture_url VARCHAR(500),
    bio         TEXT,
    app_user_id BIGINT NOT NULL UNIQUE REFERENCES app_user(id)
);
CREATE INDEX idx_user_profile_nickname ON user_profile(nickname);
