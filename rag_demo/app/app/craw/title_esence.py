import requests
r = requests.get("https://namu.wiki/robots.txt", headers={"User-Agent": USER_AGENTS[0]})
print(r.text)
