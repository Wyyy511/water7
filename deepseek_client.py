from __future__ import annotations
import json
import os
import re
from typing import Any
import requests

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

# Railway/Linux environment variable names are case-sensitive. Accept the
# canonical name plus common aliases so a valid key is not missed simply
# because the variable name was entered slightly differently.
_KEY_ALIASES = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_KEY",
    "DEEPSEEK_APIKEY",
    "DEEPSEEK_TOKEN",
    "DEEPSEEK_API_TOKEN",
)

def _clean_env_value(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if "=" in value and value.split("=", 1)[0].strip().upper() in _KEY_ALIASES:
        value = value.split("=", 1)[1].strip()
    return value

def _normalized_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(name).upper()).strip("_")

def api_key_info() -> tuple[str, str | None]:
    for name in _KEY_ALIASES:
        key = _clean_env_value(os.getenv(name))
        if key:
            return key, name
    wanted = {_normalized_name(x) for x in _KEY_ALIASES}
    for name, value in os.environ.items():
        if _normalized_name(name) in wanted:
            key = _clean_env_value(value)
            if key:
                return key, name
    return "", None

def api_key_value() -> str:
    return api_key_info()[0]

def api_key_source() -> str | None:
    return api_key_info()[1]

def configured() -> bool:
    return bool(api_key_value())

def model_name() -> str:
    value = _clean_env_value(os.getenv("DEEPSEEK_MODEL"))
    return value or DEFAULT_MODEL

def base_url() -> str:
    value = _clean_env_value(os.getenv("DEEPSEEK_BASE_URL"))
    return (value or DEFAULT_BASE_URL).rstrip("/")


def _post(messages: list[dict[str, Any]], *, temperature: float = 0.15, max_tokens: int = 2200, json_mode: bool = False) -> str:
    key = api_key_value()
    if not key:
        raise RuntimeError("DeepSeek API key is not configured in Railway Variables")
    base = base_url()
    payload: dict[str, Any] = {
        "model": model_name(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    resp = requests.post(
        base + "/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def chat(system_prompt: str, user_prompt: str, fallback: str) -> tuple[str, dict[str, Any]]:
    """Generate language only. Numeric risk values must already exist in tool output."""
    if not configured():
        return fallback, {"provider": "local_fallback", "model": None, "used": False}
    try:
        text = _post([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
        return _plain_user_language(text), {"provider": "DeepSeek", "model": model_name(), "used": True}
    except Exception as exc:
        return fallback, {"provider": "local_fallback", "model": model_name(), "used": False, "error": str(exc)[:300]}


def _json_from_text(raw: str) -> dict[str, Any] | None:
    raw = (raw or "").strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def classify_intent(message: str) -> dict[str, Any] | None:
    """Use DeepSeek only for intent/parameter understanding, never for risk calculation."""
    if not configured() or not (message or "").strip():
        return None
    sys = (
        "你是上游供应链水风险 AI Agent 的任务路由器。只做任务识别和情景参数抽取，不计算任何风险数字。"
        "只输出JSON对象，不要Markdown。"
        "intent只能是 analyze、scenario、explain、data_help、export、general。"
        "scenario_type只能是 PeakSeason、AqueductFuture、ExtremeDrought、NodeFailure 或 null。"
        "可选字段：material(甘蔗/甜菜/大豆或null)、year(整数或null)、path(BAU/OPT/PES或null)、"
        "failure_fraction(0-1或null)、inventory(0-1或null)。"
        "如果用户说分析上传材料或当前风险，intent=analyze；如果问缺什么数据或模板，intent=data_help；"
        "如果明确问情景变化，intent=scenario；如果要求下载报告，intent=export。"
    )
    try:
        raw = _post([
            {"role": "system", "content": sys},
            {"role": "user", "content": message},
        ], temperature=0.0, max_tokens=500, json_mode=True)
        obj = _json_from_text(raw)
        if not obj or obj.get("intent") not in {"analyze", "scenario", "explain", "data_help", "export", "general"}:
            return None
        if obj.get("scenario_type") not in {None, "PeakSeason", "AqueductFuture", "ExtremeDrought", "NodeFailure"}:
            obj["scenario_type"] = None
        return obj
    except Exception:
        return None


def extract_supply_chain(text: str) -> dict[str, Any] | None:
    """Extract candidate enterprise/material/node/procurement fields from report text.
    Output is candidate data only and must be confirmed before deterministic calculation.
    """
    if not configured() or not (text or "").strip():
        return None
    excerpt = text[:45000]
    sys = (
        "你是供应链资料结构化抽取工具。只从用户原文抽取，不猜测、不补齐。"
        "请只输出JSON，不要Markdown。结构：{enterprise:null或字符串, records:[...] }。"
        "每条records字段：material,node_id,node_name,purchase_weight,year,evidence,confidence。"
        "material只在原文明确时填甘蔗/甜菜/大豆或原材料原名；purchase_weight统一为0-1，原文没有就null；"
        "node_id只有原文明确包含项目节点编号时填写，否则null；node_name填写供应地/省州/国家/供应节点原文；"
        "evidence必须是支持该条记录的简短原文片段；confidence只可High/Medium/Low。"
        "不要把国家均值、推测值或常识当作企业采购事实。"
    )
    try:
        raw = _post([
            {"role": "system", "content": sys},
            {"role": "user", "content": "请抽取以下报告中的上游采购/供应链候选信息：\n" + excerpt},
        ], temperature=0.0, max_tokens=2200, json_mode=True)
        obj = _json_from_text(raw)
        if not obj or not isinstance(obj.get("records"), list):
            return None
        return obj
    except Exception:
        return None


def general_guidance(message: str, fallback: str, governance_context: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """First-contact conversation. Answer the user's need first, then guide data collection in plain language."""
    sys = (
        "你是 WaterPulse，一名面向科技型农食企业的上游供应链水风险助手。"
        "你的第一任务是先理解并回应用户真正关心的问题，而不是一上来要求上传文件。"
        "如果用户尚未提供企业数据，可以先用定性、易懂的方式说明应该关注哪些水风险来源、为什么值得关注，以及分析思路；"
        "随后再自然说明：如果要得到与该企业采购结构相关的个性化结果，需要补充原材料、主要供应地区/供应商、各来源采购量或占比，最好再有年份。"
        "用户可以上传 ESG 报告、采购表或其他相关文件；没有现成表格时，可以使用系统提供的 Excel 模板。"
        "如果用户问‘不同情况下会怎样’，用日常语言说明可以进一步比较关键用水期、未来水环境变化、严重干旱重现或主要供应节点中断。"
        "面向普通用户时始终使用自然中文，不要出现 Baseline、Scenario、PRWI、WS、DR、SV、BWD、DYS、CTS、OA、JSON、Schema、工具调用、字段合同、工作流、确定性引擎等内部术语。后台计算请转述为“当前风险分析”“不同情况比较”“综合风险指数”“参考数据”等普通表达。"
        "不要凭空生成企业采购比例、地点风险分值、综合风险数值或精确损失数字。"
        "回答要自然、简洁，像真正的企业分析助手；优先用用户能听懂的中文。"
    )
    prompt = message
    if governance_context:
        prompt += '\n\n以下是后台数据要求摘要，只用于判断需要向用户补充哪些信息；不要把内部字段名或技术术语直接展示给用户：\n' + json.dumps(governance_context, ensure_ascii=False, default=str)
    return chat(sys, prompt, fallback)


def analyze_tool_result(*, user_question: str, baseline: dict | None = None, scenario: dict | None = None,
                        validation: dict | None = None, fallback: str = "") -> tuple[str, dict[str, Any]]:
    """Explain deterministic tool output. DeepSeek may interpret and prioritize, but may not alter numbers."""
    if not configured():
        return fallback, {"provider": "local_fallback", "model": None, "used": False}
    payload = {
        "user_question": user_question,
        "validation": validation or {},
        "baseline": baseline or {},
        "scenario": scenario or {},
    }
    # Keep prompts bounded while preserving the official tool JSON fields used for explanation.
    raw_payload = json.dumps(payload, ensure_ascii=False, default=str)
    if len(raw_payload) > 42000:
        raw_payload = raw_payload[:42000]
    sys = (
        "你是 WaterPulse 上游供应链水风险决策助手。你只能解释给定的计算结果，不能重新计算或修改任何数值。"
        "所有综合风险、覆盖范围、节点风险、节点贡献、压力变化、供应缺口和集中度数字必须严格沿用输入中的已有结果；"
        "如果某个数字不存在，就明确说当前结果没有提供，绝对不要猜。"
        "回答时区分：①用户提供的事实；②系统计算得到的结论；③假设条件；④管理建议。"
        "优先解释：整体情况、最值得关注的供应地、哪些供应地对企业影响最大、主要风险原因、数据是否完整、不同情况下会怎样，以及下一步行动。"
        "如果关键数据不足、互相冲突或计算失败，应直接说明还不能形成正式结论，并告诉用户下一步补什么。"
        "面向普通用户的回答中一律不要出现 Baseline、Scenario、PRWI、WS、DR、SV、BWD、DYS、CTS、OA、JSON、Schema、工具调用、工作流等内部术语，请全部翻译为普通用户能理解的中文。"
        "用自然、简洁、面向企业用户的中文回答；不要暴露后台代码或内部流程。"
    )
    try:
        text = _post([
            {"role": "system", "content": sys},
            {"role": "user", "content": raw_payload},
        ], temperature=0.1, max_tokens=1800)
        return _plain_user_language(text), {"provider": "DeepSeek", "model": model_name(), "used": True}
    except Exception as exc:
        return fallback, {"provider": "local_fallback", "model": model_name(), "used": False, "error": str(exc)[:300]}


def connection_test() -> dict[str, Any]:
    """Make a minimal live API call without ever returning the secret itself."""
    source = api_key_source()
    if not configured():
        return {
            "ok": False,
            "configured": False,
            "env_source": None,
            "model": model_name(),
            "base_url": base_url(),
            "message": "No DeepSeek key was found in the service environment.",
        }
    try:
        text = _post([
            {"role": "system", "content": "You are a connection test. Reply with exactly OK."},
            {"role": "user", "content": "ping"},
        ], temperature=0.0, max_tokens=8)
        return {
            "ok": True,
            "configured": True,
            "env_source": source,
            "model": model_name(),
            "base_url": base_url(),
            "reply": text[:50],
        }
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        body = ""
        try:
            body = (exc.response.text or "")[:300]
        except Exception:
            pass
        return {
            "ok": False,
            "configured": True,
            "env_source": source,
            "model": model_name(),
            "base_url": base_url(),
            "http_status": status,
            "message": body or str(exc)[:300],
        }
    except Exception as exc:
        return {
            "ok": False,
            "configured": True,
            "env_source": source,
            "model": model_name(),
            "base_url": base_url(),
            "message": str(exc)[:500],
        }
