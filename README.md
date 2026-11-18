# CS 1.6 server list (backup)

`steam_servers.txt` is the list of real Counter-Strike 1.6 servers used by the native Mac build of
the game, one `ip:port` per line. It comes from Valve's master list (Steam Web API
`IGameServersService/GetServerList`) and is rebuilt every 30 minutes by GitHub Actions
(`.github/workflows/steam-list.yml`).

Fake servers are removed with the rules of [fakeservers.link](https://fakeservers.link):
farms (3+ listings with the same name, map and slot count), 10+ listings on one IP, 50+ in one /24,
impossible slot/player counts and private addresses. See `steam-list.py`.
