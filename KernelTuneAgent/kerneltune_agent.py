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
        self.prompt_builder = PromptBuilder()
        self.tuning_phase=Phase.EXPLORATION
        # 默认系统提示词
        self.system_prompt = self.prompt_builder.build_system_prompt_messages()

        # --- 新增：用于追踪最佳效果的变量 ---
        self.best_improvement_ratio = -1.0  # 记录历史最高的提升率
        self.best_step_index = 0            # 记录达到最高提升率时的步数索引（对应 memory 中的位置或轮次）


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

        # 添加新的用户请求
        self.memory.add_message(Message.user_message(self.prompt_builder.build_feedback_prompt(self.tuning_phase,baseline,None)))
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

            # --- 新增：更新最佳记录 ---
            if improvement_ratio > self.best_improvement_ratio:
                self.best_improvement_ratio = improvement_ratio
                self.best_step_index = self.current_step # 记录当前步数为最佳步数
                print(f"✨ 发现新的最佳效果！提升率: {improvement_ratio:.2%}, 步数: {self.current_step}")

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
                    raw_content  = result.output
                    result_content = self._truncate_tool_output(raw_content, max_length=600)
                    print(f"✅ 工具执行成功: {result_content[:100]}... (原始长度: {len(raw_content)}, 处理后长度: {len(result_content)})")
                else:
                    result_content = f"错误: {result.error}"
                    if len(result_content) > 1000:
                        result_content = result_content[:1000] + "... [错误信息过长已截断]"
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
    def _truncate_tool_output(self, text: str, max_length: int = 600, keep_head_ratio: float = 0.4) -> str:
        """
        截断过长的工具输出，保留头部和尾部，中间用省略号代替。
        
        Args:
            text: 原始文本
            max_length: 允许的最大字符数
            keep_head_ratio: 头部保留的比例 (0.4 表示保留前 40%)
            
        Returns:
            截断后的文本
        """
        if len(text) <= max_length:
            return text
        
        # 计算头部和尾部的长度
        head_len = int(max_length * keep_head_ratio)
        tail_len = max_length - head_len - 50 # 50 留给省略号和提示语
        
        if tail_len < 100: # 如果尾部太短，调整比例
            head_len = int(max_length * 0.6)
            tail_len = max_length - head_len - 50

        head = text[:head_len]
        tail = text[-tail_len:]
        
        # 尝试按行截断，避免切断 JSON 或日志的一半（可选优化）
        # 这里简单按字符截断，如果需要更智能可以按 '\n' 分割
        
        separator = f"\n\n... [日志中间部分已省略，原始长度 {len(text)} 字符，为节省 Token 已截断] ...\n\n"
        
        return head + separator + tail


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
    def update_phase(self,current_phase: Phase, improvement_ratio: float) -> Phase:
        """
        根据当前阶段和性能提升比例决定是否进入下一阶段。
        注意：current_phase 是 Phase 枚举实例，不是字符串！
        """

        if current_phase == Phase.EXPLORATION and improvement_ratio >= 0.05:
            return Phase.EXPLOITATION
        if current_phase == Phase.EXPLOITATION and improvement_ratio >= 0.12:
            return Phase.REFINEMENT
        return current_phase
    # TODO:从中获取调优效果最好的一次，作为结果返回
    def _generate_summary(self) -> str:
        """
        生成任务执行摘要。
        逻辑：
        1. 从 SYSCTL_PARAM_META 初始化所有参数的默认值。
        2. 仅遍历到 best_step_index 为止的消息，解析 sysctl 和 echo 命令。
        3. 后续轮次的修改不会生效，保证输出的是“最佳时刻”的参数状态。
        """
        messages = self.memory.messages
        if not messages:
            return "没有执行任何操作"

        # 引入参数元数据
        SYSCTL_PARAM_META = {
            "fs.file-max": {"default": "1048576"},
            "kernel.threads-max": {"default": "3092111"},
            "vm.watermark_scale_factor": {"default": "10"},
            "vm.page-cluster": {"default": "3"},
            "transparent_hugepage": {"default": "madvise"},
            "vm.dirty_background_ratio": {"default": "10"},
            "vm.dirty_expire_centisecs": {"default": "3000"},
            "vm.dirty_ratio": {"default": "30"},
            "vm.dirty_writeback_centisecs": {"default": "500"},
            "vm.overcommit_memory": {"default": "0"},
            "vm.overcommit_ratio": {"default": "50"},
            "vm.swappiness": {"default": "10"},
            "kernel.numa_balancing": {"default": "1"},
        }

        # 1. 初始化参数为默认值
        final_param_values = {}
        for param, meta in SYSCTL_PARAM_META.items():
            final_param_values[param] = meta["default"]

        # 2. 遍历消息，但限制在 best_step_index 之前
        # 注意：这里的逻辑假设 message 的顺序和 step 是线性对应的
        # 我们遍历所有消息，但通过逻辑判断是否处理
        # 为了更精确，我们需要知道每条消息属于哪个 Step。
        # 由于代码中没有显式的 step_id 在 message 中，我们假设消息是按顺序追加的。
        # 简单的做法是：统计处理过的 Assistant 消息数量，直到达到 best_step_index。
        
        assistant_action_count = 0
        
        for msg in messages:
            # 只有 Assistant 的消息包含工具调用（行动）
            if msg.role == Role.ASSISTANT and msg.tool_calls:
                assistant_action_count += 1
                
                # 核心修改：如果当前行动轮次超过了最佳轮次，停止解析
                if assistant_action_count > self.best_step_index:
                    break
                
                for tool_call in msg.tool_calls:
                    if 'function' in tool_call and 'arguments' in tool_call['function']:
                        try:
                            arguments = json.loads(tool_call['function']['arguments'])
                            command = arguments.get('command', '')
                            import re

                            # 处理 sysctl 命令
                            if command.startswith('sysctl'):
                                matches = re.findall(r'([\w\.\-]+)=([\d\w\.\-]+)', command)
                                for key, value in matches:
                                    if key in final_param_values:
                                        final_param_values[key] = value

                            # 处理 echo 命令
                            elif command.startswith('echo'):
                                if 'transparent_hugepage' in command:
                                    match = re.search(r'echo\s+(\w+)\s+>', command)
                                    if match:
                                        value = match.group(1)
                                        final_param_values['transparent_hugepage'] = value

                        except (json.JSONDecodeError, KeyError):
                            continue

        # 3. 构建摘要信息
        summary = "📝 任务执行摘要 (基于最佳轮次)\n"
        summary += "-" * 50 + "\n"
        summary += f"最佳效果轮次: 第 {self.best_step_index} 轮\n"
        summary += f"最佳提升率: {self.best_improvement_ratio:.2%}\n"
        summary += "-" * 50 + "\n"
        summary += "最佳状态下的参数取值:\n"
        
        for param in sorted(final_param_values.keys()):
            summary += f"  - {param}: {final_param_values[param]}\n"
            
        summary += "-" * 50

        return summary
