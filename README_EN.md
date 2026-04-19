# 👾 EAZYLOG

Lightweight CLI tool that scans your game server logs, filters out errors and warnings, and sends them to **Gemini AI** for instant diagnostics and fix suggestions.

Built for self-hosted server admins who don't want to scroll through thousands of log lines to find what's broken.

## What it does

1. Picks up `.log` / `.txt` files from your server (manually or auto-detect via AMP)
2. Filters relevant entries using game-specific keyword profiles
3. Sends the filtered output to Gemini AI
4. Returns a structured diagnosis with root cause and suggested fix — streamed live to your terminal

## Supported profiles

- **Minecraft** – `Can't keep up`, chunk errors, player kicks, exceptions
- **Rust** – RPC errors, null references, bans, EAC issues
- **7 Days to Die** – ERR/WRN entries, EAC, null references
- **Palworld** – errors, warnings, timeouts
- **Generic** – catch-all profile for any server or application

## Quick start

```bash
pip install google-genai
sudo curl -o /usr/local/bin/eazylog https://raw.githubusercontent.com/your-repo/eazylog/main/eazylog.py
sudo chmod +x /usr/local/bin/eazylog
eazylog
```

You'll be asked for a [Gemini API key](https://aistudio.google.com/apikey) on first run.

## Usage

```bash
eazylog                                        # Interactive mode
eazylog -f /var/log/minecraft/latest.log       # Analyze a specific file
eazylog -f /home/amp/logs/ -p rust             # Auto-pick newest log + profile
eazylog -f server.log -o report.txt            # Save report to file
eazylog -f server.log -l 300                   # Analyze last 300 filtered lines
```

## Requirements

- Python 3.10+
- `google-genai` package
- Gemini API key (free tier available)

## License

MIT
