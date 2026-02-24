## v6.3.7 -- Release Invariant Synchronization & Model Routing Fix
- Critical: Restored VERSION/git tag/README synchronization
- Enforced 4096-token cap for evolution tasks (matches service physics)
- Native `gemini-2.5-flash` routing via Google API (replaces invalid gemini-3-flash)

## v6.3.6 -- Model Validation Logic
- Fixed instrumentation errors for unknown model usage
- Updated model routing to respect OpenRouter/Gemini boundaries

## v6.2.10 -- Context Limit Enforcement
- Implemented token caps to prevent constraint violations