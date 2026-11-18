# CS 1.6 server list (backup)

`steam_servers.txt` is the list of real Counter-Strike 1.6 servers used by the native Mac build of
the game, one `ip:port` per line. It comes from Valve's master list (Steam Web API
`IGameServersService/GetServerList`) and is rebuilt once a day by GitHub Actions
(`.github/workflows/steam-list.yml`).

Fake servers are removed with the rules of [fakeservers.link](https://fakeservers.link):
farms (3+ listings with the same name, map and slot count), 10+ listings on one IP, 50+ in one /24,
impossible slot/player counts and private addresses. See `steam-list.py`.

## Build your own master list on GitHub

You don't need a server or a computer that stays on. GitHub runs the collector for free and hosts
the result. Steam returns the list only with a Steam Web API key, and Valve gives keys only to
accounts that have spent at least $5 on Steam.

1. **Get a Steam Web API key** at <https://steamcommunity.com/dev/apikey> (any domain name works).
   Keep it private: anyone with it can use your Steam API quota.
2. **Copy this repository**: click **Fork** at the top of this page, or
   create a new **public** repository and upload `steam-list.py` and
   `.github/workflows/steam-list.yml` into it (same folder names).
3. **Add your key as a secret**: in your repository open **Settings > Secrets and variables >
   Actions > New repository secret**. Name: `STEAM_API_KEY`, value: your key. Secrets are never
   shown in logs or files, and people who fork your repository don't get them.
4. **Allow the job to save the list**: **Settings > Actions > General > Workflow permissions**, select
   **Read and write permissions** and save.
5. **Run it once**: **Actions** tab > **steam server list** > **Run workflow**. If a page says that
   workflows are disabled for a fork, click **I understand my workflows, go ahead and enable them**
   first. It takes about 3 minutes; then `steam_servers.txt` appears in your repository.
   After that it runs by itself every day at 04:17 UTC. To change that, edit the `cron:` line in
   `.github/workflows/steam-list.yml` (for example `"17 */6 * * *"` for every 6 hours).
6. **Use it in the game**: see [Using a list in the game](#using-a-list-in-the-game) below.
   Your list's address is
   `https://raw.githubusercontent.com/YOUR-NAME/YOUR-REPO/main/steam_servers.txt`.

The job log (Actions tab, open a run, step **Collect and filter**) shows how many servers Steam
returned and how many were hidden for each rule.

GitHub pauses scheduled jobs in public repositories after 60 days without activity. The daily list
commits normally count as activity, but if it ever stops, open the Actions tab and click
**Enable workflow**.

## Using a list in the game

The Mac game reads its list sources from one plain text file:

```
~/Library/Application Support/Xash3D/steam_list_url.txt
```

The installer creates it with this repository's list:

```
https://raw.githubusercontent.com/v4lstspolicija/cs16-server-list/main/steam_servers.txt
```

**How the game uses it.** Each time you start the game it reads the file from top to bottom and
downloads the first address that gives a real list (at least 100 servers; error pages are
ignored). The list is saved as `cstrike/steam_servers.txt` in the same folder. If no address
answers, it keeps the list it already has. It downloads at most once every 10 minutes, so
restarting the game a lot does not hammer anyone's site.

**Add your own list.**

1. Check that your list works: open your list's address in a browser. You should see lines like
   `1.2.3.4:27015`.
2. Open the file: in Finder press **Cmd+Shift+G**, paste
   `~/Library/Application Support/Xash3D/steam_list_url.txt`, press Return, and open it with
   TextEdit. In Terminal you can also use `open -e ~/Library/Application\ Support/Xash3D/steam_list_url.txt`.
3. Add your address on its own line:
   - **at the top** to use your list first and the others as backup,
   - **at the bottom** to use it only when the others are down,
   - **as the only line** to use only your list.

   Lines that don't start with `http://` or `https://` are ignored, so you can comment a line out
   with `#`.
4. Save the file and quit the game completely (Cmd+Q), then start it again.
5. Open **Find Servers > Internet**. The servers from your list appear and fill in as the game
   asks each one for its name, map and players.

To force a fresh download straight away, delete
`~/Library/Application Support/Xash3D/cstrike/steam_servers.txt` before starting the game.

Re-running the installer keeps your lines; it only adds this repository's address if it is missing.

**Use your own key in the game instead.** If you have your own Steam Web API key, you don't need
any list website. In the game open **Options > Advanced**, paste the key into **Own Steam Web API key for the server list**
and click OK. The game then builds the list itself on your Mac with `steam-list.py` (at most every
30 minutes, in the background) and ignores `steam_list_url.txt`. The key is saved only on your Mac,
in `cstrike/steam_api_key.txt`. Clear the field to go back to the list websites.

## Without GitHub

`steam-list.py` needs only Python 3, nothing to install:

```sh
echo YOUR_KEY > key.txt
python3 steam-list.py key.txt steam_servers.txt
```

Run it from cron or a systemd timer on any Linux server and publish the file with any web server.
