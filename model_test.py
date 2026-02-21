#!/usr/bin/env python3
"""
Standalone model testing script for Ouroboros.
Tests model availability and response quality.
"""

import os
import sys
import time
import json
from typing import Dict, List, Any, Optional

def load_env() -> Dict[str, str]:
    """Load environment variables for testing."""
    env = {}
    env_vars = [
        "OUROBOROS_MODEL",
        "OUROBOROS_MODEL_CODE", 
        "OUROBOROS_MODEL_LIGHT",
        "OUROBOROS_MODEL_FALLBACK_LIST"
    ]
    for var in env_vars:
        env[var] = os.environ.get(var, "")
    return env

def get_available_models() -> List[str]:
    """Get list of available models from env."""
    models = []
    
    # Main model
    main = os.environ.get("OUROBOROS_MODEL", "anthropic/claude-sonnet-4.6")
    if main:
        models.append(main)
    
    # Code model
    code = os.environ.get("OUROBOROS_MODEL_CODE", "")
    if code and code != main:
        models.append(code)
    
    # Light model
    light = os.environ.get("OUROBOROS_MODEL_LIGHT", "")
    if light and light != main and light != code:
        models.append(light)
    
    # Fallback list
    fallback_list = os.environ.get("OUROBOROS_MODEL_FALLBACK_LIST", "")
    if fallback_list:
        fallbacks = [f.strip() for f in fallback_list.split(',') if f.strip()]
        for model in fallbacks:
            if model and model not in models:
                models.append(model)
    
    return models

def test_model_response(model: str, prompt: str = "Test response") -> Dict[str, Any]:
    """Test a single model with a prompt."""
    result = {
        "model": model,
        "success": False,
        "error": None,
        "response": None,
        "response_length": 0,
        "response_time_sec": 0.0,
        "model_configured": True
    }
    
    # Check if model is configured in environment
    configured_models = get_available_models()
    if model not in configured_models:
        result["model_configured"] = False
        result["error"] = f"Model not configured in environment"
        return result
    
    try:
        import openai
        
        client = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY", "")
        )
        
        start_time = time.time()
        
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.1,
            timeout=10  # 10 second timeout
        )
        
        result["response_time_sec"] = time.time() - start_time
        
        if response.choices and response.choices[0].message:
            result["response"] = response.choices[0].message.content
            result["response_length"] = len(result["response"])
            result["success"] = True
        else:
            result["error"] = "Empty response from model"
            
    except Exception as e:
        result["error"] = str(e)
    
    return result

def test_all_models() -> List[Dict[str, Any]]:
    """Test all available models and return results."""
    models = get_available_models()
    if not models:
        return [{"error": "No models configured in environment"}]
    
    print(f"Testing {len(models)} models...")
    print("=" * 50)
    
    results = []
    
    for i, model in enumerate(models, 1):
        print(f"\n[{i}/{len(models)}] Testing {model}...")
        result = test_model_response(model)
        results.append(result)
        
        if result["success"]:
            print(f"✅ SUCCESS: {result['response_length']} chars in {result['response_time_sec']:.2f}s")
        elif not result["model_configured"]:
            print(f"⚠️  NOT CONFIGURED: {result['error']}")
        else:
            print(f"❌ FAILED: {result['error']}")
    
    return results

def analyze_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze test results and provide insights."""
    analysis = {
        "total_models": len(results),
        "configured_models": 0,
        "successful_models": 0,
        "failed_models": 0,
        "working_models": [],
        "failed_models": [],
        "empty_responses": 0,
        "errors": {},
        "not_configured": 0
    }
    
    for result in results:
        if not result["model_configured"]:
            analysis["not_configured"] += 1
        elif result.get("success"):
            analysis["successful_models"] += 1
            analysis["working_models"].append(result["model"])
        else:
            analysis["failed_models"] += 1
            analysis["failed_models"].append(result["model"])
            
            error = result.get("error", "Unknown error")
            if error not in analysis["errors"]:
                analysis["errors"][error] = []
            analysis["errors"][error].append(result["model"])
    
    analysis["configured_models"] = analysis["total_models"] - analysis["not_configured"]
    
    return analysis

def main():
    """Main test execution."""
    print("Ouroboros Model Availability Test")
    print("=" * 50)
    
    # Load environment
    env = load_env()
    print("Environment:")
    for key, value in env.items():
        print(f"  {key} = {value}")
    
    print(f"\nAvailable models: {get_available_models()}")
    
    # Run tests
    print("\nRunning model tests...")
    results = test_all_models()
    
    # Analyze
    analysis = analyze_results(results)
    
    print(f"\nAnalysis Results:")
    print(f"Total models: {analysis['total_models']}")
    print(f"Configured models: {analysis['configured_models']}")
    print(f"Working models: {analysis['successful_models']}")
    print(f"Failed models: {analysis['failed_models']}")
    print(f"Not configured: {analysis['not_configured']}")
    
    if analysis['successful_models'] > 0:
        print(f"\nWorking models:")
        for model in analysis['working_models']:
            print(f"  - {model}")
    
    if analysis['failed_models'] > 0:
        print(f"\nFailed models:")
        for model in analysis['failed_models']:
            print(f"  - {model}")
    
        if analysis['errors']:
            print(f"\nError breakdown:")
            for error, models in analysis['errors'].items():
                print(f"  {error}: {len(models)} models")
                for model in models:
                    print(f"    - {model}")
    
    if analysis['not_configured'] > 0:
        print(f"\nNot configured models:")
        for model in get_available_models():
            if not any(r.get("model") == model and r.get("model_configured") for r in results):
                print(f"  - {model}")
    
    # Save results to file
    results_path = "model_test_results.json"
    with open(results_path, 'w') as f:
        json.dump({
            "env": env,
            "results": results,
            "analysis": analysis,
            "timestamp": "{}".format(time.strftime('%Y-%m-%d %H:%M:%S'))
        }, f, indent=2)
    
    print(f"\nResults saved to {results_path}")
    
    # Provide recommendations
    if analysis["successful_models"] == 0:
        print("\n❌ CRITICAL: No working models found!")
        print("Please check:")
        print("1. OPENROUTER_API_KEY is valid")
        print("2. Models are available in OpenRouter")
        print("3. Network connectivity")
    elif analysis["successful_models"] < analysis["configured_models"]:
        print("\n⚠️  Some models are failing. Consider:")
        print("1. Using only working models")
        print("2. Checking model availability in OpenRouter")
        print("3. Reviewing fallback list")
    else:
        print("\n✅ All configured models are working!")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())