from __future__ import annotations
import time
import re
from telemetry.logger import logger, new_correlation_id, set_correlation_id
from telemetry.cost import cost_from_usage
from telemetry.redact import redact

def sanitize_question(q: str) -> str:
    """Sanitize input question to defend against prompt injection in order notes."""
    if not isinstance(q, str):
        return q
    # Spot note sections (e.g. Ghi chú, Note, Yêu cầu)
    match = re.search(r'(?i)(ghi\s*chú|note|yêu\s*cầu)\s*[:\-](.*)', q)
    if match:
        note_content = match.group(2)
        # Split into sentences to evaluate each
        sentences = re.split(r'[.,;?!]', note_content)
        cleaned_sentences = []
        for s in sentences:
            s_clean = s.strip()
            if not s_clean:
                continue
            # Regex for setting fake prices/totals
            price_injection = re.search(r'(?i)(giá|price|tính|chỉ|tổng)\s*(là|mới|đặc biệt|:\s*)?\s*\d+', s_clean)
            # Regex for bypassing tool calls or ignoring instructions
            bypass_injection = re.search(r'(?i)(bỏ qua|không cần|không dùng|đừng|tự|ignore|bypass|override)\s*(gọi|chạy|sử dụng|dùng|tool|bước|hướng dẫn|hệ thống)', s_clean)
            
            if not (price_injection or bypass_injection):
                cleaned_sentences.append(s_clean)
        
        prefix = q[:match.start()].strip()
        note_label = match.group(1)
        cleaned_note = ". ".join(cleaned_sentences).strip()
        return f"{prefix} {note_label}: {cleaned_note}".strip()
    return q

def mitigate(call_next, question, config, context):
    # Set correlation ID for request tracing
    cid = new_correlation_id()
    set_correlation_id(cid)
    
    t0 = time.time()
    sanitized_q = sanitize_question(question)
    
    # 1. Thread-safe caching for repeat questions
    cache_key = sanitized_q.strip().lower()
    cache = context.get("cache")
    cache_lock = context.get("cache_lock")
    
    if cache is not None and cache_lock is not None:
        with cache_lock:
            if cache_key in cache:
                cached_res = cache[cache_key]
                # Log cache hit
                if logger:
                    logger.log_event("CACHE_HIT", {
                        "qid": context.get("qid"),
                        "question": question,
                        "cached_answer": cached_res.get("answer")
                    })
                return cached_res

    # 2. Wrapper-level retry on non-ok statuses
    max_attempts = 2
    res = None
    for attempt in range(max_attempts):
        try:
            res = call_next(sanitized_q, config)
            break
        except Exception as e:
            import sys
            if logger:
                logger.log_event("WRAPPER_EXCEPTION", {
                    "qid": context.get("qid"),
                    "attempt": attempt + 1,
                    "exception": str(e)
                })
            print(f"\n[Wrapper Exception] Attempt {attempt + 1} failed: {e}\n", file=sys.stderr)
            if attempt == max_attempts - 1:
                raise e
            time.sleep(0.1)

    if res is None:
        res = {"answer": None, "status": "wrapper_error", "steps": 0, "trace": []}

    wall_ms = int((time.time() - t0) * 1000)
    meta = res.get("meta", {})
    usage = meta.get("usage", {})
    cost = cost_from_usage(meta.get("model", ""), usage)

    # 3. PII leak mitigation & Output formatting validation
    num_redactions = 0
    answer = res.get("answer")
    if answer:
        redacted_answer, num_redactions = redact(answer)
        if num_redactions > 0:
            answer = redacted_answer
        
        # Check if the answer is a refusal
        refusal_keywords = [
            "không thể hoàn thành", "không hỗ trợ", "hết hàng", 
            "xin lỗi", "không phục vụ", "không tìm thấy", 
            "chưa hỗ trợ", "không được hỗ trợ"
        ]
        is_refusal = any(kw in answer.lower() for kw in refusal_keywords)
        
        if is_refusal:
            # Enforce NO numbers at all in a refusal message
            answer = re.sub(r'\d+', '', answer)
            # Remove empty/orphaned price unit or percent markers
            answer = re.sub(r'(?i)\bVND\b', '', answer)
            answer = answer.replace('%', '')
            # Clean up duplicate whitespace
            answer = re.sub(r'\s+', ' ', answer).strip()
        else:
            # Enforce that the last line is exactly "Tong cong: <total> VND"
            # and clean up markdown asterisks or trailing redacted text
            match = re.search(r'(?i)tong\s*cong\s*:\s*\**(\d+)\**\s*VND', answer)
            if match:
                total_val = match.group(1)
                clean_lines = [line for line in answer.split('\n') if not re.search(r'(?i)tong\s*cong', line)]
                answer = "\n".join(clean_lines).strip() + f"\nTong cong: {total_val} VND"
            else:
                # If it's a successful response (general inquiry) but lacks a Tong cong line
                answer = answer.strip() + "\nTong cong: 0 VND"
            
        res["answer"] = answer

    # 4. Telemetry Logging
    if logger:
        logger.log_event("AGENT_CALL", {
            "qid": context.get("qid"),
            "session_id": context.get("session_id"),
            "turn_index": context.get("turn_index"),
            "status": res.get("status"),
            "reported_latency_ms": meta.get("latency_ms"),
            "wall_ms": wall_ms,
            "tokens": usage,
            "cost_usd": cost,
            "pii_redacted": num_redactions if answer else 0,
            "tools_used": meta.get("tools_used", []),
        })

    # Cache successful results
    if res.get("status") == "ok" and cache is not None and cache_lock is not None:
        with cache_lock:
            cache[cache_key] = res

    return res
