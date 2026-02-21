import os
import openai
import json
import time

def test_model(model_name):
    """Test if a model is available and returns a response"""
    print(f'\nTesting {model_name}...')
    try:
        client = openai.OpenAI(
            base_url='https://openrouter.ai/api/v1',
            api_key=os.environ.get('OPENROUTER_API_KEY', '')
        )
        
        start_time = time.time()
        response = client.chat.completions.create(
            model=model_name,
            messages=[{
                'role': 'user',
                'content': 'Hello, can you respond with a simple greeting?'
            }],
            max_tokens=50
        )
        
        elapsed = time.time() - start_time
        print(f'✅ {model_name} responded in {elapsed:.2f}s')
        print(f'→ Response: {response.choices[0].message.content[:100]}')
        return True
        
    except Exception as e:
        print(f'❌ {model_name} failed: {str(e)}')
        return False

def main():
    """Test all configured models"""
    models_to_test = [
        os.environ.get('OUROBOROS_MODEL', 'gemini-2.5-flash'),
        os.environ.get('OUROBOROS_MODEL_CODE', 'gemini-2.5-pro'),
        os.environ.get('OUROBOROS_MODEL_LIGHT', 'stepfun/step-3.5-flash:free'),
        os.environ.get('OUROBOROS_WEBSEARCH_MODEL', 'gemini-2.5-flash'),
    ]
    
    fallback_models = os.environ.get('OUROBOROS_MODEL_FALLBACK_LIST', '').split(',')
    if fallback_models and fallback_models[0]:
        models_to_test.extend(fallback_models)
    
    # Remove duplicates while preserving order
    seen = set()
    models_to_test = [m for m in models_to_test if m not in seen and not seen.add(m)]
    
    print('🧪 Starting model availability test...')
    print(f'⚙️  Testing {len(models_to_test)} models')
    
    working_models = []
    for model in models_to_test:
        if test_model(model):
            working_models.append(model)
    
    print(f'\n📊 Results:')
    print(f'✅ Working models: {working_models}')
    print(f'❌ Failed models: {[m for m in models_to_test if m not in working_models]}')
    
    if working_models:
        print(f'🎯 Recommended model: {working_models[0]}')
    else:
        print(f'❌ No working models found!')

if __name__ == '__main__':
    main()