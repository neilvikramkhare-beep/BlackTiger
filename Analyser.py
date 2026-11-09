#!/usr/bin/env python3
"""
analyzer.py - Network / Phone number / Email (Gmail) analyser

Usage:
  python analyzer.py phone  "+91 98765 43210"
  python analyzer.py email  "john.doe+news@gmail.com"
  python analyzer.py host   example.com            # DNS, IP class, ports, TLS
  python analyzer.py local                         # your own machine / LAN
  Add --json for machine-readable output.

Optional (recommended) installs:
  pip install phonenumbers dnspython

ETHICS: Port scanning is only for hosts you own or have written permission to test.
This tool analyses technical metadata only. It does NOT identify who owns a number
or mailbox, and does not locate people.
"""
import argparse, ipaddress, json, platform, re, socket, ssl, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

try:
    import phonenumbers
    from phonenumbers import carrier, geocoder, timezone, PhoneNumberType
except ImportError:
    phonenumbers = None
try:
    import dns.resolver
except ImportError:
    dns = None

# ------------------------------------------------------------------ PHONE
LINE_TYPES = {}
if phonenumbers:
    LINE_TYPES = {
        PhoneNumberType.FIXED_LINE: "Fixed line", PhoneNumberType.MOBILE: "Mobile",
        PhoneNumberType.FIXED_LINE_OR_MOBILE: "Fixed line or mobile",
        PhoneNumberType.TOLL_FREE: "Toll free", PhoneNumberType.PREMIUM_RATE: "Premium rate",
        PhoneNumberType.SHARED_COST: "Shared cost", PhoneNumberType.VOIP: "VoIP",
        PhoneNumberType.PERSONAL_NUMBER: "Personal number", PhoneNumberType.PAGER: "Pager",
        PhoneNumberType.UAN: "UAN", PhoneNumberType.VOICEMAIL: "Voicemail",
        PhoneNumberType.UNKNOWN: "Unknown",
    }

def analyze_phone(raw, default_region="IN"):
    if not phonenumbers:
        return {"error": "Install the 'phonenumbers' package: pip install phonenumbers"}
    r = {"input": raw}
    try:
        n = phonenumbers.parse(raw, None if raw.strip().startswith("+") else default_region)
    except phonenumbers.NumberParseException as e:
        return {"input": raw, "error": f"Cannot parse: {e}"}
    F = phonenumbers.PhoneNumberFormat
    r["valid"] = phonenumbers.is_valid_number(n)
    r["possible"] = phonenumbers.is_possible_number(n)
    r["possible_reason"] = str(phonenumbers.is_possible_number_with_reason(n))
    r["country_code"] = n.country_code
    r["national_number"] = n.national_number
    r["formats"] = {
        "E164": phonenumbers.format_number(n, F.E164),
        "international": phonenumbers.format_number(n, F.INTERNATIONAL),
        "national": phonenumbers.format_number(n, F.NATIONAL),
        "RFC3966": phonenumbers.format_number(n, F.RFC3966),
    }
    r["region_code"] = phonenumbers.region_code_for_number(n)
    r["line_type"] = LINE_TYPES.get(phonenumbers.number_type(n), "Unknown")
    r["location_hint"] = geocoder.description_for_number(n, "en") or "n/a (country-level only)"
    r["carrier_original"] = carrier.name_for_number(n, "en") or "unknown"
    r["timezones"] = list(timezone.time_zones_for_number(n))
    r["notes"] = [
        "Carrier is the ORIGINAL allocation; ported numbers may now belong to another carrier.",
        "Location is the number's registration area, not where the phone currently is.",
    ]
    return r

# ------------------------------------------------------------------ EMAIL
DISPOSABLE = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "temp-mail.org",
    "yopmail.com", "trashmail.com", "throwawaymail.com", "sharklasers.com", "getnada.com",
    "maildrop.cc", "dispostable.com", "fakeinbox.com", "mailnesia.com",
}
FREE_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "proton.me", "protonmail.com", "aol.com", "zoho.com", "rediffmail.com",
}
ROLE_ACCOUNTS = {"admin", "info", "support", "sales", "contact", "noreply", "no-reply",
                 "postmaster", "webmaster", "abuse", "billing", "help", "hr", "office"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")

def dns_query(name, rtype):
    if dns:
        try:
            return [a.to_text() for a in dns.resolver.resolve(name, rtype, lifetime=5)]
        except Exception:
            return []
    if rtype in ("A", "AAAA"):
        try:
            fam = socket.AF_INET if rtype == "A" else socket.AF_INET6
            return sorted({i[4][0] for i in socket.getaddrinfo(name, None, fam)})
        except socket.gaierror:
            return []
    return None  # needs dnspython

def analyze_email(raw):
    e = raw.strip()
    r = {"input": raw, "syntax_valid": bool(EMAIL_RE.match(e)) and len(e) <= 254}
    if not r["syntax_valid"]:
        return r
    local, domain = e.rsplit("@", 1)
    domain = domain.lower()
    r.update(local_part=local, domain=domain, local_length=len(local))
    r["provider_type"] = ("disposable" if domain in DISPOSABLE
                          else "free webmail" if domain in FREE_PROVIDERS else "custom/corporate domain")
    r["role_account"] = local.lower().split("+")[0] in ROLE_ACCOUNTS
    r["local_has_plus_tag"] = "+" in local
    if domain in ("gmail.com", "googlemail.com"):
        base = local.split("+")[0].replace(".", "").lower()
        r["gmail"] = {
            "canonical_address": f"{base}@gmail.com",
            "plus_tag": local.split("+", 1)[1] if "+" in local else None,
            "dots_ignored": True,
            "valid_gmail_username_rules": bool(re.fullmatch(r"[a-z0-9]{6,30}", base)),
            "note": "Gmail ignores dots and anything after '+', so all variants deliver to one inbox.",
        }
    mx = dns_query(domain, "MX")
    if mx is None:
        r["dns"] = {"error": "Install dnspython for MX/SPF/DMARC: pip install dnspython"}
        r["dns"]["A"] = dns_query(domain, "A")
    else:
        txt = dns_query(domain, "TXT") or []
        dmarc = dns_query("_dmarc." + domain, "TXT") or []
        r["dns"] = {
            "MX": sorted(mx), "A": dns_query(domain, "A"), "AAAA": dns_query(domain, "AAAA"),
            "SPF": [t for t in txt if "v=spf1" in t], "DMARC": dmarc,
            "NS": dns_query(domain, "NS"),
        }
        r["can_receive_mail"] = bool(mx)
    r["notes"] = ["Cannot confirm the mailbox exists or who owns it without sending mail / the owner's consent."]
    return r

# ------------------------------------------------------------------ HOST / NETWORK
COMMON_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP", 110: "POP3",
    143: "IMAP", 443: "HTTPS", 445: "SMB", 465: "SMTPS", 587: "SMTP-sub", 993: "IMAPS",
    995: "POP3S", 1433: "MSSQL", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    5900: "VNC", 6379: "Redis", 8080: "HTTP-alt", 8443: "HTTPS-alt", 27017: "MongoDB",
}

def scan_port(ip, port, timeout=1.5):
    t0 = time.time()
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            rtt = round((time.time() - t0) * 1000, 1)
            banner = ""
            try:
                s.settimeout(1)
                if port in (80, 8080):
                    s.sendall(b"HEAD / HTTP/1.0\r\n\r\n")
                banner = s.recv(120).decode(errors="ignore").strip().splitlines()[0] if True else ""
            except Exception:
                pass
            return {"port": port, "service": COMMON_PORTS.get(port, "?"), "rtt_ms": rtt, "banner": banner}
    except Exception:
        return None

def tls_info(host, port=443):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=4) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                c = ss.getpeercert()
                return {
                    "tls_version": ss.version(), "cipher": ss.cipher()[0],
                    "issuer": dict(x[0] for x in c.get("issuer", [])),
                    "subject": dict(x[0] for x in c.get("subject", [])),
                    "valid_from": c.get("notBefore"), "valid_to": c.get("notAfter"),
                    "san": [v for k, v in c.get("subjectAltName", [])][:15],
                }
    except Exception as e:
        return {"error": str(e)}

def analyze_host(target, ports=None):
    r = {"target": target}
    try:
        ip = str(ipaddress.ip_address(target))
    except ValueError:
        try:
            ip = socket.gethostbyname(target)
        except socket.gaierror as e:
            return {"target": target, "error": f"DNS resolution failed: {e}"}
        r["dns"] = {t: dns_query(target, t) for t in ("A", "AAAA", "MX", "NS", "TXT")}
    a = ipaddress.ip_address(ip)
    r["ip"] = ip
    r["ip_version"] = a.version
    r["classification"] = {
        "private": a.is_private, "global": a.is_global, "loopback": a.is_loopback,
        "multicast": a.is_multicast, "link_local": a.is_link_local, "reserved": a.is_reserved,
    }
    try:
        r["reverse_dns"] = socket.gethostbyaddr(ip)[0]
    except Exception:
        r["reverse_dns"] = None
    plist = ports or list(COMMON_PORTS)
    with ThreadPoolExecutor(max_workers=50) as ex:
        res = [x for x in ex.map(lambda p: scan_port(ip, p), plist) if x]
    r["open_ports"] = sorted(res, key=lambda x: x["port"])
    risky = {23: "Telnet is unencrypted", 21: "FTP is unencrypted", 445: "SMB exposed",
             3389: "RDP exposed", 5900: "VNC exposed", 6379: "Redis exposed",
             27017: "MongoDB exposed", 3306: "MySQL exposed", 1433: "MSSQL exposed", 5432: "PostgreSQL exposed"}
    r["warnings"] = [f"Port {p['port']}: {risky[p['port']]}" for p in r["open_ports"] if p["port"] in risky]
    if any(p["port"] == 443 for p in r["open_ports"]):
        r["tls"] = tls_info(target)
    return r

def analyze_local():
    r = {"hostname": socket.gethostname(), "os": platform.platform(), "python": platform.python_version()}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        r["primary_local_ip"] = s.getsockname()[0]
        s.close()
    except Exception:
        r["primary_local_ip"] = None
    r["all_ips"] = sorted({i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)})
    cmds = {"Windows": ["arp", "-a"], "Linux": ["ip", "neigh"], "Darwin": ["arp", "-a"]}
    try:
        out = subprocess.run(cmds.get(platform.system(), ["arp", "-a"]),
                             capture_output=True, text=True, timeout=10).stdout
        r["lan_neighbours"] = [l.strip() for l in out.splitlines() if l.strip()][:60]
    except Exception as e:
        r["lan_neighbours"] = f"unavailable: {e}"
    return r

# ------------------------------------------------------------------ OUTPUT
def show(d, indent=0):
    pad = "  " * indent
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (dict, list)) and v:
                print(f"{pad}{k}:"); show(v, indent + 1)
            else:
                print(f"{pad}{k}: {v}")
    elif isinstance(d, list):
        for v in d:
            if isinstance(v, (dict, list)):
                show(v, indent); print()
            else:
                print(f"{pad}- {v}")

def main():
    ap = argparse.ArgumentParser(description="Network / phone / email analyser")
    ap.add_argument("mode", choices=["phone", "email", "host", "local"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--region", default="IN", help="default region for numbers without +code")
    ap.add_argument("--ports", help="comma-separated ports for host mode")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.mode != "local" and not a.target:
        ap.error("target required")
    if a.mode == "phone": out = analyze_phone(a.target, a.region)
    elif a.mode == "email": out = analyze_email(a.target)
    elif a.mode == "host":
        out = analyze_host(a.target, [int(p) for p in a.ports.split(",")] if a.ports else None)
    else: out = analyze_local()
    print(json.dumps(out, indent=2, default=str)) if a.json else show(out)

if __name__ == "__main__":
    main()