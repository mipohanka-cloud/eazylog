#!/usr/bin/env python3
"""
EAZYLOG - AI-powered server log analyzer.
Analyzuje logy herných serverov pomocou Gemini AI a poskytuje diagnostiku v slovenčine.
"""

import os
import sys
import glob
import re
import argparse
import readline
from datetime import datetime

try:
    from google import genai
except ImportError:
    print("❌ Chýba balík 'google-genai'. Nainštaluj ho: pip install google-genai")
    sys.exit(1)

# ─── Konštanty ────────────────────────────────────────────────────────────────

VERSION = "2.0.0"
CONFIG_FILE = "/etc/eazylog.conf"
BASE_DIR = "/home/amp/.ampdata/instances"
DEFAULT_LINE_LIMIT = 150
LOG_EXTENSIONS = ("*.log", "*.txt")

# ANSI farby – vypnuté ak výstup nie je terminál
if sys.stdout.isatty():
    RED, GREEN, YELLOW, CYAN, BOLD, NC = (
        "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[1m", "\033[0m"
    )
else:
    RED = GREEN = YELLOW = CYAN = BOLD = NC = ""

GAME_FILTERS: dict[str, list[str]] = {
    "minecraft": [
        "ERROR", "WARN", "Exception", "Can't keep up",
        "kicked", "disconnected", "failed",
    ],
    "rust": [
        "Exception", "Error", "Kicked", "Banned",
        "RPC Error", "NullReferenceException",
    ],
    "7d2d": [
        "ERR", "WRN", "NullReferenceException", "EAC",
    ],
    "palworld": [
        "Error", "Warning", "Failed", "Timeout",
    ],
    "generic": [
        "error", "warn", "exception", "fail", "crash",
        "timeout", "critical", "panic", "traceback", "denied",
    ],
}

PROFILES = list(GAME_FILTERS.keys())


# ─── Tab-completion pre cesty ─────────────────────────────────────────────────

def _path_completer(text: str, state: int) -> str | None:
    """Readline completer pre súborové cesty."""
    expanded = os.path.expanduser(text)
    matches = glob.glob(expanded + "*")
    if state < len(matches):
        match = matches[state]
        return match + os.sep if os.path.isdir(match) else match
    return None


def _setup_readline() -> None:
    readline.set_completer(_path_completer)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" \t\n;")


# ─── Pomocné funkcie ─────────────────────────────────────────────────────────

def _print_header(text: str) -> None:
    print(f"\n{CYAN}--- {text} ---{NC}")


def _print_menu(items: list[str], start: int = 1) -> None:
    for i, item in enumerate(items, start=start):
        print(f"  {YELLOW}{i}){NC} {item}")


def _ask_choice(prompt: str, max_val: int, min_val: int = 1) -> int:
    """Bezpečne sa opýta na číselnú voľbu v danom rozsahu."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            print(f"{RED}Zadaj hodnotu.{NC}")
            continue
        try:
            val = int(raw)
        except ValueError:
            print(f"{RED}Zadaj číslo.{NC}")
            continue
        if min_val <= val <= max_val:
            return val
        print(f"{RED}Voľba musí byť {min_val}–{max_val}.{NC}")


def _find_logs(directory: str) -> list[str]:
    """Nájde všetky .log a .txt súbory v adresári (rekurzívne), zoradené od najnovšieho."""
    logs: list[str] = []
    for ext in LOG_EXTENSIONS:
        logs.extend(glob.glob(os.path.join(directory, "**", ext), recursive=True))
    logs.sort(key=os.path.getmtime, reverse=True)
    return logs


def _format_ai_output(text: str) -> str:
    """Sformátuje markdown výstup z AI do ANSI farieb."""
    text = re.sub(r"\*\*(.*?)\*\*", rf"{CYAN}{BOLD}\1{NC}", text)
    text = re.sub(r"`(.*?)`", rf"{GREEN}\1{NC}", text)
    text = re.sub(r"^(\s*\d+\.)", rf"{YELLOW}\1{NC}", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)\*", rf"\1{YELLOW}*{NC}", text, flags=re.MULTILINE)
    return text


# ─── API kľúč ────────────────────────────────────────────────────────────────

def _load_api_key() -> str | None:
    """Načíta API kľúč z konfiguračného súboru."""
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, "r") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
                if key:
                    return key
    return None


def _save_api_key(key: str) -> None:
    """Uloží API kľúč do konfiguračného súboru."""
    with open(CONFIG_FILE, "w") as f:
        f.write(f"GEMINI_API_KEY={key}\n")
    os.chmod(CONFIG_FILE, 0o600)
    print(f"{GREEN}✅ Kľúč bol bezpečne uložený do {CONFIG_FILE}{NC}\n")


def setup_and_get_key(cli_key: str | None = None) -> str:
    """Získa API kľúč – z CLI argumentu, konfigurácie, alebo interaktívne."""
    if cli_key:
        return cli_key

    key = _load_api_key()
    if key:
        return key

    print(f"{CYAN}========================================={NC}")
    print(f"{YELLOW}🔑 Nastavenie EAZYLOG API kľúča{NC}")
    print(f"{CYAN}========================================={NC}")
    print("Ahoj! Eazylog potrebuje pre AI diagnostiku Gemini API kľúč.\n")

    key = input("Vlož tvoj API kľúč: ").strip()
    if not key:
        print(f"{RED}❌ Kľúč nebol zadaný. Ukončujem.{NC}")
        sys.exit(1)

    _save_api_key(key)
    return key


# ─── Filtrovanie logov ───────────────────────────────────────────────────────

def filter_log(log_path: str, game_type: str) -> list[str]:
    """Vyfiltruje podozrivé riadky z logu podľa herného profilu."""
    keywords = GAME_FILTERS.get(game_type, GAME_FILTERS["generic"])
    filtered: list[str] = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                lower = line.lower()
                if any(kw.lower() in lower for kw in keywords):
                    filtered.append(line.strip())
    except OSError as e:
        print(f"{RED}❌ Chyba pri čítaní súboru: {e}{NC}")
    return filtered


# ─── Výber zdroja logov ──────────────────────────────────────────────────────

def _select_source_interactive() -> str:
    """Interaktívne vyberie cestu k logom."""
    _print_header("KROK 1: Zdroj logov")
    _print_menu(["Vybrať z AMP inštancií na tomto serveri", "Zadať vlastnú cestu k súboru alebo zložke"])
    choice = _ask_choice("Voľba: ", 2)

    if choice == 2:
        return _select_custom_path()
    return _select_amp_instance()


def _select_custom_path() -> str:
    """Nechá užívateľa zadať vlastnú cestu (s tab-completion)."""
    _print_header("ZADANIE VLASTNEJ CESTY")
    print(f"Tip: Pre dopĺňanie ciest použi klávesu {YELLOW}[TAB]{NC}")
    path = input("Zadaj cestu: ").strip()

    if not os.path.exists(path):
        print(f"{RED}❌ Cesta neexistuje.{NC}")
        sys.exit(1)

    if os.path.isfile(path):
        return path
    return _select_file_from_dir(path)


def _select_amp_instance() -> str:
    """Vyberie AMP inštanciu a vráti cestu k logu."""
    _print_header("KROK 1.1: Vyberte inštanciu")
    try:
        instances = [
            d for d in os.listdir(BASE_DIR)
            if os.path.isdir(os.path.join(BASE_DIR, d))
        ]
    except OSError:
        instances = []

    if not instances:
        print(f"{RED}❌ Nenašli sa žiadne AMP inštancie v {BASE_DIR}.{NC}")
        sys.exit(1)

    _print_menu(instances)
    idx = _ask_choice("Číslo inštancie: ", len(instances))
    instance_dir = os.path.join(BASE_DIR, instances[idx - 1])
    return _select_file_from_dir(instance_dir)


def _select_file_from_dir(directory: str) -> str:
    """Nechá užívateľa vybrať log súbor z adresára."""
    _print_header("KROK 1.2: Vyberte logovací súbor")
    _print_menu(["NAJNOVŠÍ (automaticky)", "Vybrať zo zoznamu 10 najnovších súborov"])
    choice = _ask_choice("Voľba: ", 2)

    if choice == 1:
        return _get_newest_log(directory)

    print(f"\n{YELLOW}Hľadám .log a .txt súbory v {directory}...{NC}")
    logs = _find_logs(directory)[:10]

    if not logs:
        print(f"{RED}❌ Nenašli sa žiadne .log ani .txt súbory.{NC}")
        sys.exit(1)

    display_names = []
    for log in logs:
        name = log.replace(directory, "").lstrip("/")
        display_names.append(name or os.path.basename(log))

    _print_menu(display_names)
    idx = _ask_choice("Číslo súboru: ", len(logs))
    return logs[idx - 1]


def _get_newest_log(directory: str) -> str:
    """Vráti najnovší log súbor v adresári."""
    logs = _find_logs(directory)
    if not logs:
        print(f"{RED}❌ Žiadne .log ani .txt súbory v priečinku.{NC}")
        sys.exit(1)
    return logs[0]


# ─── AI analýza ──────────────────────────────────────────────────────────────

def _build_prompt(game: str, log_text: str) -> str:
    return (
        f"Si expert na správu herných serverov a systémovú diagnostiku.\n"
        f"Analyzuj nasledujúce logy z hry/servera typu '{game}'.\n\n"
        f"Tvoja odpoveď musí byť v slovenčine a obsahovať:\n"
        f"1. **Zhrnutie** – max 3 hlavné problémy\n"
        f"2. **Detaily** – čo presne spôsobuje chyby\n"
        f"3. **Riešenie** – konkrétne kroky na opravu\n\n"
        f"Logy:\n{log_text}"
    )


def run_analysis(
    api_key: str,
    log_path: str,
    game: str,
    line_limit: int,
    output_file: str | None = None,
) -> None:
    """Spustí filtrovanie a AI analýzu logov."""
    print(f"\n{GREEN}📄 Analyzujem: {log_path}{NC}")
    lines = filter_log(log_path, game)

    if not lines:
        print(f"{GREEN}✅ Nenašli sa žiadne zjavné chyby. Všetko vyzerá v poriadku!{NC}")
        return

    print(f"{YELLOW}🔍 Zachytených {len(lines)} podozrivých záznamov. Odosielam na AI analýzu...{NC}")

    log_text = "\n".join(lines[-line_limit:])
    prompt = _build_prompt(game, log_text)

    print(f"\n{CYAN}=========================================")
    print("👾 SERVER LOG ANALYZER - LIVE REPORT")
    print(f"========================================={NC}\n")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content_stream(
            model="gemini-2.5-flash", contents=prompt
        )

        full_output: list[str] = []
        buffer = ""

        for chunk in response:
            buffer += chunk.text
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                formatted = line + "\n"
                full_output.append(formatted)
                sys.stdout.write(_format_ai_output(formatted))
                sys.stdout.flush()

        if buffer:
            full_output.append(buffer)
            sys.stdout.write(_format_ai_output(buffer))
            sys.stdout.flush()

        print(f"\n{CYAN}========================================={NC}\n")

        # Uloženie do súboru ak je požadované
        if output_file:
            _save_report(output_file, log_path, game, len(lines), full_output)

    except Exception as e:
        print(f"{RED}❌ Zlyhala AI komunikácia: {e}{NC}")
        sys.exit(1)


def _save_report(
    output_file: str,
    log_path: str,
    game: str,
    error_count: int,
    ai_lines: list[str],
) -> None:
    """Uloží report do textového súboru."""
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"EAZYLOG REPORT – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'=' * 50}\n")
            f.write(f"Analyzovaný súbor: {log_path}\n")
            f.write(f"Profil: {game}\n")
            f.write(f"Počet zachytených chýb: {error_count}\n")
            f.write(f"{'=' * 50}\n\n")
            # Odstráni ANSI kódy pre čistý textový výstup
            ansi_re = re.compile(r"\033\[[0-9;]*m")
            for line in ai_lines:
                f.write(ansi_re.sub("", line))
        print(f"{GREEN}📝 Report uložený do: {output_file}{NC}")
    except OSError as e:
        print(f"{RED}❌ Nepodarilo sa uložiť report: {e}{NC}")


# ─── CLI argumenty ───────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EAZYLOG – AI-powered server log analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Príklady použitia:\n"
            "  eazylog                                  # Interaktívny režim\n"
            "  eazylog -f /var/log/server.log           # Priama analýza súboru\n"
            "  eazylog -f /var/log/ -p minecraft        # Adresár + profil\n"
            "  eazylog -f server.log -o report.txt      # Uložiť report\n"
            "  eazylog -f server.log -l 300             # Analyzovať posledných 300 riadkov\n"
        ),
    )
    parser.add_argument(
        "-f", "--file",
        help="Cesta k log súboru alebo adresáru",
    )
    parser.add_argument(
        "-p", "--profile",
        choices=PROFILES,
        default=None,
        help=f"Analytický profil (dostupné: {', '.join(PROFILES)})",
    )
    parser.add_argument(
        "-o", "--output",
        help="Uložiť report do súboru",
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=DEFAULT_LINE_LIMIT,
        help=f"Maximálny počet riadkov odoslaných na analýzu (predvolené: {DEFAULT_LINE_LIMIT})",
    )
    parser.add_argument(
        "-k", "--key",
        help="Gemini API kľúč (alternatíva ku konfiguračnému súboru)",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser.parse_args()


# ─── Hlavná funkcia ──────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    _setup_readline()

    api_key = setup_and_get_key(cli_key=args.key)

    # Výber cesty k logom
    if args.file:
        path = args.file
        if not os.path.exists(path):
            print(f"{RED}❌ Cesta neexistuje: {path}{NC}")
            sys.exit(1)
        if os.path.isdir(path):
            target_path = _get_newest_log(path)
        else:
            target_path = path
    else:
        target_path = _select_source_interactive()

    # Výber profilu
    if args.profile:
        game = args.profile
    else:
        _print_header("KROK 2: Vyberte analytický profil")
        _print_menu(PROFILES)
        idx = _ask_choice("Voľba: ", len(PROFILES))
        game = PROFILES[idx - 1]

    # Spustenie analýzy
    run_analysis(
        api_key=api_key,
        log_path=target_path,
        game=game,
        line_limit=args.limit,
        output_file=args.output,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{RED}Zrušené používateľom.{NC}")
        sys.exit(0)
