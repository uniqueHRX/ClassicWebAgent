"""VLM 子代理 —— 唯一接口 SubAgent。

from classic_web_agent.subagent import SubAgent

sub = SubAgent(vlm=vlm_client, browser=browser, memory=memory)
result = sub.run(sub_task="搜索论文A的摘要")
"""

from classic_web_agent.subagent.core import SubAgent

__all__ = ["SubAgent"]
