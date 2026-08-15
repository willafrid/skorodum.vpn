# ASN inventory for an IP allow-list

`asn.check.py` converts a plain list of IP addresses into CSV reports grouped by
network owner (ASN). It uses the public Team Cymru bulk ASN service, rather than
launching one `whois` process per address. This is important for the supplied
large list: it reduces requests from roughly 141,000 to a few hundred batches.

## Run

```sh
python3 asn.check.py -i ips.txt
```

The default settings use batches of 500 addresses and four concurrent requests.
They are intentionally conservative toward the public lookup service. To tune
them for a reliable connection:

```sh
python3 asn.check.py -i ips.txt --batch-size 500 --workers 4 --timeout 20
```

If the network blocks WHOIS on port 43, use the HTTPS fallback instead:

```sh
python3 asn.check.py -i ips.txt --source ripe --workers 4
```

The fallback is slower and returns ASN/prefix data without a friendly ASN name,
so use it primarily to recover from a blocked bulk lookup.

Input accepts one IPv4 or IPv6 address per line. Empty lines and `#` comments
are ignored; malformed values are retained in `ip_report.csv` with an error in
the `status` column. Duplicate IPs are removed by default. Use
`--keep-duplicates` only when their frequency matters.

## Output

- `ip_report.csv` — every submitted address: ASN, BGP prefix, country,
  registry, allocation date, ASN name and lookup status.
- `asn_summary.csv` — the primary decision table: one row per ASN, number of
  allow-listed IPs, unique prefixes and example IPs. Sort by `ip_count`.
- `provider_summary.csv` — aggregate grouped by ASN name and country.
- `provider_summary_ru.csv` — only rows whose registry response says `RU`.
- `whois_results.txt` — compact text version, kept for compatibility with the
  previous script.

The ASN name identifies the network announcing an address, not necessarily the
commercial VPS brand that resells capacity there. Use `asn_summary.csv` to make
a shortlist, then independently confirm each candidate's current IP ranges,
region, price, support and terms before renting anything. Presence in a
historical input list is evidence only; it is not a promise of reachability or
future allow-list status.

## Useful spreadsheet filters

1. In `asn_summary.csv`, sort `ip_count` descending to find networks with the
   largest representation.
2. Filter `country`, `registry` or provider/ASN name according to your hosting
   requirements.
3. Treat `prefix_count` as a rough diversity signal: more distinct prefixes can
   indicate broader coverage, but does not imply better service.
4. Inspect `sample_ips` and `prefixes` before contacting a provider, so you can
   verify that its advertised allocation overlaps the observed networks.
