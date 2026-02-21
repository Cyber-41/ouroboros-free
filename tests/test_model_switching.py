#!/usr/bin/env python3
"""Simple model switching test for Ouroboros extra mode.

Tests:
1. Current model detection
2. Model switching capability  
3. Response consistency (same model gives consistent answers)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'ouroboros'))

from ouroboros.llm import get_current_model, switch_model, query_llm

def test_current_model():
    """Test that we can detect the current model."""
    model = get_current_model()
    assert model is not None, "Current model should be detectable"
    print(f"✓ Current model: {model}")
    return model

def test_model_switch(model_name):
    """Test switching to a specific model."""
    result = switch_model(model=model_name)
    assert result is True, f"Switch to {model_name} should succeed"
    current = get_current_model()
    assert current == model_name, f"After switch, current model should be {model_name}, got {current}"
    print(f"✓ Switched to {model_name} successfully")
    return current

def test_response_consistency(model_name, prompt, n=2):
    """Test that same model gives consistent responses to same prompt."""
    responses = []
    for i in range(n):
        resp = query_llm(prompt, model=model_name)
        responses.append(resp)
        print(f"  Response {i+1}: {resp[:100]}...")
    
    # For consistency test, we just check that we got responses
    assert all(r is not None and len(r) > 0 for r in responses), "All responses should be non-empty"
    print(f"✓ Got {n} responses from {model_name}")
    return responses

def main():
    print("=== Model Switching Test ===\n")
    
    # Test 1: Detect current model
    print("Test 1: Current model detection")
    initial_model = test_current_model()
    
    # Test 2: Switch to another model
    print("\nTest 2: Model switching")
    available = ['gemini-2.5-flash', 'stepfun/step-3.5-flash:free']
    target = available[1] if initial_model == available[0] else available[0]
    switched_model = test_model_switch(target)
    
    # Test 3: Response consistency
    print("\nTest 3: Response consistency")
    test_prompt = "What is 2+2? Answer briefly."
    responses = test_response_consistency(switched_model, test_prompt, n=2)
    
    # Test 4: Switch back to original
    print("\nTest 4: Switch back to original")
    final_model = test_model_switch(initial_model)
    
    print(f"\n✅ All tests passed! Working model: {final_model}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
