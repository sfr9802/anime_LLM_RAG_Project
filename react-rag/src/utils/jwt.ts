// utils/jwt.ts
export function parseJwt(token: string): { [key: string]: any } {
  try {
    const base64Payload = token.split(".")[1];
    const payload = atob(base64Payload);
    return JSON.parse(payload);
  } catch (e) {
    return {};
  }
}
