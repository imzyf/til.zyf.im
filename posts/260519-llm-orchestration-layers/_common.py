"""
Shared helpers for the workflow vs agent demo
=============================================

公共部分集中在这里 —— 两个 demo 的核心区别（控制流由谁决定）就在各自文件里。

抽到这里的:
- LLM 客户端
- Pydantic schemas（structured output 锁死返回 schema）
- 核心业务逻辑 do_extract / do_compliance / do_generate
  —— 各自被 workflow 包成 node、agent 包成 tool
- 副作用打印 print_review_queue
- 测试用对白 SAMPLE_TRANSCRIPT
- API key 守卫
"""

import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

load_dotenv()

# base_url 留空 = 直连 api.openai.com；填了就走 OpenAI 兼容的代理 / 网关
# （比如公司内部 LLM gateway、Azure OpenAI、Together、OpenRouter 等）
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-5.4-nano"),
    base_url=os.getenv("OPENAI_BASE_URL") or None,
    temperature=0,
)


# ────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ────────────────────────────────────────────────────────────────────────
# Workflow 里这是节点 I/O 契约（下游 Python 确定性消费字段）；
# Agent  里这是 tool 的输入 / 输出 schema（function calling 用）。
# 形状一样，角色不同 —— 详见两个 demo 文件里的对照注释。
# ────────────────────────────────────────────────────────────────────────

class ExtractedInfo(BaseModel):
    client_sentiment: Literal["positive", "neutral", "concerned"] = Field(
        description="Overall sentiment of the client during the meeting"
    )
    products_mentioned: list[str] = Field(
        description="Financial products discussed (insurance, annuity, fund, etc.)"
    )
    advisor_commitments: list[str] = Field(
        description="Promises/commitments the advisor made, short imperative phrases"
    )
    client_questions: list[str] = Field(
        description="Questions or concerns raised by the client"
    )


class ComplianceFlag(BaseModel):
    commitment: str = Field(description="Exact commitment that triggered the flag")
    issue: str = Field(description="Why it's non-compliant, one short sentence")
    severity: Literal["low", "high"]


class ComplianceReport(BaseModel):
    has_risk: bool
    flags: list[ComplianceFlag] = Field(default_factory=list)
    summary: str = Field(description="One-sentence overall verdict")


# ────────────────────────────────────────────────────────────────────────
# 核心业务逻辑 —— workflow 和 agent 共用
# ────────────────────────────────────────────────────────────────────────
# 这三个函数是 "纯业务"：拿到原始数据 → 调 LLM → 返回结构化结果。
# Workflow 把它们包成 (state) -> dict 节点；Agent 把它们包成 @tool。
# 包法不同，业务一样 —— 对照看就能看清范式差异在外层、不在内核。
# ────────────────────────────────────────────────────────────────────────

def do_extract(transcript: str) -> ExtractedInfo:
    """读 transcript → 吐 ExtractedInfo Pydantic 实例（确定性 schema）。"""
    # with_structured_output 是这套 demo 最值钱的一行 —— 强制 schema 约束
    extractor = llm.with_structured_output(ExtractedInfo)
    prompt = f"""You are a financial advisor's assistant. Read the meeting transcript
below and extract structured fields. The transcript may be in Chinese or English. Reply in Chinese.

Transcript:
\"\"\"
{transcript}
\"\"\"
"""
    return extractor.invoke(prompt)


def do_compliance(commitments: list[str]) -> ComplianceReport:
    """扫顾问的每条承诺，判定是否触发合规风险。"""
    checker = llm.with_structured_output(ComplianceReport)
    listed = "\n".join(f"- {c}" for c in commitments)
    prompt = f"""You are a compliance officer. Review each commitment for regulatory risk.

HIGH-severity triggers (any of):
- Guaranteeing returns ("guaranteed", "保证收益", "拍胸脯保证", "绝对")
- Claiming no risk ("can't lose", "稳赚不赔", "从来没跌过")
- Specific return predictions without disclaimer (e.g. "8% 复利")
- Promising tax outcomes without "consult a tax professional"
- Pitching unregistered/private offerings without suitability review

LOW-severity:
- Vague timeline promises
- Missing standard risk disclosure

Commitments to review:
{listed}

Output a flag for EVERY issue. If none, set has_risk=false and flags=[]."""
    return checker.invoke(prompt)


def do_generate(extract_json: str, has_risk: bool) -> str:
    """生成 advisor action items + client meeting notes（可选合规警告）。"""
    warning = (
        "\nIMPORTANT: This meeting was flagged for compliance review. "
        "Client-facing notes MUST avoid specific return numbers, guarantee language, "
        "or unverified tax claims. Mark as DRAFT pending compliance sign-off.\n"
        if has_risk
        else ""
    )
    prompt = f"""Generate two short documents based on this meeting extract.

Extract:
{extract_json}
{warning}
Output EXACTLY in this format:

=== ADVISOR ACTION ITEMS ===
- [3-5 imperative bullets, e.g. "Send annuity sheet by Tuesday"]

=== CLIENT MEETING NOTES ===
[2-3 short paragraphs, friendly tone, no specific return numbers]"""
    return llm.invoke(prompt).content


def parse_documents(text: str) -> tuple[str, str]:
    """把 do_generate 的输出切成 (action_items, client_notes)。"""
    parts = text.split("=== CLIENT MEETING NOTES ===")
    action_items = parts[0].replace("=== ADVISOR ACTION ITEMS ===", "").strip()
    client_notes = parts[1].strip() if len(parts) > 1 else ""
    return action_items, client_notes


def print_review_queue(summary: str, flags: list) -> None:
    """副作用：把审查队列写出来。flag 可以是 ComplianceFlag 也可以是 dict。"""
    print("\n🚨  [P1] Routed to compliance review queue")
    print(f"    Verdict: {summary}")
    if not flags:
        print("    ⚠ flags 为空（agent 版常见失败：LLM 漏传参数）")
    for flag in flags:
        severity = flag["severity"] if isinstance(flag, dict) else flag.severity
        commitment = flag["commitment"] if isinstance(flag, dict) else flag.commitment
        issue = flag["issue"] if isinstance(flag, dict) else flag.issue
        print(f"    - [{severity.upper()}] {commitment}")
        print(f"      → {issue}")


def require_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY (or put it in .env)")


# ════════════════════════════════════════════════════════════════════════
# 样本对白 ── 故意写满合规雷点
# ════════════════════════════════════════════════════════════════════════
# "绝对能保证 8% 复利"、"绝不亏损"、"从来没跌过" 都是 HIGH 级触发词，
# 加上一只未审批私募 —— 默认运行会走 P1 分支。
# 把这些词改成合规版本（"历史平均年化 X%，过往业绩不代表未来"），
# 重跑就能看 safe 分支怎么走。
# ════════════════════════════════════════════════════════════════════════

SAMPLE_TRANSCRIPT = """
Advisor: 王女士，根据您 35 岁、年收入 50 万、计划 60 岁退休的情况，
我推荐这个分红型年金组合。每年投 10 万，到 60 岁绝对能保证 8% 复利收益，
绝不亏损，这点我可以拍胸脯保证。

Client: 那税务上呢？我听说这种年金分红是免税的？

Advisor: 对，目前法规下分红那部分免个税，您完全不用担心。
另外我们还有一只私募基金，年化预期 15-20%，没在公开市场挂牌，
门槛 100 万起，下周二我把材料发您。

Client: 嗯…我想再考虑一下风险。万一市场不好呢？

Advisor: 不用担心，过去 10 年这个组合从来没跌过，您 60 岁时账户里
最少有 480 万，这是底线。下周三我给您准备好合同，您签字就行。
"""
