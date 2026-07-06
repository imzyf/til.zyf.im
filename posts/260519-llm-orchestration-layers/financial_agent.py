"""
LangGraph Agent Demo —— 理财顾问会议笔记处理（agent 版）
======================================================

和 financial_workflow.py 同样的业务目标，但控制流交给 LLM。
公共部分（LLM 客户端、Pydantic schemas、核心业务逻辑 do_extract / do_compliance /
do_generate、样本对白）都在 _common.py。这个文件只保留 agent 范式独有的部分：
@tool 包装、system prompt、tools_condition、build_agent、运行时 stream loop。

对照 financial_workflow.py 看 [WORKFLOW → AGENT] 标记 —— 每条都是 workflow 版本里
的对应设计被 agent 范式替换掉的方式。

Agent 的样子（这个文件）:
    你的代码把 tool 列表塞给 LLM
        ↓
    LLM 决定调哪个 tool（也可以选择不调，直接收尾）
        ↓
    tool 跑完返回 observation
        ↓
    LLM 看 observation 决定 继续 / 停
        ↓
    （循环，运行时才知道走几轮）

编译期能画出的图只有：
    START → llm ⇄ tools → END
具体跑了几轮、每轮调了哪个工具 —— 看 messages 历史。

升级前后对照速查 (workflow → agent):
    节点函数 (state)→dict        →  @tool def fn(...) → JSON-able
    TypedDict 业务字段 state     →  MessagesState（只有 messages）
    add_edge / 你写死的流程      →  LLM 在每轮决定
    route_by_risk Python 函数    →  tools_condition（看 LLM 有没有 tool_calls）
    draw_ascii 漂亮流程图        →  只能画 llm⇄tools 循环群
"""

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

from _common import (
    SAMPLE_TRANSCRIPT,
    do_extract,
    do_compliance,
    do_generate,
    print_review_queue,
    require_api_key,
    llm,
)


# ════════════════════════════════════════════════════════════════════════
# [WORKFLOW → AGENT] ① ── 节点变成 tool
# ════════════════════════════════════════════════════════════════════════
# Workflow: 节点函数签名是 (state) -> dict，连边在 build_graph 里你写死
# Agent:    工具函数签名是普通业务参数 (transcript: str) -> JSON-able
#           "什么时候调、用什么参数、调几次" 全由 LLM 决定
#
# ★ docstring 在 agent 里不是注释 ★
#   它是给 LLM 看的"工具使用说明书"，会被序列化进 function-calling 的
#   schema description 字段。写不清楚 → LLM 选错工具 / 漏参数。
#
# 业务核心（do_extract / do_compliance / do_generate）和 workflow 版本完全一致，
# 都来自 _common.py —— 范式差异只在外层 @tool 包装上。
# ════════════════════════════════════════════════════════════════════════

@tool
def extract_info(transcript: str) -> dict:
    """Extract structured fields from a financial advisor meeting transcript.

    Returns client_sentiment, products_mentioned, advisor_commitments
    (promises the advisor made), and client_questions. Transcript may be
    Chinese or English. Call this FIRST when given a new transcript.
    """
    return do_extract(transcript).model_dump()


@tool
def compliance_check(commitments: list[str]) -> dict:
    """Scan advisor commitments for regulatory compliance risks.

    HIGH-severity triggers:
    - Guaranteed returns ("guaranteed", "保证收益", "拍胸脯保证", "绝对")
    - "Can't lose" language ("稳赚不赔", "从来没跌过")
    - Specific return predictions without disclaimer (e.g. "8% 复利")
    - Tax outcome promises without "consult a tax professional"
    - Unregistered/private offerings without suitability review

    LOW-severity: vague timeline promises, missing risk disclosure.

    Call AFTER extract_info, passing its advisor_commitments field.
    Returns has_risk, flags ([{commitment, issue, severity}, ...]), summary.
    """
    return do_compliance(commitments).model_dump()


# ────────────────────────────────────────────────────────────────────────
# ★ Agent 经典失败模式 ★ —— 为什么 flags 默认 None 是防御性设计
# ────────────────────────────────────────────────────────────────────────
# 小模型 (gpt-5.4-nano / Haiku 等) 实测经常这样调：
#     queue_for_review(summary="...合规风险...")    ← 漏了 flags
# 然后 Pydantic 抛 "flags: Field required"，ToolNode 把错误塞回 messages，
# LLM 才会重试。重试一两次就要多烧好几倍 token。
#
# 这就是把控制流交给 LLM 的真实成本 —— LLM 在工具调用之间会"漏参数 /
# 选错工具 / 顺序乱跳"，必须代码侧防御。
#
# 防御手段（从轻到重，按需叠加）:
#   1. 可选参数加默认值                    —— 别让 schema 校验崩
#   2. docstring 显式写 REQUIRED + 字段形状  —— 降低 LLM 漏参概率
#   3. 工具签名收敛成一个 dict 参数          —— LLM 只需要"原样复制" observation
#   4. 系统提示里明确每个工具的必填字段       —— belt & suspenders
#   5. 上更强的模型（gpt-5.4 / Claude Opus）  —— 推理能力直接解决一部分
#
# 对比 workflow 版本：route_by_risk 直接读 state["risk_level"] 字段，
# 根本不存在"LLM 要记得在工具间传参"这回事。这就是控制流归属换人付出的代价。
# ────────────────────────────────────────────────────────────────────────

@tool
def queue_for_review(summary: str, flags: list[dict] | None = None) -> str:
    """Send a flagged meeting to the compliance review queue.

    Call this ONLY when compliance_check returned has_risk=true.

    Args:
        summary: the one-sentence verdict from compliance_check.summary
        flags: REQUIRED — the full list from compliance_check.flags. Each item
               is shaped {"commitment": str, "issue": str, "severity": "low"|"high"}.
               Pass the list verbatim from the compliance report. Do not omit,
               do not summarize, do not reshape.

    Returns a short confirmation string.
    """
    print_review_queue(summary, flags)
    return f"Queued. {len(flags)} flag(s) recorded."


@tool
def generate_documents(extract_json: str, has_risk: bool) -> str:
    """Generate advisor action items + client meeting notes.

    Pass extract_json = the JSON string of the ExtractedInfo from
    extract_info. Pass has_risk=true if compliance_check flagged this
    meeting — output will be marked DRAFT and stripped of specific
    return numbers. Call this LAST.
    """
    return do_generate(extract_json, has_risk)


TOOLS = [extract_info, compliance_check, queue_for_review, generate_documents]


# ════════════════════════════════════════════════════════════════════════
# [WORKFLOW → AGENT] ② ── State 退化成对话历史
# ════════════════════════════════════════════════════════════════════════
# Workflow:  TypedDict 里有 transcript / extracted / compliance / ... 业务字段
# Agent:     MessagesState 只有 messages: list[BaseMessage]
#            所有信息 —— observation、tool 入参、LLM 回复 —— 都在对话里
#            因为消费者是 LLM，它读的就是对话历史本身
#
# 这是为什么 agent 经常被吐槽"context 越滚越大" —— 每一轮 observation 都
# 进 messages，下一轮 LLM 看的 prompt 越来越长，token 成本线性增长。
# 长 agent loop 通常要配 summary / 截断策略。
# ════════════════════════════════════════════════════════════════════════
# 直接用 langgraph 自带的 MessagesState 即可，不用自己定义


# ════════════════════════════════════════════════════════════════════════
# [WORKFLOW → AGENT] ③ ── 路由变成 tools_condition，由 LLM 控制 ★★★
# ════════════════════════════════════════════════════════════════════════
# 这一行就是 workflow vs agent 在代码里的分水岭。
#
# Workflow:
#     def route_by_risk(state) -> Literal["safe", "p1"]:
#         return state["risk_level"]                ← Python 看字段判断
#     g.add_conditional_edges("compliance", route_by_risk, {...})
#
# Agent:
#     g.add_conditional_edges("llm", tools_condition)
#         ↑ tools_condition 看 LLM 最后一条消息：
#             有 tool_calls → 去 "tools" 节点
#             没有 tool_calls → 去 END
#         "调不调、调哪个、调几次" 全是 LLM 在运行时决定
#
# 失去的代码控制力 = 引入的不确定性。
# 收益 = 不用穷举所有分支；任务变种你不写新代码，LLM 自己 cover。
# ════════════════════════════════════════════════════════════════════════

# ★ 关键：system prompt 是 agent 的"流程图" ★
# Workflow 里的流程是 add_edge 声明的；
# Agent 里的流程是 system prompt 描述的 —— 写得不清楚，LLM 就乱跳。
SYSTEM_PROMPT = """You are a financial advisor's assistant. You process meeting
transcripts through compliance review and produce documents.

Available tools (use in this logical order):
  1. extract_info       — pull structured fields from the transcript
  2. compliance_check   — review advisor commitments for regulatory risk
  3. queue_for_review   — ONLY IF compliance_check returned has_risk=true.
                          MUST pass BOTH summary AND the full flags list from
                          the compliance report (do not omit flags).
  4. generate_documents — produce final action items + client notes (always last).
                          MUST pass BOTH extract_json (the ExtractedInfo JSON
                          from extract_info) AND has_risk (the boolean from
                          compliance_check).

When all four (or three, if no risk) steps are done, reply with a one-sentence
summary of what you did and STOP calling tools. Do not call generate_documents
more than once."""


def llm_node(state: MessagesState) -> dict:
    """LLM 决策节点：每次进来都让 LLM 看完整对话 → 决定下一步调啥工具（或停）。"""
    llm_with_tools = llm.bind_tools(TOOLS)
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def build_agent():
    g = StateGraph(MessagesState)

    g.add_node("llm", llm_node)
    g.add_node("tools", ToolNode(TOOLS))      # ToolNode 自动按 tool_calls 派发

    g.add_edge(START, "llm")

    # ★ 分水岭这一行 ★ —— LLM 决定要不要继续调工具
    g.add_conditional_edges("llm", tools_condition)

    # tools 跑完一定回 llm —— 让 LLM 看 observation 再决定下一步
    g.add_edge("tools", "llm")

    return g.compile()


# ════════════════════════════════════════════════════════════════════════
# [WORKFLOW → AGENT] ④ ── 你也可以一行写完整个 agent
# ════════════════════════════════════════════════════════════════════════
# 上面这个 build_agent() 等价于：
#
#     from langgraph.prebuilt import create_react_agent
#     app = create_react_agent(llm, TOOLS, prompt=SYSTEM_PROMPT)
#
# create_react_agent 把 "llm 节点 + ToolNode + tools_condition + 循环边"
# 这套 ReAct 模板一次性给你。生产里直接用它就行 —— 上面手写版本只为了
# 让你看清楚 agent 的骨架。
# ════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    require_api_key()

    app = build_agent()

    # ─── 编译期能画出来的图就这么多 ────────────────────────────────
    # 对比一下 workflow 版本的 draw_ascii：那个能看到 extract → compliance →
    # (safe|p1) → generate → END 完整路径。agent 这里只能画到 llm⇄tools 循环。
    print("Agent graph (编译期只能看到循环骨架 —— 真实路径在 messages 历史里):")
    print(app.get_graph().draw_ascii())

    initial = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Process this meeting transcript:\n\n{SAMPLE_TRANSCRIPT}"),
        ]
    }

    # ─── 用 stream 看运行时真实路径 ─────────────────────────────────
    # 每出一条新消息就打印一次，能直观看到 LLM 怎么一轮一轮决策
    print("\n" + "=" * 60)
    print("AGENT LOOP (运行时才知道走几轮)")
    print("=" * 60)

    final_state = None
    seen = 0
    for event in app.stream(initial, stream_mode="values"):
        final_state = event
        msgs = event["messages"]
        for msg in msgs[seen:]:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    args_keys = list(tc["args"].keys())
                    print(f"\n[LLM → tool] {tc['name']}(args={args_keys})")
            elif isinstance(msg, ToolMessage):
                preview = msg.content if len(msg.content) <= 200 else msg.content[:200] + "..."
                print(f"\n[tool → LLM] {msg.name}\n    {preview}")
            elif isinstance(msg, AIMessage):
                print(f"\n[LLM final] {msg.content}")
        seen = len(msgs)

    # ─── 最终产物 ──────────────────────────────────────────────────
    # 在 agent 范式下，"最终产物" 不像 workflow 那样有专门的 state 字段，
    # 而是散落在 ToolMessage 里 —— 这里把 generate_documents 的输出挑出来。
    print("\n" + "=" * 60)
    print("FINAL DOCUMENTS (从 messages 里挑出最后一次 generate_documents 的输出)")
    print("=" * 60)
    for msg in reversed(final_state["messages"]):
        if isinstance(msg, ToolMessage) and msg.name == "generate_documents":
            print(msg.content)
            break
