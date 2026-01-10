"""
智能代理核心实现
"""
import json
from typing import Optional

from kerneltune_agent.schema import Message, AgentState, Memory, Role
from kerneltune_agent.llm import SimpleLLM
from kerneltune_agent.tools import ToolCollection
from kerneltune_agent.prompt_build import SysctlPromptBuilder

class KernelTuneAgent:
    """内核参数调优智能代理实现"""
    
    def __init__(
        self, 
        llm: SimpleLLM,
        name: str = "KernelTuneAgent",
        system_prompt: Optional[str] = None,
        max_steps: int = 15
    ):
        self.name = name
        self.llm = llm
        self.tools = ToolCollection()
        self.memory = Memory()
        self.state = AgentState.IDLE
        self.max_steps = max_steps
        self.current_step = 0
        
        # 默认系统提示词
        self.system_prompt =(
            "根据实验环境推荐 sysctl 配置,可以使用各种工具来完成任务。\n\n"
            "【可用工具】\n"
            "python_execute: 执行Python代码"
            "file_editor: 读写文件和查看目录"
            "bash_execute: 执行命令行命令"
            "【实验环境】\n"
            "CPU: 48 cores\n"
            "内存: 366GB\n"
            "磁盘: 250GB SSD\n"
            "操作系统: Ubuntu 22.04\n"
            "深度学习模型: ResNet50\n\n"
            "【参数详情】\n"
            + SysctlPromptBuilder.param_info + "\n\n"
            "【任务要求】\n"
            "第一轮通过命令行修改参数的默认取值，跑一次模型，读取日志文件，获取baseline训练时长.\n"
            "之后根据调优阶段规则进行参数推荐，每个字段以 'key: value' 格式返回，同样通过命令行修改参数取值为推荐值，跑一次模型，读取日志文件，获取该轮的训练时长。\n"
            "持续调优，直到训练时长满足提升要求8%\n"
        )
    
    async def run(self, user_input: str) -> str:
        """执行用户请求"""
        print(f"\n🚀 {self.name} 开始执行任务: {user_input}")
        
        # 初始化
        self.state = AgentState.RUNNING
        self.current_step = 0
        
        # 添加用户消息到记忆
        self.memory.add_message(Message.user_message(user_input))
        
        # 执行循环
        while self.state == AgentState.RUNNING and self.current_step < self.max_steps:
            self.current_step += 1
            print(f"\n--- 第 {self.current_step} 步 ---")
            
            # Think: 思考下一步行动
            should_continue = await self.think()
            if not should_continue:
                break
            
            # Act: 执行行动
            await self.act()
        
        self.state = AgentState.FINISHED
        result = self._generate_summary()
        print(f"\n✅ 任务完成! 总共执行了 {self.current_step} 步")
        return result
    
    async def think(self) -> bool:
        """思考阶段：分析当前状态，决定下一步行动"""
        print("🤔 正在思考...")
        
        try:
            # 获取LLM响应
            response = await self.llm.chat(
                messages=self.memory.get_messages(),
                system_prompt=self.system_prompt,
                tools=self.tools.get_tool_definitions()
            )
            
            print(f"💭 思考结果: {response.content}")
            
            # 保存助手消息
            self.memory.add_message(
                Message.assistant_message(
                    content=response.content,
                    tool_calls=response.tool_calls
                )
            )
            
            # 检查是否需要调用工具
            if response.tool_calls:
                return True
            else:
                # 没有工具调用，任务可能已完成
                self.state = AgentState.FINISHED
                return False
                
        except Exception as e:
            print(f"❌ 思考过程出错: {e}")
            self.state = AgentState.FINISHED
            return False
    
    async def act(self) -> None:
        """行动阶段：执行工具调用"""
        print("⚡ 正在执行行动...")
        
        # 获取最后一条消息的工具调用
        last_message = self.memory.messages[-1]
        if not last_message.tool_calls:
            return
        
        # 执行所有工具调用
        for tool_call in last_message.tool_calls:
            tool_id = tool_call["id"]
            function_name = tool_call["function"]["name"]
            
            try:
                # 解析参数
                arguments = json.loads(tool_call["function"]["arguments"])
                print(f"🔧 执行工具: {function_name} with {arguments}")
                
                # 执行工具
                result = await self.tools.execute_tool(function_name, **arguments)
                
                # 准备结果消息
                if result.success:
                    result_content = result.output
                    print(f"✅ 工具执行成功: {result_content[:100]}...")
                else:
                    result_content = f"错误: {result.error}"
                    print(f"❌ 工具执行失败: {result.error}")
                
                # 保存工具结果
                self.memory.add_message(
                    Message.tool_message(
                        content=result_content,
                        tool_call_id=tool_id
                    )
                )
                
            except Exception as e:
                error_msg = f"工具执行异常: {str(e)}"
                print(f"❌ {error_msg}")
                self.memory.add_message(
                    Message.tool_message(
                        content=error_msg,
                        tool_call_id=tool_id
                    )
                )
    
    def _generate_summary(self) -> str:
        """生成任务执行摘要"""
        messages = self.memory.messages
        if not messages:
            return "没有执行任何操作"
        
        # 提取关键信息
        user_requests = [msg.content for msg in messages if msg.role == Role.USER]
        assistant_responses = [msg.content for msg in messages if msg.role == Role.ASSISTANT and msg.content]
        
        summary = f"""
任务执行摘要:
- 用户请求: {user_requests[0] if user_requests else '未知'}
- 执行步数: {self.current_step}
- 最终状态: {self.state.value}
- 主要响应: {assistant_responses[-1] if assistant_responses else '无响应'}
"""
        return summary