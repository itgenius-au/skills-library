#!/usr/bin/env python3
"""glm_call.py - stdlib HTTP client for z.ai (GLM) OpenAI-compatible chat completions.

Called by glm-exec.sh; not meant to be invoked by hand (use the wrapper, which resolves
the key and endpoint). Reads config from env, prompt/system from files, prints the
assistant text to stdout, and CLASSIFIES failures so the caller never mistakes a billing
or auth problem for a code finding.

Env (all set by glm-exec.sh):
  ZAI_API_KEY      required - the z.ai key (id.secret string), used as a Bearer token
  GLM_URL          required - full chat/completions URL (coding or general endpoint)
  GLM_MODEL        default glm-5.2
  GLM_MAX_TOKENS   default 2048
  GLM_TEMPERATURE  default 0.3
  GLM_RETRIES      default 1   (transient-only retries)
  GLM_RETRY_SLEEP  default 20  (seconds between transient retries)
  GLM_TIMEOUT      default 600 (per-request seconds; GLM-5.2 reviews can take minutes)

Args:  glm_call.py <prompt_file> [system_file]

Exit codes: 0 = assistant text printed; 1 = surfaced failure (unfunded/auth/transient-exhausted/parse);
            2 = bad args/config. A failure is always SURFACED on stderr - never guessed around.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request


def die(msg, code=2):
    sys.stderr.write(f"glm_call.py: {msg}\n")
    sys.exit(code)


def read_file(path):
    try:
        # Always UTF-8: diffs and docs carry non-ASCII; the platform default encoding
        # (e.g. cp1252) would crash on them.
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        die(f"cannot read {path}: {e}")


def main():
    if not (2 <= len(sys.argv) <= 3):
        die("usage: glm_call.py <prompt_file> [system_file]")

    key = os.environ.get("ZAI_API_KEY", "").strip()
    url = os.environ.get("GLM_URL", "").strip()
    if not key:
        die("ZAI_API_KEY is empty (export your z.ai key before calling glm-exec.sh)", 1)
    if not url:
        die("GLM_URL is empty (glm-exec.sh should set this)")

    model = os.environ.get("GLM_MODEL", "glm-5.2").strip()
    try:
        max_tokens = int(os.environ.get("GLM_MAX_TOKENS", "2048"))
        temperature = float(os.environ.get("GLM_TEMPERATURE", "0.3"))
        retries = int(os.environ.get("GLM_RETRIES", "1"))
        retry_sleep = float(os.environ.get("GLM_RETRY_SLEEP", "20"))
        # GLM-5.2 reasons heavily - a large review can take minutes. 180s was too short
        # (a slow-but-completing call timed out, got mis-classified transient, and retried).
        request_timeout = float(os.environ.get("GLM_TIMEOUT", "600"))
    except ValueError as e:
        die(f"bad numeric env config ({e}) - check GLM_MAX_TOKENS / GLM_TEMPERATURE / "
            f"GLM_RETRIES / GLM_RETRY_SLEEP / GLM_TIMEOUT")

    # Guard against silent no-ops: a negative retry count makes range(retries+1) empty, so the
    # loop never runs and we fall through to a bare `return 1` with nothing surfaced.
    if retries < 0 or max_tokens < 0:
        die("GLM_RETRIES and GLM_MAX_TOKENS must be >= 0")

    prompt = read_file(sys.argv[1])
    if not prompt.strip():
        die("prompt file is empty", 1)

    messages = []
    if len(sys.argv) == 3:
        system = read_file(sys.argv[2])
        if system.strip():
            messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }).encode()

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept-Language": "en-US,en",
    }

    def post():
        """Return (status:int|None, parsed_json|None, raw:str)."""
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=request_timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                try:
                    return r.status, json.loads(raw), raw
                except ValueError:
                    return r.status, None, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw), raw
            except ValueError:
                return e.code, None, raw
        except Exception as e:  # URLError, timeout, socket - all transient
            return None, None, f"{type(e).__name__}: {e}"

    def err_code(parsed):
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if isinstance(err, dict):
                return str(err.get("code", "")), str(err.get("message", ""))
            # Defensive: some vendors return a top-level {"code","message"} envelope.
            if "code" in parsed:
                return str(parsed.get("code", "")), str(parsed.get("message", ""))
        return "", ""

    for attempt in range(retries + 1):
        status, parsed, raw = post()

        # --- Success ---
        if status == 200 and isinstance(parsed, dict):
            try:
                choice = parsed["choices"][0]
                msg = choice["message"]
                content = (msg.get("content") or "").strip()
                if not content:
                    # Some GLM models put the answer in reasoning_content if content is empty.
                    content = (msg.get("reasoning_content") or "").strip()
                if content:
                    if choice.get("finish_reason") == "length":
                        sys.stderr.write("::GLM-TRUNCATED:: response hit max_tokens - the answer may "
                                         "be cut off. Raise --max-tokens (GLM-5.2 reasons heavily).\n")
                    print(content)
                    return 0
                sys.stderr.write("::GLM-EMPTY:: 200 OK but no assistant content. Raw below.\n")
                sys.stderr.write(raw[:2000] + "\n")
                return 1
            except (KeyError, IndexError, TypeError):
                sys.stderr.write("::GLM-PARSE:: 200 OK but unexpected response shape. Raw below.\n")
                sys.stderr.write(raw[:2000] + "\n")
                return 1

        code, message = err_code(parsed)

        # --- Unfunded: the #1 expected failure. NOT a code finding, NOT transient. ---
        if code == "1113":
            sys.stderr.write("::GLM-UNFUNDED:: z.ai account has no balance / no resource package.\n")
            sys.stderr.write("::GLM-UNFUNDED:: subscribe to a GLM Coding Plan or top up at https://z.ai/subscribe, then retry.\n")
            sys.stderr.write(f"::GLM-UNFUNDED:: (HTTP {status}, code {code}: {message})\n")
            return 1

        # --- Auth: surface, don't retry. ---
        if status in (401, 403):
            sys.stderr.write(f"::GLM-AUTH:: auth rejected (HTTP {status}, code {code}: {message}).\n")
            sys.stderr.write("::GLM-AUTH:: check that ZAI_API_KEY holds a valid, current z.ai key.\n")
            return 1

        # --- Transient: rate-limit (429 not 1113), 5xx, or network. Retry then surface. ---
        transient = status is None or status >= 500 or status == 429
        if transient and attempt < retries:
            sys.stderr.write(f"::GLM-RETRY:: transient (HTTP {status}, code {code}), retry in {retry_sleep:.0f}s "
                             f"({attempt + 1}/{retries})\n")
            time.sleep(retry_sleep)
            continue

        # --- Exhausted or non-transient hard failure: surface, never guess. ---
        sys.stderr.write(f"::GLM-FAILED:: HTTP {status}, code {code}: {message}\n")
        sys.stderr.write(raw[:2000] + "\n")
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
