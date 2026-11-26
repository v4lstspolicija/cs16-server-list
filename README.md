# CS 1.6 server list

`steam_servers.txt` is the list of real Counter-Strike 1.6 servers used by the native Mac build of
the game, one `ip:port` per line. It comes from Valve's master list (Steam Web API
`IGameServersService/GetServerList`) and is rebuilt about once an hour.

Fake servers are removed in two steps (see `steam-list.py`):

1. Rules based on [fakeservers.link](https://fakeservers.link): farms (3+ listings with the same
   name, map and slot count), 40+ listings on one IP, 200+ in one /24, impossible slot/player
   counts and private addresses. Farms copy the names of real servers, so in a group of copies
   the listing on an address of its own (fewer than 10 listings) is kept as the original.
   Originals, and servers on busy hosting addresses (10+ on one IP or 50+ in one /24), are only
   kept if they answer the check below.
2. Every remaining server is asked for its info and player list, like the game does, and these
   are dropped:
   - **fake players**: 3 or more undeclared players with exactly the same connection time, or
     4 or more (and 90% of all) with whole-second times. Real connection times have a random
     fraction; only bots show whole seconds, and real servers declare their bots.
   - **name switching**: asked again 2 seconds later, the server answers with a different
     server's name (proxies copying other servers). Two such ports on one IP drop every
     server on that IP.

   Servers that honestly declare their bots stay in `steam_servers.txt`; the game hides them
   by default ("Hide servers with bots" in the filters).

Three lists are published:

- `steam_servers.txt`: every server that passed the checks above.
- `steam_servers_nobots.txt`: the same servers, only those that answered the check and had
  no bots at all.
- `steam_servers_noruro.txt`: the same servers without Russian and Romanian ones, like the
  game's "Hide Russian & Romanian" filter: hosted in Russia or Romania, a `.ru`/`.ro` address or
  RU tag in the name, Russian- or Romanian-only letters or words, or AMX Mod X language
  `ru`/`ro`. Servers hosted in Ukraine or Moldova, or with Ukrainian letters, a UA tag or AMX
  language `ua`/`uk`, are kept unless their name has a `.ru`/`.ro` address. Countries come from
  the free [DB-IP](https://db-ip.com) country database (IP Geolocation by DB-IP, CC BY 4.0),
  downloaded on every run.

   A server that doesn't answer is kept, so a server that is briefly down isn't lost.

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
4. **Set up the Actions job**: see [Setting up GitHub Actions](#setting-up-github-actions) below.
5. **Check the result**: after the first run, `steam_servers.txt` in your repository has your own
   list (a fork starts with a copy of this repository's list until your first run replaces it).
6. **Use it in the game**: see [Using a list in the game](#using-a-list-in-the-game) below.
   Your list's address is
   `https://raw.githubusercontent.com/YOUR-NAME/YOUR-REPO/main/steam_servers.txt`.

## Setting up GitHub Actions

GitHub Actions is what runs `steam-list.py` for you every day. The job is already written
(`.github/workflows/steam-list.yml`); you only have to switch it on.

1. **Allow the job to save the list.** Open **Settings** (top of your repository) > **Actions** >
   **General**. Scroll down to **Workflow permissions**, choose **Read and write permissions** and
   click **Save**. Without this, the job can't commit `steam_servers.txt`.
2. **Turn on Actions (forks only).** Open the **Actions** tab. A fork shows the message
   *"Workflows aren't being run on this forked repository"*. Click the green button
   **I understand my workflows, go ahead and enable them**. GitHub switches off scheduled jobs in
   every fork until you do this. If you made a new repository instead of forking, skip this step.
3. **Start the first run.** Still in **Actions**, click **steam server list** in the list on the
   left. On the right click **Run workflow**, keep branch `main`, and click the green
   **Run workflow** button. If a yellow note says *"This scheduled workflow is disabled"*, click
   **Enable workflow** first.
4. **Wait for it.** A new run appears with a yellow dot (running). After about 3 minutes it turns
   into a green check. Open the run, click **build**, then the step **Collect and filter** to see
   how many servers Steam returned and how many fakes were hidden.
5. **Done.** From now on it runs by itself every day at 04:17 UTC. Every run that finds a change
   adds a commit called `server list <date>`. To run it more often, edit the `cron:` line in
   `.github/workflows/steam-list.yml`; for example `"17 */6 * * *"` runs every 6 hours. Steam
   allows 100 000 API calls a day and one run uses about 130.

**If the run fails (red X)**, open it and look at the last lines of the failed step:

| Error | Fix |
| --- | --- |
| `HTTP Error 403: Forbidden` in **Collect and filter** | The `STEAM_API_KEY` secret is missing or wrong. Check its name is exactly `STEAM_API_KEY` and paste the key again. |
| `Permission to ... denied to github-actions[bot]` in **Publish** | Do step 1 above (Read and write permissions), then run it again. |
| `HTTP Error 429` or a timeout | Steam is busy or the key hit its daily limit. It runs again tomorrow, or click **Re-run jobs**. |

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
