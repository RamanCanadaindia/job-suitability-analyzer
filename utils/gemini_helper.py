import os
import json
import urllib.request
import urllib.error
import time

class GeminiError(Exception):
    pass

def query_gemini(prompt, response_json=False):
    """
    Queries Gemini using standard REST API calls to avoid gRPC hanging bugs and library conflicts.
    Handles rate-limits (429) automatically via backoff retries.
    Raises GeminiError on persistent failures to allow the UI to diagnose issues.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # Prioritize Streamlit Session State (where sidebar user inputs are stored)
    try:
        import streamlit as st
        if "GEMINI_API_KEY" in st.session_state and st.session_state["GEMINI_API_KEY"]:
            api_key = st.session_state["GEMINI_API_KEY"]
    except:
        pass
        
    # Fallback to secrets.toml
    if not api_key:
        try:
            import streamlit as st
            if "GEMINI_API_KEY" in st.secrets:
                api_key = st.secrets["GEMINI_API_KEY"]
        except:
            pass
            
    if not api_key:
        raise GeminiError("Gemini API key not configured in environment, session state, or secrets.toml.")
        
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.5-flash",
    ]
    last_error = None
    all_errors = []
    
    for model_name in models_to_try:
        print(f"[DEBUG] query_gemini: model_name={model_name}, api_key_len={len(api_key)}, api_key_start={api_key[:10]}..., api_key_end=...{api_key[-5:]}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        }
        
        if response_json:
            payload["generationConfig"] = {
                "responseMimeType": "application/json"
            }
            
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=45) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
                raise GeminiError("Received empty response from Gemini model.")
            except urllib.error.HTTPError as he:
                if he.code == 503 and attempt < 2:
                    time.sleep(3.0 * (attempt + 1))
                    continue
                    
                if he.code == 429:
                    retry_seconds = 35.0
                    try:
                        err_body = he.read().decode("utf-8", errors="ignore")
                        err_json = json.loads(err_body)
                        details = err_json.get("error", {}).get("details", [])
                        for detail in details:
                            if "retryDelay" in detail:
                                delay_str = detail.get("retryDelay", "35s")
                                retry_seconds = float(delay_str.replace("s", ""))
                                break
                    except Exception as parse_err:
                        pass
                    
                    sleep_duration = retry_seconds + 2.0
                    time.sleep(sleep_duration)
                    
                    try:
                        req_retry = urllib.request.Request(
                            url,
                            data=req_data,
                            headers={"Content-Type": "application/json"},
                            method="POST"
                        )
                        with urllib.request.urlopen(req_retry, timeout=45) as response:
                            res_data = json.loads(response.read().decode("utf-8"))
                            candidates = res_data.get("candidates", [])
                            if candidates:
                                content = candidates[0].get("content", {})
                                parts = content.get("parts", [])
                                if parts:
                                    return parts[0].get("text", "").strip()
                    except urllib.error.HTTPError as he_retry:
                        if he_retry.code == 503 and attempt < 2:
                            time.sleep(3.0 * (attempt + 1))
                            continue
                        raise GeminiError(f"Gemini API rate limit (429) persisted after retry. Details: {he_retry.reason}")
                    except Exception as retry_err:
                        raise GeminiError(f"Gemini API rate limit retry failed: {retry_err}")
                    
                    raise GeminiError("Gemini API rate limit (429) encountered. Please wait a minute and try again.")
                elif he.code in (404, 400, 503):
                    err_text = ""
                    try:
                        err_text = he.read().decode("utf-8", errors="ignore")
                    except Exception as pe:
                        err_text = f"failed to read error: {pe}"
                    msg = f"Model {model_name} returned {he.code}: {he.reason} ({err_text})"
                    all_errors.append(msg)
                    last_error = msg
                    break
                elif he.code == 403:
                    raise GeminiError("Gemini API key is invalid or lacks permission for this model (HTTP 403). Check your API Key.")
                else:
                    try:
                        err_body = he.read().decode("utf-8", errors="ignore")
                        err_json = json.loads(err_body)
                        msg = err_json.get("error", {}).get("message", he.reason)
                    except:
                        msg = he.reason
                    raise GeminiError(f"Gemini API HTTP Error {he.code}: {msg}")
            except Exception as e:
                msg = f"Error calling model {model_name}: {e}"
                all_errors.append(msg)
                last_error = msg
                break
            
    if last_error:
        raise GeminiError(f"All Gemini models failed. Details:\n" + "\n\n".join(all_errors))
    raise GeminiError("All Gemini models failed to respond.")
