#!/usr/bin/env python3
"""Valve's Counter-Strike 1.6 server list without the fake servers.

Steam Web API IGameServersService/GetServerList returns at most 10 000 rows per call and the
fakes alone are >100 000 listings, so (like fakeservers.link, github.com/romashuhov/fakeservers.link)
the query is split into smaller buckets until none is capped. Then these are dropped:
  - farms: 3+ listings with the same name + map + max players (fakeservers.link's definition)
  - 10+ listings on one IP, 50+ in one /24
  - more than 32 slots or more players than slots (impossible on GoldSrc)
  - private / reserved addresses

usage: steam-list.py KEYFILE OUTFILE
Writes "ip:port" lines. Python 3 standard library only.
"""
import collections, json, re, sys, time, urllib.parse, urllib.request

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

    why = collections.Counter()
    keep = []
    for s in servers:
        i, mx, pl = ip(s), s.get("max_players", 0), s.get("players", 0)
        if unroutable(i): why["private/reserved address"] += 1
        elif per_sig[sig(s)] >= 3: why["farm (same name+map+slots on 3+)"] += 1
        elif per_ip[i] >= 10: why["10+ on one IP"] += 1
        elif per_net[i.rsplit(".", 1)[0]] >= 50: why["50+ in one /24"] += 1
        elif mx > 32 or mx < 1 or pl > mx: why["impossible slots/players"] += 1
        elif not norm(s.get("name")) or not s.get("map"): why["empty name/map"] += 1
        else: keep.append(s["addr"])

    if not keep:
        sys.exit("no servers left, keeping the old list")
    with open(out + ".tmp", "w") as f:
        f.write("\n".join(sorted(keep)) + "\n")
    import os
    os.replace(out + ".tmp", out)
    print("%d API calls%s, %d listings, %d kept" % (c.calls, " (truncated)" if c.truncated else "", len(servers), len(keep)))
    for k, v in why.most_common():
        print("  hidden %6d  %s" % (v, k))


if __name__ == "__main__":
    main()
