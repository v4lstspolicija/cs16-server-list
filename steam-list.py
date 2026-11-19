#!/usr/bin/env python3
"""Valve's Counter-Strike 1.6 server list without the fake servers.

Steam Web API IGameServersService/GetServerList returns at most 10 000 rows per call and the
fakes alone are >100 000 listings, so (like fakeservers.link, github.com/romashuhov/fakeservers.link)
the query is split into smaller buckets until none is capped. Then these are dropped:
  - farms: 3+ listings with the same name + map + max players (fakeservers.link's definition),
    except the original: farms copy real servers' names, so a listing on an IP with fewer than
    10 listings is kept when at most 2 of the group are like that (it must answer)
  - 40+ listings on one IP, 200+ in one /24 (fake farms); smaller crowds (10+ on an IP or
    50+ in a /24: hosting companies, common in AR / KZ / UZ / CN) are kept only if they
    answer our own query and pass the checks below
  - more than 32 slots or more players than slots (impossible on GoldSrc)
  - private / reserved addresses
Then every remaining server is asked for its info and player list (like the game does) and
these are dropped too (a server that doesn't answer is kept):
  - fake players: 3+ undeclared players with the very same connection time, or 4+ (and 90%)
    with whole-second times; real connection times have a random fraction, only bots
    (which servers declare) show whole seconds
  - name switching: a second answer 2 s later carries a different server's name (proxies
    copying other servers); 2+ such ports on one IP drop every server on that IP

A third list, *_noruro.txt, also leaves out Russian and Romanian servers, like the game's
"Hide Russian & Romanian" filter: hosted in RU/RO (DB-IP country lite, CC BY 4.0), a .ru/.ro
address or RU tag in the name, Russian/Romanian-only letters or words, or AMX Mod X language
ru/ro. Servers hosted in Ukraine or Moldova, or with Ukrainian letters/tags or AMX language
ua/uk, are kept (a .ru/.ro address in the name still drops them).

usage: steam-list.py KEYFILE OUTFILE
Writes "ip:port" lines. Python 3 standard library only.
"""
import collections, json, re, select, socket, struct, sys, time, urllib.parse, urllib.request

ENDPOINT = "https://api.steampowered.com/IGameServersService/GetServerList/v1/"
CAP = 10000 - 20
REGIONS = [0, 1, 2, 3, 4, 5, 6, 7, 255]
SPLITTERS = [
    lambda b: [b + "\\region\\%d" % r for r in REGIONS],
    lambda b: [b + "\\secure\\1", b + "\\nor\\1\\secure\\1"],
    lambda b: [b + "\\noplayers\\1", b + "\\nor\\1\\noplayers\\1"],
    lambda b: [b + "\\linux\\1", b + "\\nor\\1\\linux\\1"],
    lambda b: [b + "\\dedicated\\1", b + "\\nor\\1\\dedicated\\1"],
    lambda b: [b + "\\password\\0", b + "\\nor\\1\\password\\0"],
]


class Collector:
    def __init__(self, key):
        self.key, self.seen, self.calls, self.truncated = key, {}, 0, False

    def page(self, flt):
        q = urllib.parse.urlencode({"key": self.key, "filter": flt, "limit": 10000})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(ENDPOINT + "?" + q, timeout=120) as r:
                    rows = json.load(r).get("response", {}).get("servers", [])
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
        self.calls += 1
        for s in rows:
            if s.get("addr"):
                self.seen.setdefault(s["addr"], s)
        return rows

    def by_maps(self, flt, sample, depth=0):
        maps = [m for m, _ in collections.Counter(s.get("map") for s in sample if s.get("map")).most_common(25)]
        if not maps or depth >= 8:
            self.truncated = True
            return
        for m in maps:
            if len(self.page(flt + "\\map\\" + m)) >= CAP:
                self.truncated = True
        rest = flt + "\\nor\\%d" % len(maps) + "".join("\\map\\" + m for m in maps)
        rows = self.page(rest)
        if len(rows) >= CAP:
            self.by_maps(rest, rows, depth + 1)

    def bucket(self, flt, depth=0):
        rows = self.page(flt)
        if len(rows) < CAP:
            return
        if depth < len(SPLITTERS):
            for sub in SPLITTERS[depth](flt):
                self.bucket(sub, depth + 1)
        else:
            self.by_maps(flt, rows)


# ---- probing: A2S_INFO twice and A2S_PLAYER, all servers in parallel over one UDP socket
HDR = b"\xff\xff\xff\xff"
A2S_INFO = HDR + b"TSource Engine Query\x00"
A2S_PLAYER = HDR + b"U"
A2S_RULES = HDR + b"V"
QUERY = {"info": A2S_INFO, "players": A2S_PLAYER + HDR, "rules": A2S_RULES + HDR}
RESEND = {"info": A2S_INFO, "players": A2S_PLAYER, "rules": A2S_RULES}


def _cstr(d, c):
    e = d.index(b"\0", c)
    return d[c:e].decode("utf-8", "replace"), e + 1


def _info(d):
    if d[4:5] == b"I":
        c = 6
        name, c = _cstr(d, c)
        for _ in range(3):
            _, c = _cstr(d, c)
        return {"name": name, "players": d[c + 2], "bots": d[c + 4]}
    if d[4:5] == b"m":
        c = 5
        _, c = _cstr(d, c)
        name, c = _cstr(d, c)
        for _ in range(3):
            _, c = _cstr(d, c)
        pl = d[c]
        c += 6
        mod = d[c]
        c += 1
        if mod:
            _, c = _cstr(d, c)
            _, c = _cstr(d, c)
            c += 11
        return {"name": name, "players": pl, "bots": d[c + 1] if c + 1 < len(d) else 0}
    return None


def _players(d):
    n, c, out = d[5], 6, []
    for _ in range(n):
        c += 1
        name, c = _cstr(d, c)
        _, dur = struct.unpack_from("<if", d, c)
        c += 8
        out.append((name, dur))
    return out


def _round(sock, addrs, kind, got, rate=250, wait=4.0, attempts=2):
    """send one query type to every address (answering challenges) and collect replies"""
    splits = {}

    def handle(d, a):
        if d[:4] == b"\xfe\xff\xff\xff":  # GoldSrc split reply
            part = splits.setdefault((a, d[4:8]), {})
            part[d[8] >> 4] = d[9:]
            if len(part) != d[8] & 15:
                return
            d = b"".join(part[i] for i in sorted(part))
        if d[:4] != HDR or len(d) < 6:
            return
        t = d[4:5]
        try:
            if t == b"A" and len(d) >= 9:
                sock.sendto(RESEND[kind] + d[5:9], a)
            elif kind == "info" and t in (b"I", b"m"):
                v = _info(d)
                if v and (a not in got or t == b"I"):
                    got[a] = v
            elif kind == "players" and t == b"D" and d[5] > 0:
                got[a] = _players(d)
            elif kind == "rules" and t == b"E":
                m = re.search(rb"amx_lang[a-z]*\x00([^\x00]*)\x00", d)
                got[a] = m.group(1).decode("utf-8", "replace").strip().lower() if m else ""
        except (ValueError, IndexError, struct.error, OSError):
            pass

    def drain(until):
        while time.time() < until:
            r, _, _ = select.select([sock], [], [], 0.02)
            while r:
                try:
                    d, a = sock.recvfrom(4096)
                except BlockingIOError:
                    break
                handle(d, a)

    for attempt in range(attempts):
        if attempt:
            time.sleep(1.5)  # servers drop queries that come too fast from one address
        start, sent = time.time(), 0
        for a in addrs:
            if a in got:
                continue
            try:
                sock.sendto(QUERY[kind], a)
            except OSError:
                continue
            sent += 1
            drain(start + sent / rate)
        drain(time.time() + wait)
    return got


def _letters(n):
    return re.sub(r"[^a-z\u0080-\uffff]", "", re.sub(r"\^\d", "", n.lower()))


def probe(addrs):
    """returns {addr: reason} for servers that show fake signs"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
    sock.setblocking(False)
    targets = []
    for a in addrs:
        h, p = a.rsplit(":", 1)
        targets.append((h, int(p)))
    info1 = _round(sock, targets, "info", {})
    asked = [a for a, v in info1.items() if v["players"] - v["bots"] >= 3]
    players = _round(sock, asked, "players", {}, attempts=4)
    time.sleep(2)
    info2 = _round(sock, list(info1), "info", {})
    time.sleep(1)
    rules = _round(sock, list(info1), "rules", {})
    sock.close()
    probe.lang = {"%s:%d" % a: v for a, v in rules.items()}
    probe.names = {"%s:%d" % a: v["name"] for a, v in info1.items()}

    bad = {}
    for a, v in info1.items():
        key = "%s:%d" % a
        pl = players.get(a) or []
        long_times = [d for _, d in pl if d > 600]
        same = max([sum(1 for y in long_times if abs(x - y) < 0.05) for x in long_times] or [0])
        timed = [d for _, d in pl if 60 < d < 100000]
        whole = sum(1 for d in timed if abs(d - round(d)) < 0.001)
        if same - v["bots"] >= 3:
            bad[key] = "fake players (same connection time)"
        elif whole - v["bots"] >= 4 and whole * 10 >= len(timed) * 9:
            bad[key] = "fake players (whole-second times)"
        elif a in info2:
            x, y = _letters(v["name"]), _letters(info2[a]["name"])
            common = 0
            while common < min(len(x), len(y)) and x[common] == y[common]:
                common += 1
            if len(x) >= 6 and len(y) >= 6 and common < 6:
                bad[key] = "switches to other servers' names"
    # proxy farms: 2+ name-switching ports on one IP -> every server on that IP
    farms = collections.Counter(k.rsplit(":", 1)[0] for k, why in bad.items() if why.startswith("switches"))
    for a in addrs:
        if farms[a.rsplit(":", 1)[0]] >= 2 and a not in bad:
            bad[a] = "on a name-switching proxy farm"
    print("probed %d servers: %d answered, %d of %d player lists" % (len(addrs), len(info1), len(players), len(asked)))
    # for the second list: servers that answered and run no bots (their own count, either query)
    probe.answered = set("%s:%d" % a for a in info1)
    probe.no_bots = set("%s:%d" % a for a, v in info1.items()
                        if v["bots"] == 0 and info2.get(a, v)["bots"] == 0)
    return bad


def load_countries():
    """DB-IP country lite (CC BY 4.0, https://db-ip.com): returns ip -> country code, or None"""
    import bisect, gzip, io
    t = time.gmtime()
    months = ["%04d-%02d" % (t.tm_year, t.tm_mon),
              "%04d-%02d" % (t.tm_year - (t.tm_mon == 1), 12 if t.tm_mon == 1 else t.tm_mon - 1)]
    for m in months:
        url = "https://download.db-ip.com/free/dbip-country-lite-%s.csv.gz" % m
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cs16-server-list/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = gzip.decompress(r.read())
        except Exception as e:
            print("country database %s: %s" % (m, e))
            continue
        starts, codes = [], []
        for line in io.StringIO(data.decode("ascii", "replace")):
            f = line.strip().split(",")
            if len(f) < 3 or ":" in f[0]:
                continue
            try:
                a = [int(x) for x in f[0].split(".")]
            except ValueError:
                continue
            starts.append((a[0] << 24) | (a[1] << 16) | (a[2] << 8) | a[3])
            codes.append(f[2].strip('"').upper())
        print("country database %s: %d ranges" % (m, len(starts)))

        def cc(ip):
            try:
                a = [int(x) for x in ip.split(".")]
            except ValueError:
                return ""
            i = bisect.bisect_right(starts, (a[0] << 24) | (a[1] << 16) | (a[2] << 8) | a[3]) - 1
            return codes[i] if i >= 0 else ""
        return cc
    return None


def _word(n, w):
    return re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", n) is not None


def looks_ru_ro(name, cc, lang):
    """the game's "Hide Russian & Romanian" rules (menus/ServerBrowser.cpp LooksRussianOrRomanian)"""
    if cc in ("RU", "RO"):
        return True
    n = re.sub(r"\^\d", "", name or "").lower()
    if re.search(r"\.(ru|ro)(?![a-z])", n):
        return True  # web address: always, even hosted in Ukraine / Moldova
    if cc in ("UA", "MD"):
        return False
    if lang in ("ua", "uk") or lang.startswith("ukr"):
        return False
    if _word(n, "md") or "moldova" in n or ".md" in n:
        return False
    if re.search("[\u0456\u0457\u0454\u0491\u0406\u0407\u0404\u0490]", name or "") or \
            _word(n, "ua") or _word(n, "ukr") or _word(n, "ukraine") or "\u0443\u043a\u0440\u0430" in n:
        return False  # Ukrainian letters / tags
    if lang in ("ru", "ro") or lang.startswith("russian") or lang.startswith("romanian"):
        return True
    if _word(n, "ru"):
        return True
    if re.search("[\u0219\u0218\u021b\u021a\u0163\u0162]", name or "") or \
            (re.search("[\u0103\u0102]", name or "") and cc != "VN"):
        return True  # Romanian-only letters
    if _word(n, "romania") or "romanesc" in n or any(_word(n, w) for w in ("romanesti", "jucatori", "gratuit", "gratuita")):
        return True
    return re.search("[\u044b\u042b\u044d\u042d\u0451\u0401]", name or "") is not None  # Russian-only letters


def main():
    keyfile, out = sys.argv[1], sys.argv[2]
    key = re.sub(r"[^A-Za-z0-9]", "", open(keyfile).read())

    c = Collector(key)
    c.bucket("\\appid\\10")
    servers = [s for s in c.seen.values() if s.get("gamedir", "cstrike") == "cstrike"]

    ip = lambda s: s["addr"].rsplit(":", 1)[0]
    norm = lambda t: re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", "", t or "")).strip().lower()
    sig = lambda s: (norm(s.get("name")), (s.get("map") or "").lower(), s.get("max_players", 0))
    per_ip = collections.Counter(ip(s) for s in servers)
    per_net = collections.Counter(ip(s).rsplit(".", 1)[0] for s in servers)
    per_sig = collections.Counter(sig(s) for s in servers)

    import ipaddress
    def unroutable(a):
        try:
            x = ipaddress.ip_address(a)
            return x.is_private or x.is_reserved or x.is_loopback or x.is_link_local or x.is_multicast or x.is_unspecified
        except ValueError:
            return True

    # clone farms copy real servers' names, so the real server is in its clones' group too.
    # The original is the listing on an IP of its own (fewer than 10 listings); clones sit on
    # farm IPs with hundreds. At most 2 such listings per group, and they must answer.
    lone = collections.defaultdict(list)
    for s in servers:
        if per_ip[ip(s)] < 10:
            lone[sig(s)].append(s["addr"])
    def original(s):
        group = lone.get(sig(s), [])
        return per_ip[ip(s)] < 10 and len(group) <= 2

    why = collections.Counter()
    keep, crowded = [], set()
    for s in servers:
        i, mx, pl = ip(s), s.get("max_players", 0), s.get("players", 0)
        if unroutable(i): why["private/reserved address"] += 1
        elif per_sig[sig(s)] >= 3 and not original(s): why["farm (same name+map+slots on 3+)"] += 1
        elif per_ip[i] >= 40: why["40+ on one IP"] += 1
        elif per_net[i.rsplit(".", 1)[0]] >= 200: why["200+ in one /24"] += 1
        elif mx > 32 or mx < 1 or pl > mx: why["impossible slots/players"] += 1
        elif not norm(s.get("name")) or not s.get("map"): why["empty name/map"] += 1
        else:
            keep.append(s["addr"])
            if per_ip[i] >= 10 or per_net[i.rsplit(".", 1)[0]] >= 50 or per_sig[sig(s)] >= 3:
                crowded.add(s["addr"])  # must answer to stay

    if not keep:
        sys.exit("no servers left, keeping the old list")

    # Steam's answer differs from call to call (some runs miss thousands of listings), so
    # servers from the previous list that Steam left out this time are checked again and kept
    # if they still answer and pass the checks. Ones Steam did list and the rules dropped stay out.
    listed = set(s["addr"] for s in servers)
    try:
        previous = set(re.findall(r"^\d+\.\d+\.\d+\.\d+:\d+$", open(out).read(), re.M))
    except OSError:
        previous = set()
    carried = sorted(a for a in previous if a not in listed)
    keep += carried
    crowded.update(carried)
    print("%d servers from the previous list were not in Steam's answer: checking them again" % len(carried))

    bad = probe(keep)
    for a in crowded:
        if a not in bad and a not in probe.answered:
            bad[a] = "crowded or cloned and didn't answer"
    for reason in bad.values():
        why[reason] += 1
    keep = [a for a in keep if a not in bad]
    with open(out + ".tmp", "w") as f:
        f.write("\n".join(sorted(keep)) + "\n")
    import os
    os.replace(out + ".tmp", out)
    # second list: the same servers, only those that answered and have no bots
    # third list: without Russian and Romanian servers
    cc = load_countries()
    api_name = {s["addr"]: s.get("name", "") for s in servers}
    noruro = [a for a in keep if not looks_ru_ro(probe.names.get(a) or api_name.get(a, ""),
                                                  cc(a.rsplit(":", 1)[0]) if cc else "",
                                                  probe.lang.get(a, ""))]
    if cc:
        out3 = out[:-4] + "_noruro.txt" if out.endswith(".txt") else out + "_noruro"
        with open(out3 + ".tmp", "w") as f:
            f.write("\n".join(sorted(noruro)) + "\n")
        os.replace(out3 + ".tmp", out3)
        print("%d servers without Russian/Romanian ones written to %s (%d rules answers)" % (len(noruro), out3, len(probe.lang)))
    else:
        print("no country database: the list without Russian/Romanian servers was not updated")
    nobots = [a for a in keep if a in probe.no_bots]
    out2 = out[:-4] + "_nobots.txt" if out.endswith(".txt") else out + "_nobots"
    with open(out2 + ".tmp", "w") as f:
        f.write("\n".join(sorted(nobots)) + "\n")
    os.replace(out2 + ".tmp", out2)
    print("%d servers without bots written to %s" % (len(nobots), out2))
    print("%d API calls%s, %d listings, %d kept" % (c.calls, " (truncated)" if c.truncated else "", len(servers), len(keep)))
    for k, v in why.most_common():
        print("  hidden %6d  %s" % (v, k))


if __name__ == "__main__":
    main()
