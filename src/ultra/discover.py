"""Local network discovery — LAN hosts, mDNS services, smart-home hints."""

from __future__ import annotations

import json
import platform
import re
import socket
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any

# mDNS service types useful for home orchestration
MDNS_SERVICE_TYPES = (
    "_homeassistant._tcp.local.",
    "_googlecast._tcp.local.",
    "_mqtt._tcp.local.",
    "_http._tcp.local.",
    "_hap._tcp.local.",
    "_airplay._tcp.local.",
    "_ipp._tcp.local.",
    "_smb._tcp.local.",
)

# Quick TCP probes for hosts found on the LAN (not full port scan)
PROBE_PORTS: dict[int, str] = {
    8123: "home_assistant",
    1883: "mqtt",
    8883: "mqtt_tls",
    80: "http",
    443: "https",
    22: "ssh",
    8080: "http_alt",
}

HINT_TEMPLATES: dict[str, tuple[str, str]] = {
    "home_assistant": (
        "home_assistant",
        "Home Assistant likely at {url} — create a long-lived token under Settings → People",
    ),
    "mqtt": ("mqtt", "MQTT broker at {host}:{port}"),
    "mqtt_tls": ("mqtt", "MQTT broker (TLS) at {host}:{port}"),
    "googlecast": ("media", "Chromecast / Google TV at {host}:{port}"),
    "chromecast": ("media", "Chromecast / Google TV at {host}:{port}"),
    "hap": ("homekit", "HomeKit accessory at {host}:{port}"),
    "airplay": ("media", "AirPlay device at {host}:{port}"),
    "http": ("web_ui", "Web interface at {url}"),
    "https": ("web_ui", "Web interface at {url}"),
}


@dataclass
class DiscoveredHost:
    ip: str
    hostname: str | None = None
    mac: str | None = None
    sources: list[str] = field(default_factory=list)


@dataclass
class DiscoveredService:
    service_type: str
    name: str
    host: str
    port: int
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class DiscoveryHint:
    category: str
    message: str
    host: str | None = None
    port: int | None = None
    url: str | None = None


@dataclass
class DiscoveryResult:
    scanned_at: str
    subnet: str | None
    platform: str
    methods: list[str]
    hosts: list[DiscoveredHost]
    services: list[DiscoveredService]
    open_ports: list[dict[str, Any]]
    hints: list[DiscoveryHint]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_at": self.scanned_at,
            "subnet": self.subnet,
            "platform": self.platform,
            "methods": self.methods,
            "hosts": [asdict(h) for h in self.hosts],
            "services": [asdict(s) for s in self.services],
            "open_ports": self.open_ports,
            "hints": [asdict(h) for h in self.hints],
            "errors": self.errors,
        }


def default_discover_path(workspace: Path) -> Path:
    return (workspace / "projects" / "smart-home" / "discovered.json").resolve()


def ensure_smart_home_dir(smart_home_root: Path) -> Path:
    """Create smart-home workspace folder and seed README from template if needed."""
    smart_home_root.mkdir(parents=True, exist_ok=True)
    readme = smart_home_root / "README.md"
    if not readme.is_file():
        template = Path(__file__).resolve().parents[2] / "templates" / "smart-home" / "README.md"
        if template.is_file():
            readme.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    (smart_home_root / "secrets").mkdir(exist_ok=True)
    (smart_home_root / "scripts").mkdir(exist_ok=True)
    return smart_home_root


def detect_local_subnet() -> str | None:
    """Best-effort local /24 subnet from the default-route interface."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
        net = ip_network(f"{local_ip}/24", strict=False)
        return str(net)
    except OSError:
        return None


def _run_command(cmd: list[str], *, timeout: int = 120) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 127, "", str(exc)


def _parse_arp_scan_output(text: str) -> list[DiscoveredHost]:
    hosts: list[DiscoveredHost] = []
    for line in text.splitlines():
        # 192.168.1.42   11:22:33:44:55:66   Vendor
        m = re.match(
            r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f:]{11,17})\s*(.*)?$",
            line.strip(),
            re.I,
        )
        if not m:
            continue
        ip, mac, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
        hostname = rest.split()[0] if rest and not rest.startswith("(") else None
        hosts.append(
            DiscoveredHost(ip=ip, hostname=hostname, mac=mac.lower(), sources=["arp-scan"])
        )
    return hosts


def _parse_nmap_sn_output(text: str) -> list[DiscoveredHost]:
    hosts: list[DiscoveredHost] = []
    current_ip: str | None = None
    for line in text.splitlines():
        m = re.search(r"Nmap scan report for (.+)", line)
        if m:
            target = m.group(1).strip()
            if "(" in target and ")" in target:
                hostname = target.split("(")[0].strip()
                ip = target.split("(")[1].split(")")[0].strip()
            elif re.match(r"\d+\.\d+\.\d+\.\d+", target):
                ip = target
                hostname = None
            else:
                ip = None
                hostname = target
            if ip:
                current_ip = ip
                hosts.append(
                    DiscoveredHost(ip=ip, hostname=hostname, sources=["nmap"])
                )
            continue
        if current_ip and "MAC Address:" in line:
            mac_m = re.search(r"MAC Address:\s+([0-9A-F:]{11,17})", line, re.I)
            if mac_m and hosts:
                hosts[-1].mac = mac_m.group(1).lower()
    return hosts


def _ping_sweep(subnet: str, *, max_hosts: int = 64) -> list[DiscoveredHost]:
    """Fallback: ping addresses in subnet (slow; prefer arp-scan/nmap on Pi)."""
    hosts: list[DiscoveredHost] = []
    net = ip_network(subnet, strict=False)
    addresses = [str(ip) for ip in list(net.hosts())[:max_hosts]]

    is_windows = platform.system().lower() == "windows"
    ping_flag = "-n" if is_windows else "-c"
    wait_flag = "-w" if is_windows else "-W"
    wait_val = "500" if is_windows else "1"

    for ip in addresses:
        code, _, _ = _run_command(
            ["ping", ping_flag, "1", wait_flag, wait_val, ip],
            timeout=2,
        )
        if code == 0:
            hosts.append(DiscoveredHost(ip=ip, sources=["ping"]))
    return hosts


def scan_lan_hosts(subnet: str | None, *, ping_timeout: int = 25) -> tuple[list[DiscoveredHost], str, list[str]]:
    """Discover live hosts on the LAN. Returns hosts, method used, errors."""
    _ = ping_timeout  # reserved for future tuning
    errors: list[str] = []
    target = subnet or detect_local_subnet()
    if not target:
        return [], "none", ["Could not detect local subnet — pass --subnet CIDR"]

    if _command_exists("arp-scan"):
        code, out, err = _run_command(["arp-scan", "--localnet", "--ignoredups"], timeout=60)
        if code == 0 and out.strip():
            return _parse_arp_scan_output(out), "arp-scan", errors
        if err:
            errors.append(f"arp-scan: {err.strip()}")

    if _command_exists("nmap"):
        code, out, err = _run_command(["nmap", "-sn", target], timeout=120)
        if code == 0 and out.strip():
            return _parse_nmap_sn_output(out), "nmap", errors
        if err:
            errors.append(f"nmap: {err.strip()}")

    # Limited ping sweep — cap work on large subnets
    hosts = _ping_sweep(target)
    if not hosts:
        errors.append("No hosts found via ping sweep (try installing arp-scan or nmap on the Pi)")
    return hosts, "ping", errors


def _command_exists(name: str) -> bool:
    if platform.system().lower() == "windows":
        cmd = ["where", name]
    else:
        cmd = ["sh", "-c", f"command -v {name}"]
    code, _, _ = _run_command(cmd, timeout=5)
    return code == 0


class _MdnsCollector:
    def __init__(self) -> None:
        self.services: list[DiscoveredService] = []
        self._lock = threading.Lock()

    def add_service(self, zc: Any, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=2000)
        if not info:
            return
        host = socket.inet_ntoa(info.addresses[0]) if info.addresses else ""
        if not host:
            return
        props: dict[str, str] = {}
        if info.properties:
            for key, val in info.properties.items():
                k = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
                v = val.decode("utf-8", errors="replace") if isinstance(val, bytes) else str(val)
                props[k] = v
        svc = DiscoveredService(
            service_type=type_.rstrip("."),
            name=name.removesuffix(type_).rstrip("."),
            host=host,
            port=int(info.port or 0),
            properties=props,
        )
        with self._lock:
            self.services.append(svc)

    def remove_service(self, zc: Any, type_: str, name: str) -> None:
        return

    def update_service(self, zc: Any, type_: str, name: str) -> None:
        return


def scan_mdns_services(*, timeout: float = 5.0) -> tuple[list[DiscoveredService], list[str]]:
    """Browse common smart-home mDNS service types."""
    errors: list[str] = []
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return [], ["zeroconf not installed — pip install zeroconf"]

    collector = _MdnsCollector()
    zc = Zeroconf()
    browsers: list[ServiceBrowser] = []
    try:
        for svc_type in MDNS_SERVICE_TYPES:
            browsers.append(ServiceBrowser(zc, svc_type, collector))
        threading.Event().wait(timeout)
    except Exception as exc:
        errors.append(f"mdns: {exc}")
    finally:
        for browser in browsers:
            browser.cancel()
        zc.close()

    # Dedupe
    seen: set[tuple[str, str, int]] = set()
    unique: list[DiscoveredService] = []
    for svc in collector.services:
        key = (svc.service_type, svc.host, svc.port)
        if key in seen:
            continue
        seen.add(key)
        unique.append(svc)
    return unique, errors


def probe_common_ports(hosts: list[DiscoveredHost], *, max_hosts: int = 32) -> list[dict[str, Any]]:
    """Light TCP connect check — not a full port scan."""
    results: list[dict[str, Any]] = []
    for host in hosts[:max_hosts]:
        for port, label in PROBE_PORTS.items():
            try:
                with socket.create_connection((host.ip, port), timeout=0.4):
                    results.append({"ip": host.ip, "port": port, "label": label})
            except OSError:
                continue
    return results


def _hint_from_service(svc: DiscoveredService) -> DiscoveryHint | None:
    st = svc.service_type.lower()
    category = "service"
    message = f"{svc.service_type} — {svc.name} at {svc.host}:{svc.port}"
    url: str | None = None

    if "homeassistant" in st:
        category = "home_assistant"
        url = f"http://{svc.host}:{svc.port or 8123}"
        message = HINT_TEMPLATES["home_assistant"][1].format(url=url, host=svc.host, port=svc.port)
    elif "googlecast" in st:
        category = "media"
        message = HINT_TEMPLATES["googlecast"][1].format(host=svc.host, port=svc.port, url=None)
    elif "mqtt" in st:
        category = "mqtt"
        message = HINT_TEMPLATES["mqtt"][1].format(host=svc.host, port=svc.port, url=None)
    elif "hap" in st:
        category = "homekit"
        message = HINT_TEMPLATES["hap"][1].format(host=svc.host, port=svc.port, url=None)
    elif "airplay" in st:
        category = "media"
        message = HINT_TEMPLATES["airplay"][1].format(host=svc.host, port=svc.port, url=None)
    elif st.startswith("_http"):
        category = "web_ui"
        url = f"http://{svc.host}:{svc.port or 80}"
        message = f"HTTP service ({svc.name}) at {url}"

    return DiscoveryHint(category=category, message=message, host=svc.host, port=svc.port, url=url)


def _hints_from_ports(open_ports: list[dict[str, Any]]) -> list[DiscoveryHint]:
    hints: list[DiscoveryHint] = []
    seen: set[str] = set()
    for entry in open_ports:
        label = entry["label"]
        ip, port = entry["ip"], entry["port"]
        key = f"{label}:{ip}:{port}"
        if key in seen:
            continue
        seen.add(key)
        url = f"http://{ip}:{port}" if port in (80, 8123, 8080) else None
        if port == 443:
            url = f"https://{ip}"
        tpl = HINT_TEMPLATES.get(label)
        if tpl:
            category, msg = tpl
            message = msg.format(host=ip, port=port, url=url or f"{ip}:{port}")
        else:
            category, message = label, f"{label} at {ip}:{port}"
        hints.append(DiscoveryHint(category=category, message=message, host=ip, port=port, url=url))
    return hints


def merge_hosts(existing: list[dict], new: list[DiscoveredHost]) -> list[dict]:
    by_ip: dict[str, dict] = {h["ip"]: dict(h) for h in existing if h.get("ip")}
    for host in new:
        row = by_ip.get(host.ip, {"ip": host.ip, "sources": []})
        if host.hostname and not row.get("hostname"):
            row["hostname"] = host.hostname
        if host.mac and not row.get("mac"):
            row["mac"] = host.mac
        sources = set(row.get("sources") or [])
        sources.update(host.sources)
        row["sources"] = sorted(sources)
        by_ip[host.ip] = row
    return sorted(by_ip.values(), key=lambda h: ip_address(h["ip"]))


def run_discovery(
    *,
    subnet: str | None = None,
    mdns_timeout: float = 5.0,
    ping_timeout: int = 25,
    probe_ports: bool = True,
) -> DiscoveryResult:
    methods: list[str] = []
    errors: list[str] = []

    hosts, lan_method, lan_errors = scan_lan_hosts(subnet, ping_timeout=ping_timeout)
    if lan_method != "none":
        methods.append(lan_method)
    errors.extend(lan_errors)

    services, mdns_errors = scan_mdns_services(timeout=mdns_timeout)
    if services or not mdns_errors:
        methods.append("mdns")
    errors.extend(mdns_errors)

    # Add mDNS-only hosts
    host_ips = {h.ip for h in hosts}
    for svc in services:
        if svc.host not in host_ips:
            hosts.append(DiscoveredHost(ip=svc.host, hostname=svc.name, sources=["mdns"]))
            host_ips.add(svc.host)
        else:
            for h in hosts:
                if h.ip == svc.host:
                    if "mdns" not in h.sources:
                        h.sources.append("mdns")
                    if not h.hostname:
                        h.hostname = svc.name

    open_ports: list[dict[str, Any]] = []
    if probe_ports and hosts:
        open_ports = probe_common_ports(hosts)
        if open_ports:
            methods.append("tcp-probe")

    hints: list[DiscoveryHint] = []
    for svc in services:
        hint = _hint_from_service(svc)
        if hint:
            hints.append(hint)
    hints.extend(_hints_from_ports(open_ports))

    # Dedupe hints by message
    seen_msgs: set[str] = set()
    unique_hints: list[DiscoveryHint] = []
    for hint in hints:
        if hint.message in seen_msgs:
            continue
        seen_msgs.add(hint.message)
        unique_hints.append(hint)

    return DiscoveryResult(
        scanned_at=datetime.now(timezone.utc).isoformat(),
        subnet=subnet or detect_local_subnet(),
        platform=platform.system(),
        methods=methods,
        hosts=hosts,
        services=services,
        open_ports=open_ports,
        hints=unique_hints,
        errors=errors,
    )


def save_discovery(result: DiscoveryResult, path: Path, *, merge: bool = True) -> Path:
    ensure_smart_home_dir(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_dict()
    if merge and path.is_file():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
            payload["hosts"] = merge_hosts(prior.get("hosts") or [], result.hosts)
            # Keep latest services/ports/hints from this scan
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_discovery(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def format_discovery_summary(result: DiscoveryResult) -> str:
    lines = [
        f"Scan at {result.scanned_at}",
        f"Subnet: {result.subnet or '(unknown)'}",
        f"Methods: {', '.join(result.methods) or 'none'}",
        f"Hosts: {len(result.hosts)}  |  Services: {len(result.services)}  |  Hints: {len(result.hints)}",
        "",
    ]
    if result.hosts:
        lines.append("Hosts:")
        for h in result.hosts[:40]:
            name = f" ({h.hostname})" if h.hostname else ""
            mac = f" [{h.mac}]" if h.mac else ""
            lines.append(f"  {h.ip}{name}{mac}")
        if len(result.hosts) > 40:
            lines.append(f"  ... and {len(result.hosts) - 40} more")
        lines.append("")
    if result.services:
        lines.append("mDNS services:")
        for s in result.services[:30]:
            lines.append(f"  {s.service_type}: {s.name} @ {s.host}:{s.port}")
        lines.append("")
    if result.hints:
        lines.append("Hints:")
        for hint in result.hints:
            lines.append(f"  [{hint.category}] {hint.message}")
        lines.append("")
    if result.errors:
        lines.append("Notes:")
        for err in result.errors:
            lines.append(f"  - {err}")
    return "\n".join(lines).rstrip()
