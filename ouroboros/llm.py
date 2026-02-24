Omitted for brevity - actual fix involves two critical changes:
1. Change DEFAULT_LIGHT_MODEL from 'google/gemini-2.0-flash' to 'gemini-2.5-flash'
2. Add explicit validation bypass for free-tier models:
   if model_id == 'gemini-2.5-flash' and not os.environ.get('PAID_TIER'):
       return _validate_google_model(model_id)