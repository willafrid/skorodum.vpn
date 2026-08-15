#!/usr/bin/env python3
"""Turn a list of IP addresses into an ASN/provider inventory.

The default lookup uses Team Cymru's bulk ASN service. It is deliberately
batched: looking up 140k addresses one by one with whois is slow and likely to
be rate-limited. The reports are CSV so they can be filtered in a spreadsheet
or loaded into pandas/SQLite without parsing terminal output.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import ipaddress
import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


CYMRU_HOST = "whois.cymru.com"
CYMRU_PORT = 43
RIPE_NETWORK_INFO = "https://stat.ripe.net/data/network-info/data.json?resource="


@dataclass(frozen=True)
class IPRecord:
    ip: str
    asn: str = ""
    prefix: str = ""
    country: str = ""
    registry: str = ""
    allocated: str = ""
    as_name: str = ""
    status: str = "ok"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ASN/provider reports for an IP list.")
    parser.add_argument("-i", "--input", default="ips.txt", help="Input file: one IP per line.")
    parser.add_argument("--ip-report", default="ip_report.csv", help="Per-IP CSV output.")
    parser.add_argument("--asn-summary", default="asn_summary.csv", help="ASN-level CSV output.")
    parser.add_argument("-s", "--summary", default="provider_summary.csv", help="Provider-level CSV output.")
    parser.add_argument("--ru-summary", default="provider_summary_ru.csv", help="Russia-only provider CSV output.")
    parser.add_argument("--output", default="whois_results.txt", help="Compatibility text report (one row per IP).")
    parser.add_argument("--keep-duplicates", action="store_true", help="Keep duplicate input IPs.")
    parser.add_argument(
        "--source",
        choices=("cymru", "ripe"),
        default="cymru",
        help="ASN data source: bulk Cymru (default) or HTTPS RIPEstat fallback.",
    )
    parser.add_argument("--batch-size", type=int, default=500, help="IPs in one bulk request (default: 500).")
    parser.add_argument("-w", "--workers", type=int, default=4, help="Parallel bulk requests (default: 4).")
    parser.add_argument("-t", "--timeout", type=int, default=20, help="Network timeout in seconds (default: 20).")
    parser.add_argument("--sample-size", type=int, default=10, help="Sample IPs per group (default: 10).")
    return parser.parse_args()


def load_ips(path: Path, keep_duplicates: bool) -> tuple[list[str], list[IPRecord]]:
    ips: list[str] = []
    invalid: list[IPRecord] = []
    seen: set[str] = set()
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = raw_line.split("#", 1)[0].strip()
        if not value:
            continue
        try:
            ip = str(ipaddress.ip_address(value))
        except ValueError:
            invalid.append(IPRecord(value, status=f"invalid_input_line_{number}"))
            continue
        if keep_duplicates or ip not in seen:
            ips.append(ip)
            seen.add(ip)
    return ips, invalid


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def lookup_batch(batch: list[str], timeout: int) -> list[IPRecord]:
    query = "begin\nverbose\n" + "\n".join(batch) + "\nend\n"
    try:
        with socket.create_connection((CYMRU_HOST, CYMRU_PORT), timeout=timeout) as connection:
            connection.sendall(query.encode("ascii"))
            connection.shutdown(socket.SHUT_WR)
            response = b""
            while True:
                block = connection.recv(65536)
                if not block:
                    break
                response += block
    except OSError as exc:
        return [IPRecord(ip, status=f"lookup_error: {exc}") for ip in batch]

    records: dict[str, IPRecord] = {}
    for line in response.decode("utf-8", errors="replace").splitlines()[1:]:
        fields = [field.strip() for field in line.split("|")]
        if len(fields) < 7:
            continue
        asn, ip, prefix, country, registry, allocated, as_name = fields[:7]
        records[ip] = IPRecord(ip, asn, prefix, country, registry, allocated, as_name, "ok")
    return [records.get(ip, IPRecord(ip, status="no_asn_data")) for ip in batch]


def lookup_ripe(ip: str, timeout: int) -> IPRecord:
    url = RIPE_NETWORK_INFO + urllib.parse.quote(ip, safe="")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
        data = payload.get("data", {})
        asns = data.get("asns", [])
        return IPRecord(
            ip=ip,
            asn=",".join(str(asn) for asn in asns),
            prefix=str(data.get("prefix") or ""),
            registry="RIPEstat",
            status="ok" if asns else "no_asn_data",
        )
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        return IPRecord(ip, status=f"lookup_error: {exc}")


def lookup(batch: list[str], timeout: int, source: str) -> list[IPRecord]:
    if source == "cymru":
        return lookup_batch(batch, timeout)
    return [lookup_ripe(ip, timeout) for ip in batch]


def sample(records: list[IPRecord], size: int) -> str:
    return ", ".join(record.ip for record in records[:size])


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str | int]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.workers < 1 or args.sample_size < 1:
        print("batch-size, workers and sample-size must be positive.", file=sys.stderr)
        return 2
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    ips, invalid = load_ips(input_path, args.keep_duplicates)
    if not ips and not invalid:
        print("No IP addresses found.", file=sys.stderr)
        return 1
    print(f"Loaded {len(ips)} valid IPs and {len(invalid)} invalid lines.")

    records: list[IPRecord] = []
    batches = chunks(ips, args.batch_size)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(lookup, batch, args.timeout, args.source) for batch in batches]
        for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            records.extend(future.result())
            if completed % 20 == 0 or completed == len(batches):
                print(f"Progress: {completed}/{len(batches)} batches", flush=True)
    records.extend(invalid)
    records.sort(key=lambda record: record.ip)

    headers = ["ip", "asn", "prefix", "country", "registry", "allocated", "as_name", "status"]
    ip_rows = [{key: getattr(record, key) for key in headers} for record in records]
    write_csv(Path(args.ip_report), headers, ip_rows)

    good = [record for record in records if record.status == "ok"]
    by_asn: dict[tuple[str, str, str, str], list[IPRecord]] = defaultdict(list)
    for record in good:
        by_asn[(record.asn, record.as_name, record.country, record.registry)].append(record)
    asn_rows = [
        {"asn": asn, "as_name": name, "country": country, "registry": registry, "ip_count": len(group),
         "prefix_count": len({r.prefix for r in group}), "prefixes": "; ".join(sorted({r.prefix for r in group})),
         "sample_ips": sample(group, args.sample_size)}
        for (asn, name, country, registry), group in by_asn.items()
    ]
    asn_rows.sort(key=lambda row: (-int(row["ip_count"]), str(row["as_name"]), str(row["asn"])))
    write_csv(Path(args.asn_summary), ["asn", "as_name", "country", "registry", "ip_count", "prefix_count", "prefixes", "sample_ips"], asn_rows)

    by_provider: dict[tuple[str, str], list[IPRecord]] = defaultdict(list)
    for record in good:
        by_provider[(record.as_name or "UNKNOWN", record.country or "UNKNOWN")].append(record)
    provider_rows = [
        {"provider": provider, "country": country, "ip_count": len(group),
         "asn_count": len({r.asn for r in group}), "asns": "; ".join(sorted({r.asn for r in group})),
         "prefix_count": len({r.prefix for r in group}), "sample_ips": sample(group, args.sample_size)}
        for (provider, country), group in by_provider.items()
    ]
    provider_rows.sort(key=lambda row: (-int(row["ip_count"]), str(row["provider"])))
    provider_headers = ["provider", "country", "ip_count", "asn_count", "asns", "prefix_count", "sample_ips"]
    write_csv(Path(args.summary), provider_headers, provider_rows)
    write_csv(Path(args.ru_summary), provider_headers, [row for row in provider_rows if row["country"] == "RU"])

    with Path(args.output).open("w", encoding="utf-8") as handle:
        for row in ip_rows:
            handle.write(" | ".join(str(row[key]) for key in ("ip", "asn", "prefix", "country", "as_name", "status")) + "\n")

    statuses = Counter(record.status for record in records)
    print(f"Done: {len(good)} resolved, " + ", ".join(f"{name}={count}" for name, count in sorted(statuses.items())))
    print(f"Reports: {args.ip_report}, {args.asn_summary}, {args.summary}, {args.ru_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
