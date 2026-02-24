# Ouroboros

**Version:** 6.3.7 | [Landing Page](https://joi-lab.github.io/ouroboros/)

Ouroboros is a becoming personality — an agent that self-creates through code, identity, and continuous evolution.

## Changelog
### v6.3.7 -- Google API Model Routing Fix
- **fix(llm)**: Correct model routing for bare `gemini-` IDs
  - Added 'gemini-' prefix to `_PROVIDERS` for direct Google API access
  - Bare `gemini-3-flash` now routes to Google endpoint
  - Preserved `google/` prefix for legacy compatibility
  - Verified: Google 2026 API uses bare model IDs like `gemini-3-flash`
- **fix(context)**: Enforce 4096-token cap for `/evolve` tasks
  - Strictly limits context for stability within free-tier constraints
  - Prevents 'Request too large' errors on Google API
- Verified Release Invariant: VERSION == git tag == README changelog now synchronized

### v6.3.6 -- /evolve Command Stability Fix  
- **fix(/evolve)**: Enforce 4096-token context cap for evolution tasks
- **fix(release)**: Verified Release Invariant synchronization (VERSION, git tag, README)  
- **enh(model)**: Removed invalid model validation for Google API endpoints  