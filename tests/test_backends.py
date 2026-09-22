"""백엔드 테스트. LLM 호출 없이 도는 부분만.

CLI 경로에는 서버측 스키마 강제가 없어서 JSON 추출과 검증이 직접 방어선이 된다.
"""

import pytest
from pydantic import BaseModel, ValidationError

from ragdiag.backends import Usage, extract_json
from ragdiag.prompts import output_contract
from ragdiag.schema import GroundingCheck, Observation, SufficiencyJudgment


def test_extracts_plain_json():
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_strips_markdown_fence():
    # CLI는 시스템 프롬프트로 막아도 코드펜스를 붙이는 경우가 있다.
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_ignores_prose_before_and_after():
    assert extract_json('결과입니다:\n{"a": 1}\n이상입니다.') == '{"a": 1}'


def test_braces_inside_strings_do_not_break_parsing():
    # 인용문에 중괄호가 들어올 수 있다. rfind('}')로는 못 잡는다.
    raw = '{"quote": "규정 {제3조} 참고", "n": 1} 뒤에 붙은 산문 }'
    assert extract_json(raw) == '{"quote": "규정 {제3조} 참고", "n": 1}'


def test_nested_objects_are_kept_whole():
    assert extract_json('{"a": {"b": {"c": 1}}}') == '{"a": {"b": {"c": 1}}}'


def test_escaped_quote_inside_string():
    raw = r'{"quote": "그는 \"맞다\"고 했다"}'
    assert extract_json(raw) == raw


@pytest.mark.parametrize("bad", ["없음", "[1,2,3]", '{"a": 1'])
def test_malformed_input_raises(bad):
    with pytest.raises(ValueError):
        extract_json(bad)


@pytest.mark.parametrize("model", [Observation, SufficiencyJudgment, GroundingCheck])
def test_contract_lists_every_field_in_declaration_order(model):
    # 필드 순서에 설계가 담겨 있다. reasoning이 먼저여야 결론이 근거의 결과가 된다.
    contract = output_contract(model)
    positions = [contract.index(name) for name in model.model_fields]
    assert positions == sorted(positions)
    assert all(name in contract for name in model.model_fields)


def test_contract_spells_out_enum_values():
    contract = output_contract(Observation)
    for value in ["content_missing", "content_wrong", "format", "none"]:
        assert f'"{value}"' in contract


def test_contract_expands_nested_array_items():
    # evidence가 배열이라는 것만으론 부족하다. 원소 구조까지 알려줘야 한다.
    contract = output_contract(SufficiencyJudgment)
    assert "chunk_index" in contract and "quote" in contract


def test_contract_forbids_extra_text():
    assert "JSON 객체 하나만" in output_contract(GroundingCheck)


def test_schema_validation_rejects_bad_enum():
    with pytest.raises(ValidationError):
        SufficiencyJudgment.model_validate_json(
            '{"reasoning":"r","evidence":[],"verdict":"엉뚱한값","missing":""}'
        )


def test_usage_accumulates():
    total = Usage()
    total.add(Usage(100, 20, 0.05))
    total.add(Usage(200, 30, 0.05))
    assert (total.input_tokens, total.output_tokens) == (300, 50)
    assert total.cost_usd == pytest.approx(0.10)


def test_strip_reasoning_takes_text_after_the_last_close_tag():
    from ragdiag.backends import strip_reasoning

    assert strip_reasoning("<think>생각</think>답") == "답"
    assert strip_reasoning("<thinking>생각</thinking>답") == "답"
    assert strip_reasoning("여는 태그 없이 생각만</think>답") == "답"
    assert strip_reasoning("추론 없음") == "추론 없음"


def test_strip_reasoning_uses_the_last_tag_not_the_first():
    from ragdiag.backends import strip_reasoning

    # 반복되거나 중첩된 블록에서도 마지막 뒤를 취해야 한다.
    assert strip_reasoning("<think>a</think>중간<think>b</think>진짜답") == "진짜답"


def test_a_closing_think_tag_inside_a_json_string_does_not_cut_the_json():
    """읽기 판정이 <think> 가 새어 나온 답변을 인용하면 JSON 안에 </think> 가 들어온다.

    마지막 태그 뒤를 취하던 시절에는 JSON 의 앞부분이 잘려 나가 3회 연속 형식 실패였다.
    추론 블록은 JSON 앞에 오므로, 뒤 태그부터 잘라 보다가 JSON 으로 읽히는 첫 후보를 쓴다.
    """
    import json

    raw = ('<think>먼저 답변을 본다</think>\n'
           '{"reasoning": "내부 사고가 새어 나옴", '
           '"quote": "<think>사용자가 연차 이월을 묻고 있다</think><think>그러면", "legible": false}')
    assert json.loads(extract_json(raw))["legible"] is False

    # 추론 블록 안의 중괄호는 여전히 집지 않는다
    raw = '<think>{"x": 1} 를 고려하면</think>\n{"legible": true}'
    assert extract_json(raw) == '{"legible": true}'


# ---------------------------------------------------------------------------
# 추론을 끄는 파라미터 — 서버마다 이름이 다르다
# ---------------------------------------------------------------------------

def _payload_for(thinking_param, thinking="off"):
    from ragdiag.backends import OpenAICompatBackend
    from ragdiag.schema import GroundingCheck

    backend = OpenAICompatBackend.__new__(OpenAICompatBackend)
    backend.model = "m"
    backend.temperature = 0.0
    backend.max_tokens = 100
    backend.thinking = thinking
    backend.thinking_param = thinking_param
    return backend._payload("s", "u", GroundingCheck, "none")


def test_vllm_gets_the_chat_template_switch():
    """실행 환경의 기본값. Qwen3 채팅 템플릿 스위치를 직접 넣는다."""
    payload = _payload_for("chat_template_kwargs")
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning" not in payload


def test_openrouter_gets_its_own_reasoning_field():
    """중계 서비스는 자기 형식으로 받는다.

    OpenRouter 에 vLLM 방식을 보내면 **조용히 무시한다.** 400 이 아니라 무시라서
    추론이 켜진 채로 돌고, 토큰 한도를 다 태우고 잘려 JSON 이 깨진다 - 실측에서
    추론 14,157자에 파싱 실패였다. 그래서 둘을 한꺼번에 보내지 않고 하나만 보낸다.
    """
    payload = _payload_for("reasoning")
    assert payload["reasoning"] == {"enabled": False}
    assert "chat_template_kwargs" not in payload


def test_auto_sends_neither():
    """auto 는 서버 기본값을 그대로 둔다 - 모르는 필드로 400 을 맞지 않는다."""
    for param in ("chat_template_kwargs", "reasoning"):
        payload = _payload_for(param, thinking="auto")
        assert "chat_template_kwargs" not in payload and "reasoning" not in payload


def test_an_unknown_thinking_param_is_refused():
    from ragdiag.backends import JudgeError, OpenAICompatBackend

    with pytest.raises(JudgeError, match="thinking_param"):
        OpenAICompatBackend(base_url="http://x", model="m", thinking_param="개똥")
