"""生成系统提示词和反馈提示词"""
from pydantic import BaseModel, create_model
from typing import Dict, Any
from enum import Enum
from kerneltune_agent.config import FIXED_SYSCTL_PARAMS,Phase,DYNAMIC_SYSCTL_PARAMS,SYSCTL_PARAM_META

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

def build_feedback_prompt(phase: Phase, baseline: float, last_value=None) -> str:
    """性能反馈的 prompt 构建"""
    perf_desc = ""
    failure_rule = ""
    
    if last_value is not None:
        diff = (last_value - baseline) / baseline * 100
        if diff > 0:
            perf_desc = f"上一轮比 baseline 慢了 {diff:.2f}%"
            failure_rule = (
                "- 上一轮参数组合未带来性能提升，视为失败方案\n"
                "- 本轮避免返回与上一轮相似的配置\n"
            )
        else:
            perf_desc = f"上一轮比 baseline 快了 {abs(diff):.2f}%"

    return (
        f"【当前阶段】{phase.value}, {phase.desc}\n\n"
        f"【阶段规则】\n"
        f"- 至少调整 {phase.min_changed_params} 个参数\n"
        f"【性能反馈】\n"
        f"baseline: {baseline:.4f} 秒\n"
        f"{perf_desc}\n\n"
        f"{failure_rule}\n\n"
        f"请严格遵循规则，返回新的 sysctl 参数组合。\n"
    )

class SysctlPromptBuilder:
    def __init__(self, config_path: str = "./sys.config"):
        self.config_path = config_path
        self.sys_cfg = self._load_sys_config()
        self.SysctlConfig = self._build_sysctl_config()
        self.param_info = self._build_param_info()

    def _load_sys_config(self) -> Dict[str, bool]:
        """从配置文件加载参数开关"""
        cfg = {}
        try:
            with open(self.config_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    key, value = line.split(":", 1)
                    cfg[key.strip()] = value.strip().lower() == "true"
        except FileNotFoundError:
            print(f"Warning: {self.config_path} not found. Using empty config.")
        return cfg

    def _collect_sysctl_fields(self) -> Dict[str, tuple]:
        fields = {}

        # 固定参数：无条件加入
        for name in FIXED_SYSCTL_PARAMS:
            fields[name] = (int, ...)

        # 动态参数：由 sys.config 控制
        for name, spec in DYNAMIC_SYSCTL_PARAMS.items():
            if self.sys_cfg.get(spec["switch"], False):
                fields[name] = (int, ...)

        return fields

    def _build_sysctl_config(self):
        fields = self._collect_sysctl_fields()
        model_name = f"SysctlConfig_{hash(frozenset(self.sys_cfg.items()))}"
        return create_model(model_name, **fields, __base__=BaseModel)

    def _build_param_info(self) -> str:
        lines = []
        for name, meta in SYSCTL_PARAM_META.items():
            sw = meta.get("switch")
            if sw is not None and not self.sys_cfg.get(sw, False):
                continue
            line = (
                f"{name}: range {meta['range']}, "
                f"default {meta['default']}, "
                f"step {meta['step']}."
            )
            lines.append(line)
        return "\n".join(lines)

    def build_initial_prompt_messages(self) -> list[dict[str, str]]:
        """构建第一轮推荐 sysctl 配置的 prompt（用于获取 baseline）"""
        content = (
            "根据实验环境推荐 sysctl 配置。\n\n"
            "【实验环境】\n"
            "CPU: 48 cores\n"
            "内存: 366GB\n"
            "磁盘: 250GB SSD\n"
            "操作系统: Ubuntu 22.04\n"
            "深度学习模型: ResNet50\n\n"
            "【参数详情】\n"
            + self.param_info + "\n\n"
            "【任务要求】\n"
            "请根据上述环境，第一轮返回 12 个 sysctl 参数的默认取值获取baseline训练时长，每个字段以 'key: value' 格式填写。\n"
        )
        return [{"role": "user", "content": content}]

    def get_config_model(self):
        """返回动态生成的 Pydantic 模型，可用于校验 LLM 输出"""
        return self.SysctlConfig

    def get_active_param_names(self) -> list[str]:
        """返回当前启用的参数名列表"""
        return list(self.SysctlConfig.model_fields.keys())

"""# JSON Schema
json_schema = SysctlConfig.model_json_schema()

model = "output/qwen3_lora"   
client = OpenAI(base_url="http://localhost:8000/v1", api_key="none")

phase = Phase.EXPLORATION
round_id = 1
baseline = None
last_value = None
threshold=0.08"""

