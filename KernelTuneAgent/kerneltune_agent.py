"""
智能代理核心实现
"""
import json
from typing import Optional
import re
from KernelTuneAgent.schema import Message, AgentState, Memory, Role
from KernelTuneAgent.llm import SimpleLLM
from KernelTuneAgent.tools import ToolCollection
from KernelTuneAgent.prompt_build import PromptBuilder
from KernelTuneAgent.config import Phase
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
        prompt_builder = PromptBuilder()
        tuning_phase=Phase.EXPLORATION
        # 默认系统提示词
        self.system_prompt = prompt_builder.build_system_prompt_messages()

    async def run(self) -> str:
        """执行用户请求"""
        user_input=(
            "【用户请求】"
            "在参数的默认取值下，跑一次模型，读取日志文件.\n"
        )
        print(f"\n🚀 {self.name} 开始执行任务: {user_input}")
        
        # 初始化
        self.state = AgentState.RUNNING
        self.current_step = 0
        
        # 添加用户消息到记忆
        self.memory.add_message(Message.user_message(user_input))
        
        self.current_step += 1
        print(f"\n--- 第 {self.current_step} 步 ---")
            
        # Think: 思考下一步行动
        await self.think()
  
        # Act: 执行行动
        await self.act()

        # 获取baseline
        baseline=self._extract_training_time_from_last_tool_result()

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
            
            # 从工具执行结果里获取上一轮训练时长
            last_traing_time=self._extract_training_time_from_last_tool_result()
            # 更新调优阶段
            improvement_ratio = (baseline - last_traing_time) / baseline
            # TODO:改成用 prompt_builder 中的配置控制 判断是否结束
            if improvement_ratio >= self.prompt_builder.target:
                print("达到性能目标，搜索结束。")
                break

            # 阶段更新
            new_phase = self.update_phase(self.tuning_phase, improvement_ratio)
            if new_phase != self.tuning_phase:
                print(f"阶段切换：{self.tuning_phase.value} → {new_phase.value}")
            self.tuning_phase = new_phase

            # 添加feedback和新的调优规则
            self.memory.add_message(Message.user_message(self.prompt_builder.build_feedback_prompt(self.tuning_phase,baseline,last_traing_time)))

        self.state = AgentState.FINISHED
        result = self._generate_summary()
        print(f"\n✅ 任务完成! 总共执行了 {self.current_step} 步")
        return result
    
    async def think(self) -> bool:
        """真正执行交互LLM"""
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
            print(f"💭 调用工具: {response.tool_calls}")
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
    def _extract_training_time_from_last_tool_result(self) -> Optional[float]:
        """
            从 memory 中最后一条 tool 消息的内容中提取 '平均训练耗时: XXX 秒' 的浮点数值。
    
            返回:
            float: 提取到的训练时间（秒），如果未找到则返回 None
        """
        # 从后往前找第一条 role == Role.TOOL 的消息
        for msg in reversed(self.memory.messages):
            if msg.role == Role.TOOL and msg.content:
                # 使用正则匹配 "平均训练耗时: 123.45 秒"
                match = re.search(r"平均训练耗时:\s*([\d.]+)\s*秒", msg.content)
                if match:
                    try:
                        return float(match.group(1))
                    except ValueError:
                        continue  # 格式异常，跳过
        return None
    def update_phase(current_phase: Phase, improvement_ratio: float) -> Phase:
        """
        根据当前阶段和性能提升比例决定是否进入下一阶段。
        注意：current_phase 是 Phase 枚举实例，不是字符串！
        """

        if current_phase == Phase.EXPLORATION and improvement_ratio >= 0.05:
            return Phase.EXPLOITATION
        if current_phase == Phase.EXPLOITATION and improvement_ratio >= 0.12:
            return Phase.REFINEMENT
        return current_phase
    
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