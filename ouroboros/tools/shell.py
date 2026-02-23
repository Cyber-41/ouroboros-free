from typing import Dict, Any, Tuple, Optional
import subprocess
import json
import traceback
import logging

logger = logging.getLogger(__name__)

class ShellTool:
    # ... [other methods unchanged] ...

    def _decode_process_output(self, stdout: Optional[bytes], stderr: Optional[bytes]) -> Tuple[str, str]:
        """Decode subprocess outputs with UTF-8 fallback"""
        stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ''
        stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ''
        return stdout_text, stderr_text

    def _classify_process_result(self, exit_code: int, stdout: str, stderr: str, timeout: int) -> Dict[str, Any]:
        """Classify process result by exit code and content"""
        # Success case
        if exit_code == 0 and stdout:
            return self._handle_success_case(stdout, stderr)
        
        # Timeout string detection
        if 'timed out' in stderr.lower():
            return {
                'status': 'timeout',
                'message': f'Process timed out after {timeout}s',
                'stderr': stderr
            }
        
        # User rejection or CLI error
        if exit_code == 1:
            return self._handle_exit_code_1(stderr)
        
        # Unexpected failure
        return {
            'status': 'critical',
            'message': 'Unexpected process failure',
            'exit_code': exit_code,
            'details': stderr or f'Unknown error (exit code {exit_code})'
        }

    def _handle_success_case(self, stdout: str, stderr: str) -> Dict[str, Any]:
        try:
            result = json.loads(stdout)
            if 'diff' in result:
                return {
                    'status': 'success',
                    'diff': result['diff'],
                    'stderr': stderr
                }
            return {
                'status': 'error',
                'message': 'Invalid JSON: missing diff field',
                'stderr': stderr
            }
        except json.JSONDecodeError as e:
            return {
                'status': 'error',
                'message': f'JSON decode error: {str(e)}',
                'stderr': stderr
            }

    def _handle_exit_code_1(self, stderr: str) -> Dict[str, Any]:
        if 'rejected by user' in stderr:
            return {
                'status': 'rejected',
                'message': 'User rejected changes',
                'stderr': stderr
            }
        return {
            'status': 'error',
            'message': 'CLI execution error',
            'details': stderr.strip(),
            'stderr': stderr
        }

    def _handle_timeout_expired(self, process: subprocess.Popen, timeout: int) -> Dict[str, Any]:
        process.kill()
        stdout, stderr = process.communicate()
        stdout_text, stderr_text = self._decode_process_output(stdout, stderr)
        return {
            'status': 'timeout',
            'message': f'Process forcibly terminated after {timeout}s',
            'stdout': stdout_text,
            'stderr': stderr_text
        }

    def _handle_unexpected_exception(self, e: Exception) -> Dict[str, Any]:
        return {
            'status': 'exception',
            'message': f'Unexpected error: {str(e)}',
            'traceback': traceback.format_exc()
        }

    def _process_claude_code_edit_response(self, process: subprocess.Popen, timeout: int = 300) -> Dict[str, Any]:
        """
        Process output from claude-code CLI subprocess.
        Handles success, failure, and timeout scenarios.
        """
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            exit_code = process.returncode
            stdout_text, stderr_text = self._decode_process_output(stdout, stderr)
            return self._classify_process_result(exit_code, stdout_text, stderr_text, timeout)
        
        except subprocess.TimeoutExpired:
            return self._handle_timeout_expired(process, timeout)
        
        except Exception as e:
            return self._handle_unexpected_exception(e)