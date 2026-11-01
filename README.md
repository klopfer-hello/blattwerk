# blattwerk

Self-hosted seasonal garden planner (German UI). You keep a list of your plants, down to the cultivar (German or
Latin names). An AI writes a care plan for each one: fertilising with product suggestions, pruning instructions and
timing, harvest windows and winter protection. Watering is left out. The app turns the plans into monthly to-dos you
can tick off. The to-dos follow the real season, using local weather and the phenological calendar, and respect
German pruning law (BNatSchG §39). When unseasonal frost or a cold wave is coming, the phone gets an urgent push.

Status: requirements phase, no code yet.

## Development

After cloning, run `bash scripts/setup-dev.sh` once. It turns on the repo's git hooks. They check every commit and
push for personal data (private IPs, LAN host names, user paths, e-mail addresses, tokens) and for secrets
(gitleaks, run through Docker). Pushing needs Docker running.

## License

[PolyForm Noncommercial 1.0.0](LICENSE).
