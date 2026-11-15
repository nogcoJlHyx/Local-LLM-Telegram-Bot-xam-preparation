import json
import logging
import re
from typing import Any

import requests

logger = logging.getLogger("exam_checker")

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL_NAME = "qwen2.5:1.5b"
REQUEST_TIMEOUT = (3, 30)


def normalize_text(text: str) -> str:
    text = str(text).lower().strip().replace("ё", "е")
    text = re.sub(r"[.,;:!?()\[\]{}\"'«»]", " ", text)
    return re.sub(r"\s+", " ", text)


def parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Модель не вернула корректный JSON")
        result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError("Ответ модели должен быть JSON-объектом")
    return result


def _numbers(text: str) -> list[str]:
    """Извлекает числа, приводя десятичные запятые к точкам."""
    normalized = str(text).replace("\u00a0", " ").replace(" ", "")
    normalized = normalized.replace(",", ".")
    return re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", normalized)


def _numeric_answer_match(user_answer: str, correct_answer: str) -> bool:
    """Проверяет числовой эталон: допускает единицы и форматирование числа."""
    expected = _numbers(correct_answer)
    actual = _numbers(user_answer)
    if not expected:
        return False
    # Для числовых кратких ответов пользовательский текст должен содержать
    # эталонные числовые значения в том же порядке.
    if len(expected) == 1:
        return expected[0] in actual
    return actual[:len(expected)] == expected


def _has_period(text: str) -> bool:
    """Распознаёт формулировки про сутки/дни хранения, включая 'в день'."""
    text = normalize_text(text)
    patterns = (
        r"\bв\s+день\b", r"\bза\s+день\b", r"\bкаждый\s+день\b",
        r"\bежедневно\b", r"\bсутк", r"\bдн(?:я|ей|е|ём|ем)\b",
        r"\bв\s+сутки\b", r"\bза\s+сутки\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _fast_semantic_checks(
    user_answer: str,
    correct_answer: str,
    required: dict[str, Any],
) -> dict[str, Any] | None:
    """Надёжные локальные проверки типовых кратких числовых ответов."""
    answer = normalize_text(user_answer)
    expected = normalize_text(correct_answer)

    # Расчётный ответ вида «неверно, правильная сумма 147200 руб.»
    amount = required.get("amount")
    if amount is not None:
        amount_ok = _numeric_answer_match(user_answer, str(amount))
        verdicts = required.get("verdict", [])
        verdict_ok = not verdicts or any(normalize_text(v) in answer for v in verdicts)
        currency_terms = required.get("currency", [])
        currency_ok = not currency_terms or any(normalize_text(v) in answer for v in currency_terms)
        correct = amount_ok and verdict_ok and currency_ok
        missing = []
        if not amount_ok:
            missing.append(f"сумма {amount}")
        if not verdict_ok:
            missing.append("указание, что расчёт неверен")
        if not currency_ok:
            missing.append("валюта")
        return {
            "is_correct": correct,
            "score": 1.0 if correct else 0.0,
            "missing_elements": missing,
            "detected_elements": {},
            "explanation": "Числовая сумма и необходимые пояснения проверены по эталону." if correct else "Проверьте сумму и обязательные элементы ответа.",
        }

    # Условия хранения: сумма/ставка, единица массы и период.
    if any(k in required for k in ("range", "amount_unit", "mass", "mass_unit", "period")):
        correct_answer_norm = normalize_text(correct_answer)
        # Сначала проверяем числовые величины, явно заданные в условиях.
        required_values = []
        allowed_range = required.get("range", {})
        if isinstance(allowed_range, dict) and allowed_range.get("kind") == "allowed_values":
            required_values = [str(allowed_range.get("min")), str(allowed_range.get("max"))]
        required_mass = required.get("mass")
        if required_mass is not None:
            required_values.append(str(required_mass))

        # Для формулировки «1 или 2 руб.» нужно принять один из двух тарифов;
        # проверяем, что ответ содержит хотя бы один допустимый тариф.
        range_ok = True
        if required_values:
            allowed_rates = required_values[:2] if len(required_values) >= 2 else required_values
            answer_numbers = _numbers(user_answer)
            range_ok = any(v in answer_numbers for v in allowed_rates)
            if required_mass is not None:
                range_ok = range_ok and str(required_mass) in answer_numbers

        units = required.get("amount_unit", []) + required.get("mass_unit", [])
        units_ok = not units or any(normalize_text(u) in answer for u in units)
        periods = required.get("period", [])
        period_ok = not periods or _has_period(user_answer)
        correct = range_ok and units_ok and period_ok
        missing = []
        if not range_ok:
            missing.append("правильная ставка/величина")
        if not units_ok:
            missing.append("единица измерения")
        if not period_ok:
            missing.append("период хранения (например, «за каждый день»)")
        return {
            "is_correct": correct,
            "score": 1.0 if correct else 0.0,
            "missing_elements": missing,
            "detected_elements": {},
            "explanation": "Проверены ставка, единицы измерения и период." if correct else "Ответ неполный: проверьте указанные обязательные элементы.",
        }

    # Если эталон — короткое число с единицами или словами вокруг него.
    expected_numbers = _numbers(correct_answer)
    if expected_numbers and len(expected_numbers) == 1 and len(str(correct_answer)) < 100:
        correct = _numeric_answer_match(user_answer, correct_answer)
        return {
            "is_correct": correct,
            "score": 1.0 if correct else 0.0,
            "missing_elements": [] if correct else [f"правильное значение {expected_numbers[0]}"],
            "detected_elements": {},
            "explanation": "Числовой ответ совпадает с эталоном." if correct else "Числовое значение отличается от эталона.",
        }

    # Точное совпадение нормализованного эталона — без вызова LLM.
    if answer == expected:
        return {
            "is_correct": True,
            "score": 1.0,
            "missing_elements": [],
            "detected_elements": {},
            "explanation": "Ответ совпадает с эталоном.",
        }
    return None


def send_to_ollama(
    question: str,
    correct_answer: str,
    user_answer: str,
    required_elements: dict[str, Any],
) -> dict[str, Any]:
    prompt = (
        "Оцени, верен ли ответ по смыслу. Не требуй дословного совпадения. "
        "Сверь факты и числа с эталоном. Верни только JSON вида "
        '{"is_correct":true,"score":1,"missing_elements":[],"explanation":"кратко"}.\n'
        f"Вопрос: {question[:1800]}\n"
        f"Эталон: {correct_answer[:1200]}\n"
        f"Обязательные элементы: {json.dumps(required_elements, ensure_ascii=False)[:1000]}\n"
        f"Ответ: {user_answer[:1200]}"
    )
    payload = {
        "model": MODEL_NAME,
        "stream": False,
        "format": "json",
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_predict": 64, "num_ctx": 1024, "num_thread": 4},
        "messages": [
            {"role": "system", "content": "Ты объективный проверяющий. Верни только корректный JSON."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        result = parse_json_response(response.json()["message"]["content"])
        score = max(0.0, min(1.0, float(result.get("score", 0.0))))
        correct = result.get("is_correct")
        if not isinstance(correct, bool):
            correct = score >= 0.7
        return {
            "is_correct": correct,
            "score": score,
            "missing_elements": result.get("missing_elements", []),
            "detected_elements": result.get("detected_elements", {}),
            "explanation": str(result.get("explanation", ""))[:500],
        }
    except Exception as exc:
        logger.exception("Ошибка запроса к Ollama")
        return {
            "is_correct": False,
            "score": 0.0,
            "missing_elements": ["Проверка временно не выполнена"],
            "detected_elements": {},
            "explanation": f"Сервис проверки недоступен: {exc}",
        }


def check_choice_answer(user_answer: str, correct_answer: str, required: dict[str, Any]) -> bool:
    user = normalize_text(user_answer)
    allowed = required.get("allowed_answers", []) or [correct_answer]
    # Принимаем и обозначение варианта, и содержательный ответ, если он есть в эталоне.
    for item in allowed:
        candidate = normalize_text(str(item))
        if user == candidate or (len(candidate) > 1 and candidate in user):
            return True
    return user == normalize_text(correct_answer)


def check_multiple_answer(user_answer: str, correct_answer: str, required: dict[str, Any]) -> bool:
    def tokens(value: str) -> set[str]:
        return set(normalize_text(value).replace(",", " ").replace(";", " ").split())

    allowed = required.get("allowed_answers", []) or [correct_answer]
    expected_sets = [tokens(str(item)) for item in allowed]
    return tokens(user_answer) in expected_sets


def numeric_guard(result: dict[str, Any], user_answer: str, required: dict[str, Any]) -> dict[str, Any]:
    """Дополнительные проверки для числовых ответов; допускает форматы вроде 147200 рублей."""
    answer = normalize_text(user_answer)
    missing = result.setdefault("missing_elements", [])

    amount = required.get("amount")
    if amount is not None and str(amount) not in _numbers(user_answer):
        result["is_correct"] = False
        result["score"] = 0.0
        missing.append(f"сумма {amount}")

    mass = required.get("mass")
    if mass is not None and str(mass) not in _numbers(user_answer):
        result["is_correct"] = False
        result["score"] = 0.0
        missing.append(f"масса {mass}")

    units = required.get("mass_unit", [])
    if units and not any(normalize_text(unit) in answer for unit in units):
        result["is_correct"] = False
        result["score"] = 0.0
        missing.append("единица массы")

    periods = required.get("period", [])
    if periods and not _has_period(user_answer):
        result["is_correct"] = False
        result["score"] = 0.0
        missing.append("период хранения")

    return result


def check_answer(
    question: str,
    correct_answer: str,
    user_answer: str,
    question_type: str,
    required_elements: dict[str, Any],
) -> dict[str, Any]:
    if question_type == "single_choice":
        correct = check_choice_answer(user_answer, correct_answer, required_elements)
        return {
            "is_correct": correct,
            "score": 1.0 if correct else 0.0,
            "missing_elements": [] if correct else ["неверно выбран вариант"],
            "detected_elements": {},
            "explanation": "Ответ совпадает с эталоном." if correct else "Выбран неверный вариант.",
        }
    if question_type == "multiple_choice":
        correct = check_multiple_answer(user_answer, correct_answer, required_elements)
        return {
            "is_correct": correct,
            "score": 1.0 if correct else 0.0,
            "missing_elements": [] if correct else ["неполный или неверный набор вариантов"],
            "detected_elements": {},
            "explanation": "Набор вариантов совпадает с эталоном." if correct else "Набор вариантов отличается от эталона.",
        }

    fast_result = _fast_semantic_checks(user_answer, correct_answer, required_elements)
    if fast_result is not None:
        return fast_result

    result = send_to_ollama(question, correct_answer, user_answer, required_elements)
    return numeric_guard(result, user_answer, required_elements)
