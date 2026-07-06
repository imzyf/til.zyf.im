"""
LangGraph Workflow Demo —— 理财顾问会议笔记处理
==================================================

回答问题：
    "Workflow vs Agent 的本质差异 '控制流在谁手里'，在代码里到底是哪一行？"

Workflow 的样子（这个文件）:
    你的 Python 代码 → 调 LLM 节点 → 看返回 → 你的代码决定下一步
                                       ↑
                              整个流程图编译期就能画出来

Agent 的样子（升级成 agent 后）:
    你的代码把工具列表给 LLM → LLM 决定调哪个 → 看 observation → LLM 决定继续 / 停
                                       ↑
                                每次跑的流程图都不一样

公共部分（LLM 客户端、Pydantic schemas、核心业务逻辑 do_extract / do_compliance /
do_generate、样本对白）都在 _common.py。这个文件只保留 workflow 范式独有的部分：
state 定义、节点装配、Python 路由函数、build_graph。对照 financial_agent.py
看 [WORKFLOW vs AGENT] 标记 —— 每条都标了"升级到 agent 那一行要改成什么"。

Pipeline:
    transcript
       ↓
    [extract]      LLM ①  抽结构化字段（do_extract）
       ↓
    [compliance]   LLM ②  逐条扫合规风险（do_compliance）
       ↓
       ├─ safe ─→ [generate] LLM ③ → END
       └─ p1   ─→ [queue_p1] 写审查队列 → [generate] LLM ③ → END
"""

from typing import Literal
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from _common import (
    ExtractedInfo,
    ComplianceReport,
    SAMPLE_TRANSCRIPT,
    do_extract,
    do_compliance,
    do_generate,
    parse_documents,
    print_review_queue,
    require_api_key,
)


# ════════════════════════════════════════════════════════════════════════
# State —— 节点间的 "信封"，不是函数参数
# ════════════════════════════════════════════════════════════════════════
# 节点之间不直接传参 —— 每个节点 return dict，LangGraph 自动 merge 进
# 共享 state。total=False 让 invoke 时只传初始字段，其他由后续节点写入。
#
# 工程收益：
#   - 加节点 / 改顺序 / 中间插一步 human-in-the-loop，函数签名不用动
#   - state 字段就是节点间的 API 契约，比 args 列表更明确
#
# [WORKFLOW vs AGENT]
#   Workflow: state 字段固定，每个节点读写什么字段编译期就清晰（看这里）
#   Agent:    state 通常只有 messages (LLM 对话历史)，因为决策者是 LLM，
#             不需要应用层结构化字段（见 financial_agent.py）
# ════════════════════════════════════════════════════════════════════════

class WorkflowState(TypedDict, total=False):
    transcript: str
    extracted: ExtractedInfo
    compliance: ComplianceReport
    risk_level: Literal["safe", "p1"]
    advisor_action_items: str
    client_meeting_notes: str


# ════════════════════════════════════════════════════════════════════════
# 节点 —— 把 _common 的业务函数包成 (state) -> dict 形状
# ════════════════════════════════════════════════════════════════════════
# [WORKFLOW vs AGENT] 节点 vs tool 的签名差异：
#
#   Workflow 节点：def fn(state: WorkflowState) -> dict
#                    LangGraph 按 add_edge 顺序调，参数全在 state 里取
#
#   Agent  tool:    @tool def fn(business_arg: T) -> JSON-able
#                    LLM 看 docstring + schema 自己决定何时调、传什么参数
#
# 业务核心（do_extract / do_compliance / do_generate）一致，只是外层包法不同。
# ════════════════════════════════════════════════════════════════════════

def extract_info(state: WorkflowState) -> dict:
    return {"extracted": do_extract(state["transcript"])}


def compliance_check(state: WorkflowState) -> dict:
    report = do_compliance(state["extracted"].advisor_commitments)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 这里派生 risk_level 字段写进 state ——
    # 给下一步的"路由函数"用。路由函数是 Python 不是 LLM (见下方分水岭)，
    # 所以路由需要的判断字段必须先由 LLM 节点写进 state 里。
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    return {
        "compliance": report,
        "risk_level": "p1" if report.has_risk else "safe",
    }


def queue_for_review(state: WorkflowState) -> dict:
    # 真实场景这里会 POST 到内部审查队列 / 写 DB / 发 Slack 给合规组长
    print_review_queue(state["compliance"].summary, state["compliance"].flags)
    return {}  # 纯副作用，不改 state


def generate_documents(state: WorkflowState) -> dict:
    # 分支差异是 Python 字符串拼接控制的（has_risk → prompt 里多注入警告），
    # 不是 LLM 自己判断"该不该多加这段警告" —— 那是 agent 干的事
    text = do_generate(
        extract_json=state["extracted"].model_dump_json(indent=2),
        has_risk=state["risk_level"] == "p1",
    )
    action_items, client_notes = parse_documents(text)
    return {
        "advisor_action_items": action_items,
        "client_meeting_notes": client_notes,
    }


# ════════════════════════════════════════════════════════════════════════
# 设计决策 ★ ── 路由函数是普通 Python，不是 LLM ★★★
# ════════════════════════════════════════════════════════════════════════
# 这一行就是 Workflow 和 Agent 在代码里的分水岭：
#
#   - 我们的代码 (route_by_risk) 根据 state 字段决定走哪个分支
#   - 不是 LLM 在运行时决定 "我现在该走哪个节点"
#
# [WORKFLOW vs AGENT]
#   Workflow:
#       def route_by_risk(state) -> Literal["safe", "p1"]:
#           return state["risk_level"]           # Python 判断，确定性
#
#   Agent:
#       from langgraph.prebuilt import tools_condition
#       g.add_conditional_edges("llm", tools_condition)
#           # ↑ tools_condition 读 LLM last message 看它是要调 tool 还是结束
#           # ↑ "继续与否 + 调哪个 tool" 都是 LLM 决定的 = 不确定性
#
# 把这个文件的 route_by_risk 删掉，换成 tools_condition，
# 就完成了 workflow → agent 的升级。立刻失去的代码控制力，
# 就是 agent 引入的不确定性的具体形态。
# ════════════════════════════════════════════════════════════════════════

def route_by_risk(state: WorkflowState) -> Literal["safe", "p1"]:
    return state["risk_level"]


# ════════════════════════════════════════════════════════════════════════
# 编排 ── 把节点和边声明出来
# ════════════════════════════════════════════════════════════════════════
# 关键看 add_conditional_edges:
#   - 路由参数 route_by_risk 是你的 Python 函数
#   - mapping {"safe": "generate", "p1": "queue_p1"} 是死 dict
#   → 整个流程图在 g.compile() 之后就能用 draw_ascii() / draw_mermaid()
#     画出来，编译期就肉眼可见。
#
# [WORKFLOW vs AGENT]
#   Workflow: 流程图编译期可视化 —— 跑哪几步、什么顺序，画得出来
#   Agent:    流程图运行时才知道 —— ReAct 循环走多少轮、调哪几个 tool，
#             都是 LLM 运行时决定的。draw_mermaid 只能画出"循环节点群"
# ════════════════════════════════════════════════════════════════════════

def build_graph():
    g = StateGraph(WorkflowState)

    g.add_node("extract",    extract_info)
    g.add_node("compliance", compliance_check)
    g.add_node("queue_p1",   queue_for_review)
    g.add_node("generate",   generate_documents)

    g.add_edge(START, "extract")
    g.add_edge("extract", "compliance")

    # ★ 分水岭 ★ —— 路由参数是 Python 函数，不是 LLM
    g.add_conditional_edges(
        "compliance",
        route_by_risk,
        {"safe": "generate", "p1": "queue_p1"},
    )

    g.add_edge("queue_p1", "generate")   # P1 也要生成文档，prompt 里会带 warning
    g.add_edge("generate", END)

    return g.compile()


if __name__ == "__main__":
    require_api_key()

    app = build_graph()

    # ─── 编译期可视化：workflow 的特征之一 ─────────────────────────────
    # Agent 的图你也能画，但只能看到"循环群"，看不到具体每次跑的路径
    print("Workflow graph (编译期就能画出来 —— 这本身就是 workflow 的特征):")
    print(app.get_graph().draw_ascii())

    final = app.invoke({"transcript": SAMPLE_TRANSCRIPT})

    sep = "=" * 60
    print(f"\n{sep}\nEXTRACTED\n{sep}")
    print(final["extracted"].model_dump_json(indent=2))

    print(f"\n{sep}\nCOMPLIANCE\n{sep}")
    print(final["compliance"].model_dump_json(indent=2))

    print(f"\n{sep}\nADVISOR ACTION ITEMS\n{sep}\n{final['advisor_action_items']}")
    print(f"\n{sep}\nCLIENT MEETING NOTES\n{sep}\n{final['client_meeting_notes']}")
